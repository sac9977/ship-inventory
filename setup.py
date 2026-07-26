#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  ⚓ SHIP INVENTORY MANAGEMENT SYSTEM — INSTALLER            ║
║  Run this once to set up the inventory system.              ║
╚══════════════════════════════════════════════════════════════╝

Usage:
    python3 setup.py          (auto-detects everything)
    python3 setup.py --port 8888   (custom port)
    python3 setup.py --reset       (reset database)
"""
import os
import sys
import subprocess
import shutil
import platform
import argparse

# ── Config ──
DEFAULT_PORT = 8080
REQUIRED_PYTHON = (3, 8)
VENV_DIR = "venv"
DEPS = ["flask", "pdfplumber", "markupsafe", "jinja2", "werkzeug", "click", "itsdangerous", "blinker", "cryptography", "cffi", "pycparser", "charset-normalizer"]

def banner():
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║       ⚓  SHIP INVENTORY MANAGEMENT SYSTEM                   ║
║       Stores & Spare Parts Management                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

def step(msg):
    print(f"\n  ▸ {msg} ... ", end="", flush=True)

def ok(msg="done"):
    print(f"✓ {msg}")

def fail(msg):
    print(f"✗ FAILED: {msg}")
    sys.exit(1)

def get_python():
    """Find the best Python 3 executable."""
    candidates = ["python3", "python", "python3.12", "python3.11", "python3.10", "python3.9", "python3.8"]
    for cmd in candidates:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                ver = r.stdout.strip()
                # Extract version tuple
                parts = ver.replace("Python ", "").split(".")
                major, minor = int(parts[0]), int(parts[1])
                if (major, minor) >= REQUIRED_PYTHON:
                    return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            continue
    return None

def get_lan_ip():
    """Best-effort LAN IP detection."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def main():
    parser = argparse.ArgumentParser(description="Ship Inventory Installer")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default {DEFAULT_PORT})")
    parser.add_argument("--ship-name", type=str, default="", help="Ship name (e.g. 'MV Pacific Star')")
    parser.add_argument("--reset", action="store_true", help="Reset database (WARNING: deletes all data)")
    parser.add_argument("--skip-venv", action="store_true", help="Skip venv creation (use system Python)")
    args = parser.parse_args()

    banner()

    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)
    sys.path.insert(0, app_dir)

    # ── Step 1: Check Python ──
    step("Checking Python version")
    py_cmd = get_python()
    if not py_cmd:
        fail(
            f"Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ is required but not found.\n"
            f"      Install from https://www.python.org/downloads/\n"
            f"      Make sure to check 'Add Python to PATH' during install (Windows)."
        )
    r = subprocess.run([py_cmd, "--version"], capture_output=True, text=True)
    ok(f"{r.stdout.strip()} ({py_cmd})")

    # ── Step 2: Create virtual environment ──
    if not args.skip_venv:
        venv_path = os.path.join(app_dir, VENV_DIR)
        if os.path.exists(venv_path) and args.reset:
            step("Removing old virtual environment")
            shutil.rmtree(venv_path)
            ok("removed")

        if not os.path.exists(venv_path):
            step("Creating virtual environment")
            r = subprocess.run([py_cmd, "-m", "venv", VENV_DIR], capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"Could not create venv: {r.stderr}")
            ok()

        # Find pip in venv
        if platform.system() == "Windows":
            pip_cmd = os.path.join(venv_path, "Scripts", "pip.exe")
            python_in_venv = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            pip_cmd = os.path.join(venv_path, "bin", "pip")
            python_in_venv = os.path.join(venv_path, "bin", "python")

        # ── Step 3: Install dependencies ──
        step("Installing dependencies")
        for dep in DEPS:
            r = subprocess.run([pip_cmd, "install", "-q", "--force-reinstall", dep], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"\n      ⚠ Warning: could not install {dep}: {r.stderr[:200]}")
        ok(f"{', '.join(DEPS)}")

    else:
        python_in_venv = py_cmd

    # ── Step 4: Initialize database ──
    step("Initializing database")
    db_path = os.path.join(app_dir, "ship_inventory.db")
    if args.reset and os.path.exists(db_path):
        os.remove(db_path)
        print("(reset) ", end="")

    # Import and init — need to handle hermes path contamination
    import database as db
    db.init_db()
    db.ensure_admin_user()
    ok("tables created, admin user ready")

    # ── Step 5: Write port config ──
    step("Writing config")
    config_path = os.path.join(app_dir, "config.txt")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(f"port={args.port}\n")
        if args.ship_name:
            f.write(f"ship_name={args.ship_name}\n")
    ok(f"port={args.port}")

    # ── Step 6: Generate launch scripts ──
    step("Generating launch scripts")

    # Generate start.sh
    sh_content = f"""#!/bin/bash
cd "$(dirname "$0")"

# Read port from config.txt (written by setup.py)
PORT={args.port}
SHIP_NAME=""
if [ -f "config.txt" ]; then
    PORT_VAL=$(grep "^port=" config.txt 2>/dev/null | cut -d= -f2)
    [ -n "$PORT_VAL" ] && PORT=$PORT_VAL
    SHIP_NAME_VAL=$(grep "^ship_name=" config.txt 2>/dev/null | cut -d= -f2)
    [ -n "$SHIP_NAME_VAL" ] && SHIP_NAME="$SHIP_NAME_VAL"
fi

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
if [ -n "$SHIP_NAME" ]; then
echo "  ║  ⚓ $SHIP_NAME                              ║"
fi
echo "  ║  Inventory System — Starting on port $PORT   ║"
echo "  ╚═══════════════════════════════════════════════╝"
    PYTHON="venv/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
elif command -v python &> /dev/null; then
    PYTHON="python"
else
    echo "ERROR: Python not found. Run: python3 setup.py"
    exit 1
fi

# Get LAN IP
LAN_IP=$(ifconfig 2>/dev/null | grep "inet " | grep -v 127.0.0.1 | awk '{{print $2}}' | head -1)
if [ -z "$LAN_IP" ]; then
    LAN_IP=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){{3}}' | grep -v 127 | head -1)
fi

echo "═══════════════════════════════════════════════════"
echo "  ACCESS FROM ANY DEVICE ON THE NETWORK:"
echo ""
if [ -n "$LAN_IP" ]; then
    echo "  🌐  http://$LAN_IP:$PORT"
fi
echo "  💻  http://localhost:$PORT"
echo ""
echo "  Login:  admin / admin"
echo "  (Change the password after first login!)"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Press CTRL+C to stop the server"
echo ""

$PYTHON app.py
"""
    with open(os.path.join(app_dir, "start.sh"), "w", encoding="utf-8") as f:
        f.write(sh_content)
    os.chmod(os.path.join(app_dir, "start.sh"), 0o755)

    # Generate start.bat
    bat_content = f"""@echo off
title Ship Inventory Management System
cd /d "%~dp0"
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║  Starting Ship Inventory on port {args.port}...     ║
echo  ╚═══════════════════════════════════════════════╝
echo.

REM Find Python
if exist "venv\\Scripts\\python.exe" (
    set "PYTHON=venv\\Scripts\\python.exe"
) else (
    set "PYTHON=python"
)

echo  ===================================================
echo   ACCESS FROM ANY DEVICE ON THE NETWORK:
echo.
echo   http://localhost:{args.port}
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
"""
    with open(os.path.join(app_dir, "start.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)
    ok("start.sh + start.bat created")

    # ── Done ──
    lan_ip = get_lan_ip()
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║  ✅  INSTALLATION COMPLETE!{f"  — {args.ship_name}" if args.ship_name else ""}
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  To START the inventory system:                              ║
║                                                              ║
║    macOS/Linux:   ./start.sh                                 ║
║    Windows:       double-click start.bat                     ║
║                                                              ║
║  Then open in ANY browser on the ship's network:             ║
║                                                              ║
║    🌐  http://{lan_ip}:{args.port:<24}║
║    💻  http://localhost:{args.port:<27}║
║                                                              ║
║  Default Login:                                              ║
║    Username: admin                                           ║
║    Password: admin                                           ║
║                                                              ║
║  ⚠  CHANGE THE ADMIN PASSWORD AFTER FIRST LOGIN!            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

if __name__ == "__main__":
    main()
