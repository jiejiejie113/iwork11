<#
.SYNOPSIS
    卸载 iwork Windows 服务（不删除 Docker 容器和数据卷）
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$nssm = "$ProjectRoot\tools\nssm.exe"

if (-not (Test-Path $nssm)) {
    Write-Host "NSSM 未找到，无法卸载服务" -ForegroundColor Red
    Write-Host "请确保 $nssm 存在" -ForegroundColor Red
    exit 1
}

Write-Host "卸载 iwork Windows 服务..." -ForegroundColor Yellow

@("iwork-django", "iwork-daphne", "iwork-celery-worker", "iwork-celery-beat") | ForEach-Object {
    & $nssm stop $_ 2>$null
    & $nssm remove $_ confirm 2>$null
    Write-Host "  已卸载: $_"
}

Write-Host "所有服务已卸载" -ForegroundColor Green
Write-Host ""
Write-Host "Docker 容器和数据卷未修改。当前部署由 Docker 管理。" -ForegroundColor Yellow
