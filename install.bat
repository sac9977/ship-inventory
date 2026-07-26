@echo off
title Ship Inventory — Installer
cd /d "%~dp0"
echo.
echo  ╔══════════════════════════════════════════════════════════════╗
echo  ║       ⚓  SHIP INVENTORY MANAGEMENT SYSTEM                  ║
echo  ║       INSTALLER                                            ║
echo  ╚══════════════════════════════════════════════════════════════╝
echo.

REM Try python3 first, then python
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY=python3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "PY=python"
    ) else (
        echo  ERROR: Python is not installed!
        echo.
        echo  Download Python from:
        echo  https://www.python.org/downloads/
        echo.
        echo  IMPORTANT: Check "Add Python to PATH" during install!
        echo.
        pause
        exit /b 1
    )
)

echo  Found Python:
%PY% --version
echo.

REM Prompt for ship name
set "SHIP_NAME="
set /p SHIP_NAME="  Enter ship name (e.g. MV Pacific Star), or press Enter to skip: "

echo.
echo  Running installer...
echo.

if "%SHIP_NAME%"=="" (
    %PY% setup.py
) else (
    %PY% setup.py --ship-name "%SHIP_NAME%"
)

echo.
echo  Press any key to close...
pause >nul
