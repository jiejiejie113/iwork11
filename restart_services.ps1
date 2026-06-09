<#
.SYNOPSIS
    重启 iwork 所有 Windows 服务
#>

$ErrorActionPreference = "Stop"

Write-Host "重启 iwork 所有服务..." -ForegroundColor Yellow

@("iwork-daphne", "iwork-celery-worker", "iwork-celery-beat") | ForEach-Object {
    Restart-Service -Name $_ -Force
    Write-Host "  已重启: $_"
}

Write-Host "所有服务已重启" -ForegroundColor Green
