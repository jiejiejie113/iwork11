<#
.SYNOPSIS
    iwork 项目部署脚本
.DESCRIPTION
    用法:
      .\deploy.ps1                    首次部署（完整流程）
      .\deploy.ps1 -Upgrade           升级更新（仅代码+依赖+迁移+重载服务）
      .\deploy.ps1 -ServiceOnly       仅注册/更新 Windows 服务
      .\deploy.ps1 -Status            查看所有服务状态
#>

param(
    [switch]$Upgrade,
    [switch]$ServiceOnly,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PythonVersion = "3.11"

# ===== 配置 =====
$VENV_PATH = "$ProjectRoot\.venv"
$DJANGO_PORT = 8000
$DJANGO_BIND = "0.0.0.0"
$CELERY_LOG_LEVEL = "info"

# ===== 工具函数 =====
function Write-Step { Write-Host "`n>>> $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "    [OK] $($args[0])" -ForegroundColor Green }
function Write-Warn { Write-Host "    [WARN] $($args[0])" -ForegroundColor Yellow }
function Write-Err  { Write-Host "    [ERR] $($args[0])" -ForegroundColor Red; exit 1 }

function Test-Command($cmd) {
    try { Get-Command $cmd -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

# ===== 状态查看 =====
if ($Status) {
    Write-Step "服务状态检查"
    Write-Host ""
    docker compose ps 2>$null
    Write-Host ""
    Get-Service -Name "iwork-*" -ErrorAction SilentlyContinue |
        Select-Object Name, Status, StartType | Format-Table
    Write-Host ""
    Write-Host "Django Server: http://localhost:$DJANGO_PORT/"
    return
}

# ===== 仅注册服务 =====
if ($ServiceOnly) {
    Write-Step "仅注册/更新 Windows 服务"
    Register-Services
    Write-OK "服务注册完成"
    return
}

# ===== 环境检查 =====
Write-Step "第 1 步：环境检查"

# Docker Desktop
if (-not (Test-Command docker)) {
    Write-Err "未检测到 Docker，请先安装 Docker Desktop"
}
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker 未运行，请先启动 Docker Desktop"
}
Write-OK "Docker Desktop 已就绪"

# Python
if (-not (Test-Command python)) {
    Write-Err "未检测到 Python $PythonVersion，请先安装"
}
$actualVersion = python --version 2>&1
if ($actualVersion -notmatch $PythonVersion) {
    Write-Warn "Python 版本: $actualVersion (期望 3.11.x)"
}
Write-OK "Python 已安装: $actualVersion"

# ===== Docker Compose 启动中间件 =====
Write-Step "第 2 步：启动 Docker 中间件 (Redis + MySQL)"
docker compose up -d
Write-OK "Docker 中间件已启动"

# 等待 MySQL 就绪
Write-Host "    等待 MySQL 就绪..."
$retry = 0
do {
    Start-Sleep -Seconds 2
    $retry++
    docker exec mysql-iwork mysqladmin ping -h localhost --silent 2>$null
} while ($LASTEXITCODE -ne 0 -and $retry -lt 30)

if ($retry -ge 30) {
    Write-Err "MySQL 启动超时，请检查 Docker 日志: docker compose logs mysql"
}
Write-OK "MySQL 已就绪"

# ===== 虚拟环境 =====
if (-not $Upgrade -or -not (Test-Path $VENV_PATH)) {
    Write-Step "第 3 步：创建 Python 虚拟环境"
    python -m venv $VENV_PATH
    Write-OK "虚拟环境已创建"
} else {
    Write-Step "第 3 步：虚拟环境已存在，跳过"
}

# 激活并升级 pip
. "$VENV_PATH\Scripts\Activate.ps1"
python -m pip install --upgrade pip --quiet

# ===== 安装依赖 =====
Write-Step "第 4 步：安装 Python 依赖"
pip install -r "$ProjectRoot\requirements.txt" --quiet
Write-OK "依赖安装完成"

# ===== 数据库迁移 =====
Write-Step "第 5 步：数据库迁移"
python manage.py migrate --database=default
Write-OK "Django 系统库迁移完成"

python manage.py migrate --database=iwork_local 2>$null
Write-OK "本地业务库迁移完成"

# ===== 创建超级用户（仅首次） =====
if (-not $Upgrade) {
    Write-Step "第 6 步：检查管理员账户"
    $adminCount = python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True).count())"
    if ([int]$adminCount -eq 0) {
        Write-Warn "未检测到管理员账户，请创建："
        python manage.py createsuperuser
    } else {
        Write-OK "管理员账户已存在 ($adminCount 个)"
    }
}

# ===== 静态文件 =====
Write-Step "第 7 步：收集静态文件"
python manage.py collectstatic --noinput
Write-OK "静态文件收集完成"

# ===== 注册 Windows 服务 =====
Write-Step "第 8 步：注册 Windows 系统服务"
Register-Services
Write-OK "服务注册完成"

# ===== 启动服务 =====
Write-Step "第 9 步：启动应用服务"
Start-Service -Name "iwork-django" -ErrorAction SilentlyContinue
Start-Service -Name "iwork-celery-worker" -ErrorAction SilentlyContinue
Start-Service -Name "iwork-celery-beat" -ErrorAction SilentlyContinue
Write-OK "所有服务已启动"

# ===== 完成 =====
Write-Host ""
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host "  部署完成！" -ForegroundColor Green
Write-Host ("=" * 50) -ForegroundColor Green
Write-Host ""
Write-Host "  看板地址:  http://nginx地址/"
Write-Host "  直接访问:  http://localhost:$DJANGO_PORT/"
Write-Host "  管理后台:  http://localhost:$DJANGO_PORT/admin/"
Write-Host "  查看状态:  .\deploy.ps1 -Status"
Write-Host "  停止服务:  .\stop_services.ps1"
Write-Host "  升级更新:  .\deploy.ps1 -Upgrade"
Write-Host ""

# ===== Windows 服务注册函数 =====
function Register-Services {
    $nssm = "$ProjectRoot\tools\nssm.exe"

    # 确保 NSSM 可用
    if (-not (Test-Path $nssm)) {
        Write-Warn "NSSM 未找到，正在下载..."
        $toolsDir = "$ProjectRoot\tools"
        if (-not (Test-Path $toolsDir)) {
            New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
        }
        $nssmZip = "$env:TEMP\nssm.zip"
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip
        Expand-Archive -Path $nssmZip -DestinationPath $toolsDir -Force
        $nssmDir = Get-ChildItem "$toolsDir\nssm-*" -Directory | Select-Object -First 1
        Copy-Item "$($nssmDir.FullName)\win64\nssm.exe" $nssm
        Write-OK "NSSM 下载完成"
    }

    $pythonExe = "$VENV_PATH\Scripts\python.exe"
    $celeryExe = "$VENV_PATH\Scripts\celery.exe"

    # 日志目录
    $logDir = "$ProjectRoot\logs"
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    # ===== Django 服务 =====
    & $nssm stop "iwork-django" 2>$null
    & $nssm remove "iwork-django" confirm 2>$null

    & $nssm install "iwork-django" "$pythonExe" "manage.py runserver ${DJANGO_BIND}:${DJANGO_PORT}"
    & $nssm set "iwork-django" AppDirectory "$ProjectRoot"
    & $nssm set "iwork-django" AppStdout "$logDir\django_stdout.log"
    & $nssm set "iwork-django" AppStderr "$logDir\django_stderr.log"
    & $nssm set "iwork-django" Start SERVICE_AUTO_START
    Write-OK "Django 服务已注册"

    # ===== Celery Worker 服务 =====
    & $nssm stop "iwork-celery-worker" 2>$null
    & $nssm remove "iwork-celery-worker" confirm 2>$null

    & $nssm install "iwork-celery-worker" "$celeryExe" "-A iwork worker -l $CELERY_LOG_LEVEL -P solo"
    & $nssm set "iwork-celery-worker" AppDirectory "$ProjectRoot"
    & $nssm set "iwork-celery-worker" AppStdout "$logDir\celery_worker_stdout.log"
    & $nssm set "iwork-celery-worker" AppStderr "$logDir\celery_worker_stderr.log"
    & $nssm set "iwork-celery-worker" Start SERVICE_AUTO_START
    & $nssm set "iwork-celery-worker" AppExit Default Restart
    Write-OK "Celery Worker 服务已注册"

    # ===== Celery Beat 服务 =====
    & $nssm stop "iwork-celery-beat" 2>$null
    & $nssm remove "iwork-celery-beat" confirm 2>$null

    & $nssm install "iwork-celery-beat" "$celeryExe" "-A iwork beat -l $CELERY_LOG_LEVEL"
    & $nssm set "iwork-celery-beat" AppDirectory "$ProjectRoot"
    & $nssm set "iwork-celery-beat" AppStdout "$logDir\celery_beat_stdout.log"
    & $nssm set "iwork-celery-beat" AppStderr "$logDir\celery_beat_stderr.log"
    & $nssm set "iwork-celery-beat" Start SERVICE_AUTO_START
    & $nssm set "iwork-celery-beat" AppExit Default Restart
    Write-OK "Celery Beat 服务已注册"
}
