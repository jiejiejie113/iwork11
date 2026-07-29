param(
    [switch]$RunNow,
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# ======
# Windows 计划任务配置
$TASK_PATH = '\DKT\'
$TASK_NAME = 'iwork-Production-Orders-Sync'
$SYNC_SCRIPT = 'D:\DM\iwork\scripts\sync-production-orders.ps1'
$POWERSHELL_EXE = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$DAILY_START_TIME = '00:00'
$EXECUTION_TIMEOUT_MINUTES = 20
$RESTART_COUNT = 2
$RESTART_INTERVAL_MINUTES = 5

function Install-ProductionOrdersSyncTask {
    # 创建或覆盖 iwork 生产订单每日同步计划任务。
    $serverTimeZone = Get-TimeZone
    if ($serverTimeZone.Id -ne 'China Standard Time') {
        throw (
            '服务器时区不是北京时间，拒绝安装每日 00:00 任务: {0}' -f
            $serverTimeZone.Id
        )
    }
    if (-not (Test-Path -LiteralPath $SYNC_SCRIPT -PathType Leaf)) {
        throw "每日同步脚本不存在: $SYNC_SCRIPT"
    }

    $action = New-ScheduledTaskAction `
        -Execute $POWERSHELL_EXE `
        -Argument (
            '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f
            $SYNC_SCRIPT
        )
    $trigger = New-ScheduledTaskTrigger -Daily -At $DAILY_START_TIME
    $principal = New-ScheduledTaskPrincipal `
        -UserId 'SYSTEM' `
        -LogonType ServiceAccount `
        -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $EXECUTION_TIMEOUT_MINUTES) `
        -RestartCount $RESTART_COUNT `
        -RestartInterval (New-TimeSpan -Minutes $RESTART_INTERVAL_MINUTES) `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskPath $TASK_PATH `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description '每日 00:00 将 production_orders.db 精确同步到 iwork MySQL' `
        -Force | Out-Null

    Write-Host "计划任务已安装: $TASK_PATH$TASK_NAME" -ForegroundColor Green
    if ($RunNow) {
        Start-ScheduledTask -TaskPath $TASK_PATH -TaskName $TASK_NAME
        Write-Host '已触发一次计划任务运行' -ForegroundColor Green
    }
}

if (-not $NoRun) {
    Install-ProductionOrdersSyncTask
}
