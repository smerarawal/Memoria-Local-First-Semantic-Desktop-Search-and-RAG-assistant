@echo off
title Memoria Stopper
echo Stopping Memoria processes on ports 8000 and 5173...

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Stopping backend PID %%a
    taskkill /f /pid %%a >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo Stopping frontend PID %%a
    taskkill /f /pid %%a >nul 2>&1
)

echo Memoria stopped.
pause
