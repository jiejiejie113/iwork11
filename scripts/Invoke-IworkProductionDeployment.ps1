[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Preflight', 'Deploy')]
    [string]$Mode,

    [string]$ImageDigest,
    [string]$ExpectedRevision,
    [string]$ConfigDigest,
    [string]$ConfigBundlePath,
    [string]$ConfigArtifactDigest,
    [string]$PreflightRunId = 'none',
    [string]$PreflightRequestId = 'none',

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string]$RequestId,

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
    [string]$WatchdogSha256 = '',
    [string]$WatchdogManifestPath = '',
    [string]$WatchdogManifestSha256 = '',
    [string]$WatchdogTaskName = '',
    [string]$WatchdogTaskPath = '\',
    [string]$ExternalProbeUri = '',
    [string]$ExternalProbeReceiptPath = '',
    [string]$ExternalProbeAuthorizationEnvVar = '',
    [string]$ExternalProbeProducerPath = '',
    [string]$ExternalProbeProducerSha256 = '',
    [string]$ExternalProbeSigningSecretFile = '',
    [string]$ExternalProbeSigningSecretSha256 = '',
    [string]$ExternalProbeProducerExpectedIdentity = '',
    [string]$TrustManifestPath = '',
    [string]$TrustManifestSha256 = '',
    [ValidateRange(1, 3600)]
    [int]$ExternalProbeMaxAgeSeconds = 300,
    [ValidateRange(1, 600)]
    [int]$ExternalProbeTimeoutSeconds = 30,
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
$DEPLOYMENT_LOCK_FILE = Join-Path $LockRoot 'production-deploy.lock'
$RELEASE_CONFIG_ROOT = Join-Path $StateRoot 'release-config'
$REQUEST_CONSUMPTION_ROOT = Join-Path $StateRoot 'request-consumption'
$ACTIVE_RELEASE_FILE = Join-Path $StateRoot 'active-release.json'
$LEGACY_COMPOSE_FILE = Join-Path $IworkRoot 'docker-compose.yml'
$LEGACY_PROFILE_FILE = Join-Path $IworkRoot 'env\production.env'
$EXPECTED_CONTAINERS = @('DKT_iwork', 'DKT_iwork_alert_worker')
$RUN_MIGRATIONS_ENABLED = $RunMigrations -eq 'true'
$ROLLBACK_DRILL_ENABLED = $RollbackDrill -eq 'true'
$WATCHDOG_RECOVERY_MUTEX = 'Global\DKT-Docker-Recovery'
$WATCHDOG_MECHANISM_SCHEMA = 'dkt-docker-health-watchdog/v1'
$WATCHDOG_EXECUTION_IDENTITY = 'NT AUTHORITY\SYSTEM'
$EXTERNAL_PROBE_CONTRACT_ID = 'iwork-external-probes-v2'
$OWNER_ACL_TRUST_SCHEMA = 'iwork-owner-acl/v1'
$OWNER_ACL_POLICY_ID = 'iwork-production-trust-v1'
$OWNER_ACL_BLOCKED_SIDS = @(
    'S-1-1-0',       # Everyone
    'S-1-5-11',      # Authenticated Users
    'S-1-5-32-544',  # Administrators
    'S-1-5-32-545'   # Users
)
# 只把会改变对象内容、权限或所有权的位纳入写权限判断，避免把Write/Modify复合值误判。
$OWNER_ACL_WRITE_RIGHTS = [long](
    [Security.AccessControl.FileSystemRights]::WriteData -bor
    [Security.AccessControl.FileSystemRights]::AppendData -bor
    [Security.AccessControl.FileSystemRights]::WriteAttributes -bor
    [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
    [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
    [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
)
$OWNER_ACL_READ_RIGHTS = [long](
    [Security.AccessControl.FileSystemRights]::ReadData -bor
    [Security.AccessControl.FileSystemRights]::ListDirectory -bor
    [Security.AccessControl.FileSystemRights]::ReadAttributes -bor
    [Security.AccessControl.FileSystemRights]::ReadExtendedAttributes -bor
    [Security.AccessControl.FileSystemRights]::ReadPermissions -bor
    [Security.AccessControl.FileSystemRights]::ExecuteFile -bor
    [Security.AccessControl.FileSystemRights]::Synchronize
)
$OWNER_ACL_ALLOWED_RIGHTS = $OWNER_ACL_WRITE_RIGHTS -bor $OWNER_ACL_READ_RIGHTS
$EXTERNAL_PROBE_NAMES = @(
    'https_nginx',
    'oidc_discovery',
    'sse_first_event',
    'sse_heartbeat',
    'business_read',
    'notification_chain'
)
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

function Invoke-DockerCommandWithProfile {
    <#
    .SYNOPSIS
    在单次Compose调用期间固定服务env_file为已验证配置包文件。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ProfileFile,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousProfile = $env:IWORK_RELEASE_PROFILE_FILE
    $hadPreviousProfile = Test-Path -LiteralPath Env:IWORK_RELEASE_PROFILE_FILE
    try {
        $env:IWORK_RELEASE_PROFILE_FILE = $ProfileFile
        return Invoke-DockerCommand -Arguments $Arguments
    }
    finally {
        if ($hadPreviousProfile) {
            $env:IWORK_RELEASE_PROFILE_FILE = $previousProfile
        }
        else {
            Remove-Item `
                -LiteralPath Env:IWORK_RELEASE_PROFILE_FILE `
                -ErrorAction SilentlyContinue
        }
    }
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

function Get-Sha256 {
    <#
    .SYNOPSIS
    计算文件的小写SHA-256。
    #>
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($stream)
        return (
            [BitConverter]::ToString($hash) -replace '-', ''
        ).ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Get-CanonicalTextSha256 {
    <#
    .SYNOPSIS
    规范化UTF-8文本的BOM和换行后计算SHA-256。
    #>
    param([Parameter(Mandatory = $true)][string]$Path)

    $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
    try {
        $text = $strictUtf8.GetString([IO.File]::ReadAllBytes($Path))
    }
    catch {
        throw "配置文件不是有效UTF-8：$Path"
    }
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
        $text = $text.Substring(1)
    }
    $text = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return (
            [BitConverter]::ToString($sha256.ComputeHash($bytes)) -replace '-', ''
        ).ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-ConfigDigestValue {
    <#
    .SYNOPSIS
    按固定字段和LF编码计算生产配置逻辑Digest。
    #>
    param([Parameter(Mandatory = $true)][object]$Manifest)

    $canonical = @(
        "schema=$($Manifest.schema)"
        "application=$($Manifest.application)"
        "source_commit=$($Manifest.source_commit)"
        "image_digest=$($Manifest.image_digest)"
        "compose_sha256=$($Manifest.compose_sha256)"
        "production_env_sha256=$($Manifest.production_env_sha256)"
    ) -join "`n"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes("$canonical`n")
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($bytes)
        return 'sha256:' + (
            [BitConverter]::ToString($hash) -replace '-', ''
        ).ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Assert-ProductionConfigBundle {
    <#
    .SYNOPSIS
    验证配置包结构、清单、来源身份、文件哈希和敏感键边界。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$BundlePath,
        [Parameter(Mandatory = $true)][string]$ExpectedConfigDigest,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceCommit,
        [Parameter(Mandatory = $true)][string]$ExpectedImageDigest
    )

    if (-not (Test-Path -LiteralPath $BundlePath -PathType Container)) {
        throw "生产配置包目录不存在：$BundlePath"
    }
    $rootItem = Get-Item -LiteralPath $BundlePath -Force
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '生产配置包根目录不能是重解析点。'
    }
    $rootFullPath = [IO.Path]::GetFullPath($rootItem.FullName).TrimEnd('\') + '\'
    $allowedFiles = @(
        'config-manifest.json',
        'docker-compose.yml',
        'env/production.env'
    )
    $actualFiles = @()
    foreach ($item in Get-ChildItem -LiteralPath $BundlePath -Recurse -Force) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "生产配置包包含重解析点：$($item.FullName)"
        }
        $fullPath = [IO.Path]::GetFullPath($item.FullName)
        if (-not $fullPath.StartsWith($rootFullPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "生产配置包路径越界：$fullPath"
        }
        if (-not $item.PSIsContainer) {
            $actualFiles += $fullPath.Substring($rootFullPath.Length).Replace('\', '/')
        }
    }
    $unexpectedFiles = @($actualFiles | Where-Object { $_ -notin $allowedFiles })
    $missingFiles = @($allowedFiles | Where-Object { $_ -notin $actualFiles })
    if ($unexpectedFiles.Count -gt 0 -or $missingFiles.Count -gt 0) {
        throw (
            '生产配置包文件集合不符合契约；unexpected=' +
            ($unexpectedFiles -join ',') + '; missing=' + ($missingFiles -join ',')
        )
    }

    $manifestPath = Join-Path $BundlePath 'config-manifest.json'
    $composePath = Join-Path $BundlePath 'docker-compose.yml'
    $profilePath = Join-Path $BundlePath 'env\production.env'
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw '生产配置清单不是有效JSON对象。'
    }
    $requiredFields = @(
        'schema', 'application', 'source_commit', 'image_digest',
        'compose_sha256', 'production_env_sha256', 'config_digest'
    )
    $manifestFields = @($manifest.PSObject.Properties.Name)
    if (
        @($requiredFields | Where-Object { $_ -notin $manifestFields }).Count -gt 0 -or
        @($manifestFields | Where-Object { $_ -notin $requiredFields }).Count -gt 0
    ) {
        throw '生产配置清单字段集合不符合固定Schema。'
    }
    if ($manifest.schema -cne 'iwork-production-config/v1') {
        throw "生产配置Schema不受支持：$($manifest.schema)"
    }
    if ($manifest.application -cne 'iwork') {
        throw "生产配置应用标识不正确：$($manifest.application)"
    }
    if ([string]$manifest.source_commit -cne $ExpectedSourceCommit) {
        throw '生产配置包Commit与候选提交不一致。'
    }
    if ([string]$manifest.image_digest -cne $ExpectedImageDigest) {
        throw '生产配置包镜像Digest与候选镜像不一致。'
    }
    $composeSha = Get-Sha256 -Path $composePath
    $profileSha = Get-Sha256 -Path $profilePath
    if ([string]$manifest.compose_sha256 -cne $composeSha) {
        throw '生产Compose文件SHA-256不匹配。'
    }
    if ([string]$manifest.production_env_sha256 -cne $profileSha) {
        throw '生产环境配置SHA-256不匹配。'
    }
    $calculatedDigest = Get-ConfigDigestValue -Manifest $manifest
    if (
        [string]$manifest.config_digest -cne $calculatedDigest -or
        $ExpectedConfigDigest -cne $calculatedDigest
    ) {
        throw '生产配置逻辑Digest不匹配。'
    }

    foreach ($line in Get-Content -LiteralPath $profilePath) {
        if ($line -match '^\s*(?:#|$)') { continue }
        if ($line -notmatch '^([A-Z][A-Z0-9_]*)=') {
            throw '生产环境配置包含无效键。'
        }
        $key = $Matches[1]
        if ($key -match '(?i)(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|CERTIFICATE|COOKIE)') {
            throw "生产配置包禁止包含敏感键：$key"
        }
        if ($line -match '(?i)BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY') {
            throw '生产配置包禁止包含私钥内容。'
        }
    }

    foreach ($line in Get-Content -LiteralPath $composePath) {
        $trimmed = $line.Trim()
        if ($trimmed -match '^(?:-\s*)?(?<key>[A-Z][A-Z0-9_]*)\s*(?:=|:)\s*(?<value>.*)$') {
            $key = $Matches['key']
            $value = $Matches['value'].Trim()
            if ($key -notmatch '(?i)(PASSWORD|SECRET|TOKEN|PRIVATE_KEY|CERTIFICATE|COOKIE)') {
                continue
            }
            if ($value -notmatch '^[''\"]?\$\{[A-Z][A-Z0-9_]*(?::[^}]*)?\}[''\"]?$') {
                throw "生产Compose禁止包含敏感明文：$key"
            }
        }
        if ($trimmed -match '(?i)BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY') {
            throw '生产Compose禁止包含私钥内容。'
        }
    }

    return [pscustomobject]@{
        ConfigDigest = $calculatedDigest
        BundlePath = [IO.Path]::GetFullPath($BundlePath)
        ComposePath = [IO.Path]::GetFullPath($composePath)
        ProfilePath = [IO.Path]::GetFullPath($profilePath)
        ComposeSha256 = $composeSha
        ProductionEnvSha256 = $profileSha
        SourceCommit = [string]$manifest.source_commit
        ImageDigest = [string]$manifest.image_digest
    }
}

function Save-ProductionConfigBundle {
    <#
    .SYNOPSIS
    将已验证配置包原子保存到受控状态目录并再次复验。
    #>
    param([Parameter(Mandatory = $true)][object]$ValidatedBundle)

    $digestHex = $ValidatedBundle.ConfigDigest.Substring('sha256:'.Length)
    $targetPath = Join-Path $RELEASE_CONFIG_ROOT $digestHex
    if (Test-Path -LiteralPath $targetPath -PathType Container) {
        return Assert-ProductionConfigBundle `
            -BundlePath $targetPath `
            -ExpectedConfigDigest $ValidatedBundle.ConfigDigest `
            -ExpectedSourceCommit $ValidatedBundle.SourceCommit `
            -ExpectedImageDigest $ValidatedBundle.ImageDigest
    }
    New-Item -ItemType Directory -Path $RELEASE_CONFIG_ROOT -Force | Out-Null
    $temporaryPath = "$targetPath.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        New-Item -ItemType Directory -Path (Join-Path $temporaryPath 'env') -Force |
            Out-Null
        foreach ($relativePath in @(
            'config-manifest.json', 'docker-compose.yml', 'env\production.env'
        )) {
            $destinationPath = Join-Path $temporaryPath $relativePath
            Copy-Item `
                -LiteralPath (Join-Path $ValidatedBundle.BundlePath $relativePath) `
                -Destination $destinationPath
        }
        $copied = Assert-ProductionConfigBundle `
            -BundlePath $temporaryPath `
            -ExpectedConfigDigest $ValidatedBundle.ConfigDigest `
            -ExpectedSourceCommit $ValidatedBundle.SourceCommit `
            -ExpectedImageDigest $ValidatedBundle.ImageDigest
        Move-Item -LiteralPath $temporaryPath -Destination $targetPath
        return Assert-ProductionConfigBundle `
            -BundlePath $targetPath `
            -ExpectedConfigDigest $copied.ConfigDigest `
            -ExpectedSourceCommit $copied.SourceCommit `
            -ExpectedImageDigest $copied.ImageDigest
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Recurse -Force -ErrorAction SilentlyContinue
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

function ConvertTo-OwnerAclSid {
    <#
    .SYNOPSIS
    将清单中的SID严格转换为SecurityIdentifier并返回规范值。
    #>
    param([Parameter(Mandatory = $true)][object]$Value)
    $text = [string]$Value
    if ($text -notmatch '^S-1-[0-9]+(?:-[0-9]+)+$') {
        throw "Owner/ACL信任清单包含无效SID：$text"
    }
    try {
        return ([Security.Principal.SecurityIdentifier]::new($text)).Value
    }
    catch {
        throw "Owner/ACL信任清单SID无法解析：$text"
    }
}

function Assert-NoOwnerAclReparsePath {
    <#
    .SYNOPSIS
    验证目标路径及其已存在父目录不包含重解析点。
    #>
    param([Parameter(Mandatory = $true)][string]$Path)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $current = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Owner/ACL信任对象不能位于重解析路径：$fullPath"
        }
        $parentPath = [IO.Path]::GetDirectoryName($current.FullName)
        if ([String]::IsNullOrWhiteSpace($parentPath) -or
            $parentPath -eq $current.FullName) {
            break
        }
        if (-not (Test-Path -LiteralPath $parentPath)) { break }
        $current = Get-Item -LiteralPath $parentPath -Force -ErrorAction Stop
    }
}

function Get-OwnerAclManifestObject {
    <#
    .SYNOPSIS
    从严格校验过的Owner/ACL信任清单取得对象声明。
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$ObjectId
    )
    $matches = @($Manifest.objects | Where-Object { [string]$_.id -ceq $ObjectId })
    if ($matches.Count -ne 1) {
        throw "Owner/ACL信任清单缺少唯一对象声明：$ObjectId"
    }
    return $matches[0]
}

function Assert-OwnerAclObject {
    <#
    .SYNOPSIS
    按SID、显式DACL和对象声明校验一个受保护文件或目录。
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$ObjectId,
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedSha256 = '',
        [Parameter(Mandatory = $true)][string]$Description
    )
    $declaration = Get-OwnerAclManifestObject -Manifest $Manifest -ObjectId $ObjectId
    $declaredPath = [IO.Path]::GetFullPath([string]$declaration.path)
    $actualPath = [IO.Path]::GetFullPath($Path)
    if ($declaredPath -ine $actualPath) {
        throw "$Description路径与Owner/ACL信任清单不一致。"
    }
    if ([string]$declaration.kind -notin @('file', 'directory')) {
        throw "$Description对象类型无效。"
    }
    if ([bool]$declaration.reparse_allowed) {
        throw "$Description信任清单不得允许重解析点。"
    }
    if (-not [bool]$declaration.inheritance_protected) {
        throw "$Description信任清单必须关闭ACL继承。"
    }
    if (-not (Test-Path -LiteralPath $actualPath)) {
        throw "$Description不存在：$actualPath"
    }
    $item = Get-Item -LiteralPath $actualPath -Force
    if (($declaration.kind -eq 'file' -and $item.PSIsContainer) -or
        ($declaration.kind -eq 'directory' -and -not $item.PSIsContainer)) {
        throw "$Description对象类型与实际路径不一致。"
    }
    Assert-NoOwnerAclReparsePath -Path $actualPath
    if (-not [String]::IsNullOrWhiteSpace($ExpectedSha256)) {
        if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
            throw "$Description SHA-256必须是64位小写十六进制。"
        }
        if ([string]$declaration.content_sha256 -cne $ExpectedSha256 -or
            (Get-Sha256 -Path $actualPath) -cne $ExpectedSha256) {
            throw "$Description SHA-256不匹配。"
        }
    }
    $ownerSections = [Security.AccessControl.AccessControlSections]::Owner -bor
        [Security.AccessControl.AccessControlSections]::Access
    $acl = if ($item.PSIsContainer) {
        [IO.Directory]::GetAccessControl($actualPath, $ownerSections)
    }
    else {
        [IO.File]::GetAccessControl($actualPath, $ownerSections)
    }
    if (-not $acl.AreAccessRulesProtected) {
        throw "$Description ACL继承未关闭。"
    }
    $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    $ownerSids = @($declaration.owner_sids | ForEach-Object {
        ConvertTo-OwnerAclSid -Value $_
    })
    if ($ownerSid -notin $ownerSids) {
        throw "$Description所有者SID不在信任清单中：$ownerSid"
    }
    $readSids = @($declaration.allowed_read_sids | ForEach-Object {
        ConvertTo-OwnerAclSid -Value $_
    })
    $writeSids = @($declaration.allowed_write_sids | ForEach-Object {
        ConvertTo-OwnerAclSid -Value $_
    })
    $declaredSids = @($readSids + $writeSids | Sort-Object -Unique)
    if ($readSids.Count -eq 0 -or $declaredSids.Count -eq 0) {
        throw "$Description必须声明非空显式读权限集合。"
    }
    $rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($rules.Count -eq 0) { throw "$Description缺少显式DACL。" }
    foreach ($rule in $rules) {
        $sid = ([Security.Principal.SecurityIdentifier]$rule.IdentityReference).Value
        if ($rule.IsInherited -or
            (($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -ne 0) -or
            $rule.InheritanceFlags -ne [Security.AccessControl.InheritanceFlags]::None) {
            throw "$Description ACL包含继承或InheritOnly ACE：$sid"
        }
        if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
            throw "$Description ACL包含不受支持的拒绝ACE：$sid"
        }
        $rights = [long]$rule.FileSystemRights
        if (($rights -band (-bnot $OWNER_ACL_ALLOWED_RIGHTS)) -ne 0) {
            throw "$Description ACL包含超出允许掩码的权限：$sid"
        }
        $hasWrite = (($rights -band $OWNER_ACL_WRITE_RIGHTS) -ne 0)
        $hasRead = (($rights -band $OWNER_ACL_READ_RIGHTS) -ne 0)
        if ($sid -in $OWNER_ACL_BLOCKED_SIDS -and $hasWrite) {
            throw "$Description ACL禁止宽泛主体写入：$sid"
        }
        if ($sid -notin $declaredSids) {
            throw "$Description ACL包含未声明SID：$sid"
        }
        if ($hasWrite -and $sid -notin $writeSids) {
            throw "$Description ACL写入SID未获对象授权：$sid"
        }
        if ($hasRead -and $sid -notin $readSids) {
            throw "$Description ACL读取SID未获对象授权：$sid"
        }
    }
    return $declaration
}

function Assert-OwnerAclTrustManifest {
    <#
    .SYNOPSIS
    校验主机级Owner/ACL信任清单及部署执行SID。
    #>
    if ([String]::IsNullOrWhiteSpace($TrustManifestPath) -or
        [String]::IsNullOrWhiteSpace($TrustManifestSha256)) {
        throw '缺少显式Owner/ACL信任清单路径或SHA-256。'
    }
    if ($TrustManifestSha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Owner/ACL信任清单SHA-256必须是64位小写十六进制。'
    }
    Assert-RequiredFile -Path $TrustManifestPath -Description 'Owner/ACL信任清单'
    Assert-NoOwnerAclReparsePath -Path $TrustManifestPath
    if ((Get-Sha256 -Path $TrustManifestPath) -cne $TrustManifestSha256) {
        throw 'Owner/ACL信任清单SHA-256不匹配。'
    }
    try {
        $manifest = Get-Content -LiteralPath $TrustManifestPath -Raw |
            ConvertFrom-Json
    }
    catch {
        throw 'Owner/ACL信任清单不是有效JSON对象。'
    }
    if ($manifest -isnot [pscustomobject]) {
        throw 'Owner/ACL信任清单必须是JSON对象。'
    }
    $requiredFields = @(
        'schema', 'policy_id', 'environment', 'deployment_identity_sid',
        'probe_producer_identity_sid', 'objects', 'receipt_schema',
        'probe_contract_id'
    )
    $fields = @($manifest.PSObject.Properties.Name)
    if (@($requiredFields | Where-Object { $_ -notin $fields }).Count -gt 0 -or
        @($fields | Where-Object { $_ -notin $requiredFields }).Count -gt 0) {
        throw 'Owner/ACL信任清单字段集合不符合固定Schema。'
    }
    if ([string]$manifest.schema -cne $OWNER_ACL_TRUST_SCHEMA -or
        [string]$manifest.policy_id -cne $OWNER_ACL_POLICY_ID -or
        [string]$manifest.environment -cne 'production' -or
        [string]$manifest.receipt_schema -cne 'iwork-external-probe-receipt/v3' -or
        [string]$manifest.probe_contract_id -cne $EXTERNAL_PROBE_CONTRACT_ID) {
        throw 'Owner/ACL信任清单Schema或策略标识不受支持。'
    }
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $deploymentSid = ConvertTo-OwnerAclSid -Value $manifest.deployment_identity_sid
    if ($deploymentSid -cne $currentSid) {
        throw "部署执行SID与Owner/ACL信任清单不一致：$currentSid"
    }
    $producerSid = ConvertTo-OwnerAclSid -Value $manifest.probe_producer_identity_sid
    if ($producerSid -cne $currentSid) {
        throw '外部探针生产者必须由清单声明的当前受控SID执行。'
    }
    $objects = @($manifest.objects)
    if ($objects.Count -lt 5) { throw 'Owner/ACL信任清单对象声明不完整。' }
    $objectIds = @($objects | ForEach-Object { [string]$_.id })
    if (@($objectIds | Sort-Object -Unique).Count -ne $objects.Count) {
        throw 'Owner/ACL信任清单对象ID重复。'
    }
    foreach ($object in $objects) {
        $objectFields = @($object.PSObject.Properties.Name)
        $expectedObjectFields = @(
            'id', 'kind', 'path', 'content_sha256', 'owner_sids',
            'allowed_read_sids', 'allowed_write_sids', 'inheritance_protected',
            'reparse_allowed'
        )
        if (@($expectedObjectFields | Where-Object { $_ -notin $objectFields }).Count -gt 0 -or
            @($objectFields | Where-Object { $_ -notin $expectedObjectFields }).Count -gt 0) {
            throw "Owner/ACL对象字段集合无效：$($object.id)"
        }
        if (-not [IO.Path]::IsPathRooted([string]$object.path) -or
            [string]$object.path -match '[*?]') {
            throw "Owner/ACL对象路径必须是固定绝对路径：$($object.id)"
        }
        if ([string]$object.content_sha256 -ne '' -and
            [string]$object.content_sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "Owner/ACL对象内容SHA-256无效：$($object.id)"
        }
        foreach ($sid in @($object.owner_sids + $object.allowed_read_sids + $object.allowed_write_sids)) {
            $normalizedSid = ConvertTo-OwnerAclSid -Value $sid
            if ($normalizedSid -in $OWNER_ACL_BLOCKED_SIDS) {
                throw "Owner/ACL对象禁止使用宽泛或管理员SID：$($object.id) / $normalizedSid"
            }
        }
        if ([bool]$object.reparse_allowed -or -not [bool]$object.inheritance_protected) {
            throw "Owner/ACL对象必须禁止重解析并关闭继承：$($object.id)"
        }
    }
    foreach ($requiredId in @('probe-producer', 'probe-signing-secret', 'probe-receipt-directory', 'probe-receipt', 'probe-signature')) {
        Get-OwnerAclManifestObject -Manifest $manifest -ObjectId $requiredId | Out-Null
    }
    return $manifest
}

function Assert-TrustedProbeFile {
    <#
    .SYNOPSIS
    兼容旧调用签名，使用Owner/ACL信任清单验证外部探针文件。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][object]$TrustManifest,
        [Parameter(Mandatory = $true)][string]$ObjectId
    )
    Assert-OwnerAclObject -Manifest $TrustManifest -ObjectId $ObjectId `
        -Path $Path -ExpectedSha256 $ExpectedSha256 -Description $Description | Out-Null
}

function Assert-ExternalProbeProducer {
    <#
    .SYNOPSIS
    在候选切换前验证探针生产者和签名密钥文件的信任边界。
    #>
    param([switch]$ValidateOnly)
    if ([String]::IsNullOrWhiteSpace($ExternalProbeProducerPath)) {
        throw '缺少受信外部探针生产者。'
    }
    Assert-RequiredFile -Path $ExternalProbeProducerPath -Description '外部探针生产者'
    Assert-RequiredFile -Path $ExternalProbeSigningSecretFile -Description '外部探针签名密钥'
    if ([String]::IsNullOrWhiteSpace($ExternalProbeReceiptPath)) {
        throw '缺少外部探针六项收据路径。'
    }
    $trustManifest = Assert-OwnerAclTrustManifest
    if (-not [String]::IsNullOrWhiteSpace($ExternalProbeProducerExpectedIdentity)) {
        $legacyProducerSid = ([Security.Principal.NTAccount]::new(
            $ExternalProbeProducerExpectedIdentity
        ).Translate([Security.Principal.SecurityIdentifier])).Value
        if ($legacyProducerSid -cne ([string]$trustManifest.probe_producer_identity_sid)) {
            throw '旧版外部探针生产者身份参数与Owner/ACL信任清单不一致。'
        }
    }
    Assert-TrustedProbeFile `
        -Path $ExternalProbeProducerPath `
        -ExpectedSha256 $ExternalProbeProducerSha256 `
        -Description '外部探针生产者' `
        -TrustManifest $trustManifest -ObjectId 'probe-producer'
    Assert-TrustedProbeFile `
        -Path $ExternalProbeSigningSecretFile `
        -ExpectedSha256 $ExternalProbeSigningSecretSha256 `
        -Description '外部探针签名密钥' `
        -TrustManifest $trustManifest -ObjectId 'probe-signing-secret'
    $receiptParent = [IO.Path]::GetDirectoryName(
        [IO.Path]::GetFullPath($ExternalProbeReceiptPath)
    )
    if (-not (Test-Path -LiteralPath $receiptParent -PathType Container)) {
        throw "外部探针收据目录不存在：$receiptParent"
    }
    $receiptParentItem = Get-Item -LiteralPath $receiptParent -Force
    if (($receiptParentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '外部探针收据目录不能是重解析点。'
    }
    Assert-OwnerAclObject -Manifest $trustManifest -ObjectId 'probe-receipt-directory' `
        -Path $receiptParent -Description '外部探针收据目录' | Out-Null
    if ($ValidateOnly) { return }
    if (Test-Path -LiteralPath $ExternalProbeReceiptPath) {
        throw '外部探针收据在候选切换前已存在，拒绝复用或覆盖。'
    }
}

function Test-FixedTimeBytesEqual {
    <#
    .SYNOPSIS
    使用固定长度逐字节比较验证签名，避免提前返回。
    #>
    param([byte[]]$Left, [byte[]]$Right)
    if ($null -eq $Left -or $null -eq $Right -or $Left.Length -ne $Right.Length) {
        return $false
    }
    $difference = 0
    for ($index = 0; $index -lt $Left.Length; $index++) {
        $difference = $difference -bor ($Left[$index] -bxor $Right[$index])
    }
    return $difference -eq 0
}

function Invoke-AndAssertExternalProbe {
    <#
    .SYNOPSIS
    在宿主机上验证生产外部探针生成的六项不可变收据。

    .DESCRIPTION
    外部探针必须在候选双容器切换完成后，由哈希固定且ACL受控的本地主机
    生产者完成HTTPS/Nginx、OIDC、SSE首事件、
    SSE心跳、关键只读业务接口和通知链路六项检查。收据绑定当前请求、
    部署Run、候选Commit、镜像与配置Digest，并且在有限时间内生成；
    缺少、重复、未知或未成功的探针项目均失败关闭。
    #>
    param(
        [Parameter(Mandatory = $true)][DateTimeOffset]$SwitchedAt,
        [Parameter(Mandatory = $true)][object[]]$CandidateContainers
    )
    $trustManifest = Assert-OwnerAclTrustManifest
    if (-not [String]::IsNullOrWhiteSpace($ExternalProbeUri) -or
        -not [String]::IsNullOrWhiteSpace($ExternalProbeAuthorizationEnvVar)) {
        throw '外部探针URI模式已禁用，只接受受控主机生成的六项收据。'
    }
    if ([String]::IsNullOrWhiteSpace($ExternalProbeReceiptPath)) {
        throw '缺少外部探针六项收据路径。'
    }
    $nonce = [Guid]::NewGuid().ToString('N')
    $challengeRoot = Join-Path $StateRoot 'external-probe-challenges'
    if (-not (Test-Path -LiteralPath $challengeRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $challengeRoot -Force | Out-Null
    }
    $challengePath = Join-Path $challengeRoot "$RunId-$nonce.json"
    $signaturePath = "$ExternalProbeReceiptPath.sig"
    foreach ($outputPath in @($ExternalProbeReceiptPath, $signaturePath, $challengePath)) {
        if (Test-Path -LiteralPath $outputPath) {
            throw "外部探针一次性输出已存在，拒绝复用：$outputPath"
        }
    }
    $challenge = [ordered]@{
        schema = 'iwork-external-probe-challenge/v1'
        nonce = $nonce
        request_id = $RequestId
        deployment_run_id = $RunId
        switched_at = $SwitchedAt.ToString('o')
        producer_sha256 = $ExternalProbeProducerSha256
        containers = $CandidateContainers
    }
    Write-JsonAtomic -Path $challengePath -Value $challenge
    try {
        # 在创建者进程启动前再次复验固定文件、清单和收据目录，缩短TOCTOU窗口。
        Assert-ExternalProbeProducer -ValidateOnly
        $powershellPath = Join-Path $env:SystemRoot `
            'System32\WindowsPowerShell\v1.0\powershell.exe'
        Assert-RequiredFile -Path $powershellPath -Description 'Windows PowerShell'
        $producerArguments = @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $ExternalProbeProducerPath,
            '-ChallengePath', $challengePath,
            '-ReceiptPath', $ExternalProbeReceiptPath,
            '-SignaturePath', $signaturePath,
            '-SigningSecretFile', $ExternalProbeSigningSecretFile
        )
        & $powershellPath @producerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "受信外部探针生产者失败；exit=$LASTEXITCODE"
        }
    }
    finally {
        Remove-Item -LiteralPath $challengePath -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $ExternalProbeReceiptPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) {
        throw '受信外部探针生产者没有生成完整收据和签名。'
    }
    Assert-OwnerAclObject -Manifest $trustManifest -ObjectId 'probe-receipt' `
        -Path $ExternalProbeReceiptPath -Description '外部探针六项收据' | Out-Null
    Assert-OwnerAclObject -Manifest $trustManifest -ObjectId 'probe-signature' `
        -Path $signaturePath -Description '外部探针六项签名' | Out-Null
    $receiptItem = Get-Item -LiteralPath $ExternalProbeReceiptPath -Force
    if (($receiptItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '外部探针六项收据不能位于重解析文件。'
    }
    $receiptBytes = [IO.File]::ReadAllBytes($ExternalProbeReceiptPath)
    try {
        $providedSignature = [Convert]::FromBase64String(
            ([IO.File]::ReadAllText($signaturePath, [Text.UTF8Encoding]::new($false))).Trim()
        )
        $hmac = [Security.Cryptography.HMACSHA256]::new(
            [IO.File]::ReadAllBytes($ExternalProbeSigningSecretFile)
        )
        try { $expectedSignature = $hmac.ComputeHash($receiptBytes) } finally { $hmac.Dispose() }
        if (-not (Test-FixedTimeBytesEqual -Left $providedSignature -Right $expectedSignature)) {
            throw 'signature mismatch'
        }
        $receipt = [Text.UTF8Encoding]::new($false, $true).GetString($receiptBytes) |
            ConvertFrom-Json
    }
    catch {
        throw "外部探针六项收据签名或JSON无效：$ExternalProbeReceiptPath"
    }
    if ($receipt -isnot [pscustomobject]) {
        throw '外部探针六项收据必须是JSON对象。'
    }
    $requiredFields = @(
        'schema', 'application', 'status', 'request_id', 'deployment_run_id',
        'source_commit', 'image_digest', 'config_digest',
        'config_artifact_digest', 'probe_contract_id', 'nonce', 'switched_at',
        'checked_at', 'producer_identity', 'producer_sha256', 'containers', 'probes'
    )
    $actualFields = @($receipt.PSObject.Properties.Name)
    if (
        @($requiredFields | Where-Object { $_ -notin $actualFields }).Count -gt 0 -or
        @($actualFields | Where-Object { $_ -notin $requiredFields }).Count -gt 0
    ) {
        throw '外部探针六项收据字段集合不符合固定Schema。'
    }
    if ([string]$receipt.schema -cne 'iwork-external-probe-receipt/v3') {
        throw '外部探针六项收据Schema不受支持。'
    }
    if ([string]$receipt.application -cne 'iwork') {
        throw '外部探针六项收据应用标识不正确。'
    }
    if ([string]$receipt.status -cne 'succeeded') {
        throw '外部探针六项收据状态不是succeeded。'
    }
    if ([string]$receipt.request_id -cne $RequestId) {
        throw '外部探针六项收据request_id不匹配。'
    }
    if ([string]$receipt.deployment_run_id -cne $RunId) {
        throw '外部探针六项收据deployment_run_id不匹配。'
    }
    if ([string]$receipt.source_commit -cne $ExpectedRevision) {
        throw '外部探针六项收据source_commit不匹配。'
    }
    if ([string]$receipt.image_digest -cne $ImageDigest) {
        throw '外部探针六项收据image_digest不匹配。'
    }
    if ([string]$receipt.config_digest -cne $ConfigDigest) {
        throw '外部探针六项收据config_digest不匹配。'
    }
    if ([string]$receipt.config_artifact_digest -cne $ConfigArtifactDigest) {
        throw '外部探针六项收据config_artifact_digest不匹配。'
    }
    if ([string]$receipt.probe_contract_id -cne $EXTERNAL_PROBE_CONTRACT_ID) {
        throw '外部探针六项收据契约标识不受支持。'
    }
    if ([string]$receipt.nonce -cne $nonce) {
        throw '外部探针六项收据一次性nonce不匹配。'
    }
    $receiptProducerSid = $null
    try {
        $receiptProducerSid = ([Security.Principal.NTAccount]::new(
            [string]$receipt.producer_identity
        ).Translate([Security.Principal.SecurityIdentifier])).Value
    }
    catch {
        throw '外部探针六项收据生产者身份无法解析为SID。'
    }
    if ($receiptProducerSid -cne ([string]$trustManifest.probe_producer_identity_sid) -or
        (-not [String]::IsNullOrWhiteSpace($ExternalProbeProducerExpectedIdentity) -and
         [string]$receipt.producer_identity -ine $ExternalProbeProducerExpectedIdentity) -or
        [string]$receipt.producer_sha256 -cne $ExternalProbeProducerSha256) {
        throw '外部探针六项收据生产者身份或哈希不匹配。'
    }

    $parseTimestamp = {
        param([string]$Value, [string]$Description)
        if ($Value -notmatch '(?:Z|[+-]\d{2}:\d{2})$') {
            throw "$Description时间必须包含时区。"
        }
        $parsed = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse($Value, [ref]$parsed)) {
            throw "$Description时间无效。"
        }
        $ageSeconds = ([DateTimeOffset]::UtcNow - $parsed).TotalSeconds
        if ($ageSeconds -lt -60 -or $ageSeconds -gt $ExternalProbeMaxAgeSeconds) {
            throw "$Description证据已过期或来自未来时间。"
        }
        return $parsed
    }
    $receiptSwitchedAt = & $parseTimestamp ([string]$receipt.switched_at) '候选切换'
    if ([Math]::Abs(($receiptSwitchedAt - $SwitchedAt).TotalMilliseconds) -gt 1000) {
        throw '外部探针六项收据switched_at不匹配。'
    }
    $receiptCheckedAt = & $parseTimestamp ([string]$receipt.checked_at) '外部探针六项收据'
    if ($receiptCheckedAt -lt $SwitchedAt) {
        throw '外部探针六项收据生成于候选切换前。'
    }
    $actualContainers = @($receipt.containers)
    if ($actualContainers.Count -ne $CandidateContainers.Count) {
        throw '外部探针六项收据缺少候选双容器绑定。'
    }
    foreach ($expectedContainer in $CandidateContainers) {
        $matches = @($actualContainers | Where-Object {
            [string]$_.Name -ceq [string]$expectedContainer.Name -and
            [string]$_.ContainerId -ceq [string]$expectedContainer.ContainerId -and
            [string]$_.ImageDigest -ceq [string]$expectedContainer.ImageDigest -and
            [string]$_.Revision -ceq [string]$expectedContainer.Revision
        })
        if ($matches.Count -ne 1) {
            throw "外部探针六项收据候选容器绑定不匹配：$($expectedContainer.Name)"
        }
    }

    $probeItems = @($receipt.probes)
    if ($probeItems.Count -ne $EXTERNAL_PROBE_NAMES.Count) {
        throw "外部探针必须恰好包含六项，实际：$($probeItems.Count)"
    }
    $probeNames = @($probeItems | ForEach-Object { [string]$_.name })
    if (@($probeNames | Sort-Object -Unique).Count -ne $EXTERNAL_PROBE_NAMES.Count -or
        @($probeNames | Where-Object { $_ -notin $EXTERNAL_PROBE_NAMES }).Count -gt 0 -or
        @($EXTERNAL_PROBE_NAMES | Where-Object { $_ -notin $probeNames }).Count -gt 0) {
        throw '外部探针收据必须恰好包含固定六项，且不得重复或包含未知项。'
    }

    $probeResults = [ordered]@{}
    foreach ($probe in $probeItems) {
        if ($probe -isnot [pscustomobject]) {
            throw '外部探针项目必须是JSON对象。'
        }
        $probeFields = @($probe.PSObject.Properties.Name)
        $expectedProbeFields = @(
            'name', 'status', 'uri', 'http_status', 'checked_at',
            'duration_ms', 'evidence'
        )
        if (
            @($expectedProbeFields | Where-Object { $_ -notin $probeFields }).Count -gt 0 -or
            @($probeFields | Where-Object { $_ -notin $expectedProbeFields }).Count -gt 0
        ) {
            throw "外部探针项目字段集合无效：$($probe.name)"
        }
        $name = [string]$probe.name
        if ($probe.status -cne 'succeeded') {
            throw "外部探针项目未成功：$name"
        }
        try {
            $probeUri = [Uri]$probe.uri
        }
        catch {
            throw "外部探针项目URI无效：$name"
        }
        if (-not $probeUri.IsAbsoluteUri -or $probeUri.Scheme -cne 'https') {
            throw "外部探针项目URI必须是绝对HTTPS地址：$name"
        }
        $statusCode = 0
        if (-not [int]::TryParse([string]$probe.http_status, [ref]$statusCode) -or
            $statusCode -lt 200 -or $statusCode -gt 299) {
            throw "外部探针项目HTTP状态异常：$name"
        }
        $probeCheckedAt = & $parseTimestamp ([string]$probe.checked_at) "外部探针项目$name"
        $durationMs = 0L
        if (-not [long]::TryParse([string]$probe.duration_ms, [ref]$durationMs) -or
            $durationMs -lt 0) {
            throw "外部探针项目duration_ms无效：$name"
        }
        if ($probe.evidence -isnot [pscustomobject]) {
            throw "外部探针项目evidence必须是JSON对象：$name"
        }
        $evidenceFields = @($probe.evidence.PSObject.Properties.Name)
        switch ($name) {
            'https_nginx' {
                $expectedEvidence = @('reachable', 'tls_valid')
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    $probe.evidence.reachable -isnot [bool] -or
                    $probe.evidence.tls_valid -isnot [bool] -or
                    -not $probe.evidence.reachable -or -not $probe.evidence.tls_valid) {
                    throw 'HTTPS/Nginx探针证据无效。'
                }
            }
            'oidc_discovery' {
                $expectedEvidence = @('issuer', 'jwks_uri')
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    [string]::IsNullOrWhiteSpace([string]$probe.evidence.issuer) -or
                    [string]::IsNullOrWhiteSpace([string]$probe.evidence.jwks_uri)) {
                    throw 'OIDC discovery探针证据无效。'
                }
                foreach ($uriText in @([string]$probe.evidence.issuer, [string]$probe.evidence.jwks_uri)) {
                    $oidcUri = [Uri]$uriText
                    if (-not $oidcUri.IsAbsoluteUri -or $oidcUri.Scheme -cne 'https') {
                        throw 'OIDC discovery证据URI必须是绝对HTTPS地址。'
                    }
                }
            }
            'sse_first_event' {
                $expectedEvidence = @('event_type', 'received')
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    [string]::IsNullOrWhiteSpace([string]$probe.evidence.event_type) -or
                    $probe.evidence.received -isnot [bool] -or
                    -not $probe.evidence.received) {
                    throw 'SSE首事件探针证据无效。'
                }
            }
            'sse_heartbeat' {
                $expectedEvidence = @('heartbeat_received', 'interval_ms')
                $intervalMs = 0L
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    $probe.evidence.heartbeat_received -isnot [bool] -or
                    -not $probe.evidence.heartbeat_received -or
                    -not [long]::TryParse([string]$probe.evidence.interval_ms, [ref]$intervalMs) -or
                    $intervalMs -le 0) {
                    throw 'SSE心跳探针证据无效。'
                }
            }
            'business_read' {
                $expectedEvidence = @('result_nonempty')
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    $probe.evidence.result_nonempty -isnot [bool] -or
                    -not $probe.evidence.result_nonempty) {
                    throw '关键只读业务接口探针证据无效。'
                }
            }
            'notification_chain' {
                $expectedEvidence = @('correlation_id', 'delivered')
                if (@($expectedEvidence | Where-Object { $_ -notin $evidenceFields }).Count -gt 0 -or
                    @($evidenceFields | Where-Object { $_ -notin $expectedEvidence }).Count -gt 0 -or
                    [string]::IsNullOrWhiteSpace([string]$probe.evidence.correlation_id) -or
                    $probe.evidence.delivered -isnot [bool] -or
                    -not $probe.evidence.delivered -or
                    [string]$probe.evidence.correlation_id -cne $RequestId) {
                    throw '通知链路探针证据无效。'
                }
            }
            default {
                throw "未知外部探针项目：$name"
            }
        }
        $probeResults[$name] = [pscustomobject]@{
            Uri = $probeUri.AbsoluteUri
            StatusCode = $statusCode
            CheckedAt = $probeCheckedAt.ToString('o')
            DurationMs = $durationMs
        }
    }

    $receiptArchiveRoot = Join-Path $StateRoot 'external-probe-receipts'
    if (-not (Test-Path -LiteralPath $receiptArchiveRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $receiptArchiveRoot -Force | Out-Null
    }
    $receiptArchivePath = Join-Path $receiptArchiveRoot "$RunId-$nonce.json"
    $signatureArchivePath = "$receiptArchivePath.sig"
    if ((Test-Path -LiteralPath $receiptArchivePath) -or
        (Test-Path -LiteralPath $signatureArchivePath)) {
        throw '外部探针归档收据已存在，拒绝覆盖。'
    }
    Move-Item -LiteralPath $ExternalProbeReceiptPath -Destination $receiptArchivePath
    Move-Item -LiteralPath $signaturePath -Destination $signatureArchivePath

    return [pscustomobject]@{
        Mode = 'receipt'
        ContractId = $EXTERNAL_PROBE_CONTRACT_ID
        Uri = [string]$probeResults['https_nginx'].Uri
        StatusCode = [int]$probeResults['https_nginx'].StatusCode
        CheckedAt = $receiptCheckedAt.ToString('o')
        ReceiptPath = [IO.Path]::GetFullPath($receiptArchivePath)
        SignaturePath = [IO.Path]::GetFullPath($signatureArchivePath)
        ProbeCount = $probeResults.Count
        Probes = $probeResults
    }
}

function Assert-WatchdogMechanism {
    <#
    .SYNOPSIS
    验证SYSTEM看门狗脚本的SHA-256和跨仓库机制清单。
    #>
    if ($WatchdogSha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'WatchdogSha256必须是64位小写十六进制。'
    }
    if ($WatchdogManifestSha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'WatchdogManifestSha256必须是64位小写十六进制。'
    }
    Assert-RequiredFile -Path $WatchdogScript -Description 'Docker看门狗脚本'
    Assert-RequiredFile -Path $WatchdogManifestPath -Description 'Docker看门狗机制清单'
    $watchdogItem = Get-Item -LiteralPath $WatchdogScript -Force
    if (($watchdogItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Docker看门狗脚本不能位于重解析文件。'
    }
    $watchdogDirectoryPath = [IO.Path]::GetDirectoryName(
        [IO.Path]::GetFullPath($WatchdogScript)
    )
    $watchdogDirectory = Get-Item -LiteralPath $watchdogDirectoryPath -Force
    if (($watchdogDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Docker看门狗脚本目录不能是重解析目录。'
    }
    $actualSha256 = Get-Sha256 -Path $WatchdogScript
    if ($actualSha256 -cne $WatchdogSha256) {
        throw "Docker看门狗SHA-256不匹配：$actualSha256"
    }
    $actualManifestSha256 = Get-Sha256 -Path $WatchdogManifestPath
    if ($actualManifestSha256 -cne $WatchdogManifestSha256) {
        throw "Docker看门狗机制清单SHA-256不匹配：$actualManifestSha256"
    }
    $manifestItem = Get-Item -LiteralPath $WatchdogManifestPath -Force
    if (($manifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Docker看门狗机制清单不能位于重解析文件。'
    }
    try {
        $manifest = Get-Content -LiteralPath $WatchdogManifestPath -Raw |
            ConvertFrom-Json
    }
    catch {
        throw 'Docker看门狗机制清单不是有效JSON。'
    }
    if ($manifest -isnot [pscustomobject]) {
        throw 'Docker看门狗机制清单必须是JSON对象。'
    }
    $requiredFields = @(
        'schema', 'application', 'script', 'script_sha256',
        'recovery_mutex', 'execution_identity'
    )
    $manifestFields = @($manifest.PSObject.Properties.Name)
    if (
        @($requiredFields | Where-Object { $_ -notin $manifestFields }).Count -gt 0 -or
        @($manifestFields | Where-Object { $_ -notin $requiredFields }).Count -gt 0
    ) {
        throw 'Docker看门狗机制清单字段集合不符合固定Schema。'
    }
    if ([string]$manifest.schema -cne $WATCHDOG_MECHANISM_SCHEMA) {
        throw 'Docker看门狗机制清单Schema不受支持。'
    }
    if ([string]$manifest.application -cne 'DTD_nginx') {
        throw 'Docker看门狗机制清单应用标识不正确。'
    }
    if ([string]$manifest.script -cne ([IO.Path]::GetFileName($WatchdogScript))) {
        throw 'Docker看门狗机制清单脚本名不匹配。'
    }
    if ([string]$manifest.script_sha256 -cne $WatchdogSha256) {
        throw 'Docker看门狗机制清单脚本SHA-256不匹配。'
    }
    if ([string]$manifest.recovery_mutex -cne $WATCHDOG_RECOVERY_MUTEX) {
        throw 'Docker看门狗机制清单恢复Mutex不匹配。'
    }
    if ([string]$manifest.execution_identity -cne $WATCHDOG_EXECUTION_IDENTITY) {
        throw 'Docker看门狗机制清单执行身份不匹配。'
    }
    $watchdogContent = Get-Content -LiteralPath $WatchdogScript -Raw
    if ($watchdogContent -notmatch [Regex]::Escape($WATCHDOG_RECOVERY_MUTEX)) {
        throw "Docker看门狗未声明共享恢复锁：$WATCHDOG_RECOVERY_MUTEX"
    }

    # 仅验证清单中的字符串不足以证明计划任务实际以SYSTEM执行。
    # 生产Workflow必须传入固定任务名/路径；隔离测试不传时保持兼容，
    # 但不会因此降低生产准入（Workflow的固定参数会触发下面的硬校验）。
    if (-not [String]::IsNullOrWhiteSpace($WatchdogTaskName)) {
        if ($WatchdogTaskName -notmatch '^[A-Za-z0-9._ -]{1,128}$') {
            throw 'Docker看门狗计划任务名格式无效。'
        }
        if ($WatchdogTaskPath -notmatch '^\\(?:[^\\:*?"<>|]+\\)*$') {
            throw 'Docker看门狗计划任务路径格式无效。'
        }
        try {
            $tasks = @(Get-ScheduledTask `
                -TaskName $WatchdogTaskName `
                -TaskPath $WatchdogTaskPath `
                -ErrorAction Stop)
        }
        catch {
            throw "Docker看门狗计划任务不存在或不可读取：$WatchdogTaskPath$WatchdogTaskName"
        }
        if ($tasks.Count -ne 1) {
            throw "Docker看门狗计划任务不唯一：$WatchdogTaskPath$WatchdogTaskName"
        }
        $task = $tasks[0]
        $principal = $task.Principal
        if ($null -eq $principal -or
            [string]$principal.UserId -notin @('SYSTEM', 'S-1-5-18') -or
            [string]$principal.LogonType -cne 'ServiceAccount' -or
            [string]$principal.RunLevel -cne 'Highest') {
            throw 'Docker看门狗计划任务必须使用SYSTEM/ServiceAccount/Highest。'
        }
        $expectedScriptPath = [IO.Path]::GetFullPath($WatchdogScript)
        $allActions = @($task.Actions)
        $matchingActions = @($task.Actions | Where-Object {
            $execute = [string]$_.Execute
            $arguments = [string]$_.Arguments
            $arguments.IndexOf($expectedScriptPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            ($execute -match '(?i)(?:^|\\)powershell(?:\.exe)?$') -and
            $arguments -match '(?i)(?:^|\s)-File(?:\s|=)'
        })
        if ($allActions.Count -ne 1 -or $matchingActions.Count -ne 1) {
            throw 'Docker看门狗计划任务Action未固定到受信脚本。'
        }
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
    param(
        [object]$CoordinationLock,
        [switch]$DeferMaintenanceMarker
    )
    if ($ImageDigest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'ImageDigest必须是sha256加64位小写十六进制。'
    }
    if ($ExpectedRevision -notmatch '^[0-9a-f]{40}$') {
        throw 'ExpectedRevision必须是40位小写Commit SHA。'
    }
    if ($ConfigDigest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'ConfigDigest必须是sha256加64位小写十六进制。'
    }
    if ($ConfigArtifactDigest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'ConfigArtifactDigest必须是sha256加64位小写十六进制。'
    }
    if ($RUN_MIGRATIONS_ENABLED) {
        throw 'run_migrations=true已禁用：缺少机器可验证的向后兼容迁移证据。'
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
    $hasPreflight = (
        -not [String]::IsNullOrWhiteSpace($PreflightRunId) -and
        $PreflightRunId -cne 'none'
    )
    if ($Mode -eq 'Preflight' -and $hasPreflight) {
        throw '预检模式不接受上一次预检Run。'
    }
    if ($Mode -eq 'Deploy' -and -not $hasPreflight) {
        throw '正式部署必须绑定成功的apply=false预检Run。'
    }
    if ($hasPreflight -and $PreflightRunId -notmatch '^[0-9]+-[1-9][0-9]*$') {
        throw 'PreflightRunId必须是<workflow_run_id>-<run_attempt>。'
    }
    if ($hasPreflight -and $PreflightRequestId -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
        throw 'PreflightRequestId必须是有效GUID。'
    }
    if (-not $hasPreflight -and $PreflightRequestId -cne 'none' -and -not [String]::IsNullOrWhiteSpace($PreflightRequestId)) {
        throw '未绑定预检Run时不应提供PreflightRequestId。'
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -ine $ExpectedIdentity) {
        throw "部署身份不正确：$identity"
    }

    if (-not (Test-Path -LiteralPath $ConfigBundlePath -PathType Container)) {
        throw "生产配置包目录不存在：$ConfigBundlePath"
    }
    Assert-RequiredFile -Path $SecretsFile -Description '中央密钥文件'
    Assert-WatchdogMechanism
    if ($Mode -eq 'Deploy') {
        Assert-ExternalProbeProducer
    }
    else {
        Assert-ExternalProbeProducer -ValidateOnly
    }

    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
        throw "部署状态目录不存在：$StateRoot"
    }
    if (-not (Test-Path -LiteralPath $LockRoot -PathType Container)) {
        throw "部署锁目录不存在：$LockRoot"
    }
    if (Test-Path -LiteralPath $MaintenanceFile -PathType Leaf) {
        if ($DeferMaintenanceMarker) {
            # Deploy模式先做格式/身份预检；维护标记必须在取得双Mutex和协调锁后再判断，
            # 这样可信的过期标记才可以由当前持锁者原子归档，活动标记仍然失败关闭。
        }
        elseif ($null -eq $CoordinationLock) {
            throw "已有iwork部署维护标记：$MaintenanceFile"
        }
        else {
            Archive-ExpiredIworkDeploymentMarker -CoordinationLock $CoordinationLock
        }
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

function Get-PreflightReceiptPath {
    <#
    .SYNOPSIS
    根据预检Run标识生成受控状态文件路径。
    #>
    param([Parameter(Mandatory = $true)][string]$Identifier)

    if ($Identifier -notmatch '^[0-9]+-[1-9][0-9]*$') {
        throw '预检Run标识格式无效。'
    }
    return Join-Path $StateRoot "preflight-$Identifier.json"
}

function Claim-RequestId {
    <#
    .SYNOPSIS
    以不可覆盖的服务器收据消费本次部署请求ID，阻止同一请求被重新派发。

    .DESCRIPTION
    Skill的本机确认状态只能约束正常入口，不能约束直接手工触发Workflow。
    服务器在完成输入校验后使用CreateNew原子创建请求消费收据；同一request_id
    即使换成新的GitHub Run也不能再次使用。收据故意不删除，失败也必须使用新的
    request_id重新走预检/确认流程。

    .OUTPUTS
    System.String。不可覆盖的请求消费收据路径。
    #>
    if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
        throw "部署状态目录不存在：$StateRoot"
    }
    $stateItem = Get-Item -LiteralPath $StateRoot -Force
    if (($stateItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '部署状态目录不能是重解析点。'
    }
    if (-not (Test-Path -LiteralPath $REQUEST_CONSUMPTION_ROOT -PathType Container)) {
        New-Item -ItemType Directory -Path $REQUEST_CONSUMPTION_ROOT -Force | Out-Null
    }
    $consumptionRootItem = Get-Item -LiteralPath $REQUEST_CONSUMPTION_ROOT -Force
    if (($consumptionRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '请求消费目录不能是重解析点。'
    }
    $claimPath = Join-Path $REQUEST_CONSUMPTION_ROOT "$RequestId.json"
    $claim = [ordered]@{
        schema = 'iwork-request-consumption/v1'
        status = 'consumed'
        request_id = $RequestId
        mode = $Mode
        run_id = $RunId
        expected_revision = $ExpectedRevision
        image_digest = $ImageDigest
        config_digest = $ConfigDigest
        config_artifact_digest = $ConfigArtifactDigest
        created_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $claimBytes = [Text.UTF8Encoding]::new($false).GetBytes(
        (($claim | ConvertTo-Json -Depth 6) + "`n")
    )
    try {
        $stream = [IO.File]::Open(
            $claimPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $stream.Write($claimBytes, 0, $claimBytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
    }
    catch [IO.IOException] {
        if (Test-Path -LiteralPath $claimPath -PathType Leaf) {
            throw "request_id已经被服务器消费，禁止重复部署：$RequestId"
        }
        throw "请求消费收据写入失败：$claimPath；$($_.Exception.Message)"
    }
    return $claimPath
}

function Write-PreflightReceipt {
    <#
    .SYNOPSIS
    以不可覆盖方式保存本次apply=false预检证据。
    #>
    param(
        [Parameter(Mandatory = $true)][object]$ValidatedConfig,
        [Parameter(Mandatory = $true)][object[]]$ContainerBaseline,
        [Parameter(Mandatory = $true)][string]$RequestClaimPath
    )

    $receiptPath = Get-PreflightReceiptPath -Identifier $RunId
    if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
        throw "预检Run证据已存在，不允许覆盖：$receiptPath"
    }
    $receipt = [ordered]@{
        schema = 'iwork-preflight-receipt/v1'
        mode = 'Preflight'
        run_id = $RunId
        request_id = $RequestId
        request_claim_path = $RequestClaimPath
        actor = $Actor
        expected_revision = $ExpectedRevision
        image_digest = $ImageDigest
        config_digest = $ValidatedConfig.ConfigDigest
        config_artifact_digest = $ConfigArtifactDigest
        compose_sha256 = $ValidatedConfig.ComposeSha256
        production_env_sha256 = $ValidatedConfig.ProductionEnvSha256
        run_migrations = $RUN_MIGRATIONS_ENABLED
        rollback_drill = $ROLLBACK_DRILL_ENABLED
        container_baseline = $ContainerBaseline
        created_at = [DateTimeOffset]::UtcNow.ToString('o')
        result = 'validated'
    }
    Write-JsonAtomic -Path $receiptPath -Value $receipt
    return $receiptPath
}

function Assert-PreflightReceipt {
    <#
    .SYNOPSIS
    验证正式部署绑定的预检Run及三类Digest证据。
    #>
    param()

    if ($Mode -ne 'Deploy') { return $null }
    $receiptPath = Get-PreflightReceiptPath -Identifier $PreflightRunId
    Assert-RequiredFile -Path $receiptPath -Description '绑定的预检证据'
    $requestClaimPath = Join-Path $REQUEST_CONSUMPTION_ROOT "$PreflightRequestId.json"
    Assert-RequiredFile -Path $requestClaimPath -Description '预检请求消费证据'
    try {
        $receipt = Get-Content -LiteralPath $receiptPath -Raw |
            ConvertFrom-Json
    }
    catch {
        throw "预检证据无法解析：$receiptPath"
    }
    try {
        $claim = Get-Content -LiteralPath $requestClaimPath -Raw |
            ConvertFrom-Json
    }
    catch {
        throw "预检请求消费证据无法解析：$requestClaimPath"
    }
    $expected = @{
        schema = 'iwork-preflight-receipt/v1'
        mode = 'Preflight'
        run_id = $PreflightRunId
        request_id = $PreflightRequestId
        actor = $Actor
        expected_revision = $ExpectedRevision
        image_digest = $ImageDigest
        config_digest = $ConfigDigest
        config_artifact_digest = $ConfigArtifactDigest
        request_claim_path = $requestClaimPath
        run_migrations = $false
        rollback_drill = $false
        result = 'validated'
    }
    foreach ($name in $expected.Keys) {
        if ($name -in @('run_migrations', 'rollback_drill')) {
            if ([bool]$receipt.$name -ne [bool]$expected[$name]) {
                throw "预检证据字段不匹配：$name"
            }
        }
        elseif ([string]$receipt.$name -cne [string]$expected[$name]) {
            throw "预检证据字段不匹配：$name"
        }
    }
    $expectedClaim = @{
        schema = 'iwork-request-consumption/v1'
        status = 'consumed'
        request_id = $PreflightRequestId
        mode = 'Preflight'
        run_id = $PreflightRunId
        expected_revision = $ExpectedRevision
        image_digest = $ImageDigest
        config_digest = $ConfigDigest
        config_artifact_digest = $ConfigArtifactDigest
    }
    foreach ($name in $expectedClaim.Keys) {
        if ([string]$claim.$name -cne [string]$expectedClaim[$name]) {
            throw "预检请求消费证据字段不匹配：$name"
        }
    }
    if (@($receipt.container_baseline).Count -ne $EXPECTED_CONTAINERS.Count) {
        throw '预检证据缺少完整双容器基线。'
    }
    return [pscustomobject]@{
        Path = $receiptPath
        Receipt = $receipt
    }
}

function Invoke-Preflight {
    param(
        [object]$CoordinationLock,
        [object]$ValidatedConfig,
        [switch]$PersistReceipt
    )
    $startedAt = [DateTimeOffset]::UtcNow
    Assert-PreflightInputs -CoordinationLock $CoordinationLock
    $candidateImage = "$IMAGE_REPOSITORY@$ImageDigest"
    if ($null -eq $ValidatedConfig) {
        $ValidatedConfig = Assert-ProductionConfigBundle `
            -BundlePath $ConfigBundlePath `
            -ExpectedConfigDigest $ConfigDigest `
            -ExpectedSourceCommit $ExpectedRevision `
            -ExpectedImageDigest $ImageDigest
    }
    $requestClaimPath = Claim-RequestId
    if ($null -ne $CoordinationLock) {
        $ValidatedConfig = Save-ProductionConfigBundle -ValidatedBundle $ValidatedConfig
    }

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

    $null = Invoke-DockerCommandWithProfile `
        -ProfileFile $ValidatedConfig.ProfilePath `
        -Arguments @(
        'compose',
        '--project-directory', $IworkRoot,
        '-f', $ValidatedConfig.ComposePath,
        '--env-file', $ValidatedConfig.ProfilePath,
        '--env-file', $SecretsFile,
        'config', '--quiet'
        )

    $receiptPath = $null
    if ($PersistReceipt) {
        $receiptPath = Write-PreflightReceipt `
            -ValidatedConfig $ValidatedConfig `
            -ContainerBaseline $containerBaseline `
            -RequestClaimPath $requestClaimPath
    }
    [pscustomobject]@{
        Mode = 'Preflight'
        RunId = $RunId
        RequestId = $RequestId
        Actor = $Actor
        CandidateImage = $candidateImage
        ExpectedRevision = $ExpectedRevision
        ConfigDigest = $ValidatedConfig.ConfigDigest
        ConfigArtifactDigest = $ConfigArtifactDigest
        ConfigBundlePath = $ValidatedConfig.BundlePath
        ComposeSha256 = $ValidatedConfig.ComposeSha256
        ProductionEnvSha256 = $ValidatedConfig.ProductionEnvSha256
        RunMigrations = $RUN_MIGRATIONS_ENABLED
        Containers = $EXPECTED_CONTAINERS
        ContainerBaseline = $containerBaseline
        Result = 'validated'
        PreviousWebImageId = $containerBaseline[0].ImageId
        PreviousAlertWorkerImageId = $containerBaseline[1].ImageId
        StateFile = $null
        ReceiptFile = $receiptPath
        RequestClaimPath = $requestClaimPath
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

function Get-ImageRevision {
    <#
    .SYNOPSIS
    读取镜像中固定的OCI来源提交标签。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$ImageReference
    )

    $labelsJson = Invoke-DockerCommand -Arguments @(
        'image', 'inspect', $ImageReference, '--format', '{{json .Config.Labels}}'
    )
    try {
        $labels = ($labelsJson -join "`n") | ConvertFrom-Json
    }
    catch {
        throw "无法解析镜像OCI标签：$ImageReference"
    }
    $revision = [string]$labels.'org.opencontainers.image.revision'
    if ($revision -notmatch '^[0-9a-f]{40}$') {
        throw "镜像缺少有效的OCI revision标签：$ImageReference"
    }
    return $revision
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
    $configuredImage = $configuredImage.Trim()
    $expectedPrefix = [Regex]::Escape("$IMAGE_REPOSITORY@")
    if ($configuredImage -notmatch "^$expectedPrefix(?<digest>sha256:[0-9a-f]{64})$") {
        throw "容器未使用可追溯的iwork镜像Digest：$ContainerName"
    }
    $imageDigest = $Matches['digest']
    $imageId = Get-ContainerImageId -ContainerName $ContainerName
    $revision = Get-ImageRevision -ImageReference $configuredImage

    $restartCount = 0
    if (-not [int]::TryParse($restartCountText.Trim(), [ref]$restartCount)) {
        throw "无法取得容器重启次数：$ContainerName"
    }

    return [ordered]@{
        Name = $ContainerName
        ContainerId = $containerId.Trim()
        ConfiguredImage = $configuredImage
        ImageDigest = $imageDigest
        Revision = $revision
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
        [string]$ComposeFile,

        [Parameter(Mandatory = $true)]
        [string]$ProfileFile,

        [Parameter(Mandatory = $true)]
        [string[]]$CommandArguments
    )

    $arguments = @(
        'compose',
        '--project-directory', $IworkRoot,
        '--project-name', 'iwork',
        '-f', $ComposeFile,
        '-f', $OverrideFile,
        '--env-file', $ProfileFile,
        '--env-file', $SecretsFile
    ) + $CommandArguments
    return Invoke-DockerCommandWithProfile `
        -ProfileFile $ProfileFile `
        -Arguments $arguments
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

function New-SharedMutexSecurity {
    <#
    .SYNOPSIS
    为部署与Docker看门狗共享的Global Mutex创建明确ACL。

    .DESCRIPTION
    Docker看门狗以SYSTEM运行，Runner以预期部署身份运行。
    不能依赖首个创建者的默认DACL，否则两个身份交替创建时会出现“Access is denied”。
    #>
    $security = [Security.AccessControl.MutexSecurity]::new()
    $rights = [Security.AccessControl.MutexRights]::Modify -bor `
        [Security.AccessControl.MutexRights]::Synchronize
    $runnerSid = [Security.Principal.NTAccount]::new($ExpectedIdentity).Translate(
        [Security.Principal.SecurityIdentifier]
    )
    $identities = @(
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'),
        $runnerSid
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

function Enter-DeploymentMutex {
    <#
    .SYNOPSIS
    使用显式ACL尝试取得Windows互斥锁。

    .DESCRIPTION
    看门狗可能在另一个身份下短暂持有旧ACL的同名Global Mutex。
    对访问被拒绝仅做有界重试，到期仍失败关闭；绝不把权限错误当作“锁空闲”。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [ValidateRange(0, 600)]
        [int]$AccessDeniedRetrySeconds = 30
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($AccessDeniedRetrySeconds)
    while ($true) {
        $mutex = $null
        try {
            $createdNew = $false
            $security = New-SharedMutexSecurity
            $mutex = [Threading.Mutex]::new(
                $false,
                $Name,
                [ref]$createdNew,
                $security
            )
        }
        catch [UnauthorizedAccessException] {
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
                throw (
                    "无法访问共享部署互斥锁：$Name；当前身份：$identity；" +
                    '要求SYSTEM、管理员和Runner部署身份使用显式共享ACL。' +
                    "原始错误：$($_.Exception.Message)"
                )
            }
            Start-Sleep -Seconds 1
            continue
        }

        try {
            try {
                $acquired = $mutex.WaitOne(0)
            }
            catch [UnauthorizedAccessException] {
                $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
                throw (
                    "无法取得共享部署互斥锁：$Name；当前身份：$identity；" +
                    '要求SYSTEM、管理员和Runner部署身份使用显式共享ACL。' +
                    "原始错误：$($_.Exception.Message)"
                )
            }
            catch [Security.SecurityException] {
                $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
                throw (
                    "无法取得共享部署互斥锁：$Name；当前身份：$identity；" +
                    'Mutex安全描述符拒绝访问。' +
                    "原始错误：$($_.Exception.Message)"
                )
            }
            catch [Threading.AbandonedMutexException] {
                # 上一次持有者异常退出时，本次已取得互斥锁，继续由统一文件锁严格核验残留内容。
                $acquired = $true
            }
            if (-not $acquired) {
                throw "部署互斥锁已被占用：$Name"
            }
            return $mutex
        }
        catch {
            $mutex.Dispose()
            throw
        }
    }
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

function Get-PreviousProductionConfig {
    <#
    .SYNOPSIS
    读取上一活动配置；首次迁移时只允许与候选配置完全相同的旧工作区基线。
    #>
    param([Parameter(Mandatory = $true)][object]$CandidateConfig)

    if (Test-Path -LiteralPath $ACTIVE_RELEASE_FILE -PathType Leaf) {
        try {
            $active = Get-Content -LiteralPath $ACTIVE_RELEASE_FILE -Raw |
                ConvertFrom-Json
        }
        catch {
            throw "活动发布指针无法解析：$ACTIVE_RELEASE_FILE"
        }
        if (
            $active.schema -cne 'iwork-active-release/v1' -or
            [string]$active.request_id -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
            [string]$active.config_digest -notmatch '^sha256:[0-9a-f]{64}$' -or
            [string]$active.config_artifact_digest -notmatch '^sha256:[0-9a-f]{64}$' -or
            [string]$active.source_commit -notmatch '^[0-9a-f]{40}$' -or
            [string]$active.image_digest -notmatch '^sha256:[0-9a-f]{64}$' -or
            [string]$active.compose_sha256 -notmatch '^[0-9a-f]{64}$' -or
            [string]$active.production_env_sha256 -notmatch '^[0-9a-f]{64}$'
        ) {
            throw '活动发布指针字段无效。'
        }
        $activeConfigArtifactDigest = [string]$active.config_artifact_digest
        $bundlePath = Join-Path `
            $RELEASE_CONFIG_ROOT `
            ([string]$active.config_digest).Substring('sha256:'.Length)
        $validated = Assert-ProductionConfigBundle `
            -BundlePath $bundlePath `
            -ExpectedConfigDigest ([string]$active.config_digest) `
            -ExpectedSourceCommit ([string]$active.source_commit) `
            -ExpectedImageDigest ([string]$active.image_digest)
        if (
            [string]$active.compose_sha256 -cne $validated.ComposeSha256 -or
            [string]$active.production_env_sha256 -cne $validated.ProductionEnvSha256
        ) {
            throw '活动发布指针中的配置文件哈希与实际配置包不一致。'
        }
        return [pscustomobject]@{
            Config = $validated
            Bootstrap = $false
            ConfigArtifactDigest = $activeConfigArtifactDigest
        }
    }

    Assert-RequiredFile -Path $LEGACY_COMPOSE_FILE -Description '迁移期旧生产Compose文件'
    Assert-RequiredFile -Path $LEGACY_PROFILE_FILE -Description '迁移期旧生产环境配置'
    if (
        (Get-CanonicalTextSha256 -Path $LEGACY_COMPOSE_FILE) -cne
        $CandidateConfig.ComposeSha256
    ) {
        throw '首次配置包迁移时，服务器旧Compose与候选配置不一致。'
    }
    if (
        (Get-CanonicalTextSha256 -Path $LEGACY_PROFILE_FILE) -cne
        $CandidateConfig.ProductionEnvSha256
    ) {
        throw '首次配置包迁移时，服务器旧生产环境配置与候选配置不一致。'
    }
    return [pscustomobject]@{
        Config = $CandidateConfig
        Bootstrap = $true
        ConfigArtifactDigest = $ConfigArtifactDigest
    }
}

function Write-ActiveRelease {
    <#
    .SYNOPSIS
    在发布验证成功后原子更新活动镜像与配置指针。
    #>
    param([Parameter(Mandatory = $true)][object]$CandidateConfig)

    $active = [ordered]@{
        schema = 'iwork-active-release/v1'
        source_commit = $ExpectedRevision
        image_digest = $ImageDigest
        config_digest = $CandidateConfig.ConfigDigest
        config_artifact_digest = $ConfigArtifactDigest
        compose_sha256 = $CandidateConfig.ComposeSha256
        production_env_sha256 = $CandidateConfig.ProductionEnvSha256
        deployment_run_id = $RunId
        request_id = $RequestId
        activated_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Write-JsonAtomic -Path $ACTIVE_RELEASE_FILE -Value $active
}

function Invoke-Deploy {
    $startedAt = [DateTimeOffset]::UtcNow
    $candidateImage = "$IMAGE_REPOSITORY@$ImageDigest"
    $stateFile = Join-Path $StateRoot "$RunId.json"
    $candidateOverride = Join-Path $StateRoot "$RunId.candidate.yml"
    $rollbackOverride = Join-Path $StateRoot "$RunId.rollback.yml"
    $productionMutex = $null
    $recoveryMutex = $null
    $coordinationLock = $null
    $state = $null
    $switchAttempted = $false
    $ownsMaintenanceFile = $false
    $ownsDrillAttempt = $false
    $controlledRollbackRequested = $false
    $drillAttempt = $null
    $candidateConfig = $null
    $previousConfig = $null
    $previousConfigBootstrap = $false
    $previousActiveReleaseBytes = $null
    $activeReleaseUpdated = $false
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()

    try {
        Assert-PreflightInputs `
            -CoordinationLock $null `
            -DeferMaintenanceMarker
        $productionMutex = Enter-DeploymentMutex -Name $ProductionMutexName
        $recoveryMutex = Enter-DeploymentMutex `
            -Name $RecoveryMutexName `
            -AccessDeniedRetrySeconds 30
        $coordinationLock = Enter-ProductionCoordinationLock `
            -LockRoot $LockRoot `
            -Repository 'GuChenkano/iwork' `
            -Service 'iwork' `
            -RunId $RunId `
            -Actor $Actor `
            -ExpectedRevision $ExpectedRevision `
            -RequestId $RequestId `
            -ArtifactDigests @{
                iwork = $ImageDigest
                iwork_config = $ConfigDigest
                iwork_config_artifact = $ConfigArtifactDigest
            }
        Assert-PreflightInputs -CoordinationLock $coordinationLock
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'candidate_validation'
        $preflightReceipt = Assert-PreflightReceipt
        $candidateConfig = Assert-ProductionConfigBundle `
            -BundlePath $ConfigBundlePath `
            -ExpectedConfigDigest $ConfigDigest `
            -ExpectedSourceCommit $ExpectedRevision `
            -ExpectedImageDigest $ImageDigest
        $candidateConfig = Save-ProductionConfigBundle -ValidatedBundle $candidateConfig
        $preflightResult = Invoke-Preflight `
            -CoordinationLock $coordinationLock `
            -ValidatedConfig $candidateConfig
        $requestClaimPath = $preflightResult.RequestClaimPath
        $previousConfigSelection = Get-PreviousProductionConfig `
            -CandidateConfig $candidateConfig
        $previousConfig = $previousConfigSelection.Config
        $previousConfigBootstrap = $previousConfigSelection.Bootstrap
        $previousConfigArtifactDigest = $previousConfigSelection.ConfigArtifactDigest
        if (Test-Path -LiteralPath $ACTIVE_RELEASE_FILE -PathType Leaf) {
            $previousActiveReleaseBytes = [IO.File]::ReadAllBytes($ACTIVE_RELEASE_FILE)
        }
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'preflight_complete'
        $previousContainers = foreach ($containerName in $EXPECTED_CONTAINERS) {
            Assert-ContainerHealthy -ContainerName $containerName
            Get-ContainerBaseline -ContainerName $containerName
        }
        $previousContainers = @($previousContainers)
        if ($null -ne $preflightReceipt) {
            foreach ($containerName in $EXPECTED_CONTAINERS) {
                $preflightContainer = @(
                    $preflightReceipt.Receipt.container_baseline |
                        Where-Object { [string]$_.Name -ceq $containerName }
                )
                $currentContainer = @(
                    $previousContainers |
                        Where-Object { [string]$_.Name -ceq $containerName }
                )
                if (
                    $preflightContainer.Count -ne 1 -or
                    $currentContainer.Count -ne 1 -or
                    [string]$preflightContainer[0].ContainerId -cne [string]$currentContainer[0].ContainerId -or
                    [string]$preflightContainer[0].ImageId -cne [string]$currentContainer[0].ImageId -or
                    [int]$preflightContainer[0].RestartCount -ne [int]$currentContainer[0].RestartCount
                ) {
                    throw "预检后生产容器基线已变化：$containerName"
                }
            }
        }
        $previousImageDigests = @(
            $previousContainers.ImageDigest | Select-Object -Unique
        )
        $previousRevisions = @(
            $previousContainers.Revision | Select-Object -Unique
        )
        if ($previousImageDigests.Count -ne 1 -or $previousRevisions.Count -ne 1) {
            throw '当前iwork双容器的镜像Digest或OCI revision不一致。'
        }
        $previousImageDigest = [string]$previousImageDigests[0]
        $previousRevision = [string]$previousRevisions[0]
        if (
            -not $previousConfigBootstrap -and
            (
                $previousConfig.ImageDigest -cne $previousImageDigest -or
                $previousConfig.SourceCommit -cne $previousRevision
            )
        ) {
            throw '活动发布指针与当前运行容器的镜像身份不一致。'
        }
        $previousWebImageId = $previousContainers[0].ImageId
        $previousAlertImageId = $previousContainers[1].ImageId
        $previousImage = "$IMAGE_REPOSITORY@$previousImageDigest"

        if ($ROLLBACK_DRILL_ENABLED) {
            $drillAttempt = [ordered]@{
                Version = 1
                RunId = $RunId
                RequestId = $RequestId
                Actor = $Actor
                Status = 'started'
                CandidateImage = $candidateImage
                ExpectedRevision = $ExpectedRevision
                CandidateConfigDigest = $candidateConfig.ConfigDigest
                CandidateConfigArtifactDigest = $ConfigArtifactDigest
                CandidateComposeSha256 = $candidateConfig.ComposeSha256
                CandidateProductionEnvSha256 = $candidateConfig.ProductionEnvSha256
                PreviousConfigDigest = $previousConfig.ConfigDigest
                PreviousConfigArtifactDigest = $previousConfigArtifactDigest
                PreviousImageDigest = $previousImageDigest
                PreviousRevision = $previousRevision
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
            RequestId = $RequestId
            RequestClaimPath = $requestClaimPath
            Actor = $Actor
            Mode = 'Deploy'
            Status = 'deploying'
            CandidateImage = $candidateImage
            ExpectedRevision = $ExpectedRevision
            CandidateConfigDigest = $candidateConfig.ConfigDigest
            CandidateConfigArtifactDigest = $ConfigArtifactDigest
            CandidateComposeSha256 = $candidateConfig.ComposeSha256
            CandidateProductionEnvSha256 = $candidateConfig.ProductionEnvSha256
            CandidateConfigBundlePath = $candidateConfig.BundlePath
            PreviousConfigDigest = $previousConfig.ConfigDigest
            PreviousConfigArtifactDigest = $previousConfigArtifactDigest
            PreviousComposeSha256 = $previousConfig.ComposeSha256
            PreviousProductionEnvSha256 = $previousConfig.ProductionEnvSha256
            PreviousConfigBundlePath = $previousConfig.BundlePath
            PreviousConfigBootstrap = $previousConfigBootstrap
            PreviousImageDigest = $previousImageDigest
            PreviousRevision = $previousRevision
            PreflightRunId = $PreflightRunId
            PreflightRequestId = $PreflightRequestId
            RunMigrations = $RUN_MIGRATIONS_ENABLED
            RollbackDrill = $ROLLBACK_DRILL_ENABLED
            ChangeDescription = $ChangeDescription
            PreviousWebImageId = $previousWebImageId
            PreviousAlertWorkerImageId = $previousAlertImageId
            PreviousContainers = $previousContainers
            WebRollbackImage = $previousImage
            AlertWorkerRollbackImage = $previousImage
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
            -WebImage $previousImage `
            -AlertWorkerImage $previousImage `
            -AllowMigrations $false

        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'switching'

        $maintenance = [ordered]@{
            application = 'iwork'
            operation = 'production_deployment'
            workflow_run_id = $RunId
            request_id = $RequestId
            actor = $Actor
            image_digest = $ImageDigest
            config_digest = $candidateConfig.ConfigDigest
            config_artifact_digest = $ConfigArtifactDigest
            started_at = [DateTimeOffset]::UtcNow.ToString('o')
            expires_at = [DateTimeOffset]::UtcNow.AddMinutes(20).ToString('o')
        }
        Write-JsonAtomic -Path $MaintenanceFile -Value $maintenance
        $ownsMaintenanceFile = $true

        $null = Invoke-ComposeCommand `
            -OverrideFile $candidateOverride `
            -ComposeFile $candidateConfig.ComposePath `
            -ProfileFile $candidateConfig.ProfilePath `
            -CommandArguments @('config', '--quiet')
        $switchAttempted = $true
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'production_validation'
        $null = Invoke-ComposeCommand `
            -OverrideFile $candidateOverride `
            -ComposeFile $candidateConfig.ComposePath `
            -ProfileFile $candidateConfig.ProfilePath `
            -CommandArguments @(
                'up', '-d', '--no-build', '--no-deps', 'iwork', 'alert-worker'
            )
        $candidateSwitchedAt = [DateTimeOffset]::UtcNow
        Wait-IworkReleaseHealthy
        Assert-DeployedImage -ContainerName 'DKT_iwork' -ExpectedImage $candidateImage
        Assert-DeployedImage `
            -ContainerName 'DKT_iwork_alert_worker' `
            -ExpectedImage $candidateImage
        Assert-IworkApplication
        $candidateContainers = @(
            Get-ContainerBaseline -ContainerName 'DKT_iwork'
            Get-ContainerBaseline -ContainerName 'DKT_iwork_alert_worker'
        )
        $externalProbe = Invoke-AndAssertExternalProbe `
            -SwitchedAt $candidateSwitchedAt `
            -CandidateContainers $candidateContainers
        $state.ExternalProbe = $externalProbe

        if ($ROLLBACK_DRILL_ENABLED) {
            $controlledRollbackRequested = $true
            throw '受控回滚演练触发'
        }

        Write-ActiveRelease -CandidateConfig $candidateConfig
        $activeReleaseUpdated = $true
        $state.Status = 'deployed'
        $state.CompletedAt = [DateTimeOffset]::UtcNow.ToString('o')
        Write-JsonAtomic -Path $stateFile -Value $state
        Update-ProductionCoordinationLock `
            -Lock $coordinationLock `
            -Phase 'completed'

        [pscustomobject]@{
            Mode = 'Deploy'
            RunId = $RunId
            RequestId = $RequestId
            CandidateImage = $candidateImage
            ConfigDigest = $candidateConfig.ConfigDigest
            ConfigArtifactDigest = $ConfigArtifactDigest
            ConfigBundlePath = $candidateConfig.BundlePath
            ComposeSha256 = $candidateConfig.ComposeSha256
            ProductionEnvSha256 = $candidateConfig.ProductionEnvSha256
            ExternalProbe = $externalProbe
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
                    -ComposeFile $previousConfig.ComposePath `
                    -ProfileFile $previousConfig.ProfilePath `
                    -CommandArguments @(
                        'up', '-d', '--no-build', '--no-deps', 'iwork', 'alert-worker'
                )
                Wait-IworkReleaseHealthy
                Assert-DeployedImage `
                    -ContainerName 'DKT_iwork' `
                    -ExpectedImage $previousImage
                Assert-DeployedImage `
                    -ContainerName 'DKT_iwork_alert_worker' `
                    -ExpectedImage $previousImage
                Assert-ContainerImageId `
                    -ContainerName 'DKT_iwork' `
                    -ExpectedImageId $previousWebImageId
                Assert-ContainerImageId `
                    -ContainerName 'DKT_iwork_alert_worker' `
                    -ExpectedImageId $previousAlertImageId
                Assert-IworkApplication
                if ($activeReleaseUpdated) {
                    if ($null -eq $previousActiveReleaseBytes) {
                        Remove-Item `
                            -LiteralPath $ACTIVE_RELEASE_FILE `
                            -Force `
                            -ErrorAction SilentlyContinue
                    }
                    else {
                        $activeTemporaryPath = (
                            "$ACTIVE_RELEASE_FILE." +
                            "$([Guid]::NewGuid().ToString('N')).rollback.tmp"
                        )
                        try {
                            [IO.File]::WriteAllBytes(
                                $activeTemporaryPath,
                                $previousActiveReleaseBytes
                            )
                            Move-Item `
                                -LiteralPath $activeTemporaryPath `
                                -Destination $ACTIVE_RELEASE_FILE `
                                -Force
                        }
                        finally {
                            Remove-Item `
                                -LiteralPath $activeTemporaryPath `
                                -Force `
                                -ErrorAction SilentlyContinue
                        }
                    }
                }
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
                    RequestId = $RequestId
                    CandidateImage = $candidateImage
                    ConfigDigest = $candidateConfig.ConfigDigest
                    ConfigArtifactDigest = $ConfigArtifactDigest
                    PreviousConfigDigest = $previousConfig.ConfigDigest
                    PreviousConfigArtifactDigest = $previousConfigArtifactDigest
                    PreviousImageDigest = $previousImageDigest
                    PreviousRevision = $previousRevision
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
        Invoke-Preflight -PersistReceipt
    }
    'Deploy' {
        Invoke-Deploy
    }
}
