#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$SourceCommit,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^sha256:[0-9a-f]{64}$')]
    [string]$ImageDigest
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# ======
# 固定生产配置包规则
$SCHEMA = 'iwork-production-config/v1'
$APPLICATION = 'iwork'
$COMPOSE_NAME = 'docker-compose.yml'
$PRODUCTION_ENV_NAME = 'env/production.env'
$SENSITIVE_KEY_PATTERN = '(?i)(PASSWORD|PASSWD|SECRET|TOKEN|PRIVATE[_-]?KEY|API[_-]?KEY|ACCESS[_-]?KEY|CREDENTIAL|AUTHORIZATION|BEARER|CERTIFICATE|PASSPHRASE|COOKIE|PWD)'

function ConvertTo-FullPath {
    <#
    .SYNOPSIS
    将用户提供的路径转换为规范绝对路径。

    .PARAMETER Path
    要转换的文件或目录路径。

    .OUTPUTS
    System.String。规范化后的绝对路径。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([String]::IsNullOrWhiteSpace($Path)) {
        throw '路径不能为空。'
    }
    try {
        if ([IO.Path]::IsPathRooted($Path)) {
            return [IO.Path]::GetFullPath($Path)
        }
        return [IO.Path]::GetFullPath((Join-Path -Path (Get-Location).Path -ChildPath $Path))
    }
    catch {
        throw "路径无效：$Path；$($_.Exception.Message)"
    }
}

function Assert-NoPathTraversal {
    <#
    .SYNOPSIS
    拒绝入口路径中的显式父级跳转段，避免越界访问或输出。

    .PARAMETER Path
    用户提供的源目录或目标目录路径。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $segments = $Path -split '[\\/]'
    if ($segments | Where-Object { $_ -eq '..' }) {
        throw "路径包含不允许的父级跳转段：$Path"
    }
}

function Assert-NoReparsePointOnPath {
    <#
    .SYNOPSIS
    拒绝路径自身及其已有父级中的符号链接、联接点和其他重解析点。

    .PARAMETER Path
    要检查的文件或目录路径，可以尚不存在。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $fullPath = ConvertTo-FullPath -Path $Path
    $probe = $fullPath
    while (-not (Test-Path -LiteralPath $probe)) {
        $parent = [IO.Path]::GetDirectoryName($probe)
        if ([String]::IsNullOrEmpty($parent) -or $parent -eq $probe) {
            throw "路径父级不存在：$Path"
        }
        $probe = $parent
    }

    while ($true) {
        $item = Get-Item -LiteralPath $probe -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "拒绝通过重解析点访问路径：$probe"
        }
        $parent = $item.Parent
        if ($null -eq $parent -or $parent.FullName -eq $item.FullName) {
            break
        }
        $probe = $parent.FullName
    }
}

function Assert-RequiredSourceFiles {
    <#
    .SYNOPSIS
    验证生产配置源目录、Compose 文件和生产环境文件均为普通文件。

    .PARAMETER SourceRootPath
    配置源目录的绝对路径。

    .OUTPUTS
    System.String[]。Compose 文件和生产环境文件的绝对路径。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRootPath
    )

    if (-not (Test-Path -LiteralPath $SourceRootPath -PathType Container)) {
        throw "源目录不存在：$SourceRootPath"
    }
    Assert-NoReparsePointOnPath -Path $SourceRootPath

    $composePath = Join-Path -Path $SourceRootPath -ChildPath 'docker-compose.yml'
    $productionEnvPath = Join-Path -Path (Join-Path -Path $SourceRootPath -ChildPath 'env') -ChildPath 'production.env'
    foreach ($sourcePath in @($composePath, $productionEnvPath)) {
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "源配置文件不存在：$sourcePath"
        }
        Assert-NoReparsePointOnPath -Path $sourcePath
    }
    return @($composePath, $productionEnvPath)
}

function ConvertTo-CanonicalUtf8Bytes {
    <#
    .SYNOPSIS
    以严格 UTF-8 解码配置文本并统一为 LF、无 BOM 的 UTF-8 字节。

    .PARAMETER Path
    要读取的配置文件路径。

    .OUTPUTS
    System.Byte[]。规范化后的 UTF-8 字节。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $rawBytes = [IO.File]::ReadAllBytes($Path)
    $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $text = $strictUtf8.GetString($rawBytes)
    }
    catch {
        throw "配置文件不是有效 UTF-8：$Path"
    }
    if ($text.Length -gt 0 -and $text[0] -eq [Char]0xFEFF) {
        $text = $text.Substring(1)
    }
    $text = $text -replace "`r`n", "`n"
    $text = $text -replace "`r", "`n"
    $canonicalUtf8 = [System.Text.UTF8Encoding]::new($false)
    return $canonicalUtf8.GetBytes($text)
}

function Get-Sha256Hex {
    <#
    .SYNOPSIS
    计算字节数组的 SHA-256 小写十六进制摘要。

    .PARAMETER Bytes
    要计算摘要的字节数组。

    .OUTPUTS
    System.String。64 位小写十六进制摘要。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$Bytes
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($Bytes)
    }
    finally {
        $sha256.Dispose()
    }
    return ([BitConverter]::ToString($digest) -replace '-', '').ToLowerInvariant()
}

function Assert-NoSensitiveEnvironmentKeys {
    <#
    .SYNOPSIS
    检查生产环境文件中的键名，拒绝可能承载密钥的敏感配置。

    .PARAMETER EnvironmentBytes
    已规范化的生产环境文件 UTF-8 字节。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$EnvironmentBytes
    )

    $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $text = $utf8.GetString($EnvironmentBytes)
    foreach ($line in ($text -split "`n")) {
        $trimmed = $line.Trim()
        if ([String]::IsNullOrEmpty($trimmed) -or $trimmed.StartsWith('#')) {
            continue
        }
        if ($trimmed -notmatch '^(?<key>[A-Z][A-Z0-9_]*)=') {
            throw "生产环境文件包含无法识别的配置行：$trimmed"
        }
        $key = $Matches['key']
        if ($key -match $SENSITIVE_KEY_PATTERN) {
            throw "生产环境文件包含敏感键，拒绝生成配置包：$key"
        }
    }
}

function Assert-NoPlaintextSecretsInCompose {
    <#
    .SYNOPSIS
    拒绝Compose环境映射或列表中的敏感明文，只允许运行时环境变量引用。

    .PARAMETER ComposeBytes
    已规范化的Compose UTF-8字节。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$ComposeBytes
    )

    $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $text = $utf8.GetString($ComposeBytes)
    foreach ($line in ($text -split "`n")) {
        $trimmed = $line.Trim()
        if ($trimmed -match '^(?:-\s*)?(?<key>[A-Z][A-Z0-9_]*)\s*(?:=|:)\s*(?<value>.*)$') {
            $key = $Matches['key']
            $value = $Matches['value'].Trim()
            if ($key -notmatch $SENSITIVE_KEY_PATTERN) {
                continue
            }
            if ($value -notmatch '^[''\"]?\$\{[A-Z][A-Z0-9_]*(?::[^}]*)?\}[''\"]?$') {
                throw "Compose禁止包含敏感明文：$key"
            }
        }
        if ($trimmed -match '(?i)BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY') {
            throw 'Compose禁止包含私钥内容。'
        }
    }
}

function Get-ConfigDigest {
    <#
    .SYNOPSIS
    按固定六行规范计算不包含自身的配置摘要。

    .DESCRIPTION
    输入为 schema、application、source_commit、image_digest、compose_sha256、
    production_env_sha256 六行，固定顺序、每行使用 LF，并在最后追加一个 LF；
    对其 UTF-8 无 BOM 字节计算 SHA-256。manifest 不参与计算，因此不存在自引用。

    .PARAMETER ComposeSha256
    Compose 规范字节摘要。

    .PARAMETER ProductionEnvSha256
    生产环境文件规范字节摘要。

    .OUTPUTS
    System.String。配置内容摘要。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeSha256,

        [Parameter(Mandatory = $true)]
        [string]$ProductionEnvSha256
    )

    $canonicalLines = @(
        "schema=$SCHEMA"
        "application=$APPLICATION"
        "source_commit=$SourceCommit"
        "image_digest=$ImageDigest"
        "compose_sha256=$ComposeSha256"
        "production_env_sha256=$ProductionEnvSha256"
    )
    $canonicalText = ($canonicalLines -join "`n") + "`n"
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    return 'sha256:' + (Get-Sha256Hex -Bytes $utf8.GetBytes($canonicalText))
}

function Assert-MinimalBundle {
    <#
    .SYNOPSIS
    验证暂存包只含清单、Compose 文件和生产环境文件。

    .PARAMETER BundlePath
    待验证的暂存目录路径。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$BundlePath
    )

    $actual = @(Get-ChildItem -LiteralPath $BundlePath -Recurse -Force | ForEach-Object {
        if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "配置包包含重解析点：$($_.FullName)"
        }
        $_.FullName.Substring($BundlePath.Length).TrimStart('\', '/').Replace('\', '/')
    } | Sort-Object)
    $expected = @('config-manifest.json', 'docker-compose.yml', 'env', 'env/production.env') | Sort-Object
    if (($actual -join "`n") -cne ($expected -join "`n")) {
        throw "配置包内容不符合最小文件集合要求。"
    }
}

function New-IworkProductionConfigBundle {
    <#
    .SYNOPSIS
    从生产 Compose 和环境文件创建一次性不可覆盖的 iwork 配置包。

    .DESCRIPTION
    输入配置会规范化为 UTF-8、LF、无 BOM 字节，包目录原子落盘且不会覆盖已有目录。
    输出仅包含 config-manifest.json、docker-compose.yml 和 env/production.env。

    .OUTPUTS
    System.String。已创建的配置包绝对路径。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRootPath,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    $sourceFiles = Assert-RequiredSourceFiles -SourceRootPath $SourceRootPath
    $composeBytes = ConvertTo-CanonicalUtf8Bytes -Path $sourceFiles[0]
    $productionEnvBytes = ConvertTo-CanonicalUtf8Bytes -Path $sourceFiles[1]
    Assert-NoPlaintextSecretsInCompose -ComposeBytes $composeBytes
    Assert-NoSensitiveEnvironmentKeys -EnvironmentBytes $productionEnvBytes

    $composeSha256 = Get-Sha256Hex -Bytes $composeBytes
    $productionEnvSha256 = Get-Sha256Hex -Bytes $productionEnvBytes
    $configDigest = Get-ConfigDigest -ComposeSha256 $composeSha256 -ProductionEnvSha256 $productionEnvSha256

    $outputFullPath = ConvertTo-FullPath -Path $OutputPath
    if (Test-Path -LiteralPath $outputFullPath) {
        throw "目标配置包已存在，不允许覆盖：$outputFullPath"
    }
    $outputParent = [IO.Path]::GetDirectoryName($outputFullPath)
    if ([String]::IsNullOrEmpty($outputParent) -or -not (Test-Path -LiteralPath $outputParent -PathType Container)) {
        throw "目标目录的父级不存在：$outputParent"
    }
    Assert-NoReparsePointOnPath -Path $outputParent

    $stagingPath = Join-Path -Path $outputParent -ChildPath ('.iwork-production-config-' + [Guid]::NewGuid().ToString('N'))
    try {
        [IO.Directory]::CreateDirectory($stagingPath) | Out-Null
        Assert-NoReparsePointOnPath -Path $stagingPath
        [IO.Directory]::CreateDirectory((Join-Path -Path $stagingPath -ChildPath 'env')) | Out-Null
        [IO.File]::WriteAllBytes((Join-Path -Path $stagingPath -ChildPath $COMPOSE_NAME), $composeBytes)
        [IO.File]::WriteAllBytes(
            (Join-Path -Path (Join-Path -Path $stagingPath -ChildPath 'env') -ChildPath 'production.env'),
            $productionEnvBytes
        )

        $manifest = [ordered]@{
            schema = $SCHEMA
            application = $APPLICATION
            source_commit = $SourceCommit
            image_digest = $ImageDigest
            compose_sha256 = $composeSha256
            production_env_sha256 = $productionEnvSha256
            config_digest = $configDigest
        }
        $manifestJson = $manifest | ConvertTo-Json -Compress
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllBytes(
            (Join-Path -Path $stagingPath -ChildPath 'config-manifest.json'),
            $utf8.GetBytes($manifestJson + "`n")
        )
        Assert-MinimalBundle -BundlePath $stagingPath
        if (Test-Path -LiteralPath $outputFullPath) {
            throw "目标配置包在写入期间已存在，不允许覆盖：$outputFullPath"
        }
        [IO.Directory]::Move($stagingPath, $outputFullPath)
        $stagingPath = $null
    }
    finally {
        if ($null -ne $stagingPath -and (Test-Path -LiteralPath $stagingPath)) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    return $outputFullPath
}

try {
    Assert-NoPathTraversal -Path $SourceRoot
    Assert-NoPathTraversal -Path $OutputDirectory
    $sourceRootFullPath = ConvertTo-FullPath -Path $SourceRoot
    $outputDirectoryFullPath = ConvertTo-FullPath -Path $OutputDirectory
    $createdPath = New-IworkProductionConfigBundle `
        -SourceRootPath $sourceRootFullPath `
        -OutputPath $outputDirectoryFullPath
    Write-Output "已生成不可变 iwork 生产配置包：$createdPath"
}
catch {
    Write-Error "生产配置包生成失败：$($_.Exception.Message)"
    exit 1
}
