<#
.SYNOPSIS
    停止 iwork 所有服务（Windows 服务 + Docker 中间件）
#>

$ErrorActionPreference = "SilentlyContinue"

Write-Host "停止 iwork 所有服务..." -ForegroundColor Yellow

@("iwork-daphne", "iwork-celery-worker", "iwork-celery-beat") | ForEach-Object {
    Stop-Service -Name $_ -Force
    Write-Host "  已停止: $_"
}

docker compose down
Write-Host "  已停止 Docker 中间件"

Write-Host "所有服务已停止" -ForegroundColor Green
