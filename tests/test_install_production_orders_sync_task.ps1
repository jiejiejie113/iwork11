param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$InstallScript = Join-Path $PSScriptRoot '..\scripts\install-production-orders-sync-task.ps1'
. $InstallScript -NoRun

$TestRoot = Join-Path ([IO.Path]::GetTempPath()) (
    'iwork-production-orders-task-test-' + [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null
$SYNC_SCRIPT = Join-Path $TestRoot 'sync-production-orders.ps1'
New-Item -ItemType File -Path $SYNC_SCRIPT -Force | Out-Null

$script:Failures = 0
$script:CapturedTrigger = $null
$script:CapturedPrincipal = $null
$script:CapturedSettings = $null
$script:CapturedRegistration = $null
$script:TimeZoneChecks = 0

function Assert-True([bool]$Condition, [string]$Message) {
    # 记录计划任务安装行为断言结果。
    if ($Condition) {
        Write-Host "[通过] $Message" -ForegroundColor Green
    } else {
        Write-Host "[失败] $Message" -ForegroundColor Red
        $script:Failures++
    }
}

function Get-TimeZone {
    $script:TimeZoneChecks++
    return [pscustomobject]@{ Id='China Standard Time' }
}

function New-ScheduledTaskAction {
    param($Execute, $Argument)
    return [pscustomobject]@{ Execute=$Execute; Argument=$Argument }
}

function New-ScheduledTaskTrigger {
    param([switch]$Daily, $At)
    $script:CapturedTrigger = [pscustomobject]@{ Daily=$Daily; At=$At }
    return $script:CapturedTrigger
}

function New-ScheduledTaskPrincipal {
    param($UserId, $LogonType, $RunLevel)
    $script:CapturedPrincipal = [pscustomobject]@{
        UserId=$UserId; LogonType=$LogonType; RunLevel=$RunLevel
    }
    return $script:CapturedPrincipal
}

function New-ScheduledTaskSettingsSet {
    param(
        $MultipleInstances,
        $ExecutionTimeLimit,
        $RestartCount,
        $RestartInterval,
        [switch]$StartWhenAvailable
    )
    $script:CapturedSettings = [pscustomobject]@{
        MultipleInstances=$MultipleInstances
        ExecutionTimeLimit=$ExecutionTimeLimit
        RestartCount=$RestartCount
        RestartInterval=$RestartInterval
        StartWhenAvailable=$StartWhenAvailable
    }
    return $script:CapturedSettings
}

function Register-ScheduledTask {
    param(
        $TaskPath,
        $TaskName,
        $Action,
        $Trigger,
        $Principal,
        $Settings,
        $Description,
        [switch]$Force
    )
    $script:CapturedRegistration = [pscustomobject]@{
        TaskPath=$TaskPath; TaskName=$TaskName; Action=$Action
        Trigger=$Trigger; Principal=$Principal; Settings=$Settings
        Description=$Description; Force=$Force
    }
}

Install-ProductionOrdersSyncTask

Assert-True ($script:CapturedTrigger.Daily) '任务按每日频率触发'
Assert-True ($script:CapturedTrigger.At -eq '00:00') '任务在服务器本地时间 00:00 触发'
Assert-True ($script:CapturedPrincipal.UserId -eq 'SYSTEM') '任务使用 SYSTEM 账户'
Assert-True ($script:CapturedPrincipal.RunLevel -eq 'Highest') '任务使用最高权限'
Assert-True ($script:CapturedSettings.MultipleInstances -eq 'IgnoreNew') '并发任务使用 IgnoreNew'
Assert-True ($script:CapturedSettings.ExecutionTimeLimit.TotalMinutes -eq 20) '任务超时为 20 分钟'
Assert-True ($script:CapturedSettings.RestartCount -eq 2) '失败最多重试两次'
Assert-True ($script:CapturedSettings.RestartInterval.TotalMinutes -eq 5) '失败重试间隔为 5 分钟'
Assert-True ($script:CapturedRegistration.TaskPath -eq '\DKT\') '任务注册到 DKT 目录'
Assert-True ($script:CapturedRegistration.TaskName -eq 'iwork-Production-Orders-Sync') '任务名正确'
Assert-True ($script:TimeZoneChecks -eq 1) '安装前验证服务器使用北京时间'

Write-Host "=== 汇总: $($script:Failures) 项失败 ===" -ForegroundColor Cyan
$exitCode = $script:Failures
Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
exit $exitCode
