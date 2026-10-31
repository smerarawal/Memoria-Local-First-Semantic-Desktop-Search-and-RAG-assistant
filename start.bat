@echo off
title Memoria Launcher
cd /d "%~dp0"

echo ============================================
echo   Starting Memoria Backend + Frontend...
echo ============================================

:: 1. Start Backend in its own window
start "Memoria Backend (port 8000)" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --port 8000 --reload"

:: Wait 4 seconds for backend to initialize
timeout /t 4 /nobreak >nul

:: 2. Start Frontend in its own window
start "Memoria Frontend (port 5173)" cmd /k "cd /d %~dp0frontend && npm run dev"

:: Wait 2 seconds and open browser
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo Memoria is running!
echo Close the two command windows whenever you want to stop.
echo.
pause
