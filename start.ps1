# start.ps1 — Start both Memoria backend and frontend in separate windows
# Usage: Right-click → Run with PowerShell, or: powershell -File start.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host "    Memoria — Starting backend + frontend..." -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# Start backend (uvicorn on port 8000)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; Write-Host 'Memoria Backend (port 8000)' -ForegroundColor Green; python -m uvicorn main:app --port 8000 --reload" -WorkingDirectory "$root\backend"

# Small delay so backend starts first
Start-Sleep -Seconds 2

# Start frontend (Vite dev server on port 5173)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; Write-Host 'Memoria Frontend (port 5173)' -ForegroundColor Green; npm run dev" -WorkingDirectory "$root\frontend"

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Opening browser..." -ForegroundColor Gray
Start-Process "http://localhost:5173"
Write-Host ""
Write-Host "  Close the two terminal windows to stop Memoria." -ForegroundColor Gray
Write-Host ""
