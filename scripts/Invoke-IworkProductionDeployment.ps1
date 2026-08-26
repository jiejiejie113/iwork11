[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Preflight', 'Deploy')]
    [string]$Mode,

    [string]$ImageDigest,
    [string]$ExpectedRevision,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$RunId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9-]+$')]
    [string]$Actor,

    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 500)]
    [string]$ChangeDescription,

    [ValidateSet('true', 'false')]
    [string]$RunMigrations = 'false',
    [ValidateSet('true', 'false')]
    [string]$RollbackDrill = 'false',
    [string]$ExpectedIdentity = 'DONGMING\shuju',
    [string]$IworkRoot = 'D:\DM\iwork',
    [string]$StateRoot = 'D:\DM\cicd-state\iwork',
    [string]$LockRoot = 'D:\DM\cicd-locks',
    [string]$MaintenanceFile = 'D:\DM\DTD_nginx\logs\watchdog\maintenance\iwork-deployment.json',
    [string]$WeeklyMaintenanceFile = 'D:\DM\DTD_nginx\logs\watchdog\maintenance\docker-weekly-restart.json',
    [string]$SecretsFile = 'D:\DM\dkt-secrets.env',
    [string]$WatchdogScript = 'D:\DM\DTD_nginx\scripts\docker-health-watchdog.ps1',
    [string]$DockerCommand = 'docker',
    [string]$ProductionMutexName = 'Global\DKT-Production-Deploy',
    [string]$RecoveryMutexName = 'Global\DKT-Docker-Recovery',
    [ValidateRange(1, 600)]
    [int]$HealthTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# ======
# 固定部署配置
$IMAGE_REPOSITORY = 'ghcr.io/guchenkano/iwork'
$COMPOSE_FILE = Join-Path $IworkRoot 'docker-compose.yml'
$PROFILE_FILE = Join-Path $IworkRoot 'env\production.env'
$DEPLOYMENT_LOCK_FILE = Join-Path $LockRoot 'production-deploy.lock'
$EXPECTED_CONTAINERS = @('DKT_iwork', 'DKT_iwork_alert_worker')
$RUN_MIGRATIONS_ENABLED = $RunMigrations -eq 'true'
$ROLLBACK_DRILL_ENABLED = $RollbackDrill -eq 'true'
$WATCHDOG_RECOVERY_MUTEX = 'Global\DKT-Docker-Recovery'
$ROLLBACK_DRILL_FILE = Join-Path $StateRoot 'rollback-drill-v1.json'
$COORDINATION_MODULE = Join-Path $PSScriptRoot 'ProductionCoordination.psm1'
Import-Module -Name $COORDINATION_MODULE -Force

function Invoke-DockerCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Docker Compose会把正常进度写入stderr。Windows PowerShell 5.1在
        # ErrorActionPreference=Stop时会先抛出NativeCommandError，导致退出码0
        # 的成功命令被误判失败，因此这里只按原生命令退出码决定成败。
        $ErrorActionPreference = 'Continue'
        $output = & $DockerCommand @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    if ($exitCode -ne 0) {
        $message = ($output | Out-String).Trim()
        throw "Docker命令失败（exit=$exitCode）：$($Arguments -join ' ')；$message"
    }
    return @($output)
}

function Assert-RequiredFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description 不存在：$Path"
    }
}

function Assert-ContainerHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )

    $stateJson = Invoke-DockerCommand -Arguments @(
        'inspect', $ContainerName, '--format', '{{json .State}}'
    )
    $state = (($stateJson -join "`n") | ConvertFrom-Json)
    if (-not $state.Running) {
        throw "容器未运行：$ContainerName"
    }
    if (-not $state.Health) {
        throw "容器缺少健康检查：$ContainerName"
    }
    if ($state.Health.Status -ne 'healthy') {
        throw "容器健康状态异常：$ContainerName ($($state.Health.Status))"
    }
}

function Archive-ExpiredIworkDeploymentMarker {
    <#
    .SYNOPSIS
    在已取得双Mutex和新协调锁后归档过期的iwork部署维护标记。
    #>
    param([Parameter(Mandatory = $true)][object]$CoordinationLock)

    if (-not (Test-Path -LiteralPath $MaintenanceFile -PathType Leaf)) { return }
    if ($CoordinationLock.Fields['service'] -cne 'iwork') {
        throw '当前协调锁不属于iwork，拒绝处理部署维护标记。'
    }
    try {
        $marker = Get-Content -LiteralPath $MaintenanceFile -Raw | ConvertFrom-Json
        if ($marker -isnot [pscustomobject]) {
            throw '标记不是JSON对象'
        }
        $workflowRunId = $marker.workflow_run_id
        $actor = $marker.actor
        $startedAtText = [string]$marker.started_at
        $expiresAtText = [string]$marker.expires_at
        $statusInvalid = (
            $marker.PSObject.Properties.Name -contains 'status' -and
            [string]$marker.status -ne 'running'
        )
        if (
            $marker.application -ne 'iwork' -or
            $marker.operation -ne 'production_deployment' -or
            $workflowRunId -isnot [string] -or
            [string]::IsNullOrWhiteSpace($workflowRunId.Trim()) -or
            $workflowRunId.Trim().Length -gt 128 -or
            $workflowRunId.Trim() -notmatch '^[-A-Za-z0-9._:]+$' -or
            $actor -isnot [string] -or
            [string]::IsNullOrWhiteSpace($actor.Trim()) -or
            $actor.Length -gt 128 -or
            $statusInvalid -or
            [string]::IsNullOrWhiteSpace($startedAtText) -or
            [string]::IsNullOrWhiteSpace($expiresAtText) -or
            $startedAtText -notmatch '(?:Z|[+-]\d{2}:\d{2})$' -or
            $expiresAtText -notmatch '(?:Z|[+-]\d{2}:\d{2})$'
        ) {
            throw '字段无效'
        }
        $startedAt = [DateTimeOffset]::MinValue
        $expiresAt = [DateTimeOffset]::MinValue
        if (
            -not [DateTimeOffset]::TryParse($startedAtText, [ref]$startedAt) -or
            -not [DateTimeOffset]::TryParse($expiresAtText, [ref]$expiresAt)
        ) {
            throw '维护时间无效'
        }
        $maintenanceMinutes = ($expiresAt - $startedAt).TotalMinutes
        if ($maintenanceMinutes -le 0 -or $maintenanceMinutes -gt 20) {
            throw '维护窗口无效'
        }
        if ($startedAt -gt [DateTimeOffset]::UtcNow) {
            throw '维护窗口尚未开始'
        }
    }
    catch {
        throw "已有iwork部署维护标记且无法可信解析，拒绝自动处理：$MaintenanceFile"
    }
    if ($expiresAt -gt [DateTimeOffset]::UtcNow) {
        throw "已有iwork部署维护标记：$MaintenanceFile"
    }

    $archivePath = '{0}.stale.{1}.{2}.json' -f @(
        $MaintenanceFile,
        [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ'),
        [Guid]::NewGuid().ToString('N')
    )
    [IO.File]::Move($MaintenanceFile, $archivePath)
}

function Assert-PreflightInputs {
    param([object]$CoordinationLock)
    if ($ImageDigest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'ImageDigest必须是sha256加64位小写十六进制。'
    }
    if ($ExpectedRevision -notmatch '^[0-9a-f]{40}$') {
        throw 'ExpectedRevision必须是40位小写Commit SHA。'
    }
    if ($Actor -cne 'GuChenkano') {
        throw "部署触发账号不正确：$Actor"
    }
    if ($ROLLBACK_DRILL_ENABLED -and $Mode -ne 'Deploy') {
        throw '受控回滚演练只能使用Deploy模式。'
    }
    if ($ROLLBACK_DRILL_ENABLED -and $RUN_MIGRATIONS_ENABLED) {
        throw '受控回滚演练禁止执行数据库迁移。'
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -ine $ExpectedIdentity) {
        throw "部署身份不正确：$identity"
    }

    Assert-RequiredFile -Path $COMPOSE_FILE -Description '生产Compose文件'
    Assert-RequiredFile -Path $PROFILE_FILE -Description '生产环境配置'
    Assert-RequiredFile -Path $SecretsFile -Description '中央密钥文件'
    Assert-RequiredFile -Path $WatchdogScript -Description 'Docker看门狗脚本'
    $watchdogContent = Get-Content -LiteralPath $WatchdogScript -Raw
    if ($watchdogContent -notmatch [Regex]::Escape($WATCHDOG_RECOVERY_MUTEX)) {
        throw "Docker看门狗未声明共享恢复锁：$WATCHDOG_RECOVERY_MUTEX"
    }

    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
        throw "部署状态目录不存在：$StateRoot"
    }
    if (-not (Test-Path -LiteralPath $LockRoot -PathType Container)) {
        throw "部署锁目录不存在：$LockRoot"
    }
    if (Test-Path -LiteralPath $MaintenanceFile -PathType Leaf) {
        if ($null -eq $CoordinationLock) {
            throw "已有iwork部署维护标记：$MaintenanceFile"
        }
        Archive-ExpiredIworkDeploymentMarker -CoordinationLock $CoordinationLock
    }
    if (Test-Path -LiteralPath $WeeklyMaintenanceFile -PathType Leaf) {
        throw "Docker周重启维护标记存在，拒绝开始iwork部署：$WeeklyMaintenanceFile"
    }
    if (
        $ROLLBACK_DRILL_ENABLED -and
        (Test-Path -LiteralPath $ROLLBACK_DRILL_FILE -PathType Leaf)
    ) {
        throw "受控回滚演练已经执行或启动过，拒绝重复执行：$ROLLBACK_DRILL_FILE"
    }
}

function Invoke-Preflight {
    param([object]$CoordinationLock)
    $startedAt = [DateTimeOffset]::UtcNow
    Assert-PreflightInputs -CoordinationLock $CoordinationLock
    $candidateImage = "$IMAGE_REPOSITORY@$ImageDigest"

    $null = Invoke-DockerCommand -Arguments @('info', '--format', '{{.ServerVersion}}')
    $labelsJson = Invoke-DockerCommand -Arguments @(
        'image', 'inspect', $candidateImage, '--format', '{{json .Config.Labels}}'
    )
    $labels = (($labelsJson -join "`n") | ConvertFrom-Json)
    $actualRevision = [string]$labels.'org.opencontainers.image.revision'
    if ($actualRevision -cne $ExpectedRevision) {
        throw "候选镜像OCI revision不匹配：$actualRevision"
    }

    Wait-IworkReleaseHealthy
    $containerBaseline = foreach ($containerName in $EXPECTED_CONTAINERS) {
        Assert-ContainerHealthy -ContainerName $containerName
        Get-ContainerBaseline -ContainerName $containerName
    }
    $containerBaseline = @($containerBaseline)

    $null = Invoke-DockerCommand -Arguments @(
        'compose',
        '--project-directory', $IworkRoot,
        '-f', $COMPOSE_FILE,
        '--env-file', $PROFILE_FILE,
        '--env-file', $SecretsFile,
        'config', '--quiet'
    )

    [pscustomobject]@{
        Mode = 'Preflight'
        RunId = $RunId
        Actor = $Actor
        CandidateImage = $candidateImage
        ExpectedRevision = $ExpectedRevision
        RunMigrations = $RUN_MIGRATIONS_ENABLED
        Containers = $EXPECTED_CONTAINERS
        ContainerBaseline = $containerBaseline
        Result = 'validated'
        PreviousWebImageId = $containerBaseline[0].ImageId
        PreviousAlertWorkerImageId = $containerBaseline[1].ImageId
        StateFile = $null
        DurationSeconds = [Math]::Round(
            ([DateTimeOffset]::UtcNow - $startedAt).TotalSeconds,
            1
        )
    } | ConvertTo-Json -Compress
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporaryPath = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $json = $Value | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText($temporaryPath, $json, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function New-RollbackDrillAttempt {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $json = $Value | ConvertTo-Json -Depth 8
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
    $stream = [IO.File]::Open(
        $ROLLBACK_DRILL_FILE,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ContainerImageId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )

    $output = Invoke-DockerCommand -Arguments @(
        'inspect', $ContainerName, '--format', '{{.Image}}'
    )
    $imageId = ($output -join '').Trim()
    if ($imageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "无法取得容器镜像ID：$ContainerName"
    }
    return $imageId
}

function Get-ContainerBaseline {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )

    $containerId = (
        Invoke-DockerCommand -Arguments @(
            'inspect', $ContainerName, '--format', '{{.Id}}'
        )
    ) -join ''
    $configuredImage = (
        Invoke-DockerCommand -Arguments @(
            'inspect', $ContainerName, '--format', '{{.Config.Image}}'
        )
    ) -join ''
    $restartCountText = (
        Invoke-DockerCommand -Arguments @(
            'inspect', $ContainerName, '--format', '{{.RestartCount}}'
        )
    ) -join ''
    $stateJson = Invoke-DockerCommand -Arguments @(
        'inspect', $ContainerName, '--format', '{{json .State}}'
    )
    $state = (($stateJson -join "`n") | ConvertFrom-Json)
    $imageId = Get-ContainerImageId -ContainerName $ContainerName

    $restartCount = 0
    if (-not [int]::TryParse($restartCountText.Trim(), [ref]$restartCount)) {
        throw "无法取得容器重启次数：$ContainerName"
    }

    return [ordered]@{
        Name = $ContainerName
        ContainerId = $containerId.Trim()
        ConfiguredImage = $configuredImage.Trim()
        ImageId = $imageId
        Status = [string]$state.Status
        Health = [string]$state.Health.Status
        RestartCount = $restartCount
    }
}

function Write-ComposeOverride {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$WebImage,

        [Parameter(Mandatory = $true)]
        [string]$AlertWorkerImage,

        [Parameter(Mandatory = $true)]
        [bool]$AllowMigrations
    )

    $migrationValue = $AllowMigrations.ToString().ToLowerInvariant()
    $content = @"
services:
  iwork:
    image: "$WebImage"
    environment:
      IWORK_RUN_MIGRATIONS: "$migrationValue"
  alert-worker:
    image: "$AlertWorkerImage"
"@
    [IO.File]::WriteAllText($Path, $content, [Text.UTF8Encoding]::new($false))
}

function Invoke-ComposeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$OverrideFile,

        [Parameter(Mandatory = $true)]
        [string[]]$CommandArguments
    )

    $arguments = @(
        'compose',
        '--project-directory', $IworkRoot,
        '--project-name', 'iwork',
        '-f', $COMPOSE_FILE,
        '-f', $OverrideFile,
        '--env-file', $PROFILE_FILE,
        '--env-file', $SecretsFile
    ) + $CommandArguments
    return Invoke-DockerCommand -Arguments $arguments
}

function Wait-IworkReleaseHealthy {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    do {
        try {
            foreach ($containerName in $EXPECTED_CONTAINERS) {
                Assert-ContainerHealthy -ContainerName $containerName
            }
            return
        }
        catch {
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                throw
            }
            Start-Sleep -Seconds 2
        }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw '等待iwork发布单元健康状态超时。'
}

function Assert-DeployedImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedImage
    )

    $output = Invoke-DockerCommand -Arguments @(
        'inspect', $ContainerName, '--format', '{{.Config.Image}}'
    )
    $actualImage = ($output -join '').Trim()
    if ($actualImage -cne $ExpectedImage) {
        throw "容器未使用预期镜像：$ContainerName；actual=$actualImage"
    }
}

function Assert-ContainerImageId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedImageId
    )

    $actualImageId = Get-ContainerImageId -ContainerName $ContainerName
    if ($actualImageId -cne $ExpectedImageId) {
        throw "容器底层镜像ID未恢复：$ContainerName；actual=$actualImageId"
    }
}

function Assert-IworkApplication {
    $null = Invoke-DockerCommand -Arguments @(
        'exec', 'DKT_iwork', 'python', 'manage.py', 'check', '--deploy'
    )
    $null = Invoke-DockerCommand -Arguments @(
        'exec', 'DKT_iwork', 'python', '-c',
        "import urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/',headers={'Host':'iwork'}); assert urllib.request.urlopen(r,timeout=10).status == 200"
    )
    $workerPing = Invoke-DockerCommand -Arguments @(
        'exec', 'DKT_iwork_alert_worker',
        'celery', '-A', 'iwork', 'inspect', 'ping', '--timeout', '5'
    )
    if (($workerPing -join "`n") -notmatch 'pong') {
        throw '告警Worker未返回pong。'
    }
}

function Enter-DeploymentMutex {
    <#
    .SYNOPSIS
    尝试立即取得指定的Windows互斥锁。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $mutex = [Threading.Mutex]::new($false, $Name)
    try {
        if (-not $mutex.WaitOne(0)) {
            $mutex.Dispose()
            throw "部署互斥锁已被占用：$Name"
        }
    }
    catch [Threading.AbandonedMutexException] {
        # 上一次持有者异常退出时，本次已取得互斥锁，继续由统一文件锁严格核验残留内容。
    }
    return $mutex
}

function Exit-DeploymentMutex {
    <#
    .SYNOPSIS
    释放指定的Windows互斥锁。
    #>
    param([Threading.Mutex]$Mutex)

    if ($null -ne $Mutex) {
        try {
            $Mutex.ReleaseMutex()
        }
        finally {
            $Mutex.Dispose()
        }
    }
}

function Protect-BackupFileAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $identities = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User,
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    foreach ($identity in $identities) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    [IO.FileInfo]::new($Path).SetAccessControl($acl)
}

function Backup-IworkDatabases {
    $backupDirectory = Join-Path $StateRoot "backups\$RunId"
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    $backupPath = Join-Path $backupDirectory 'mysql-before-migration.sql'
    $containerBackupPath = "/tmp/iwork-$RunId.sql"
    $dumpCommand = (
        'set -eu; umask 077; ' +
        'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" ' +
        '--single-transaction --routines --triggers --events --hex-blob ' +
        '--databases iwork_system iwork_local > ' +
        $containerBackupPath
    )

    try {
        $null = Invoke-DockerCommand -Arguments @(
            'exec', 'DKT_mysql', 'sh', '-c', $dumpCommand
        )
        $null = Invoke-DockerCommand -Arguments @(
            'cp', "DKT_mysql:$containerBackupPath", $backupPath
        )
        if (
            -not (Test-Path -LiteralPath $backupPath -PathType Leaf) -or
            (Get-Item -LiteralPath $backupPath).Length -le 0
        ) {
            throw '数据库备份文件不存在或为空。'
        }
        Protect-BackupFileAcl -Path $backupPath
        $stream = [IO.File]::OpenRead($backupPath)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $checksumBytes = $sha256.ComputeHash($stream)
            $checksum = ([BitConverter]::ToString($checksumBytes) -replace '-', '').ToLowerInvariant()
        }
        finally {
            $sha256.Dispose()
            $stream.Dispose()
        }
        return [pscustomobject]@{
            Path = $backupPath
            Sha256 = $checksum
        }
    }
    finally {
        try {
            $null = Invoke-DockerCommand -Arguments @(
                'exec', 'DKT_mysql', 'rm', '-f', $containerBackupPath
            )
        }
        catch {
            # 容器临时文件清理失败不得掩盖备份或部署的原始结果。
        }
    }
}

function Invoke-Deploy {
    $startedAt = [DateTimeOffset]::UtcNow
    $candidateImage = "$IMAGE_REPOSITORY@$ImageDigest"
    $stateFile = Join-Path $StateRoot "$RunId.json"
    $candidateOverride = Join-Path $StateRoot "$RunId.candidate.yml"
    $rollbackOverride = Join-Path $StateRoot "$RunId.rollback.yml"
    $webRollbackTag = "dkt-cicd/iwork-web-rollback:$RunId"
    $alertRollbackTag = "dkt-cicd/iwork-alert-worker-rollback:$RunId"
    $productionMutex = $null
    $recoveryMutex = $null
    $coordinationLock = $null
    $state = $null
    $switchAttempted = $false
    $ownsMaintenanceFile = $false
    $ownsDrillAttempt = $false
    $controlledRollbackRequested = $false
    $drillAttempt = $null
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()

    try {
        $productionMutex = Enter-DeploymentMutex -Name $ProductionMutexName
        $recoveryMutex = Enter-DeploymentMutex -Name $RecoveryMutexName
        $coordinationLock = Enter-ProductionCoordinationLock `
            -LockRoot $LockRoot `
            -Repository 'GuChenkano/iwork' `
            -Service 'iwork' `
            -RunId $RunId `
            -Actor $Actor `
            -ExpectedRevision $ExpectedRevision `
            -ArtifactDigests @{ iwork = $ImageDigest }
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'candidate_validation'
        $null = Invoke-Preflight -CoordinationLock $coordinationLock
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'preflight_complete'
        $previousContainers = foreach ($containerName in $EXPECTED_CONTAINERS) {
            Assert-ContainerHealthy -ContainerName $containerName
            Get-ContainerBaseline -ContainerName $containerName
        }
        $previousContainers = @($previousContainers)
        $previousWebImageId = $previousContainers[0].ImageId
        $previousAlertImageId = $previousContainers[1].ImageId
        $null = Invoke-DockerCommand -Arguments @('tag', $previousWebImageId, $webRollbackTag)
        $null = Invoke-DockerCommand -Arguments @('tag', $previousAlertImageId, $alertRollbackTag)

        if ($ROLLBACK_DRILL_ENABLED) {
            $drillAttempt = [ordered]@{
                Version = 1
                RunId = $RunId
                Actor = $Actor
                Status = 'started'
                CandidateImage = $candidateImage
                ExpectedRevision = $ExpectedRevision
                PreviousWebImageId = $previousWebImageId
                PreviousAlertWorkerImageId = $previousAlertImageId
                StartedAt = [DateTimeOffset]::UtcNow.ToString('o')
                CompletedAt = $null
                StateFile = $stateFile
                Error = $null
            }
            New-RollbackDrillAttempt -Value $drillAttempt
            $ownsDrillAttempt = $true
        }

        $state = [ordered]@{
            RunId = $RunId
            Actor = $Actor
            Mode = 'Deploy'
            Status = 'deploying'
            CandidateImage = $candidateImage
            ExpectedRevision = $ExpectedRevision
            RunMigrations = $RUN_MIGRATIONS_ENABLED
            RollbackDrill = $ROLLBACK_DRILL_ENABLED
            ChangeDescription = $ChangeDescription
            PreviousWebImageId = $previousWebImageId
            PreviousAlertWorkerImageId = $previousAlertImageId
            PreviousContainers = $previousContainers
            WebRollbackTag = $webRollbackTag
            AlertWorkerRollbackTag = $alertRollbackTag
            StartedAt = [DateTimeOffset]::UtcNow.ToString('o')
            CompletedAt = $null
            RollbackSucceeded = $false
            CleanupSucceeded = $true
            CleanupErrors = @()
            DatabaseBackupPath = $null
            DatabaseBackupSha256 = $null
        }
        Write-JsonAtomic -Path $stateFile -Value $state
        if ($RUN_MIGRATIONS_ENABLED) {
            $backup = Backup-IworkDatabases
            $state.DatabaseBackupPath = $backup.Path
            $state.DatabaseBackupSha256 = $backup.Sha256
            Write-JsonAtomic -Path $stateFile -Value $state
        }
        Write-ComposeOverride `
            -Path $candidateOverride `
            -WebImage $candidateImage `
            -AlertWorkerImage $candidateImage `
            -AllowMigrations $RUN_MIGRATIONS_ENABLED
        Write-ComposeOverride `
            -Path $rollbackOverride `
            -WebImage $webRollbackTag `
            -AlertWorkerImage $alertRollbackTag `
            -AllowMigrations $false

        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'switching'

        $maintenance = [ordered]@{
            application = 'iwork'
            operation = 'production_deployment'
            workflow_run_id = $RunId
            actor = $Actor
            started_at = [DateTimeOffset]::UtcNow.ToString('o')
            expires_at = [DateTimeOffset]::UtcNow.AddMinutes(20).ToString('o')
        }
        Write-JsonAtomic -Path $MaintenanceFile -Value $maintenance
        $ownsMaintenanceFile = $true

        $null = Invoke-ComposeCommand `
            -OverrideFile $candidateOverride `
            -CommandArguments @('config', '--quiet')
        $switchAttempted = $true
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'production_validation'
        $null = Invoke-ComposeCommand `
            -OverrideFile $candidateOverride `
            -CommandArguments @(
                'up', '-d', '--no-build', '--no-deps', 'iwork', 'alert-worker'
            )
        Wait-IworkReleaseHealthy
        Assert-DeployedImage -ContainerName 'DKT_iwork' -ExpectedImage $candidateImage
        Assert-DeployedImage `
            -ContainerName 'DKT_iwork_alert_worker' `
            -ExpectedImage $candidateImage
        Assert-IworkApplication

        if ($ROLLBACK_DRILL_ENABLED) {
            $controlledRollbackRequested = $true
            throw '受控回滚演练触发'
        }

        $state.Status = 'deployed'
        $state.CompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
        Write-JsonAtomic -Path $stateFile -Value $state
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'completed'

        [pscustomobject]@{
            Mode = 'Deploy'
            RunId = $RunId
            CandidateImage = $candidateImage
            Result = 'deployed'
            StateFile = $stateFile
            PreviousWebImageId = $previousWebImageId
            PreviousAlertWorkerImageId = $previousAlertImageId
            DurationSeconds = [Math]::Round(
                ([DateTimeOffset]::UtcNow - $startedAt).TotalSeconds,
                1
            )
        } | ConvertTo-Json -Compress
    }
    catch {
        $deploymentError = $_
        if ($null -ne $coordinationLock) {
            try {
                if ($switchAttempted) {
                    Update-ProductionCoordinationLock `
                        -Lock $coordinationLock `
                        -Phase 'automatic_rollback'
                }
                else {
                    Update-ProductionCoordinationLock `
                        -Lock $coordinationLock `
                        -Phase 'failed_before_switch'
                }
            }
            catch {
                $null = $cleanupErrors.Add(
                    "协调锁失败阶段更新失败：$($_.Exception.Message)"
                )
            }
        }
        if ($switchAttempted -and $null -ne $state) {
            try {
                $null = Invoke-ComposeCommand `
                    -OverrideFile $rollbackOverride `
                    -CommandArguments @(
                        'up', '-d', '--no-build', '--no-deps', 'iwork', 'alert-worker'
                )
                Wait-IworkReleaseHealthy
                Assert-DeployedImage `
                    -ContainerName 'DKT_iwork' `
                    -ExpectedImage $webRollbackTag
                Assert-DeployedImage `
                    -ContainerName 'DKT_iwork_alert_worker' `
                    -ExpectedImage $alertRollbackTag
                Assert-ContainerImageId `
                    -ContainerName 'DKT_iwork' `
                    -ExpectedImageId $previousWebImageId
                Assert-ContainerImageId `
                    -ContainerName 'DKT_iwork_alert_worker' `
                    -ExpectedImageId $previousAlertImageId
                Assert-IworkApplication
                $state.Status = 'rolled_back'
                $state.RollbackSucceeded = $true
            }
            catch {
                $state.Status = 'rollback_failed'
                $state.RollbackSucceeded = $false
                $state.RollbackError = $_.Exception.Message
            }
            $state.CompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
            $state.DeploymentError = $deploymentError.Exception.Message
            Write-JsonAtomic -Path $stateFile -Value $state
        }
        elseif ($null -ne $state) {
            $state.Status = 'failed_before_switch'
            $state.CompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
            $state.DeploymentError = $deploymentError.Exception.Message
            Write-JsonAtomic -Path $stateFile -Value $state
        }

        if ($ownsDrillAttempt) {
            $drillSucceeded = (
                $controlledRollbackRequested -and
                $null -ne $state -and
                $state.Status -eq 'rolled_back' -and
                $state.RollbackSucceeded
            )
            $drillAttempt.Status = if ($drillSucceeded) { 'succeeded' } else { 'failed' }
            $drillAttempt.CompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
            $drillAttempt.Error = if ($drillSucceeded) {
                $null
            }
            else {
                $deploymentError.Exception.Message
            }
            Write-JsonAtomic -Path $ROLLBACK_DRILL_FILE -Value $drillAttempt

            if ($drillSucceeded) {
                return [pscustomobject]@{
                    Mode = 'Deploy'
                    RunId = $RunId
                    CandidateImage = $candidateImage
                    Result = 'rolled_back'
                    RollbackDrill = $true
                    StateFile = $stateFile
                    PreviousWebImageId = $previousWebImageId
                    PreviousAlertWorkerImageId = $previousAlertImageId
                    DurationSeconds = [Math]::Round(
                        ([DateTimeOffset]::UtcNow - $startedAt).TotalSeconds,
                        1
                    )
                } | ConvertTo-Json -Compress
            }
        }

        if ($null -ne $state -and $state.Status -eq 'rollback_failed') {
            throw (
                '候选部署失败，且自动回滚失败：' +
                "$($state.RollbackError)；原始部署错误：" +
                $deploymentError.Exception.Message
            )
        }
        throw $deploymentError
    }
    finally {
        try {
            if ($ownsMaintenanceFile) {
                Remove-Item `
                    -LiteralPath $MaintenanceFile `
                    -Force `
                    -ErrorAction Stop
            }
        }
        catch {
            $null = $cleanupErrors.Add(
                "维护标记清理失败：$($_.Exception.Message)"
            )
        }

        try {
            if ($null -ne $coordinationLock) {
                Exit-ProductionCoordinationLock -Lock $coordinationLock
                $coordinationLock = $null
            }
        }
        catch {
            $null = $cleanupErrors.Add(
                "协调锁清理失败：$($_.Exception.Message)"
            )
        }

        try {
            Exit-DeploymentMutex -Mutex $recoveryMutex
        }
        catch {
            $null = $cleanupErrors.Add(
                "Recovery Mutex释放失败：$($_.Exception.Message)"
            )
        }

        try {
            Exit-DeploymentMutex -Mutex $productionMutex
        }
        catch {
            $null = $cleanupErrors.Add(
                "Production Mutex释放失败：$($_.Exception.Message)"
            )
        }

        if ($cleanupErrors.Count -gt 0) {
            if ($null -ne $state) {
                $state.Status = 'cleanup_failed'
                $state.CleanupSucceeded = $false
                $state.CleanupErrors = @($cleanupErrors)
                try {
                    Write-JsonAtomic -Path $stateFile -Value $state
                }
                catch {
                    $null = $cleanupErrors.Add(
                        "清理失败记录写入失败：$($_.Exception.Message)"
                    )
                }
            }
            throw (
                '部署清理失败：' + ($cleanupErrors -join '；')
            )
        }
    }
}

switch ($Mode) {
    'Preflight' {
        Invoke-Preflight
    }
    'Deploy' {
        Invoke-Deploy
    }
}
