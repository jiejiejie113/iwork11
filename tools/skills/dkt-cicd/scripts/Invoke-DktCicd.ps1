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
$RUN_DISCOVERY_TIMEOUT_SECONDS = 45
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
        [Parameter(Mandatory = $true)][string]$RequiredApprovalText
    )

    New-Item -ItemType Directory -Path $CONFIRMATION_STATE_ROOT -Force | Out-Null
    $statePath = Join-Path $CONFIRMATION_STATE_ROOT "$ServiceName.json"
    $tempPath = "$statePath.$([Guid]::NewGuid().ToString('N')).tmp"
    $createdAt = [DateTimeOffset]::UtcNow
    $state = [ordered]@{
        Service = $ServiceName
        Fingerprint = Get-PreviewFingerprint -Preview $Preview
        RequiredApprovalText = $RequiredApprovalText
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
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
            throw '未找到本次生产部署预览，请先不带确认词生成并展示完整预览。'
        }
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw '生产确认状态无法读取，已失败关闭；请重新生成完整预览。'
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
        '--json', 'databaseId,workflowName,displayTitle,status,conclusion,headSha,url,createdAt,startedAt,updatedAt,event'
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
        '--json', 'databaseId,workflowName,status,conclusion,headSha,url,createdAt,startedAt,updatedAt,jobs'
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
        [string[]]$Digests = @()
    )

    return [ordered]@{
        Service = $ServiceName
        Workflow = [string]$Run.workflowName
        RunId = [long]$Run.databaseId
        Status = [string]$Run.status
        Conclusion = [string]$Run.conclusion
        Commit = [string]$Run.headSha
        Digests = @($Digests)
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
        [Parameter(Mandatory = $true)][string]$Description
    )

    $successful = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 50 | Where-Object {
        $_.headSha -ceq $ExpectedRevision -and
        $_.status -eq 'completed' -and
        $_.conclusion -eq 'success'
    })
    if ($successful.Count -eq 0) {
        throw "没有找到同一 Commit 的成功$Description，已停止触发。"
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
        [Parameter(Mandatory = $true)][DateTimeOffset]$DispatchStartedAt
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RUN_DISCOVERY_TIMEOUT_SECONDS)
    do {
        $candidates = @(Get-WorkflowRuns -ServiceName $ServiceName -Workflow $Workflow -Count 20 | Where-Object {
            $_.headSha -ceq $ExpectedRevision -and
            $_.event -eq 'workflow_dispatch' -and
            [long]$_.databaseId -notin $PreviousRunIds -and
            [DateTimeOffset]::Parse([string]$_.createdAt) -ge $DispatchStartedAt.AddSeconds(-2)
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
                    [DateTimeOffset]::Parse([string]$_.createdAt) -ge $DispatchStartedAt.AddSeconds(-2)
                })
                if ($settledCandidates.Count -ne 1) {
                    throw 'Run 发现稳定窗口内出现并发歧义，无法安全关联本次触发。请人工核对现有 Run，禁止重复触发。'
                }
                return $settledCandidates[0]
            }
            return $candidates[0]
        }
        Start-Sleep -Seconds $RUN_DISCOVERY_INTERVAL_SECONDS
    } while ([DateTimeOffset]::UtcNow -lt $deadline)

    throw 'Workflow 已提交，但在限定时间内未发现对应 Run。请使用 status 动作核对，禁止重复触发。'
}

function Get-RunDigests {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][long]$Id
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
            'ghcr\.io/guchenkano/iwork@(?<digest>sha256:[0-9a-f]{64})'
        )
        $digests = @($matches | ForEach-Object { $_.Groups['digest'].Value } | Select-Object -Unique)
        if ($digests.Count -ne 1) {
            throw "iwork Run 日志必须提供一个唯一完整 Digest，实际：$($digests.Count)"
        }
        return $digests
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
    return @($digestsByImage['dtd-nginx'], $digestsByImage['dtd-oauth2-proxy'])
}

function Invoke-WorkflowDispatch {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$Workflow,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [hashtable]$Inputs = @{}
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
        $arguments = @(
            'workflow', 'run', $Workflow,
            '--repo', $config.Repository,
            '--ref', $config.Branch
        )
        foreach ($key in @($Inputs.Keys | Sort-Object)) {
            $arguments += @('-f', "$key=$($Inputs[$key])")
        }
        $dispatchStartedAt = [DateTimeOffset]::UtcNow
        Invoke-GhCommand -Arguments $arguments | Out-Null

        $run = Wait-ForNewWorkflowRun `
            -ServiceName $ServiceName `
            -Workflow $Workflow `
            -ExpectedRevision $ExpectedRevision `
            -PreviousRunIds $previousIds `
            -DispatchStartedAt $dispatchStartedAt
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
                $digests = if (
                    $WorkflowKind -eq 'release' -and
                    $details.status -eq 'completed' -and
                    $details.conclusion -eq 'success'
                ) {
                    @(Get-RunDigests -ServiceName $serviceName -Id ([long]$run.databaseId))
                }
                else {
                    @()
                }
                $result += ConvertTo-RunResult -ServiceName $serviceName -Run $details -Digests $digests
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
            $digests = if ($details.status -eq 'completed') {
                @(Get-RunDigests -ServiceName $Service -Id ([long]$run.databaseId))
            }
            else {
                @()
            }
            $runs += ConvertTo-RunResult -ServiceName $Service -Run $details -Digests $digests
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
            -Value (ConvertTo-RunResult -ServiceName $Service -Run $dispatchResult.Run)
    }

    if ($Action -eq 'release') {
        Assert-SuccessfulWorkflowForRevision `
            -ServiceName $Service `
            -Workflow $config.CiWorkflow `
            -ExpectedRevision $resolvedRevision `
            -Description '纯 CI' | Out-Null
        $dispatchResult = Invoke-WorkflowDispatch `
            -ServiceName $Service `
            -Workflow $config.ReleaseWorkflow `
            -ExpectedRevision $resolvedRevision
        $digests = if ($dispatchResult.Run.status -eq 'completed' -and $dispatchResult.Run.conclusion -eq 'success') {
            @(Get-RunDigests -ServiceName $Service -Id ([long]$dispatchResult.Run.databaseId))
        }
        else {
            @()
        }
        Complete-Result `
            -ExitCode (Get-DispatchExitCode -DispatchResult $dispatchResult) `
            -Value (ConvertTo-RunResult -ServiceName $Service -Run $dispatchResult.Run -Digests $digests)
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

    Assert-SuccessfulWorkflowForRevision `
        -ServiceName $Service `
        -Workflow $config.CiWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Description '纯 CI' | Out-Null
    $releaseRun = Assert-SuccessfulWorkflowForRevision `
        -ServiceName $Service `
        -Workflow $config.ReleaseWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Description 'GHCR 发布'

    $inputs = @{}
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
        if ($ImageDigest -cnotmatch $DIGEST_PATTERN) {
            throw 'iwork 必须提供有效的 -ImageDigest。'
        }
        $publishedDigests = @(Get-RunDigests -ServiceName $Service -Id ([long]$releaseRun.databaseId))
        if ($publishedDigests.Count -ne 1 -or $publishedDigests[0] -cne $ImageDigest) {
            throw 'iwork 输入 Digest 与同一 Commit 的成功 GHCR 发布产物不一致，已停止触发。'
        }
        $preview['ImageDigest'] = $ImageDigest
        $inputs = @{
            image_digest = $ImageDigest
            expected_revision = $resolvedRevision
            apply = if ($Action -eq 'deploy') { 'true' } else { 'false' }
            rollback_drill = 'false'
            run_migrations = if ($Action -eq 'deploy' -and $RunMigrations) { 'true' } else { 'false' }
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
        $publishedDigests = @(Get-RunDigests -ServiceName $Service -Id ([long]$releaseRun.databaseId))
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
            rollback_drill = 'false'
            rollback_drill_retry = 'false'
            rollback_drill_retry_of = 'none'
            rollback_drill_recovery = 'false'
            rollback_drill_recovery_of = 'none'
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
                -RequiredApprovalText $requiredApproval
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
        Use-ConfirmationPreview `
            -ServiceName $Service `
            -Preview $preview `
            -RequiredApprovalText $requiredApproval
    }

    $dispatchResult = Invoke-WorkflowDispatch `
        -ServiceName $Service `
        -Workflow $config.DeployWorkflow `
        -ExpectedRevision $resolvedRevision `
        -Inputs $inputs

    $digests = if ($Service -eq 'iwork') {
        @($ImageDigest)
    }
    else {
        @($PortalDigest, $ProxyDigest)
    }
    Complete-Result -ExitCode (Get-DispatchExitCode -DispatchResult $dispatchResult) -Value ([ordered]@{
        Preview = $preview
        Run = ConvertTo-RunResult -ServiceName $Service -Run $dispatchResult.Run -Digests $digests
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
