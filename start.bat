@echo off
title Ship Inventory Management System
cd /d "%~dp0"
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║  Starting Ship Inventory on port 8080...     ║
echo  ╚═══════════════════════════════════════════════╝
echo.

REM Find Python
if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo  ===================================================
echo   ACCESS FROM ANY DEVICE ON THE NETWORK:
echo.
echo   http://localhost:8080
echo.
echo   Default Login:
echo   Username: admin
echo   Password: admin
echo  ===================================================
echo.
echo   Press CTRL+C to stop the server
echo.

%PYTHON% app.py
pause
