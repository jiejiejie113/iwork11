@echo off
setlocal enabledelayedexpansion
title Production Dashboard Launcher

echo ========================================
echo    Production Dashboard Startup Script
echo ========================================
echo.

:: Kill previous processes to avoid duplicates
echo [0] Stopping old processes...
taskkill /f /im celery.exe >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq CeleryWorker*" >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq CeleryBeat*" >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq DjangoServer*" >nul 2>&1
del /q celerybeat-schedule.* >nul 2>&1
echo     Cleared old processes

:: Activate virtual environment
set VENV=%~dp0.venv
if not exist "%VENV%\Scripts\python.exe" (
    echo     Virtual environment not found at %VENV%
    pause
    exit /b 1
)
set PYTHON=%VENV%\Scripts\python.exe
set CELERY=%VENV%\Scripts\celery.exe
echo     Virtual environment: %VENV%
echo.

:: Check Docker Desktop
echo [1] Checking Docker Desktop...
docker ps >nul 2>&1
if %errorlevel% equ 0 (
    echo     Docker Desktop is running
    goto :redis_check
)

echo     Docker Desktop is not running
echo     Starting Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

:: Wait for Docker to be ready (max 60 seconds)
set /a docker_wait=0

:wait_docker
set /a docker_wait+=1
if !docker_wait! gtr 60 (
    echo     Docker Desktop startup timeout (60s)
    echo     Please start Docker Desktop manually and try again
    pause
    exit /b 1
)

ping 127.0.0.1 -n 2 >nul
docker ps >nul 2>&1
if %errorlevel% neq 0 (
    echo     Waiting for Docker... [!docker_wait!s/60s]
    goto wait_docker
)

echo     Docker Desktop started successfully

:redis_check
echo.

:: Check Docker Redis
echo [2] Checking Redis (Docker)...

:: Check if container exists
docker inspect redis-iwork >nul 2>&1
if %errorlevel% neq 0 (
    echo     Creating and starting Redis container...
    docker run -d --name redis-iwork -p 6379:6379 redis:7-alpine >nul 2>&1
) else (
    :: Check if container is running
    for /f "tokens=*" %%i in ('docker inspect redis-iwork --format "{{.State.Running}}" 2^>nul') do set redis_running=%%i
    if "!redis_running!"=="true" (
        echo     Redis container is running
        goto :celery_start
    ) else (
        echo     Starting existing Redis container...
        docker start redis-iwork >nul 2>&1
    )
)

:: Verify Redis started
ping 127.0.0.1 -n 3 >nul
for /f "tokens=*" %%i in ('docker inspect redis-iwork --format "{{.State.Running}}" 2^>nul') do set redis_running=%%i
if "!redis_running!"=="true" (
    echo     Redis started successfully
) else (
    echo     Redis startup failed
    pause
    exit /b 1
)

:celery_start

echo.

:: Start Celery Worker
echo [3] Starting Celery Worker...
set IWORK_PROCESS_ROLE=celery
start "CeleryWorker" /min "%CELERY%" -A iwork worker -l info -P solo
echo     Celery Worker started

echo.

:: Start Celery Beat
echo [4] Starting Celery Beat...
set IWORK_PROCESS_ROLE=celery
start "CeleryBeat" /min "%CELERY%" -A iwork beat -l info
echo     Celery Beat started

echo.

:: Start Django Server
echo [5] Starting Django Server...
set IWORK_PROCESS_ROLE=web
start "DjangoServer" /min "%PYTHON%" manage.py runserver 0.0.0.0:8000
echo     Django Server started

echo.

:: Start Log Monitor
echo [6] Starting Log Monitor...
ping 127.0.0.1 -n 3 >nul
start "LogMonitor" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\watch_logs.ps1"
echo     Log Monitor started

echo.

echo ========================================
echo       All services started!
echo ========================================
echo.
echo Dashboard URL: http://localhost:8000/
echo.
echo To stop, run: stop_dashboard.bat
echo.

pause
