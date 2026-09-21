[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$OutputDirectory,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([String]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
if ([String]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $SourceRoot 'dist'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

# ======
# 运行必需文件：缺失即失败，避免打包出不可运行的目录
$REQUIRED_RELATIVE_PATHS = @(
    'Dockerfile',
    'docker-compose.yml',
    '.dockerignore',
    'start.sh',
    'entrypoint.sh',
    'manage.py',
    'requirements-prod.lock',
    'deploy.ps1',
    'env/local.env',
    'env/production.env',
    'iwork/settings.py',
    'iwork/asgi.py',
    'iwork/wsgi.py'
)

# ======
# 目录级排除（任意层级同名目录整体排除）
$EXCLUDED_DIRECTORY_NAMES = @(
    '.git', '.github', '.venv', 'venv', 'venv311', 'env311', 'node_modules',
    '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.tox',
    '.idea', '.vscode', '.claude', '.agents', '.superpowers', '.reasonix',
    '.codex', '.scratch', 'dist', 'staticfiles', 'local_dev_db', 'mysql-init',
    'htmlcov', '.hypothesis'
)

# ======
# 文件级排除：精确名称或通配符（仅匹配文件名，不匹配路径）
$EXCLUDED_FILE_NAMES = @(
    '.env',
    'dkt-secrets.env',
    'local_dev_settings.py',
    'import_remote_workorders.py',
    'desktop.ini',
    'Thumbs.db'
)
$EXCLUDED_FILE_PATTERNS = @(
    '*.local.env', 'export.env', '*.log', '*.pem', '*.key', '*.p12', '*.pfx',
    '*.bak', '*.backup', '*.db', '*.sqlite', '*.sqlite3'
)

# ======
# 打包后安全扫描：命中即失败关闭，禁止把密钥/仓库/环境带入离线包
$FORBIDDEN_STAGING_PATTERNS = @(
    '.git', 'dkt-secrets.env', 'local_dev_settings.py', '*.pem', '*.key',
    '*.p12', '*.pfx', '*.db', '*.sqlite', '*.sqlite3', 'iwork/.env'
)

function Test-ExcludedItem {
    <#
    .SYNOPSIS
    判断单个源条目是否应排除出离线包。
    #>
    param(
        [Parameter(Mandatory = $true)][IO.FileSystemInfo]$Item,
        [Parameter(Mandatory = $true)][bool]$IsDirectory
    )

    if ($IsDirectory) {
        if ($EXCLUDED_DIRECTORY_NAMES -contains $Item.Name) { return $true }
        return $false
    }
    if ($EXCLUDED_FILE_NAMES -contains $Item.Name) { return $true }
    foreach ($pattern in $EXCLUDED_FILE_PATTERNS) {
        if ($Item.Name -like $pattern) { return $true }
    }
    return $false
}

function Copy-BundleContent {
    <#
    .SYNOPSIS
    递归复制打包内容到暂存目录，并跳过排除项。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $copied = 0
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            if (Test-ExcludedItem -Item $item -IsDirectory $true) { continue }
            New-Item -ItemType Directory -Path $target -Force | Out-Null
            $copied += Copy-BundleContent -Source $item.FullName -Destination $target
        }
        else {
            if (Test-ExcludedItem -Item $item -IsDirectory $false) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
            $copied += 1
        }
    }
    return $copied
}

function New-BundleManifest {
    <#
    .SYNOPSIS
    生成相对路径与SHA-256清单（LF、UTF-8无BOM）。
    #>
    param([Parameter(Mandatory = $true)][string]$RootPath)

    $resolvedRoot = [IO.Path]::GetFullPath($RootPath).TrimEnd('\')
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($file in Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File | Sort-Object FullName) {
        # 清单统一使用正斜杠，与压缩包条目及其它平台校验工具保持一致。
        $relativePath = $file.FullName.Substring($resolvedRoot.Length + 1).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines.Add("$hash  $relativePath")
    }
    $manifestPath = Join-Path $resolvedRoot 'MANIFEST.sha256'
    [IO.File]::WriteAllText(
        $manifestPath,
        (($lines -join "`n") + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    return $lines.Count
}

function Assert-StagingSafe {
    <#
    .SYNOPSIS
    对暂存目录做打包后安全扫描，命中禁止项时失败关闭。
    #>
    param([Parameter(Mandatory = $true)][string]$RootPath)

    foreach ($entry in Get-ChildItem -LiteralPath $RootPath -Recurse -Force) {
        $relativePath = $entry.FullName.Substring($RootPath.Length + 1).Replace('\', '/')
        foreach ($pattern in $FORBIDDEN_STAGING_PATTERNS) {
            if ($relativePath -like $pattern -or $entry.Name -like $pattern) {
                throw "离线包包含禁止项，已拒绝打包：$relativePath"
            }
        }
    }
}

foreach ($required in $REQUIRED_RELATIVE_PATHS) {
    $requiredPath = Join-Path $SourceRoot $required
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "运行必需文件缺失，无法打包：$required"
    }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$operationId = [Guid]::NewGuid().ToString('N')
$stagingPath = Join-Path $OutputDirectory "staging-$operationId"

try {
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
    $fileCount = Copy-BundleContent -Source $SourceRoot -Destination $stagingPath

    # 运行期绑定挂载目标保持存在（logs 与 sqlite 由 Compose 挂载）
    foreach ($runtimeDirectory in @('logs', 'sqlite')) {
        $runtimePath = Join-Path $stagingPath $runtimeDirectory
        New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
        $placeholderPath = Join-Path $runtimePath '.keep'
        if (-not (Test-Path -LiteralPath $placeholderPath)) {
            [IO.File]::WriteAllText($placeholderPath, "runtime placeholder`n", [Text.UTF8Encoding]::new($false))
            $fileCount += 1
        }
    }

    $manifestCount = New-BundleManifest -RootPath $stagingPath
    Assert-StagingSafe -RootPath $stagingPath

    $timestamp = [DateTime]::Now.ToString('yyyyMMdd-HHmmss')
    $zipName = "iwork-offline-$timestamp.zip"
    $zipPath = Join-Path $OutputDirectory $zipName
    if (Test-Path -LiteralPath $zipPath) {
        throw "目标离线包已存在，拒绝覆盖：$zipPath"
    }
    Compress-Archive -Path (Join-Path $stagingPath '*') -DestinationPath $zipPath -CompressionLevel Optimal

    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $result = [ordered]@{
        Status = 'created'
        Source = $SourceRoot
        Bundle = $zipPath
        FileCount = $fileCount
        ManifestEntries = $manifestCount
        BundleSha256 = $zipHash
    }
    if (-not $Quiet) {
        $result | ConvertTo-Json -Depth 4
    }
    exit 0
}
finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}
