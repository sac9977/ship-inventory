#!/usr/bin/env python3
"""
⚓ Ship Inventory — Health Check & Diagnostics
Run this to check if everything is installed correctly.
"""
import os
import sys
import platform
import subprocess
import socket

APP_DIR = os.path.dirname(os.path.abspath(__file__))
issues = []
warnings = []

def check(label, fn):
    try:
        result = fn()
        if result is True:
            print(f"  ✅ {label}")
        elif result is None:
            print(f"  ⚠️  {label}")
            warnings.append(label)
        else:
            print(f"  ✅ {label}: {result}")
    except Exception as e:
        print(f"  ❌ {label}: {e}")
        issues.append(label)

print("""
╔══════════════════════════════════════════════════════════════╗
║  ⚓ SHIP INVENTORY — HEALTH CHECK                           ║
╚══════════════════════════════════════════════════════════════╝
""")

# ── System Info ──
print("📋 System Information:")
check(f"Operating System", lambda: platform.platform())
check(f"Python version", lambda: f"{sys.version.split()[0]} ({sys.executable})")
check(f"Architecture", lambda: platform.machine())
print()

# ── Python Dependencies ──
print("📦 Dependencies:")
for mod_name in ["flask", "pdfplumber", "jinja2", "werkzeug"]:
    check(f"{mod_name}", lambda m=mod_name: __import__(m).__version__ if hasattr(__import__(m), '__version__') else True)
print()

# ── App Files ──
print("📁 Application Files:")
for fname in ["app.py", "database.py", "pdf_parser.py", "requirements.txt", "static/style.css", "templates/base.html"]:
    full = os.path.join(APP_DIR, fname)
    check(fname, lambda p=full: f"{os.path.getsize(p):,} bytes" if os.path.exists(p) else (_ for _ in ()).throw(Exception(f"MISSING")))
print()

# ── Database ──
print("🗄️  Database:")
db_path = os.path.join(APP_DIR, "ship_inventory.db")
check("Database file exists", lambda: f"{os.path.getsize(db_path):,} bytes" if os.path.exists(db_path) else "will be created on first run")

if os.path.exists(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    check("Tables", lambda: f"{len(tables)}: {', '.join(tables)}")
    for table in ["machinery", "spare_parts", "stores", "transactions", "crew"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        check(f"  {table}", lambda c=count, t=table: f"{c} records")
    conn.close()
print()

# ── Network ──
print("🌐 Network:")
def check_port(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('0.0.0.0', port))
        s.close()
        return f"port {port} is available"
    except OSError:
        return None  # warning

port = 8080
config_path = os.path.join(APP_DIR, "config.txt")
if os.path.exists(config_path):
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("port="):
                port = int(line.strip().split("=")[1])

check(f"Port {port}", lambda: check_port(port))

# LAN IP
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    lan_ip = s.getsockname()[0]
    s.close()
    check("LAN IP", lambda: f"http://{lan_ip}:{port}")
except Exception:
    check("LAN IP", lambda: None)
print()

# ── Summary ──
if issues:
    print(f"❌ {len(issues)} CRITICAL ISSUE(S) FOUND:")
    for i in issues:
        print(f"   • {i}")
    print("\nFix these issues before running the server.")
    sys.exit(1)
elif warnings:
    print(f"⚠️  {len(warnings)} warning(s) — system should work but check if needed.")
    for w in warnings:
        print(f"   • {w}")
    print("\n✅ System looks good! Run ./start.sh to begin.")
else:
    print("✅ ALL CHECKS PASSED — System is ready!")
    print(f"\n   Start: ./start.sh")
    print(f"   Access: http://localhost:{port}")
