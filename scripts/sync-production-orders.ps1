param(
    [switch]$Force,
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# ======
# 文件路径配置
$SOURCE_DB_PATH = 'D:\DM\iwork\sqlite\production_orders.db'
$LOG_DIR = 'D:\DM\iwork\logs'
$STATE_FILE = Join-Path $LOG_DIR 'production-orders-sync-state.json'
$MAINTENANCE_FILE = 'D:\DM\DTD_nginx\logs\watchdog\maintenance\iwork-production-orders.json'

# ======
# Docker 与执行配置
$DOCKER_CLI = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$IWORK_CONTAINER = 'DKT_iwork'
$SYNC_MUTEX_NAME = 'Global\DKT-iwork-Production-Orders-Sync'
$MAINTENANCE_TTL_MINUTES = 30
$IMPORT_TIMEOUT_SECONDS = 1200

function Write-SyncLog([string]$Level, [string]$Message) {
    # 将同步过程写入独立日志文件。
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
    $line = '{0} | {1} | {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -LiteralPath (Join-Path $LOG_DIR 'production-orders-sync.log') `
        -Value $line -Encoding UTF8
}

function Get-SuccessState {
    # 读取上次成功同步状态；状态不存在或损坏时返回空值。
    if (-not (Test-Path -LiteralPath $STATE_FILE -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $STATE_FILE -Raw | ConvertFrom-Json
    } catch {
        Write-SyncLog 'WARNING' "上次成功状态无法读取，将重新同步: $($_.Exception.Message)"
        return $null
    }
}

function Set-SuccessState([string]$Sha256) {
    # 仅在导入成功后原子记录已发布快照。
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
    $state = [ordered]@{
        sha256 = $Sha256
        completed_at = [DateTimeOffset]::Now.ToString('o')
        source_path = $SOURCE_DB_PATH
        source_size = (Get-Item -LiteralPath $SOURCE_DB_PATH).Length
    }
    $tempPath = "$STATE_FILE.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText(
            $tempPath,
            ($state | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $tempPath -Destination $STATE_FILE -Force
    } finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-IworkMaintenance {
    # 创建带过期时间的维护标记，仅放行 iwork HTTP 健康检查。
    $maintenanceDirectory = Split-Path $MAINTENANCE_FILE -Parent
    New-Item -ItemType Directory -Path $maintenanceDirectory -Force | Out-Null
    $startedAt = [DateTimeOffset]::UtcNow
    $marker = [ordered]@{
        application = 'iwork'
        operation = 'production_orders_sync'
        started_at = $startedAt.ToString('o')
        expires_at = $startedAt.AddMinutes(
            $MAINTENANCE_TTL_MINUTES
        ).ToString('o')
        process_id = $PID
    }
    $tempPath = "$MAINTENANCE_FILE.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText(
            $tempPath,
            ($marker | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $tempPath -Destination $MAINTENANCE_FILE -Force
    } finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-IworkMaintenance {
    # 清除当前同步任务创建的维护标记。
    if (Test-Path -LiteralPath $MAINTENANCE_FILE) {
        Remove-Item -LiteralPath $MAINTENANCE_FILE -Force
    }
}

function Enter-SyncLock {
    # 获取全局互斥锁，防止两个同步进程并发发布同一快照。
    $mutex = New-Object Threading.Mutex($false, $SYNC_MUTEX_NAME)
    try {
        if (-not $mutex.WaitOne(0)) {
            $mutex.Dispose()
            return $null
        }
    } catch [Threading.AbandonedMutexException] {
        Write-SyncLog 'WARNING' '检测到上一次同步异常退出，已接管互斥锁'
    }
    return $mutex
}

function Exit-SyncLock($Mutex) {
    # 释放同步互斥锁。
    if ($null -eq $Mutex) {
        return
    }
    try {
        $Mutex.ReleaseMutex()
    } catch {
        Write-SyncLog 'WARNING' "释放同步互斥锁失败: $($_.Exception.Message)"
    } finally {
        $Mutex.Dispose()
    }
}

function ConvertTo-NativeArgument([string]$Argument) {
    # 将参数转换为 Windows 原生命令行可安全解析的形式。
    if ($null -eq $Argument) {
        return '""'
    }
    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }
    $escaped = $Argument -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 30
    )

    # 有界执行原生命令并返回标准输出、错误和退出状态。
    $process = $null
    try {
        $startInfo = New-Object Diagnostics.ProcessStartInfo
        $startInfo.FileName = $FilePath
        $startInfo.Arguments = (($Arguments | ForEach-Object {
            ConvertTo-NativeArgument ([string]$_)
        }) -join ' ')
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true

        $process = New-Object Diagnostics.Process
        $process.StartInfo = $startInfo
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $timedOut = -not $process.WaitForExit($TimeoutSeconds * 1000)
        if ($timedOut) {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            [void]$process.WaitForExit(5000)
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $exitCode = if ($timedOut) { -1 } else { $process.ExitCode }
        return [pscustomobject]@{
            Succeeded = (-not $timedOut -and $exitCode -eq 0)
            TimedOut = $timedOut
            ExitCode = $exitCode
            StdOut = $stdout
            StdErr = $stderr
        }
    } catch {
        return [pscustomobject]@{
            Succeeded = $false
            TimedOut = $false
            ExitCode = -1
            StdOut = ''
            StdErr = $_.Exception.Message
        }
    } finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

function Test-IworkRuntime {
    # 检查 Docker Engine 与 iwork 容器是否可执行同步命令。
    $dockerResult = Invoke-NativeCommand -FilePath $DOCKER_CLI `
        -Arguments @('version', '--format', '{{.Server.Version}}') `
        -TimeoutSeconds 30
    if (-not $dockerResult.Succeeded) {
        Write-SyncLog 'ERROR' "Docker Engine 不可用: $($dockerResult.StdErr)"
        return $false
    }

    $containerResult = Invoke-NativeCommand -FilePath $DOCKER_CLI `
        -Arguments @('inspect', '--format', '{{.State.Status}}', $IWORK_CONTAINER) `
        -TimeoutSeconds 30
    if (-not $containerResult.Succeeded -or $containerResult.StdOut.Trim() -ne 'running') {
        Write-SyncLog 'ERROR' "iwork 容器未运行: $($containerResult.StdErr)"
        return $false
    }
    return $true
}

function Invoke-IworkImport {
    # 在 iwork 容器中执行生产订单导入命令。
    $result = Invoke-NativeCommand -FilePath $DOCKER_CLI `
        -Arguments @(
            'exec', $IWORK_CONTAINER, 'python', 'manage.py',
            'import_production_orders'
        ) `
        -TimeoutSeconds $IMPORT_TIMEOUT_SECONDS
    if (-not $result.Succeeded) {
        Write-SyncLog 'ERROR' (
            '容器内导入失败: timeout={0}, exit={1}, stderr={2}' -f
            $result.TimedOut, $result.ExitCode, $result.StdErr.Trim()
        )
        return $false
    }
    Write-SyncLog 'INFO' "容器内导入完成: $($result.StdOut.Trim())"
    return $true
}

function Invoke-ProductionOrdersSync {
    param([switch]$ForceRun)

    # 根据快照哈希决定跳过或执行生产订单同步。
    $mutex = Enter-SyncLock
    if ($null -eq $mutex) {
        Write-SyncLog 'INFO' '已有同步任务运行，本次成功跳过'
        return 0
    }

    try {
        if (-not (Test-Path -LiteralPath $SOURCE_DB_PATH -PathType Leaf)) {
            Write-SyncLog 'ERROR' "生产订单快照不存在: $SOURCE_DB_PATH"
            return 1
        }

        $sourceHash = (Get-FileHash -LiteralPath $SOURCE_DB_PATH -Algorithm SHA256).Hash
        $state = Get-SuccessState
        if (-not $ForceRun -and $null -ne $state -and $state.sha256 -eq $sourceHash) {
            Write-SyncLog 'INFO' "快照未变化，成功跳过: SHA256=$sourceHash"
            return 0
        }

        if (-not (Test-IworkRuntime)) {
            return 1
        }

        Start-IworkMaintenance
        try {
            if (-not (Invoke-IworkImport)) {
                return 1
            }
            $hashAfterImport = (
                Get-FileHash -LiteralPath $SOURCE_DB_PATH -Algorithm SHA256
            ).Hash
            if ($hashAfterImport -ne $sourceHash) {
                Write-SyncLog 'ERROR' (
                    '导入期间源快照发生变化，本次不记录成功状态: before={0}, after={1}' -f
                    $sourceHash, $hashAfterImport
                )
                return 1
            }
            Set-SuccessState -Sha256 $sourceHash
            Write-SyncLog 'SUCCESS' "生产订单同步完成: SHA256=$sourceHash"
            return 0
        } finally {
            Stop-IworkMaintenance
        }
    } catch {
        Write-SyncLog 'ERROR' "同步任务异常: $($_.Exception.Message)"
        return 1
    } finally {
        Exit-SyncLock $mutex
    }
}

if (-not $NoRun) {
    exit (Invoke-ProductionOrdersSync -ForceRun:$Force)
}
