[CmdletBinding()]
param(
    [string]$SourcePath,
    [string]$DestinationPath,
    [switch]$TestMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([String]::IsNullOrWhiteSpace($SourcePath)) {
    $SourcePath = Join-Path $PSScriptRoot '..\tools\skills\dkt-cicd'
}
if ([String]::IsNullOrWhiteSpace($DestinationPath)) {
    $DestinationPath = Join-Path $env:USERPROFILE '.agents\skills\dkt-cicd'
}

function Get-SkillManifest {
    <#
    .SYNOPSIS
    生成技能目录的相对路径与SHA-256清单。
    #>
    param([Parameter(Mandatory = $true)][string]$RootPath)

    $resolvedRoot = [IO.Path]::GetFullPath($RootPath).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
        throw "技能目录不存在：$resolvedRoot"
    }

    $manifest = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File | Sort-Object FullName) {
        $relativePath = $file.FullName.Substring($resolvedRoot.Length + 1)
        $manifest[$relativePath] = (
            Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    return $manifest
}

function Test-ManifestsEqual {
    <#
    .SYNOPSIS
    判断两个技能文件清单是否完全一致。
    #>
    param(
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Expected,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Actual
    )

    if ($Expected.Count -ne $Actual.Count) {
        return $false
    }
    foreach ($relativePath in $Expected.Keys) {
        if (-not $Actual.Contains($relativePath) -or
            $Actual[$relativePath] -cne $Expected[$relativePath]) {
            return $false
        }
    }
    return $true
}

function Assert-SafeManagedPath {
    <#
    .SYNOPSIS
    限制安装与清理路径只能位于允许的技能根目录或隔离测试根目录。
    #>
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $allowedRoot = if ($TestMode) {
        [IO.Path]::GetFullPath((Join-Path $env:TEMP 'dkt-cicd-install-test-'))
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.agents\skills')) + '\'
    }
    if (-not $resolvedPath.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作允许范围外的路径：$resolvedPath"
    }
    $leafName = Split-Path -Leaf $resolvedPath
    if ($leafName -cnotmatch '^dkt-cicd(?:\.(?:staging|backup)\.[0-9a-f]{32})?$') {
        throw "拒绝操作非dkt-cicd技能路径：$resolvedPath"
    }
    return $resolvedPath
}

$resolvedSource = [IO.Path]::GetFullPath($SourcePath)
$expectedSource = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\skills\dkt-cicd'))
if (-not $resolvedSource.Equals($expectedSource, [StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝安装非仓库版本源：$resolvedSource"
}
$resolvedDestination = Assert-SafeManagedPath -Path $DestinationPath
if (-not (Test-Path -LiteralPath (Join-Path $resolvedSource 'SKILL.md') -PathType Leaf)) {
    throw "版本化技能源缺少SKILL.md：$resolvedSource"
}

$sourceManifest = Get-SkillManifest -RootPath $resolvedSource
if ($sourceManifest.Count -eq 0) {
    throw '版本化技能源为空，拒绝安装。'
}

if (Test-Path -LiteralPath $resolvedDestination -PathType Container) {
    $installedManifest = Get-SkillManifest -RootPath $resolvedDestination
    if (Test-ManifestsEqual -Expected $sourceManifest -Actual $installedManifest) {
        [ordered]@{
            Status = 'current'
            Source = $resolvedSource
            Destination = $resolvedDestination
            FileCount = $sourceManifest.Count
        } | ConvertTo-Json -Depth 4
        exit 0
    }
}

$destinationParent = Split-Path -Parent $resolvedDestination
New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
$operationId = [Guid]::NewGuid().ToString('N')
$stagingPath = Assert-SafeManagedPath -Path (Join-Path $destinationParent "dkt-cicd.staging.$operationId")
$backupPath = Assert-SafeManagedPath -Path (Join-Path $destinationParent "dkt-cicd.backup.$operationId")
$backupCreated = $false
$destinationSwitched = $false

try {
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $resolvedSource -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $stagingPath -Recurse -Force
    }

    $stagingManifest = Get-SkillManifest -RootPath $stagingPath
    if (-not (Test-ManifestsEqual -Expected $sourceManifest -Actual $stagingManifest)) {
        throw '暂存技能与版本化技能源不一致，拒绝切换。'
    }

    if (Test-Path -LiteralPath $resolvedDestination) {
        Move-Item -LiteralPath $resolvedDestination -Destination $backupPath
        $backupCreated = $true
    }
    Move-Item -LiteralPath $stagingPath -Destination $resolvedDestination
    $destinationSwitched = $true

    $finalManifest = Get-SkillManifest -RootPath $resolvedDestination
    if (-not (Test-ManifestsEqual -Expected $sourceManifest -Actual $finalManifest)) {
        throw '安装后的技能与版本化技能源不一致。'
    }

    if ($backupCreated -and (Test-Path -LiteralPath $backupPath)) {
        Remove-Item -LiteralPath $backupPath -Recurse -Force
        $backupCreated = $false
    }

    [ordered]@{
        Status = 'installed'
        Source = $resolvedSource
        Destination = $resolvedDestination
        FileCount = $sourceManifest.Count
    } | ConvertTo-Json -Depth 4
}
catch {
    if ($destinationSwitched -and (Test-Path -LiteralPath $resolvedDestination)) {
        Remove-Item -LiteralPath $resolvedDestination -Recurse -Force
    }
    if ($backupCreated -and (Test-Path -LiteralPath $backupPath)) {
        Move-Item -LiteralPath $backupPath -Destination $resolvedDestination
        $backupCreated = $false
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
}
