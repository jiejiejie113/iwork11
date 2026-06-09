@echo off
title Production Dashboard Stopper

echo ========================================
echo    Production Dashboard Stop Script
echo ========================================
echo.

:: Stop Celery Worker
echo Stopping Celery Worker...
taskkill /f /im celery.exe >nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq CeleryWorker*" >nul 2>&1
echo     Done

:: Stop Celery Beat
echo Stopping Celery Beat...
taskkill /f /im python.exe /fi "WINDOWTITLE eq CeleryBeat*" >nul 2>&1
echo     Done

:: Stop Django Server
echo Stopping Django Server...
taskkill /f /im python.exe /fi "WINDOWTITLE eq DjangoServer*" >nul 2>&1
echo     Done

:: Stop Log Monitor
echo Stopping Log Monitor...
taskkill /f /im powershell.exe /fi "WINDOWTITLE eq LogMonitor*" >nul 2>&1
echo     Done

:: Clean up celery beat schedule files
del /q celerybeat-schedule.* >nul 2>&1

echo.
echo ========================================
echo       All services stopped
echo ========================================
echo.

set /p close_redis="Stop Redis container? (Y/N): "
if /i "%close_redis%" equ "Y" (
    echo.
    echo Stopping Redis container...
    docker stop redis-iwork >nul 2>&1
    echo     Redis container stopped
) else (
    echo Redis container keeps running
)

echo.
pause