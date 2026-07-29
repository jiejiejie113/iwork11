param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$SyncScript = Join-Path $PSScriptRoot '..\scripts\sync-production-orders.ps1'
. $SyncScript -NoRun

$TestRoot = Join-Path ([IO.Path]::GetTempPath()) (
    'iwork-production-orders-sync-test-' + [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null

$SOURCE_DB_PATH = Join-Path $TestRoot 'production_orders.db'
$LOG_DIR = Join-Path $TestRoot 'logs'
$STATE_FILE = Join-Path $LOG_DIR 'production-orders-sync-state.json'
$MAINTENANCE_FILE = Join-Path $TestRoot 'iwork-production-orders.json'
[IO.File]::WriteAllText($SOURCE_DB_PATH, 'same snapshot')

$script:Failures = 0

function Assert-True([bool]$Condition, [string]$Message) {
    # 记录 PowerShell 行为测试断言结果。
    if ($Condition) {
        Write-Host "[通过] $Message" -ForegroundColor Green
    } else {
        Write-Host "[失败] $Message" -ForegroundColor Red
        $script:Failures++
    }
}

Write-Host '=== T1: 相同快照应成功跳过，不调用 Docker ===' -ForegroundColor Cyan
$sourceHash = (Get-FileHash -LiteralPath $SOURCE_DB_PATH -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
@{
    sha256 = $sourceHash
    completed_at = '2026-07-29T00:00:00+08:00'
    row_count = 29043
} | ConvertTo-Json | Set-Content -LiteralPath $STATE_FILE -Encoding UTF8

$script:RuntimeChecks = 0
$script:ImportCalls = 0
Set-Item Function:Test-IworkRuntime {
    $script:RuntimeChecks++
    return $true
}
Set-Item Function:Invoke-IworkImport {
    $script:ImportCalls++
    return $true
}

$result = Invoke-ProductionOrdersSync
Assert-True ($result -eq 0) '相同快照返回成功'
Assert-True ($script:RuntimeChecks -eq 0) '相同快照不检查 Docker 运行时'
Assert-True ($script:ImportCalls -eq 0) '相同快照不执行导入'
Assert-True (-not (Test-Path -LiteralPath $MAINTENANCE_FILE)) '相同快照不创建维护标记'

Write-Host '=== T2: 新快照应在维护期内导入并更新成功状态 ===' -ForegroundColor Cyan
[IO.File]::WriteAllText($SOURCE_DB_PATH, 'changed snapshot')
$changedHash = (Get-FileHash -LiteralPath $SOURCE_DB_PATH -Algorithm SHA256).Hash
$script:RuntimeChecks = 0
$script:ImportCalls = 0
$script:MarkerWasValidDuringImport = $false
Set-Item Function:Test-IworkRuntime {
    $script:RuntimeChecks++
    return $true
}
Set-Item Function:Invoke-IworkImport {
    $script:ImportCalls++
    if (Test-Path -LiteralPath $MAINTENANCE_FILE -PathType Leaf) {
        $marker = Get-Content -LiteralPath $MAINTENANCE_FILE -Raw | ConvertFrom-Json
        $startedAt = [DateTimeOffset]::Parse($marker.started_at)
        $expiresAt = [DateTimeOffset]::Parse($marker.expires_at)
        $script:MarkerWasValidDuringImport = (
            $startedAt -le [DateTimeOffset]::UtcNow -and
            $expiresAt -gt [DateTimeOffset]::UtcNow -and
            ($expiresAt - $startedAt).TotalMinutes -le 30
        )
    }
    return $true
}

$result = Invoke-ProductionOrdersSync
$updatedState = Get-Content -LiteralPath $STATE_FILE -Raw | ConvertFrom-Json
Assert-True ($result -eq 0) '新快照同步返回成功'
Assert-True ($script:RuntimeChecks -eq 1) '新快照检查 Docker 运行时'
Assert-True ($script:ImportCalls -eq 1) '新快照执行一次导入'
Assert-True $script:MarkerWasValidDuringImport '导入期间存在未过期维护标记'
Assert-True ($updatedState.sha256 -eq $changedHash) '成功后原子更新快照哈希'
Assert-True (-not (Test-Path -LiteralPath $MAINTENANCE_FILE)) '同步完成后清除维护标记'

Write-Host '=== T3: 导入失败应保留成功状态并清除维护标记 ===' -ForegroundColor Cyan
[IO.File]::WriteAllText($SOURCE_DB_PATH, 'failed snapshot')
Set-Item Function:Test-IworkRuntime { return $true }
Set-Item Function:Invoke-IworkImport { return $false }

$result = Invoke-ProductionOrdersSync
$stateAfterFailure = Get-Content -LiteralPath $STATE_FILE -Raw | ConvertFrom-Json
Assert-True ($result -eq 1) '导入失败返回非零状态'
Assert-True ($stateAfterFailure.sha256 -eq $changedHash) '导入失败不更新成功哈希'
Assert-True (-not (Test-Path -LiteralPath $MAINTENANCE_FILE)) '导入失败仍清除维护标记'

Write-Host '=== T4: 导入期间源快照变化应视为失败 ===' -ForegroundColor Cyan
[IO.File]::WriteAllText($SOURCE_DB_PATH, 'snapshot before import')
Set-Item Function:Test-IworkRuntime { return $true }
Set-Item Function:Invoke-IworkImport {
    [IO.File]::WriteAllText($SOURCE_DB_PATH, 'snapshot replaced during import')
    return $true
}

$result = Invoke-ProductionOrdersSync
$stateAfterReplacement = Get-Content -LiteralPath $STATE_FILE -Raw | ConvertFrom-Json
Assert-True ($result -eq 1) '导入期间源快照变化返回非零状态'
Assert-True ($stateAfterReplacement.sha256 -eq $changedHash) '源快照变化不更新成功哈希'
Assert-True (-not (Test-Path -LiteralPath $MAINTENANCE_FILE)) '源快照变化仍清除维护标记'

Write-Host "=== 汇总: $($script:Failures) 项失败 ===" -ForegroundColor Cyan
$exitCode = $script:Failures
Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
exit $exitCode
