$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $repositoryRoot 'tools\skills\dkt-cicd'
$installerPath = Join-Path $repositoryRoot 'scripts\Install-DktCicdSkill.ps1'
$testRoot = Join-Path $env:TEMP ('dkt-cicd-install-test-' + [Guid]::NewGuid().ToString('N'))
$destinationPath = Join-Path $testRoot 'dkt-cicd'

function Get-TestManifest {
    <#
    .SYNOPSIS
    生成测试目录的相对路径与SHA-256清单。
    #>
    param([Parameter(Mandatory = $true)][string]$RootPath)

    $resolvedRoot = [IO.Path]::GetFullPath($RootPath).TrimEnd('\')
    $manifest = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File | Sort-Object FullName) {
        $relativePath = $file.FullName.Substring($resolvedRoot.Length + 1)
        $manifest[$relativePath] = (
            Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    return $manifest
}

function Assert-TestCondition {
    <#
    .SYNOPSIS
    验证安装测试条件，不满足时终止测试。
    #>
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not $Condition) {
        throw "断言失败：$Message"
    }
}

try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

    $firstResult = & $installerPath `
        -SourcePath $sourcePath `
        -DestinationPath $destinationPath `
        -TestMode | ConvertFrom-Json
    Assert-TestCondition -Condition ($firstResult.Status -eq 'installed') -Message '首次执行应完成安装'

    $sourceManifest = Get-TestManifest -RootPath $sourcePath
    $destinationManifest = Get-TestManifest -RootPath $destinationPath
    Assert-TestCondition -Condition ($sourceManifest.Count -eq $destinationManifest.Count) -Message '源与安装副本文件数应一致'
    foreach ($relativePath in $sourceManifest.Keys) {
        Assert-TestCondition -Condition (
            $destinationManifest.Contains($relativePath) -and
            $destinationManifest[$relativePath] -ceq $sourceManifest[$relativePath]
        ) -Message "安装文件哈希应一致：$relativePath"
    }

    $secondResult = & $installerPath `
        -SourcePath $sourcePath `
        -DestinationPath $destinationPath `
        -TestMode | ConvertFrom-Json
    Assert-TestCondition -Condition ($secondResult.Status -eq 'current') -Message '重复执行应保持幂等'

    Write-Output "dkt-cicd Skill安装测试通过，共验证 $($sourceManifest.Count) 个文件。"
    $global:LASTEXITCODE = 0
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    $allowedPrefix = [IO.Path]::GetFullPath((Join-Path $env:TEMP 'dkt-cicd-install-test-'))
    if (-not $resolvedTestRoot.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理非测试目录：$resolvedTestRoot"
    }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
