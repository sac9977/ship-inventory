#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  ⚓ Ship Inventory — Start the System
# ══════════════════════════════════════════════════════════════
cd "$(dirname "$0")"

# Read port from config.txt (written by setup.py)
PORT=8080
if [ -f "config.txt" ]; then
    PORT_VAL=$(grep "^port=" config.txt 2>/dev/null | cut -d= -f2)
    [ -n "$PORT_VAL" ] && PORT=$PORT_VAL
fi

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║  ⚓ Ship Inventory Management System          ║"
echo "  ║  Starting server on port $PORT...              ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

# Find Python in venv or system
if [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "  ❌ Python not found!"
    echo "  Run: python3 setup.py"
    echo ""
    exit 1
fi

# Check if port is in use
if lsof -i :"$PORT" &>/dev/null 2>&1; then
    echo "  ⚠ Port $PORT is already in use."
    echo "  Another instance may be running."
    echo "  To use a different port: python3 setup.py --port 8888"
    echo ""
    exit 1
fi

# Get LAN IP
LAN_IP=$(ifconfig 2>/dev/null | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
if [ -z "$LAN_IP" ]; then
    LAN_IP=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127 | head -1)
fi
[ -z "$LAN_IP" ] && LAN_IP="your-ip-address"

echo "  ═══════════════════════════════════════════════════"
echo "   ACCESS FROM ANY DEVICE ON THE NETWORK:"
echo ""
echo "   🌐  http://$LAN_IP:$PORT"
echo "   💻  http://localhost:$PORT"
echo ""
echo "   Login:  admin / admin"
echo "   (Change the password after first login!)"
echo "  ═══════════════════════════════════════════════════"
echo ""
echo "   Press CTRL+C to stop the server"
echo ""

$PYTHON app.py
