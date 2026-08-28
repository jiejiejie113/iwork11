Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PRODUCTION_COORDINATION_AUDIT_MUTEX = 'Global\DKT-Production-Coordination-Audit'
$PRODUCTION_COORDINATION_RUNNER_IDENTITY = 'DONGMING\shuju'

function New-ProductionCoordinationAuditMutexSecurity {
    <#
    .SYNOPSIS
    为生产协调审计Mutex创建SYSTEM、Runner和管理员共享ACL。
    #>
    $security = [Security.AccessControl.MutexSecurity]::new()
    $rights = [Security.AccessControl.MutexRights]::Modify -bor `
        [Security.AccessControl.MutexRights]::Synchronize
    $runnerSid = [Security.Principal.NTAccount]::new(
        $PRODUCTION_COORDINATION_RUNNER_IDENTITY
    ).Translate([Security.Principal.SecurityIdentifier])
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $identities = @(
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'),
        $runnerSid,
        $currentSid
    )
    $seen = @{}
    foreach ($identity in $identities) {
        if ($seen.ContainsKey($identity.Value)) { continue }
        $seen[$identity.Value] = $true
        $rule = [Security.AccessControl.MutexAccessRule]::new(
            $identity,
            $rights,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $security.AddAccessRule($rule)
    }
    return $security
}

function New-ProductionCoordinationAuditMutex {
    <#
    .SYNOPSIS
    创建或打开使用显式共享ACL的生产协调审计Mutex。

    .DESCRIPTION
    审计事件可能由不同受控身份写入同一日志。对旧对象短暂拒绝访问时仅做
    有界重试；超时仍失败关闭，不能把权限错误当作锁空闲。
    #>
    param(
        [ValidateRange(0, 60)]
        [int]$AccessDeniedRetrySeconds = 10
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($AccessDeniedRetrySeconds)
    while ($true) {
        try {
            $createdNew = $false
            $security = New-ProductionCoordinationAuditMutexSecurity
            return [Threading.Mutex]::new(
                $false,
                $PRODUCTION_COORDINATION_AUDIT_MUTEX,
                [ref]$createdNew,
                $security
            )
        }
        catch [UnauthorizedAccessException] {
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
                throw (
                    "无法访问生产协调审计互斥锁：$PRODUCTION_COORDINATION_AUDIT_MUTEX；" +
                    "当前身份：$identity；原始错误：$($_.Exception.Message)"
                )
            }
            Start-Sleep -Seconds 1
        }
    }
}

function ConvertTo-LockText {
    <#
    .SYNOPSIS
    将协调锁字段转换为稳定的UTF-8键值文本。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Fields
    )

    return (($Fields.GetEnumerator() | ForEach-Object {
        "$($_.Key)=$($_.Value)"
    }) -join "`n") + "`n"
}

function Write-LockStream {
    <#
    .SYNOPSIS
    在保持独占文件句柄期间完整刷新协调锁内容。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [IO.FileStream]$Stream,

        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Fields
    )

    $bytes = [Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-LockText -Fields $Fields))
    $Stream.Position = 0
    $Stream.SetLength(0)
    $Stream.Write($bytes, 0, $bytes.Length)
    $Stream.Flush($true)
}

function ConvertFrom-LockText {
    <#
    .SYNOPSIS
    严格解析协调锁键值文本，拒绝未知格式和重复字段。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $fields = [ordered]@{}
    foreach ($line in ($Text -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $match = [Regex]::Match($line, '^(?<name>[a-z0-9_]+)=(?<value>.*)$')
        if (-not $match.Success) {
            throw "生产部署锁包含无效行：$line"
        }
        $name = $match.Groups['name'].Value
        if ($fields.Contains($name)) {
            throw "生产部署锁包含重复字段：$name"
        }
        $fields[$name] = $match.Groups['value'].Value
    }
    return $fields
}

function Get-RequiredLockValue {
    <#
    .SYNOPSIS
    读取非空锁字段，字段缺失时严格失败。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Fields,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not $Fields.Contains($Name) -or [string]::IsNullOrWhiteSpace([string]$Fields[$Name])) {
        throw "生产部署锁缺少必要字段：$Name"
    }
    return [string]$Fields[$Name]
}

function ConvertTo-LockTimestamp {
    <#
    .SYNOPSIS
    将带时区的ISO时间转换为DateTimeOffset。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$FieldName
    )

    $parsed = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse(
        $Value,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind,
        [ref]$parsed
    )) {
        throw "生产部署锁时间字段无效：$FieldName"
    }
    if ($Value -notmatch '(Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "生产部署锁时间字段缺少时区：$FieldName"
    }
    return $parsed
}

function Get-GitHubWorkflowRunState {
    <#
    .SYNOPSIS
    只读查询GitHub Actions Run状态；任何不可确认结果均失败关闭。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [string]$WorkflowRunId
    )

    if (
        $env:GITHUB_REPOSITORY -ceq $Repository -and
        -not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)
    ) {
        $headers = @{
            Authorization = "Bearer $env:GITHUB_TOKEN"
            Accept = 'application/vnd.github+json'
            'X-GitHub-Api-Version' = '2022-11-28'
        }
        try {
            $response = Invoke-RestMethod `
                -UseBasicParsing `
                -Uri "https://api.github.com/repos/$Repository/actions/runs/$WorkflowRunId" `
                -Headers $headers `
                -Method Get `
                -TimeoutSec 30
            return [pscustomobject]@{
                Status = [string]$response.status
                Conclusion = [string]$response.conclusion
            }
        }
        catch {
            throw "无法确认原GitHub Actions Run状态：$Repository#$WorkflowRunId"
        }
    }

    $gh = Get-Command 'gh.exe' -ErrorAction SilentlyContinue
    if (-not $gh) {
        $gh = Get-Command 'gh' -ErrorAction SilentlyContinue
    }
    if (-not $gh) {
        throw '跨仓库Run核验需要已登录的GitHub CLI，当前不可用。'
    }
    $previousTimeout = $env:GH_HTTP_TIMEOUT
    $previousGhToken = $env:GH_TOKEN
    $previousGitHubToken = $env:GITHUB_TOKEN
    try {
        # 跨仓库查询必须使用Runner账号的持久gh凭据，不能误用当前仓库短期Token。
        $env:GH_TOKEN = $null
        $env:GITHUB_TOKEN = $null
        $env:GH_HTTP_TIMEOUT = '30'
        $json = & $gh.Source api "repos/$Repository/actions/runs/$WorkflowRunId" `
            --jq '{Status: .status, Conclusion: .conclusion}' 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($json -join ''))) {
            throw 'GitHub CLI查询失败。'
        }
        return (($json -join "`n") | ConvertFrom-Json)
    }
    catch {
        throw "无法确认原GitHub Actions Run状态：$Repository#$WorkflowRunId"
    }
    finally {
        $env:GH_HTTP_TIMEOUT = $previousTimeout
        $env:GH_TOKEN = $previousGhToken
        $env:GITHUB_TOKEN = $previousGitHubToken
    }
}

function Archive-StaleCoordinationLock {
    <#
    .SYNOPSIS
    在锁过期、原进程终止且原Run完成后原子归档残留锁。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [scriptblock]$RunStateResolver
    )

    $fields = ConvertFrom-LockText -Text (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop)
    $required = @(
        'schema', 'repository', 'service', 'run_id', 'workflow_run_id',
        'run_attempt', 'actor', 'owner_pid', 'owner_process_started_at',
        'host', 'expected_revision', 'phase', 'created_at', 'updated_at', 'expires_at'
    )
    foreach ($name in $required) {
        $null = Get-RequiredLockValue -Fields $fields -Name $name
    }
    if ($fields['schema'] -cne 'production-deploy-lock-v1') {
        throw "不支持的生产部署锁Schema：$($fields['schema'])"
    }
    $allowedOwners = @{
        'GuChenkano/DTD_nginx' = 'portal'
        'GuChenkano/iwork' = 'iwork'
    }
    if (
        -not $allowedOwners.ContainsKey([string]$fields['repository']) -or
        $allowedOwners[[string]$fields['repository']] -cne [string]$fields['service']
    ) {
        throw '生产部署锁仓库与服务身份无效。'
    }
    $runMatch = [Regex]::Match(
        [string]$fields['run_id'],
        '^(?<workflow>[0-9]+)-(?<attempt>[1-9][0-9]*)$'
    )
    if (
        -not $runMatch.Success -or
        $runMatch.Groups['workflow'].Value -cne [string]$fields['workflow_run_id'] -or
        $runMatch.Groups['attempt'].Value -cne [string]$fields['run_attempt']
    ) {
        throw '生产部署锁Run字段不一致。'
    }
    if ([string]$fields['expected_revision'] -notmatch '^[0-9a-f]{40}$') {
        throw '生产部署锁Commit SHA无效。'
    }
    if ([string]$fields['phase'] -notmatch '^[a-z0-9_]+$') {
        throw '生产部署锁阶段字段无效。'
    }
    if ($fields['host'] -ine [Environment]::MachineName) {
        throw "生产部署锁来自其他主机，拒绝自动接管：$($fields['host'])"
    }

    $createdAt = ConvertTo-LockTimestamp -Value $fields['created_at'] -FieldName 'created_at'
    $updatedAt = ConvertTo-LockTimestamp -Value $fields['updated_at'] -FieldName 'updated_at'
    $expiresAt = ConvertTo-LockTimestamp -Value $fields['expires_at'] -FieldName 'expires_at'
    if (
        $updatedAt -lt $createdAt -or
        $expiresAt -le $updatedAt -or
        ($expiresAt - $updatedAt).TotalMinutes -gt 180
    ) {
        throw '生产部署锁租约时间顺序或时长无效。'
    }
    if ($expiresAt -gt [DateTimeOffset]::UtcNow) {
        throw "生产部署锁仍在有效期内：$Path"
    }

    $ownerPid = 0
    if (-not [int]::TryParse($fields['owner_pid'], [ref]$ownerPid) -or $ownerPid -le 0) {
        throw '生产部署锁owner_pid无效。'
    }
    $ownerStartedAt = ConvertTo-LockTimestamp `
        -Value $fields['owner_process_started_at'] `
        -FieldName 'owner_process_started_at'
    $ownerProcess = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    if ($ownerProcess) {
        try {
            $actualStartedAt = ([DateTimeOffset]$ownerProcess.StartTime).ToUniversalTime()
        }
        catch {
            throw "无法核验生产部署锁原进程：PID $ownerPid"
        }
        if ([Math]::Abs(($actualStartedAt - $ownerStartedAt).TotalSeconds) -lt 1) {
            throw "生产部署锁原进程仍在运行：PID $ownerPid"
        }
    }

    $runState = & $RunStateResolver $fields['repository'] $fields['workflow_run_id']
    if (-not $runState -or [string]$runState.Status -cne 'completed') {
        throw "原GitHub Actions Run尚未完成，拒绝接管：$($fields['repository'])#$($fields['workflow_run_id'])"
    }
    $terminalConclusions = @(
        'success', 'failure', 'cancelled', 'timed_out', 'action_required',
        'stale', 'neutral', 'skipped', 'startup_failure'
    )
    if ([string]$runState.Conclusion -notin $terminalConclusions) {
        throw "原GitHub Actions Run终态无效，拒绝接管：$($fields['repository'])#$($fields['workflow_run_id'])"
    }

    $archiveName = 'production-deploy.stale.{0}.{1}.lock' -f @(
        [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ'),
        $fields['run_id']
    )
    $archivePath = Join-Path (Split-Path -Parent $Path) $archiveName
    [IO.File]::Move($Path, $archivePath)
    return $archivePath
}

function Write-ProductionCoordinationEvent {
    <#
    .SYNOPSIS
    追加不含凭据的协调事件，供Run级运维审计使用。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$EventPath,

        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Fields,

        [Parameter(Mandatory = $true)]
        [string]$Event,

        [Parameter(Mandatory = $true)]
        [string]$Result
    )

    $record = [ordered]@{
        schema = 'production-coordination-event-v1'
        timestamp = [DateTimeOffset]::UtcNow.ToString('o')
        event = $Event
        result = $Result
        repository = [string]$Fields['repository']
        service = [string]$Fields['service']
        run_id = [string]$Fields['run_id']
        workflow_run_id = [string]$Fields['workflow_run_id']
        actor = [string]$Fields['actor']
        owner_pid = [string]$Fields['owner_pid']
        phase = [string]$Fields['phase']
    }
    if ($Fields.Contains('request_id')) {
        $record.request_id = [string]$Fields['request_id']
    }
    foreach ($fieldName in @($Fields.Keys | Where-Object { [string]$_ -like 'artifact_*' } | Sort-Object)) {
        $record[[string]$fieldName] = [string]$Fields[$fieldName]
    }
    $json = ($record | ConvertTo-Json -Compress) + "`n"
    $mutex = New-ProductionCoordinationAuditMutex
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds(10))
        }
        catch [Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw '等待生产协调审计锁超时。'
        }
        [IO.File]::AppendAllText(
            $EventPath,
            $json,
            [Text.UTF8Encoding]::new($false)
        )
    }
    finally {
        if ($acquired) {
            try { $mutex.ReleaseMutex() }
            catch { }
        }
        $mutex.Dispose()
    }
}

function Enter-ProductionCoordinationLock {
    <#
    .SYNOPSIS
    原子取得跨仓库生产部署文件锁并写入统一Schema。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$LockRoot,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[a-z0-9-]+$')]
        [string]$Service,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^(?<workflow>[0-9]+)-(?<attempt>[1-9][0-9]*)$')]
        [string]$RunId,

        [Parameter(Mandatory = $true)]
        [string]$Actor,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[0-9a-f]{40}$')]
        [string]$ExpectedRevision,

        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$ArtifactDigests,

        [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
        [string]$RequestId,

        [scriptblock]$RunStateResolver = ${function:Get-GitHubWorkflowRunState},

        [ValidateRange(1, 180)]
        [int]$LeaseMinutes = 30
    )

    New-Item -ItemType Directory -Path $LockRoot -Force | Out-Null
    $lockPath = Join-Path $LockRoot 'production-deploy.lock'
    $eventPath = Join-Path $LockRoot 'production-coordination.jsonl'
    $runMatch = [Regex]::Match($RunId, '^(?<workflow>[0-9]+)-(?<attempt>[1-9][0-9]*)$')
    $attemptFields = [ordered]@{
        repository = $Repository
        service = $Service
        run_id = $RunId
        workflow_run_id = $runMatch.Groups['workflow'].Value
        actor = $Actor
        owner_pid = $PID
        phase = 'acquire_attempt'
    }
    if (-not [String]::IsNullOrWhiteSpace($RequestId)) {
        $attemptFields['request_id'] = $RequestId
    }
    Write-ProductionCoordinationEvent `
        -EventPath $eventPath `
        -Fields $attemptFields `
        -Event 'acquire_attempt' `
        -Result 'started'
    if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
        Write-ProductionCoordinationEvent `
            -EventPath $eventPath `
            -Fields $attemptFields `
            -Event 'contention' `
            -Result 'lock_file_exists'
        try {
            $archivePath = Archive-StaleCoordinationLock `
                -Path $lockPath `
                -RunStateResolver $RunStateResolver
        }
        catch {
            Write-ProductionCoordinationEvent `
                -EventPath $eventPath `
                -Fields $attemptFields `
                -Event 'stale_rejected' `
                -Result 'fail_closed'
            throw
        }
        Write-ProductionCoordinationEvent `
            -EventPath $eventPath `
            -Fields $attemptFields `
            -Event 'stale_archived' `
            -Result (Split-Path -Leaf $archivePath)
    }
    $stream = $null
    $createdLock = $false
    try {
        $stream = [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read
        )
        $createdLock = $true
        $now = [DateTimeOffset]::UtcNow
        $process = Get-Process -Id $PID -ErrorAction Stop
        $fields = [ordered]@{
            schema = 'production-deploy-lock-v1'
            repository = $Repository
            service = $Service
            run_id = $RunId
            workflow_run_id = $runMatch.Groups['workflow'].Value
            run_attempt = $runMatch.Groups['attempt'].Value
            actor = $Actor
            owner_pid = $PID
            owner_process_started_at = ([DateTimeOffset]$process.StartTime).ToUniversalTime().ToString('o')
            host = [Environment]::MachineName
            expected_revision = $ExpectedRevision
        }
        if (-not [String]::IsNullOrWhiteSpace($RequestId)) {
            $fields['request_id'] = $RequestId
        }
        foreach ($name in @($ArtifactDigests.Keys | Sort-Object)) {
            $fields["artifact_$name"] = [string]$ArtifactDigests[$name]
        }
        $fields['phase'] = 'acquired'
        $fields['created_at'] = $now.ToString('o')
        $fields['updated_at'] = $now.ToString('o')
        $fields['expires_at'] = $now.AddMinutes($LeaseMinutes).ToString('o')
        Write-LockStream -Stream $stream -Fields $fields
        Write-ProductionCoordinationEvent `
            -EventPath $eventPath `
            -Fields $fields `
            -Event 'acquired' `
            -Result 'success'

        return [pscustomobject]@{
            Path = $lockPath
            Stream = $stream
            Fields = $fields
            LeaseMinutes = $LeaseMinutes
            EventPath = $eventPath
        }
    }
    catch {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($createdLock -and (Test-Path -LiteralPath $lockPath)) {
            Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Update-ProductionCoordinationLock {
    <#
    .SYNOPSIS
    更新当前协调锁阶段并续租，同时写入阶段审计事件。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Lock,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[a-z0-9_]+$')]
        [string]$Phase
    )

    $now = [DateTimeOffset]::UtcNow
    $Lock.Fields['phase'] = $Phase
    $Lock.Fields['updated_at'] = $now.ToString('o')
    $Lock.Fields['expires_at'] = $now.AddMinutes([int]$Lock.LeaseMinutes).ToString('o')
    Write-LockStream -Stream $Lock.Stream -Fields $Lock.Fields
    Write-ProductionCoordinationEvent `
        -EventPath $Lock.EventPath `
        -Fields $Lock.Fields `
        -Event 'phase_updated' `
        -Result 'success'
}

function Exit-ProductionCoordinationLock {
    <#
    .SYNOPSIS
    释放当前进程持有的协调锁并严格确认锁文件已清理。
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Lock
    )

    try {
        $Lock.Stream.Dispose()
        Remove-Item -LiteralPath $Lock.Path -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $Lock.Path) {
            throw "生产部署锁清理后仍存在：$($Lock.Path)"
        }
    }
    catch {
        $cleanupError = $_
        try {
            Write-ProductionCoordinationEvent `
                -EventPath $Lock.EventPath `
                -Fields $Lock.Fields `
                -Event 'cleanup_failed' `
                -Result 'fail_closed'
        }
        catch {
            # 审计写入失败不得掩盖原始锁清理错误。
        }
        throw $cleanupError
    }
    Write-ProductionCoordinationEvent `
        -EventPath $Lock.EventPath `
        -Fields $Lock.Fields `
        -Event 'released' `
        -Result 'success'
}

Export-ModuleMember -Function @(
    'Enter-ProductionCoordinationLock',
    'Update-ProductionCoordinationLock',
    'Exit-ProductionCoordinationLock'
)
