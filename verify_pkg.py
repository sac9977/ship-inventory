#!/usr/bin/env python3
"""Ad-hoc verification for packaging: setup, start scripts, healthcheck, app port config."""
import sys, os, subprocess, tempfile, shutil, time, socket

sys.path = [p for p in sys.path if 'hermes' not in p.lower()]
BASE = os.path.expanduser("~/ship-inventory")
passed = failed = 0

def check(desc, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  ✓ {desc}")
    else:
        failed += 1; print(f"  ✗ FAIL: {desc}" + (f" — {detail}" if detail else ""))

# ═══ 1: setup.py ═══
print("── 1: setup.py ──")
setup = open(os.path.join(BASE, "setup.py")).read()
check("REQUIRED_PYTHON = (3, 8)", "REQUIRED_PYTHON = (3, 8)" in setup)
check("DEPS has flask + pdfplumber", '"flask"' in setup and '"pdfplumber"' in setup)
check("--force-reinstall in pip", '"--force-reinstall"' in setup)
check("Calls db.init_db()", "db.init_db()" in setup)
check("Calls db.ensure_admin_user()", "db.ensure_admin_user()" in setup)
check("Writes config.txt with port", 'config.txt' in setup and 'port=' in setup)
check("Generates start.sh and start.bat", 'start.sh' in setup and 'start.bat' in setup)
check("--port and --reset args", '"--port"' in setup and '"--reset"' in setup)

# ═══ 2: start.sh ═══
print("\n── 2: start.sh ──")
sh = open(os.path.join(BASE, "start.sh")).read()
check("Shebang line", sh.startswith("#!/bin/bash"))
check("Reads config.txt for PORT", 'config.txt' in sh and 'PORT_VAL' in sh)
check("Finds venv/bin/python", "venv/bin/python" in sh)
check("Falls back to python3", "python3" in sh)
check("Shows LAN IP", "LAN_IP" in sh)
check("Runs app.py", "$PYTHON app.py" in sh)

# ═══ 3: install.bat ═══
print("\n── 3: install.bat ──")
bat = open(os.path.join(BASE, "install.bat")).read()
check("Calls setup.py", "setup.py" in bat)
check("Has pause for Windows", "pause" in bat)

# ═══ 4: healthcheck.py ═══
print("\n── 4: healthcheck.py ──")
hc = open(os.path.join(BASE, "healthcheck.py")).read()
check("Checks Python version", "sys.version" in hc)
check("Checks flask + pdfplumber", "flask" in hc and "pdfplumber" in hc)
check("Checks app files", "app.py" in hc and "database.py" in hc)
check("Checks database", "ship_inventory.db" in hc)
check("Checks socket/network", "socket" in hc)

# ═══ 5: app.py _get_port ═══
print("\n── 5: app.py ──")
app = open(os.path.join(BASE, "app.py")).read()
check("def _get_port exists", "def _get_port" in app)
check("Reads config.txt", "config.txt" in app)
check("Fallback 8080", "8080" in app)
check("debug=False", "debug=False" in app)

# ═══ 6: INSTALL.html ═══
print("\n── 6: INSTALL.html ──")
html = open(os.path.join(BASE, "INSTALL.html")).read()
for step in ["STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5", "STEP 6"]:
    check(f"Has {step}", step in html)
check("macOS section", "macOS" in html)
check("Windows section", "Windows" in html)
check("Default admin credentials", "admin" in html.lower())
check("Troubleshooting section", "Troubleshooting" in html)

# ═══ 7: Fresh install + server start ═══
print("\n── 7: Fresh install cycle ──")
tmpdir = tempfile.mkdtemp(prefix="hermes-verify-pkg-")
try:
    for f in ["app.py", "database.py", "pdf_parser.py", "requirements.txt",
              "setup.py", "install.bat", "healthcheck.py", "INSTALL.html", "README.md", "start.sh"]:
        shutil.copy2(os.path.join(BASE, f), os.path.join(tmpdir, f))
    shutil.copytree(os.path.join(BASE, "static"), os.path.join(tmpdir, "static"))
    shutil.copytree(os.path.join(BASE, "templates"), os.path.join(tmpdir, "templates"))

    r = subprocess.run(["/usr/bin/python3", os.path.join(tmpdir, "setup.py")],
                       capture_output=True, text=True, timeout=120, cwd=tmpdir,
                       env={"PATH": "/usr/bin:/usr/local/bin:/bin", "HOME": os.path.expanduser("~")})
    check("setup.py exits 0", r.returncode == 0, r.stderr[:200] if r.returncode else "")
    check("Creates venv/", os.path.isdir(os.path.join(tmpdir, "venv")))
    check("Creates config.txt", os.path.exists(os.path.join(tmpdir, "config.txt")))
    check("Creates ship_inventory.db", os.path.exists(os.path.join(tmpdir, "ship_inventory.db")))
    check("config.txt has port=8080", open(os.path.join(tmpdir, "config.txt")).read().strip() == "port=8080")

    # Check venv deps
    venv_lib = os.path.join(tmpdir, "venv", "lib")
    py_ver = os.listdir(venv_lib)[0]
    site = os.path.join(venv_lib, py_ver, "site-packages")
    for pkg in ["markupsafe", "jinja2", "flask", "pdfplumber", "werkzeug"]:
        check(f"venv has {pkg}", os.path.isdir(os.path.join(site, pkg)) or pkg in os.listdir(site))

    # Check generated start.sh has config.txt read
    gen_sh = open(os.path.join(tmpdir, "start.sh")).read()
    check("Generated start.sh reads config.txt", "config.txt" in gen_sh and "PORT_VAL" in gen_sh)

    # Server start test — use a free port to avoid conflicts
    free_port = 18765
    # Patch config.txt to use free port
    with open(os.path.join(tmpdir, "config.txt"), "w") as f:
        f.write(f"port={free_port}\n")
    with open(os.path.join(tmpdir, "app.py")) as f:
        app_code = f.read()

    venv_python = os.path.join(tmpdir, "venv", "bin", "python")
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/usr/local/bin:/bin"
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen([venv_python, "app.py"], cwd=tmpdir,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    time.sleep(4)
    alive = proc.poll() is None
    check("Server process stays alive", alive)
    if alive:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{free_port}/login", timeout=5)
            check(f"Login page returns 200 on port {free_port}", resp.status == 200)
        except Exception as e:
            check(f"Login page returns 200 on port {free_port}", False, str(e))
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()
    else:
        stderr = proc.stderr.read().decode()[:300]
        check("Server process stays alive", False, stderr)

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ═══ 8: ZIP ═══
print("\n── 8: Distributable zip ──")
import urllib.request  # for server test above too
zip_path = os.path.expanduser("~/Desktop/ship-inventory.zip")
check("ship-inventory.zip on Desktop", os.path.exists(zip_path))
if os.path.exists(zip_path):
    check(f"Size {os.path.getsize(zip_path)//1024}KB (20-200KB)", 20 < os.path.getsize(zip_path)//1024 < 200)

print(f"\n{'═'*50}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print("STATUS:", "ALL CHECKS PASSED" if not failed else "SOME CHECKS FAILED")
sys.exit(1 if failed else 0)
