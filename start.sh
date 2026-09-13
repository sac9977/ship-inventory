#!/bin/bash
cd "$(dirname "$0")"

# Read port from config.txt (written by setup.py). tr -d '\r' guards
# against CRLF-config files written on Windows.
PORT=8080
SHIP_NAME=""
if [ -f "config.txt" ]; then
    PORT_VAL=$(grep "^port=" config.txt 2>/dev/null | cut -d= -f2 | tr -d '\r\n')
    [ -n "$PORT_VAL" ] && PORT=$PORT_VAL
    SHIP_NAME_VAL=$(grep "^ship_name=" config.txt 2>/dev/null | cut -d= -f2 | tr -d '\r\n')
    [ -n "$SHIP_NAME_VAL" ] && SHIP_NAME="$SHIP_NAME_VAL"
fi

echo ""
echo "  ====================================================="
if [ -n "$SHIP_NAME" ]; then
echo "   ⚓  $SHIP_NAME — Inventory System"
fi
echo "  ====================================================="

# Pick the Python interpreter: project venv first, then system pythons.
if [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif [ -x "venv/Scripts/python.exe" ]; then
    PYTHON="venv/Scripts/python.exe"
elif command -v python3 &> /dev/null; then
    PYTHON="python3"
elif command -v python &> /dev/null; then
    PYTHON="python"
else
    echo "ERROR: Python not found. Run: python3 setup.py"
    exit 1
fi

# Get LAN IP (macOS ifconfig, then Linux ip)
LAN_IP=$(ifconfig 2>/dev/null | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
if [ -z "$LAN_IP" ]; then
    LAN_IP=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127 | head -1)
fi

echo ""
echo "  ACCESS FROM ANY DEVICE ON THE NETWORK:"
echo ""
if [ -n "$LAN_IP" ]; then
    echo "   🌐  http://$LAN_IP:$PORT"
fi
echo "   💻  http://localhost:$PORT"
echo ""
echo "   Login with your crew account"
echo "  ====================================================="
echo ""
echo "  Press CTRL+C to stop the server"
echo ""

exec "$PYTHON" app.py
