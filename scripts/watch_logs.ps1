# 统一日志监控脚本
chcp 65001 > $null

$logDir = Join-Path $PSScriptRoot '..\logs'

Write-Host '=== 统一日志监控 (按 Ctrl+C 退出) ===' -ForegroundColor Cyan
Write-Host ('日志目录: ' + $logDir) -ForegroundColor Cyan
Write-Host ''

$latest = $null
$waitSeconds = 0
while ($waitSeconds -lt 15) {
    $latest = Get-ChildItem ($logDir + '\all_*.log') -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) { break }
    Start-Sleep -Seconds 1
    $waitSeconds++
}

if (-not $latest) {
    Write-Host 'Waiting for log file timed out.' -ForegroundColor Yellow
    pause
    exit
}

Write-Host ('Monitoring: ' + $latest.Name) -ForegroundColor Green
Write-Host '----------------------------------------------------------------------'
Get-Content -Path $latest.FullName -Wait -Encoding UTF8
