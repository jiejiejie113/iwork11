[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'status',
        'failed-log',
        'ci',
        'release',
        'preflight',
        'deploy',
        'production-status',
        'rollback'
    )]
    [string]$Action,

    [ValidateSet('iwork', 'portal', 'all')]
    [string]$Service = 'all',

    [ValidateSet('all', 'ci', 'release', 'deploy')]
    [string]$WorkflowKind = 'all',

    [string]$Revision,
    [string]$ImageDigest,
    [string]$ConfigDigest,
    [string]$ConfigArtifactDigest,
    [string]$PreflightRunId,
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string]$CiRequestId,
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string]$ReleaseRequestId,
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string]$RequestId,
    [string]$PortalDigest,
    [string]$ProxyDigest,
    [string]$ChangeDescription,
    [string]$ApprovalText,
    [switch]$RunMigrations,
    [switch]$Wait,
    [switch]$OutputJson,
    [long]$RunId,
    [ValidateRange(1, 50)]
    [int]$Limit = 10,
    [string]$GhExecutable = 'gh'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ======
# 固定仓库与 Workflow 路由
$SERVICE_CONFIG = @{
    iwork = [ordered]@{
        Repository = 'GuChenkano/iwork'
        Branch = 'Keycloak'
        CiWorkflow = 'ci.yml'
        ReleaseWorkflow = 'release.yml'
        DeployWorkflow = 'deploy-iwork.yml'
        DeployWorkflowName = 'iwork controlled production deployment'
        Environment = 'production-iwork'
    }
    portal = [ordered]@{
        Repository = 'GuChenkano/DTD_nginx'
        Branch = 'feature/keycloak-migration'
        CiWorkflow = 'ci.yml'
        ReleaseWorkflow = 'release.yml'
        DeployWorkflow = 'deploy-portal.yml'
        Environment = 'production-portal'
    }
}
$REVISION_PATTERN = '^[0-9a-f]{40}$'
$DIGEST_PATTERN = '^sha256:[0-9a-f]{64}$'
$CONFIG_ARTIFACT_PLACEHOLDER_PATTERN = '^\$artifactDigest$'
$RUN_DISCOVERY_TIMEOUT_SECONDS = if (
    $env:DKT_CICD_TEST_MODE -ceq '1' -and
    $env:DKT_CICD_TEST_DISCOVERY_TIMEOUT_SECONDS -match '^\d+$'
) {
    [int]$env:DKT_CICD_TEST_DISCOVERY_TIMEOUT_SECONDS
}
else {
    120
}
$RUN_DISCOVERY_INTERVAL_SECONDS = 2
$RUN_DISCOVERY_SETTLE_SECONDS = if ($env:DKT_CICD_TEST_MODE -ceq '1') { 0 } else { 4 }
$DISPATCH_MUTEX_NAME = 'Local\DKT-CICD-Skill-Dispatch'
$CONFIRMATION_MUTEX_NAME = 'Local\DKT-CICD-Skill-Confirmation'
$CONFIRMATION_MAX_AGE_MINUTES = 15
$CONFIRMATION_STATE_ROOT = if (
    $env:DKT_CICD_TEST_MODE -ceq '1' -and
    -not [String]::IsNullOrWhiteSpace($env:DKT_CICD_CONFIRMATION_STATE_ROOT)
) {
    [IO.Path]::GetFullPath($env:DKT_CICD_CONFIRMATION_STATE_ROOT)
}
else {
    Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'DKT-CICD\pending-confirmations'
}

if ($GhExecutable -cne 'gh') {
    $allowedTestRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tests'))
    $resolvedGhExecutable = [IO.Path]::GetFullPath($GhExecutable)
    if ($env:DKT_CICD_TEST_MODE -cne '1' -or
        -not $resolvedGhExecutable.StartsWith(
            $allowedTestRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw 'GhExecutable 仅允许离线测试使用；真实操作固定调用当前用户 PATH 中的 gh。'
    }
    $GhExecutable = $resolvedGhExecutable
}

function Protect-SensitiveText {
    param([AllowEmptyString()][string]$Text)

    if ([String]::IsNullOrEmpty($Text)) {
        return $Text
    }

    $redacted = $Text -replace '(?i)(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+', '[REDACTED_GITHUB_TOKEN]'
    $redacted = $redacted -replace '(?i)(authorization\s*[:=]\s*(?:bearer|token)?\s*)\S+', '$1[REDACTED]'
    $redacted = $redacted -replace '(?i)(\btoken\s*[:=]\s*)\S+', '$1[REDACTED]'
    $redacted = $redacted -replace '(?i)((?:password|cookie|secret)\s*[:=]\s*)\S+', '$1[REDACTED]'
    $redacted = $redacted -replace '(?i)(https?://)[^/\s:@]+:[^@\s/]+@', '$1[REDACTED]@'
    return $redacted
}

function Get-PreviewFingerprint {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Preview)

    $previewJson = $Preview | ConvertTo-Json -Depth 8 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($previewJson)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Save-ConfirmationPreview {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Preview,
        [Parameter(Mandatory = $true)][string]$RequiredApprovalText,
        [AllowNull()][string]$RequestId
    )

    New-Item -ItemType Directory -Path $CONFIRMATION_STATE_ROOT -Force | Out-Null
    $statePath = Join-Path $CONFIRMATION_STATE_ROOT "$ServiceName.json"
    $tempPath = "$statePath.$([Guid]::NewGuid().ToString('N')).tmp"
    $createdAt = [DateTimeOffset]::UtcNow
    $state = [ordered]@{
        Service = $ServiceName
        Fingerprint = Get-PreviewFingerprint -Preview $Preview
        RequiredApprovalText = $RequiredApprovalText
        RequestId = $RequestId
        CreatedAt = $createdAt.ToString('o')
        ExpiresAt = $createdAt.AddMinutes($CONFIRMATION_MAX_AGE_MINUTES).ToString('o')
    }
    try {
        $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tempPath -Encoding UTF8
        Move-Item -LiteralPath $tempPath -Destination $statePath -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}

function Get-ConfirmationPreviewState {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    $statePath = Join-Path $CONFIRMATION_STATE_ROOT "$ServiceName.json"
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        throw '生产确认状态无法读取，已失败关闭；请重新生成完整预览。'
    }
}

function Use-ConfirmationPreview {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Preview,
        [Parameter(Mandatory = $true)][string]$RequiredApprovalText
    )

    $confirmationMutex = [Threading.Mutex]::new($false, $CONFIRMATION_MUTEX_NAME)
    $mutexAcquired = $false
    try {
        $mutexAcquired = $confirmationMutex.WaitOne([TimeSpan]::FromSeconds(5))
        if (-not $mutexAcquired) {
            throw '无法取得生产确认状态锁，已停止部署触发。'
        }
        $statePath = Join-Path $CONFIRMATION_STATE_ROOT "$ServiceName.json"
        $state = Get-ConfirmationPreviewState -ServiceName $ServiceName
        if ($null -eq $state) {
            throw '未找到本次生产部署预览，请先不带确认词生成并展示完整预览。'
        }
        $expectedFingerprint = Get-PreviewFingerprint -Preview $Preview
        if (
            [string]$state.Service -cne $ServiceName -or
            [string]$state.Fingerprint -cne $expectedFingerprint -or
            [string]$state.RequiredApprovalText -cne $RequiredApprovalText
        ) {
            throw '当前参数与已展示的生产部署预览不一致，已停止触发；请重新生成完整预览。'
        }
        if ([DateTimeOffset]::Parse([string]$state.ExpiresAt) -lt [DateTimeOffset]::UtcNow) {
            Remove-Item -LiteralPath $statePath -Force
            throw '生产部署预览已超过15分钟有效期，请重新生成完整预览。'
        }
        Remove-Item -LiteralPath $statePath -Force
        return $state
    }
    finally {
        if ($mutexAcquired) {
            $confirmationMutex.ReleaseMutex()
        }
        $confirmationMutex.Dispose()
    }
}

function Invoke-GhCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $command = Get-Command -Name $GhExecutable -ErrorAction SilentlyContinue
    if (-not $command -and -not (Test-Path -LiteralPath $GhExecutable -PathType Leaf)) {
        throw '未找到 GitHub CLI。请先安装 gh 并完成登录。'
    }

    $output = @(& $GhExecutable @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = Protect-SensitiveText -Text (($output | ForEach-Object { [string]$_ }) -join "`n")

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        if ([String]::IsNullOrWhiteSpace($text)) {
            throw "GitHub CLI 调用失败，退出码：$exitCode"
        }
        throw "GitHub CLI 调用失败，退出码：$exitCode；$text"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $text
    }
}

function Assert-GhAuthentication {
    $result = Invoke-GhCommand -Arguments @('auth', 'status', '--hostname', 'github.com') -AllowFailure
    if ($result.ExitCode -ne 0) {
        throw '当前 Windows 用户的 GitHub CLI 登录不可用，请先执行 gh auth login。'
    }
}

function ConvertFrom-GhJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $result = Invoke-GhCommand -Arguments $Arguments
    if ([String]::IsNullOrWhiteSpace($result.Output)) {
        return @()
    }
    $parsed = $result.Output | ConvertFrom-Json
    # Windows PowerShell 5.1会把JSON数组作为一个Object[]对象返回；显式写入管道以逐项展开。
    Write-Output $parsed
}

function Get-ServiceNames {
    if ($Service -eq 'all') {
        return @('iwork', 'portal')
    }
    return @($Service)
}

function Assert-SingleService {
    if ($Service -eq 'all') {
        throw "动作 '$Action' 必须明确指定 -Service iwork 或 -Service portal。"
    }
}

function Get-RemoteHeadRevision {
    param([Parameter(Mandatory = $true)][string]$ServiceName)

    $config = $SERVICE_CONFIG[$ServiceName]
    $result = Invoke-GhCommand -Arguments @(
        'api',
        "repos/$($config.Repository)/commits/$($config.Branch)",
        '--jq',
        '.sha'
    )
    $head = $result.Output.Trim()
    if ($head -cnotmatch $REVISION_PATTERN) {
        throw "GitHub 返回的远程分支 HEAD 不是有效完整 SHA：$head"
    }
    return $head
}

function Resolve-Revision {
    param([Parameter(Mandatory = $true)][string]$ServiceName)

    $head = Get-RemoteHeadRevision -ServiceName $ServiceName
    if ([String]::IsNullOrWhiteSpace($Revision)) {
        return $head
    }
    if ($Revision -cnotmatch $REVISION_PATTERN) {
        throw 'Revision 必须是 40 位小写 Commit SHA。'
    }
    if ($Revision -cne $head) {
        throw "Revision 与固定远程分支 HEAD 不一致。远程 HEAD：$head"
    }
    return $Revision
}

function Get-WorkflowRuns {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [string]$Workflow,
        [int]$Count = 10
    )

    $config = $SERVICE_CONFIG[$ServiceName]
    $arguments = @(
        'run', 'list',
        '--repo', $config.Repository,
        '--branch', $config.Branch,
        '--limit', [string]$Count,
        '--json', 'databaseId,attempt,workflowName,displayTitle,status,conclusion,headSha,url,createdAt,startedAt,updatedAt,event'
    )
    if (-not [String]::IsNullOrWhiteSpace($Workflow)) {
        $arguments += @('--workflow', $Workflow)
    }
    return @(ConvertFrom-GhJson -Arguments $arguments)
}

function Get-RunDetails {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][long]$Id
    )

    $config = $SERVICE_CONFIG[$ServiceName]
    $arguments = @(
        'run', 'view', [string]$Id,
        '--repo', $config.Repository,
        '--json', 'databaseId,attempt,workflowName,displayTitle,status,conclusion,headSha,url,createdAt,startedAt,updatedAt,event,jobs'
    )
    $items = @(ConvertFrom-GhJson -Arguments $arguments)
    if ($items.Count -ne 1) {
        throw "无法读取 Actions Run：$Id"
    }
    return $items[0]
}

function Get-RunDurationSeconds {
    param([Parameter(Mandatory = $true)]$Run)

    $startText = if (-not [String]::IsNullOrWhiteSpace([string]$Run.startedAt)) {
        [string]$Run.startedAt
    }
    else {
        [string]$Run.createdAt
    }
    if ([String]::IsNullOrWhiteSpace($startText)) {
        return $null
    }

    $start = [DateTimeOffset]::Parse($startText)
    $end = if ($Run.status -eq 'completed' -and -not [String]::IsNullOrWhiteSpace([string]$Run.updatedAt)) {
        [DateTimeOffset]::Parse([string]$Run.updatedAt)
    }
    else {
        [DateTimeOffset]::UtcNow
    }
    return [Math]::Round(($end - $start).TotalSeconds, 1)
}

function Get-RunIdentifier {
    <#
    .SYNOPSIS
    将GitHub Run数据库ID和尝试次数组合成部署锁使用的稳定标识。
    #>
    param([Parameter(Mandatory = $true)]$Run)

    $databaseId = [long]$Run.databaseId
    $attempt = 1
    if (-not [int]::TryParse([string]$Run.attempt, [ref]$attempt) -or $attempt -lt 1) {
        $attempt = 1
    }
    return "$databaseId-$attempt"
}

function Resolve-IworkRequestId {
    <#
    .SYNOPSIS
    生成或验证一次 iwork Actions 触发使用的唯一 request_id。
    #>
    param(
        [AllowNull()][string]$Candidate
    )

    $resolved = if ([String]::IsNullOrWhiteSpace($Candidate)) {
        [Guid]::NewGuid().ToString('D')
    }
    else {
        $Candidate.ToLowerInvariant()
    }
    if ($resolved -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
        throw 'iwork request_id 必须是标准小写GUID。'
    }
    return $resolved
}

function Get-IworkRequestIdFromRun {
    <#
    .SYNOPSIS
    从已核验的iwork Workflow Run名称中读取其独立request_id。
    #>
    param([Parameter(Mandatory = $true)]$Run)

    $requestMatch = [Regex]::Match(
        [string]$Run.displayTitle,
        '(?i)(?<request>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    )
    if (-not $requestMatch.Success) {
        throw 'iwork Workflow Run缺少有效request_id，拒绝继续关联。'
    }
    return Resolve-IworkRequestId -Candidate $requestMatch.Groups['request'].Value
}

function Get-FailedSteps {
    param([Parameter(Mandatory = $true)]$Run)

    $failedSteps = @()
    foreach ($job in @($Run.jobs)) {
        foreach ($step in @($job.steps)) {
            if ($step.conclusion -eq 'failure') {
                $failedSteps += [pscustomobject]@{
                    Job = [string]$job.name
                    Step = [string]$step.name
                }
            }
        }
    }
    return $failedSteps
}

function ConvertTo-RunResult {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)]$Run,
        [AllowNull()][string[]]$Digests = $null,
        [AllowNull()][object]$ImageDigest = $null,
        [AllowNull()][object]$ConfigDigest = $null,
        [AllowNull()][object]$ConfigArtifactDigest = $null,
        [AllowNull()][object]$RequestId = $null
    )

    $normalizedDigests = @()
    if ($null -ne $Digests) {
        $normalizedDigests = @($Digests | Where-Object {
            $null -ne $_ -and -not [String]::IsNullOrWhiteSpace([string]$_)
        } | ForEach-Object { [string]$_ })
    }
    $resolvedRequestId = $RequestId
    if (
        [String]::IsNullOrWhiteSpace([string]$resolvedRequestId) -and
        $ServiceName -eq 'iwork'
    ) {
        $requestMatch = [Regex]::Match(
            [string]$Run.displayTitle,
            '(?i)(?<request>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
        )
        if ($requestMatch.Success) {
            $resolvedRequestId = $requestMatch.Groups['request'].Value.ToLowerInvariant()
        }
    }
    $runAttempt = 1
    if (
        $null -ne $Run.PSObject.Properties['attempt'] -and
        [int]::TryParse([string]$Run.attempt, [ref]$runAttempt) -and
        $runAttempt -ge 1
    ) {
        # 使用Run自身的attempt。
    }
    else {
        $runAttempt = 1
    }
    return [ordered]@{
        Service = $ServiceName
        Workflow = [string]$Run.workflowName
        RunId = [long]$Run.databaseId
        RunAttempt = $runAttempt
        RunIdentifier = Get-RunIdentifier -Run $Run
        Status = [string]$Run.status
        Conclusion = [string]$Run.conclusion
        Commit = [string]$Run.headSha
        Digests = $normalizedDigests
        ImageDigest = $ImageDigest
        ConfigDigest = $ConfigDigest
        ConfigArtifactDigest = $ConfigArtifactDigest
        RequestId = $resolvedRequestId
        RunName = [string]$Run.displayTitle
        DurationSeconds = Get-RunDurationSeconds -Run $Run
        Url = [string]$Run.url
        FailedSteps = @(Get-FailedSteps -Run $Run)
    }
}

function Assert-SuccessfulWorkflowForRevision {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$Workflow,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$Description,
        [switch]$RequireWorkflowDispatch,
        [AllowNull()][string]$ExpectedRequestId
    )

    $successful = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 50 | Where-Object {
        $_.headSha -ceq $ExpectedRevision -and
        $_.status -eq 'completed' -and
        $_.conclusion -eq 'success' -and
        (-not $RequireWorkflowDispatch -or $_.event -eq 'workflow_dispatch') -and
        ([String]::IsNullOrWhiteSpace($ExpectedRequestId) -or
            ([string]$_.displayTitle).Contains($ExpectedRequestId))
    })
    if ($successful.Count -eq 0) {
        $eventRequirement = if ($RequireWorkflowDispatch) {
            ' workflow_dispatch'
        }
        else {
            ''
        }
        throw "没有找到同一 Commit 的成功$eventRequirement $Description，已停止触发。"
    }
    if (
        $ServiceName -eq 'iwork' -and
        [String]::IsNullOrWhiteSpace($ExpectedRequestId) -and
        $successful.Count -gt 1
    ) {
        throw "同一 Commit 存在多个成功$Description，缺少唯一request_id，已停止关联。"
    }
    return $successful[0]
}

function Assert-PortalSmokeEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedPortalDigest,
        [Parameter(Mandatory = $true)][string]$ExpectedProxyDigest
    )

    $successful = @(Get-WorkflowRuns -ServiceName 'portal' -Workflow 'runner-smoke.yml' -Count 50 | Where-Object {
        $_.headSha -ceq $ExpectedRevision -and
        $_.status -eq 'completed' -and
        $_.conclusion -eq 'success' -and
        ([string]$_.displayTitle).Contains($ExpectedRevision) -and
        ([string]$_.displayTitle).Contains($ExpectedPortalDigest) -and
        ([string]$_.displayTitle).Contains($ExpectedProxyDigest)
    })
    if ($successful.Count -eq 0) {
        throw '没有找到与 Portal Commit 和两个 Digest 完全匹配的成功 Runner smoke，已停止触发。'
    }
}

function Wait-ForNewWorkflowRun {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$Workflow,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][long[]]$PreviousRunIds,
        [Parameter(Mandatory = $true)][DateTimeOffset]$DispatchStartedAt,
        [AllowNull()][string]$RequestId
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RUN_DISCOVERY_TIMEOUT_SECONDS)
    while ($true) {
        $candidates = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 20 | Where-Object {
            $_.headSha -ceq $ExpectedRevision -and
            $_.event -eq 'workflow_dispatch' -and
            [long]$_.databaseId -notin $PreviousRunIds -and
            [DateTimeOffset]::Parse([string]$_.createdAt) -ge $DispatchStartedAt.AddSeconds(-2) -and
            ([String]::IsNullOrWhiteSpace($RequestId) -or
                ([string]$_.displayTitle).Contains($RequestId))
        } | Sort-Object -Property createdAt -Descending)
        if ($candidates.Count -gt 1) {
            throw '发现多个同一 Commit 的并发 workflow_dispatch Run，无法安全关联本次触发。请人工核对现有 Run，禁止重复触发。'
        }
        if ($candidates.Count -eq 1) {
            if ($RUN_DISCOVERY_SETTLE_SECONDS -gt 0) {
                Start-Sleep -Seconds $RUN_DISCOVERY_SETTLE_SECONDS
                $settledCandidates = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 20 | Where-Object {
                    $_.headSha -ceq $ExpectedRevision -and
                    $_.event -eq 'workflow_dispatch' -and
                    [long]$_.databaseId -notin $PreviousRunIds -and
                    [DateTimeOffset]::Parse([string]$_.createdAt) -ge $DispatchStartedAt.AddSeconds(-2) -and
                    ([String]::IsNullOrWhiteSpace($RequestId) -or
                        ([string]$_.displayTitle).Contains($RequestId))
                })
                if ($settledCandidates.Count -ne 1) {
                    throw 'Run 发现稳定窗口内出现并发歧义，无法安全关联本次触发。请人工核对现有 Run，禁止重复触发。'
                }
                return $settledCandidates[0]
            }
            return $candidates[0]
        }
        $remainingSeconds = ($deadline - [DateTimeOffset]::UtcNow).TotalSeconds
        if ($remainingSeconds -le 0) {
            break
        }
        $sleepSeconds = [int][Math]::Min(
            $RUN_DISCOVERY_INTERVAL_SECONDS,
            [Math]::Ceiling($remainingSeconds)
        )
        Start-Sleep -Seconds $sleepSeconds
    }

    # 即使最后一次轮询跨过截止时间，也必须再查一次，避免漏掉刚创建的 Run。
    $finalCandidates = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 20 | Where-Object {
        $_.headSha -ceq $ExpectedRevision -and
        $_.event -eq 'workflow_dispatch' -and
        [long]$_.databaseId -notin $PreviousRunIds -and
        [DateTimeOffset]::Parse([string]$_.createdAt) -ge $DispatchStartedAt.AddSeconds(-2) -and
        ([String]::IsNullOrWhiteSpace($RequestId) -or
            ([string]$_.displayTitle).Contains($RequestId))
    } | Sort-Object -Property createdAt -Descending)
    if ($finalCandidates.Count -gt 1) {
        throw '发现多个同一 Commit 的并发 workflow_dispatch Run，无法安全关联本次触发。请人工核对现有 Run，禁止重复触发。'
    }
    if ($finalCandidates.Count -eq 1) {
        return $finalCandidates[0]
    }

    throw 'Workflow 已提交，但在限定时间内未发现对应 Run。请使用 status 动作核对，禁止重复触发。'
}

function Get-RunEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][long]$Id,
        [switch]$RequireConfigDigest,
        [switch]$RequireConfigArtifactDigest
    )

    $config = $SERVICE_CONFIG[$ServiceName]
    $logResult = Invoke-GhCommand -Arguments @(
        'run', 'view', [string]$Id,
        '--repo', $config.Repository,
        '--log'
    )
    if ($ServiceName -eq 'iwork') {
        $matches = [regex]::Matches(
            $logResult.Output,
            '(?im)(?:^IWORK_IMAGE_DIGEST\s*=\s*|ghcr\.io/guchenkano/iwork@)(?<digest>sha256:[0-9a-f]{64})'
        )
        $digests = @($matches | ForEach-Object { $_.Groups['digest'].Value } | Select-Object -Unique)
        if ($digests.Count -ne 1) {
            throw "iwork Run 日志必须提供一个唯一完整 Digest，实际：$($digests.Count)"
        }
        $configMatches = [regex]::Matches(
            $logResult.Output,
            '(?im)(?:^|[^A-Za-z0-9])(?:iwork[_-])?config(?:uration)?[\s_-]*digest\s*[:=]\s*(?<digest>sha256:[0-9a-f]{64})'
        )
        $configDigests = @($configMatches | ForEach-Object {
            $_.Groups['digest'].Value
        } | Select-Object -Unique)
        if (
            $configDigests.Count -gt 1 -or
            ($RequireConfigDigest -and $configDigests.Count -ne 1)
        ) {
            throw "iwork Run 日志中的 ConfigDigest 必须唯一，实际：$($configDigests.Count)"
        }
        $configArtifactMatches = [regex]::Matches(
            $logResult.Output,
            '(?im)(?:^|[^A-Za-z0-9])IWORK_CONFIG_ARTIFACT_DIGEST\s*=\s*(?<value>[^\s\r\n]+)'
        )
        $configArtifactValues = @($configArtifactMatches | ForEach-Object {
            $_.Groups['value'].Value.Trim()
        } | Where-Object {
            $_ -cnotmatch $CONFIG_ARTIFACT_PLACEHOLDER_PATTERN
        } | Select-Object -Unique)
        $configArtifactDigests = @($configArtifactValues | Where-Object {
            $_ -cmatch $DIGEST_PATTERN
        })
        if (
            $configArtifactValues.Count -ne $configArtifactDigests.Count -or
            $configArtifactDigests.Count -gt 1 -or
            ($RequireConfigArtifactDigest -and $configArtifactDigests.Count -ne 1)
        ) {
            throw "iwork Run 日志中的 ConfigArtifactDigest 必须唯一且完整，实际：$($configArtifactDigests.Count)"
        }
        return [ordered]@{
            Digests = @($digests)
            ImageDigest = $digests[0]
            ConfigDigest = if ($configDigests.Count -eq 1) { $configDigests[0] } else { $null }
            ConfigArtifactDigest = if ($configArtifactDigests.Count -eq 1) {
                $configArtifactDigests[0]
            }
            else {
                $null
            }
        }
    }

    $portalMatches = [regex]::Matches(
        $logResult.Output,
        'ghcr\.io/guchenkano/(?<image>dtd-nginx|dtd-oauth2-proxy)@(?<digest>sha256:[0-9a-f]{64})'
    )
    $digestsByImage = @{}
    foreach ($imageName in @('dtd-nginx', 'dtd-oauth2-proxy')) {
        $imageDigests = @($portalMatches | Where-Object {
            $_.Groups['image'].Value -ceq $imageName
        } | ForEach-Object {
            $_.Groups['digest'].Value
        } | Select-Object -Unique)
        if ($imageDigests.Count -ne 1) {
            throw "Portal Run 日志中镜像 $imageName 必须提供一个唯一完整 Digest，实际：$($imageDigests.Count)"
        }
        $digestsByImage[$imageName] = $imageDigests[0]
    }
    return [ordered]@{
        Digests = @($digestsByImage['dtd-nginx'], $digestsByImage['dtd-oauth2-proxy'])
        ImageDigest = $null
        ConfigDigest = $null
        ConfigArtifactDigest = $null
    }
}

function Assert-SuccessfulPreflight {
    <#
    .SYNOPSIS
    验证正式部署绑定的apply=false预检Run及三类Digest。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$Identifier,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedImageDigest,
        [Parameter(Mandatory = $true)][string]$ExpectedConfigDigest,
        [Parameter(Mandatory = $true)][string]$ExpectedConfigArtifactDigest
    )

    if ($Identifier -notmatch '^(?<id>[0-9]+)-(?<attempt>[1-9][0-9]*)$') {
        throw '正式部署必须提供<workflow_run_id>-<run_attempt>格式的预检Run标识。'
    }
    $preflightId = [long]$Matches['id']
    $preflightAttempt = [string]$Matches['attempt']
    $run = Get-RunDetails -ServiceName $ServiceName -Id $preflightId
    $expectedWorkflowName = [string]$SERVICE_CONFIG[$ServiceName].DeployWorkflowName
    if (
        $run.status -ne 'completed' -or
        $run.conclusion -ne 'success' -or
        $run.event -ne 'workflow_dispatch' -or
        $run.headSha -cne $ExpectedRevision -or
        [string]$run.attempt -ne $preflightAttempt -or
        [string]$run.workflowName -cne $expectedWorkflowName -or
        [string]$run.displayTitle -notmatch '(?i)\bpreflight\b'
    ) {
        throw '绑定的预检Run不是同一提交的成功apply=false预检workflow_dispatch。'
    }
    $evidence = Get-RunEvidence `
        -ServiceName $ServiceName `
        -Id $preflightId `
        -RequireConfigDigest `
        -RequireConfigArtifactDigest
    if (
        $evidence.ImageDigest -cne $ExpectedImageDigest -or
        $evidence.ConfigDigest -cne $ExpectedConfigDigest -or
        $evidence.ConfigArtifactDigest -cne $ExpectedConfigArtifactDigest
    ) {
        throw '绑定预检Run中的三类Digest与当前部署输入不一致。'
    }
    $requestMatch = [Regex]::Match(
        [string]$run.displayTitle,
        '(?i)(?<request>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    )
    if (-not $requestMatch.Success) {
        throw '绑定预检Run缺少request_id。'
    }
    return [pscustomobject]@{
        Run = $run
        Evidence = $evidence
        RequestId = $requestMatch.Groups['request'].Value.ToLowerInvariant()
        RunIdentifier = $Identifier
    }
}

function Invoke-WorkflowDispatch {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$Workflow,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [hashtable]$Inputs = @{},
        [AllowNull()][string]$RequestIdOverride
    )

    $config = $SERVICE_CONFIG[$ServiceName]
    $dispatchMutex = [Threading.Mutex]::new($false, $DISPATCH_MUTEX_NAME)
    $mutexAcquired = $false
    try {
        $mutexAcquired = $dispatchMutex.WaitOne(0)
        if (-not $mutexAcquired) {
            throw '本机已有另一个 dkt-cicd Workflow 触发正在关联 Run，已停止本次触发。'
        }

        $previousIds = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 20 |
            ForEach-Object { [long]$_.databaseId })
        $requestId = if ($ServiceName -eq 'iwork') {
            $candidateRequestId = if (
                [String]::IsNullOrWhiteSpace($RequestIdOverride)
            ) {
                $RequestId
            }
            else {
                $RequestIdOverride
            }
            Resolve-IworkRequestId -Candidate $candidateRequestId
        }
        else {
            $null
        }
        $dispatchInputs = @{}
        foreach ($key in $Inputs.Keys) {
            $dispatchInputs[$key] = $Inputs[$key]
        }
        if (-not [String]::IsNullOrWhiteSpace($requestId)) {
            $dispatchInputs['request_id'] = $requestId
        }
        $arguments = @(
            'workflow', 'run', $Workflow,
            '--repo', $config.Repository,
            '--ref', $config.Branch
        )
        foreach ($key in @($dispatchInputs.Keys | Sort-Object)) {
            $arguments += @('-f', "$key=$($dispatchInputs[$key])")
        }
        $dispatchStartedAt = [DateTimeOffset]::UtcNow
        Invoke-GhCommand -Arguments $arguments | Out-Null

        $run = Wait-ForNewWorkflowRun `
            -ServiceName $ServiceName `
            -Workflow $Workflow `
            -ExpectedRevision $ExpectedRevision `
            -PreviousRunIds $previousIds `
            -DispatchStartedAt $dispatchStartedAt `
            -RequestId $requestId
    }
    finally {
        if ($mutexAcquired) {
            $dispatchMutex.ReleaseMutex()
        }
        $dispatchMutex.Dispose()
    }

    $watchExitCode = 0
    if ($Wait) {
        $watchResult = Invoke-GhCommand -Arguments @(
            'run', 'watch', [string]$run.databaseId,
            '--repo', $config.Repository,
            '--exit-status'
        ) -AllowFailure
        $watchExitCode = $watchResult.ExitCode
    }
    return [pscustomobject]@{
        Run = Get-RunDetails -ServiceName $ServiceName -Id ([long]$run.databaseId)
        WatchExitCode = $watchExitCode
        RequestId = $requestId
    }
}

function Get-DispatchExitCode {
    param([Parameter(Mandatory = $true)]$DispatchResult)

    if (-not $Wait) {
        return 0
    }
    if ($DispatchResult.WatchExitCode -ne 0 -or
        $DispatchResult.Run.status -ne 'completed' -or
        $DispatchResult.Run.conclusion -ne 'success') {
        return 2
    }
    return 0
}

function Complete-Result {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [int]$ExitCode = 0
    )

    if ($OutputJson) {
        $Value | ConvertTo-Json -Depth 10
    }
    else {
        $Value | Format-List | Out-String | Write-Output
    }
    exit $ExitCode
}

try {
    if ($Action -eq 'rollback') {
        Complete-Result -ExitCode 3 -Value ([ordered]@{
            Status = 'blocked'
            Code = 'manual_rollback_workflow_missing'
            Message = '现有 Workflow 只有失败自动回滚和受控回滚演练，没有“回滚上一次部署”的独立入口。为避免把演练误当真实回滚，本动作失败关闭。'
        })
    }

    Assert-GhAuthentication

    if ($Action -eq 'status') {
        $result = @()
        foreach ($serviceName in Get-ServiceNames) {
            $statusConfig = $SERVICE_CONFIG[$serviceName]
            $workflow = switch ($WorkflowKind) {
                'ci' { $statusConfig.CiWorkflow }
                'release' { $statusConfig.ReleaseWorkflow }
                'deploy' { $statusConfig.DeployWorkflow }
                default { $null }
            }
            foreach ($run in @(Get-WorkflowRuns -ServiceName $serviceName -Workflow $workflow -Count $Limit)) {
                $details = Get-RunDetails -ServiceName $serviceName -Id ([long]$run.databaseId)
                if (
                    [String]::IsNullOrWhiteSpace([string]$details.displayTitle) -and
                    -not [String]::IsNullOrWhiteSpace([string]$run.displayTitle)
                ) {
                    $details.displayTitle = [string]$run.displayTitle
                }
                $evidence = if (
                    $WorkflowKind -eq 'release' -and
                    $details.status -eq 'completed' -and
                    $details.conclusion -eq 'success'
                ) {
                    Get-RunEvidence `
                        -ServiceName $serviceName `
                        -Id ([long]$run.databaseId) `
                        -RequireConfigDigest:($serviceName -eq 'iwork') `
                        -RequireConfigArtifactDigest:($serviceName -eq 'iwork')
                }
                else {
                    [ordered]@{
                        Digests = @()
                        ImageDigest = $null
                        ConfigDigest = $null
                        ConfigArtifactDigest = $null
                    }
                }
                $result += ConvertTo-RunResult `
                    -ServiceName $serviceName `
                    -Run $details `
                    -Digests $evidence.Digests `
                    -ImageDigest $evidence.ImageDigest `
                    -ConfigDigest $evidence.ConfigDigest `
                    -ConfigArtifactDigest $evidence.ConfigArtifactDigest
            }
        }
        Complete-Result -Value $result
    }

    Assert-SingleService
    $config = $SERVICE_CONFIG[$Service]

    if ($Action -eq 'failed-log') {
        if ($RunId -le 0) {
            throw 'failed-log 动作必须提供正整数 -RunId。'
        }
        $details = Get-RunDetails -ServiceName $Service -Id $RunId
        $logResult = Invoke-GhCommand -Arguments @(
            'run', 'view', [string]$RunId,
            '--repo', $config.Repository,
            '--log-failed'
        )
        Complete-Result -Value ([ordered]@{
            Run = ConvertTo-RunResult -ServiceName $Service -Run $details
            FailedLog = Protect-SensitiveText -Text $logResult.Output
        })
    }

    if ($Action -eq 'production-status') {
        $runs = @()
        foreach ($run in @(Get-WorkflowRuns -ServiceName $Service -Workflow $config.DeployWorkflow -Count $Limit)) {
            $details = Get-RunDetails -ServiceName $Service -Id ([long]$run.databaseId)
            if (
                [String]::IsNullOrWhiteSpace([string]$details.displayTitle) -and
                -not [String]::IsNullOrWhiteSpace([string]$run.displayTitle)
            ) {
                $details.displayTitle = [string]$run.displayTitle
            }
            $evidence = if (
                $details.status -eq 'completed' -and
                $details.conclusion -eq 'success'
            ) {
                Get-RunEvidence -ServiceName $Service -Id ([long]$run.databaseId)
            }
            else {
                [ordered]@{
                    Digests = @()
                        ImageDigest = $null
                        ConfigDigest = $null
                        ConfigArtifactDigest = $null
                }
            }
            $runs += ConvertTo-RunResult `
                -ServiceName $Service `
                -Run $details `
                -Digests $evidence.Digests `
                -ImageDigest $evidence.ImageDigest `
                -ConfigDigest $evidence.ConfigDigest `
                -ConfigArtifactDigest $evidence.ConfigArtifactDigest
        }
        Complete-Result -Value ([ordered]@{
            EvidenceScope = 'GitHub Actions deployment evidence only; not live Docker health.'
            Runs = $runs
        })
    }

    $resolvedRevision = Resolve-Revision -ServiceName $Service

    if ($Action -eq 'ci') {
        $dispatchResult = Invoke-WorkflowDispatch `
            -ServiceName $Service `
            -Workflow $config.CiWorkflow `
            -ExpectedRevision $resolvedRevision
        Complete-Result `
            -ExitCode (Get-DispatchExitCode -DispatchResult $dispatchResult) `
            -Value (ConvertTo-RunResult `
                -ServiceName $Service `
                -Run $dispatchResult.Run `
                -RequestId $dispatchResult.RequestId)
    }

    if ($Action -eq 'release') {
        $ciRun = Assert-SuccessfulWorkflowForRevision `
            -ServiceName $Service `
            -Workflow $config.CiWorkflow `
            -ExpectedRevision $resolvedRevision `
            -Description '纯 CI' `
            -RequireWorkflowDispatch:($Service -eq 'iwork') `
            -ExpectedRequestId $(if ($Service -eq 'iwork') { $CiRequestId } else { $null })
        $releaseInputs = @{}
        if ($Service -eq 'iwork') {
            $releaseInputs['ci_request_id'] = Get-IworkRequestIdFromRun -Run $ciRun
        }
        $dispatchResult = Invoke-WorkflowDispatch `
            -ServiceName $Service `
            -Workflow $config.ReleaseWorkflow `
            -ExpectedRevision $resolvedRevision `
            -Inputs $releaseInputs
        $evidence = if ($dispatchResult.Run.status -eq 'completed' -and $dispatchResult.Run.conclusion -eq 'success') {
            Get-RunEvidence `
                -ServiceName $Service `
                -Id ([long]$dispatchResult.Run.databaseId) `
                -RequireConfigDigest:($Service -eq 'iwork') `
                -RequireConfigArtifactDigest:($Service -eq 'iwork')
        }
        else {
            [ordered]@{
                Digests = @()
                ImageDigest = $null
                ConfigDigest = $null
                ConfigArtifactDigest = $null
            }
        }
        Complete-Result `
            -ExitCode (Get-DispatchExitCode -DispatchResult $dispatchResult) `
            -Value (ConvertTo-RunResult `
                -ServiceName $Service `
                -Run $dispatchResult.Run `
                -Digests $evidence.Digests `
            -ImageDigest $evidence.ImageDigest `
            -ConfigDigest $evidence.ConfigDigest `
            -ConfigArtifactDigest $evidence.ConfigArtifactDigest `
            -RequestId $dispatchResult.RequestId)
    }

    if ($Action -notin @('preflight', 'deploy')) {
        throw "不支持的动作：$Action"
    }
    if ([String]::IsNullOrWhiteSpace($ChangeDescription)) {
        throw 'preflight/deploy 必须提供非空 -ChangeDescription。'
    }
    if ($Action -eq 'preflight' -and $RunMigrations) {
        throw 'preflight 只允许拉取和复验镜像，不接受数据库迁移开关。'
    }
    if ($Action -eq 'preflight' -and -not [String]::IsNullOrWhiteSpace($PreflightRunId)) {
        throw 'preflight 不接受已有预检Run绑定。'
    }
    if ($Action -eq 'deploy' -and $Service -eq 'iwork' -and [String]::IsNullOrWhiteSpace($PreflightRunId)) {
        throw 'iwork 正式部署必须提供成功的apply=false预检Run标识（-PreflightRunId）。'
    }

    Assert-SuccessfulWorkflowForRevision `
        -ServiceName $Service `
        -Workflow $config.CiWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Description '纯 CI' `
        -RequireWorkflowDispatch:($Service -eq 'iwork') | Out-Null
    $releaseRun = Assert-SuccessfulWorkflowForRevision `
        -ServiceName $Service `
        -Workflow $config.ReleaseWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Description 'GHCR 发布' `
        -RequireWorkflowDispatch:($Service -eq 'iwork') `
        -ExpectedRequestId $(if ($Service -eq 'iwork') { $ReleaseRequestId } else { $null })

    $inputs = @{}
    $dispatchRequestId = $null
    if ($Service -eq 'iwork') {
        $releaseRequestId = Get-IworkRequestIdFromRun -Run $releaseRun
        if (
            $Action -eq 'deploy' -and
            -not [String]::IsNullOrWhiteSpace($ApprovalText) -and
            [String]::IsNullOrWhiteSpace($RequestId)
        ) {
            $savedPreview = Get-ConfirmationPreviewState -ServiceName $Service
            if ($null -ne $savedPreview -and
                -not [String]::IsNullOrWhiteSpace([string]$savedPreview.RequestId)
            ) {
                $dispatchRequestId = Resolve-IworkRequestId `
                    -Candidate ([string]$savedPreview.RequestId)
            }
        }
        if ($null -eq $dispatchRequestId) {
            $dispatchRequestId = Resolve-IworkRequestId -Candidate $RequestId
        }
    }
    $preview = [ordered]@{
        Service = $Service
        Repository = $config.Repository
        Branch = $config.Branch
        Commit = $resolvedRevision
        Environment = $config.Environment
        ChangeDescription = $ChangeDescription.Trim()
        RunMigrations = [bool]$RunMigrations
    }
    if ($Service -eq 'iwork') {
        $preview['RequestId'] = $dispatchRequestId
    }

    if ($Service -eq 'iwork') {
        if ($ImageDigest -cnotmatch $DIGEST_PATTERN) {
            throw 'iwork 必须提供有效的 -ImageDigest。'
        }
        if ($ConfigDigest -cnotmatch $DIGEST_PATTERN) {
            throw 'iwork 必须提供有效的 -ConfigDigest。'
        }
        if ($ConfigArtifactDigest -cnotmatch $DIGEST_PATTERN) {
            throw 'iwork 必须提供有效的 -ConfigArtifactDigest。'
        }
        $publishedEvidence = Get-RunEvidence `
            -ServiceName $Service `
            -Id ([long]$releaseRun.databaseId) `
            -RequireConfigDigest `
            -RequireConfigArtifactDigest
        $publishedDigests = @($publishedEvidence.Digests)
        if ($publishedDigests.Count -ne 1 -or $publishedDigests[0] -cne $ImageDigest) {
            throw 'iwork 输入 Digest 与同一 Commit 的成功 GHCR 发布产物不一致，已停止触发。'
        }
        if ($publishedEvidence.ConfigDigest -cne $ConfigDigest) {
            throw 'iwork 输入 ConfigDigest 与同一 Commit 的成功配置发布产物不一致，已停止触发。'
        }
        if ($publishedEvidence.ConfigArtifactDigest -cne $ConfigArtifactDigest) {
            throw 'iwork 输入 ConfigArtifactDigest 与同一 Commit 的成功配置发布产物不一致，已停止触发。'
        }
        $preview['ImageDigest'] = $ImageDigest
        $preview['ConfigDigest'] = $ConfigDigest
        $preview['ConfigArtifactDigest'] = $ConfigArtifactDigest
        $preflightBinding = $null
        if ($Action -eq 'deploy') {
            $preflightBinding = Assert-SuccessfulPreflight `
                -ServiceName $Service `
                -Identifier $PreflightRunId `
                -ExpectedRevision $resolvedRevision `
                -ExpectedImageDigest $ImageDigest `
                -ExpectedConfigDigest $ConfigDigest `
                -ExpectedConfigArtifactDigest $ConfigArtifactDigest
            $preview['PreflightRunId'] = $preflightBinding.RunIdentifier
            $preview['PreflightRequestId'] = $preflightBinding.RequestId
        }
        $inputs = @{
            image_digest = $ImageDigest
            config_digest = $ConfigDigest
            config_artifact_digest = $ConfigArtifactDigest
            release_request_id = $releaseRequestId
            expected_revision = $resolvedRevision
            apply = if ($Action -eq 'deploy') { 'true' } else { 'false' }
            rollback_drill = 'false'
            run_migrations = if ($Action -eq 'deploy' -and $RunMigrations) { 'true' } else { 'false' }
            preflight_run_id = if ($Action -eq 'deploy') { $PreflightRunId } else { 'none' }
            preflight_request_id = if ($Action -eq 'deploy') { $preflightBinding.RequestId } else { 'none' }
            change_description = $ChangeDescription.Trim()
            confirmation = if ($Action -eq 'deploy' -and $RunMigrations) {
                'DEPLOY IWORK WITH MIGRATIONS'
            }
            elseif ($Action -eq 'deploy') {
                'DEPLOY IWORK'
            }
            else {
                'PREFLIGHT IWORK'
            }
        }
        $requiredApproval = if ($RunMigrations) {
            "DEPLOY IWORK WITH MIGRATIONS $resolvedRevision"
        }
        else {
            "DEPLOY IWORK $resolvedRevision"
        }
    }
    else {
        if ($PortalDigest -cnotmatch $DIGEST_PATTERN -or $ProxyDigest -cnotmatch $DIGEST_PATTERN) {
            throw 'Portal 必须同时提供有效的 -PortalDigest 和 -ProxyDigest。'
        }
        if ($RunMigrations) {
            throw 'Portal Workflow 不接受数据库迁移开关。'
        }
        $publishedEvidence = Get-RunEvidence -ServiceName $Service -Id ([long]$releaseRun.databaseId)
        $publishedDigests = @($publishedEvidence.Digests)
        if (
            $publishedDigests.Count -ne 2 -or
            $publishedDigests[0] -cne $PortalDigest -or
            $publishedDigests[1] -cne $ProxyDigest
        ) {
            throw 'Portal 输入 Digest 与同一 Commit 的成功 GHCR 发布产物不一致，已停止触发。'
        }
        Assert-PortalSmokeEvidence `
            -ExpectedRevision $resolvedRevision `
            -ExpectedPortalDigest $PortalDigest `
            -ExpectedProxyDigest $ProxyDigest
        $preview['PortalDigest'] = $PortalDigest
        $preview['ProxyDigest'] = $ProxyDigest
        $inputs = @{
            portal_digest = $PortalDigest
            proxy_digest = $ProxyDigest
            expected_revision = $resolvedRevision
            apply = if ($Action -eq 'deploy') { 'true' } else { 'false' }
            capability_drill = 'false'
            change_description = $ChangeDescription.Trim()
            confirmation = if ($Action -eq 'deploy') { 'DEPLOY PORTAL' } else { 'PREFLIGHT PORTAL' }
        }
        $requiredApproval = "DEPLOY PORTAL AND AUTHENTICATION $resolvedRevision"
    }

    if ($Action -eq 'deploy') {
        if ([String]::IsNullOrWhiteSpace($ApprovalText)) {
            Save-ConfirmationPreview `
                -ServiceName $Service `
                -Preview $preview `
                -RequiredApprovalText $requiredApproval `
                -RequestId $dispatchRequestId
            Complete-Result -ExitCode 4 -Value ([ordered]@{
                Status = 'confirmation_required'
                Preview = $preview
                RequiredApprovalText = $requiredApproval
                PreviewExpiresInMinutes = $CONFIRMATION_MAX_AGE_MINUTES
                Message = '请先向用户展示完整预览，并要求其逐字确认本次确认词。'
            })
        }
        if ($ApprovalText -cne $requiredApproval) {
            throw '生产部署确认词不匹配，已停止触发。'
        }
        $consumedPreview = Use-ConfirmationPreview `
            -ServiceName $Service `
            -Preview $preview `
            -RequiredApprovalText $requiredApproval
        if ($Service -eq 'iwork') {
            $dispatchRequestId = Resolve-IworkRequestId `
                -Candidate ([string]$consumedPreview.RequestId)
        }
    }

    $dispatchResult = Invoke-WorkflowDispatch `
        -ServiceName $Service `
        -Workflow $config.DeployWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Inputs $inputs `
        -RequestIdOverride $dispatchRequestId

    $digests = if ($Service -eq 'iwork') {
        @($ImageDigest)
    }
    else {
        @($PortalDigest, $ProxyDigest)
    }
    Complete-Result -ExitCode (Get-DispatchExitCode -DispatchResult $dispatchResult) -Value ([ordered]@{
        Preview = $preview
        Run = ConvertTo-RunResult `
            -ServiceName $Service `
            -Run $dispatchResult.Run `
            -Digests $digests `
            -ConfigDigest $(if ($Service -eq 'iwork') { $ConfigDigest } else { $null }) `
            -ConfigArtifactDigest $(if ($Service -eq 'iwork') { $ConfigArtifactDigest } else { $null }) `
            -RequestId $dispatchResult.RequestId
    })
}
catch {
    $message = Protect-SensitiveText -Text $_.Exception.Message
    Complete-Result -ExitCode 1 -Value ([ordered]@{
        Status = 'error'
        Action = $Action
        Service = $Service
        Message = $message
    })
}
