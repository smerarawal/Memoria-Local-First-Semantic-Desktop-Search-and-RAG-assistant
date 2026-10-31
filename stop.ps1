# stop.ps1 — Stop both Memoria backend and frontend
# Usage: Right-click → Run with PowerShell, or: powershell -File stop.ps1

Write-Host ""
Write-Host "  Stopping Memoria processes..." -ForegroundColor Yellow

# Kill uvicorn (backend on port 8000)
$backend = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($backend) {
    foreach ($pid in $backend) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped backend process (PID $pid)" -ForegroundColor Green
    }
} else {
    Write-Host "  Backend not running" -ForegroundColor Gray
}

# Kill Vite dev server (frontend on port 5173)
$frontend = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($frontend) {
    foreach ($pid in $frontend) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped frontend process (PID $pid)" -ForegroundColor Green
    }
} else {
    Write-Host "  Frontend not running" -ForegroundColor Gray
}

Write-Host ""
Write-Host "  Memoria stopped." -ForegroundColor Cyan
Write-Host ""
