param(
    [switch]$Force,
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# 复用现有生产订单同步的运行时检查、互斥锁、维护窗口和超时处理。
$requestedForce = $Force
$requestedNoRun = $NoRun
. (Join-Path $PSScriptRoot 'sync-production-orders.ps1') -NoRun
$Force = $requestedForce
$NoRun = $requestedNoRun

$SOURCE_DB_PATH = 'D:\DM\iwork\sqlite\iGarment_ProdOrder.db'
$IMPORT_SCRIPT_PATH = Join-Path $PSScriptRoot 'import_igarment_production_orders.py'
$STATE_FILE = Join-Path $LOG_DIR 'igarment-production-orders-sync-state.json'
$CONTAINER_IMPORT_SCRIPT = '/tmp/import_igarment_production_orders.py'

function Write-SyncLog([string]$Level, [string]$Message) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
    $line = '{0} | {1} | {2}' -f (
        Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    ), $Level, $Message
    Add-Content -LiteralPath (
        Join-Path $LOG_DIR 'igarment-production-orders-sync.log'
    ) -Value $line -Encoding UTF8
}

function Invoke-IworkImport {
    if (-not (Test-Path -LiteralPath $IMPORT_SCRIPT_PATH -PathType Leaf)) {
        Write-SyncLog 'ERROR' "导入脚本不存在: $IMPORT_SCRIPT_PATH"
        return $false
    }

    $copyResult = Invoke-NativeCommand -FilePath $DOCKER_CLI `
        -Arguments @(
            'cp', $IMPORT_SCRIPT_PATH,
            "${IWORK_CONTAINER}:$CONTAINER_IMPORT_SCRIPT"
        ) `
        -TimeoutSeconds 60
    if (-not $copyResult.Succeeded) {
        Write-SyncLog 'ERROR' (
            '复制导入脚本失败: exit={0}, stderr={1}' -f `
            $copyResult.ExitCode, $copyResult.StdErr.Trim()
        )
        return $false
    }

    $result = Invoke-NativeCommand -FilePath $DOCKER_CLI `
        -Arguments @(
            'exec', '-e', 'IWORK_PROCESS_ROLE=management',
            $IWORK_CONTAINER, 'python', $CONTAINER_IMPORT_SCRIPT
        ) `
        -TimeoutSeconds $IMPORT_TIMEOUT_SECONDS
    if (-not $result.Succeeded) {
        Write-SyncLog 'ERROR' (
            'iGarment 导入失败: timeout={0}, exit={1}, stderr={2}' -f `
            $result.TimedOut, $result.ExitCode, $result.StdErr.Trim()
        )
        return $false
    }
    Write-SyncLog 'INFO' "iGarment 导入成功: $($result.StdOut.Trim())"
    return $true
}

if (-not $NoRun) {
    exit (Invoke-ProductionOrdersSync -ForceRun:$Force)
}
