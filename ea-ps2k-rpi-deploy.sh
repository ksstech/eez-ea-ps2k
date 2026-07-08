#!/usr/bin/env bash
# ea-ps2k-rpi-deploy.sh  —  Clean + install EA-PS2k stack on RPi5
#
# Run from the directory containing all ea-ps2k files, e.g.:
#   cd /home/vh/ea-ps2k
#   bash ea-ps2k-rpi-deploy.sh
#
# What it does:
#   Phase 1 — Teardown old environment
#     1. Stop + disable ea_ps2342_bridge service
#     2. Remove old service file
#     3. Remove old udev rules
#     4. Remove old script directory /home/vh/ea_ps2342/
#   Phase 2 — Install new environment
#     5. Install pyserial (if not present)
#     6. Create /opt/ea-ps2k/ and copy files
#     7. Install consolidated udev rule (autosuspend + symlink)
#     8. Install + enable ea-ps2k-bridge.service
#     9. Install + enable ea-ps2k-monitor.service + timer
#    10. Start bridge and verify
#    11. Run health check

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/ea-ps2k"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  EA-PS2k Deploy  —  $(date)"
echo "════════════════════════════════════════════════════════"
echo ""

# ── Phase 1: Teardown ─────────────────────────────────────────────────────────

echo "[ Phase 1: Teardown ]"
echo ""

# 1. Stop and disable old bridge service
echo "[1/4] Stopping old bridge service (ea_ps2342_bridge)..."
if systemctl is-active --quiet ea_ps2342_bridge 2>/dev/null; then
    sudo systemctl stop ea_ps2342_bridge
    echo "  Stopped."
else
    echo "  Not running (OK)."
fi
if systemctl is-enabled --quiet ea_ps2342_bridge 2>/dev/null; then
    sudo systemctl disable ea_ps2342_bridge
    echo "  Disabled."
fi

# 2. Remove old service file
echo "[2/4] Removing old service file..."
if [ -f /etc/systemd/system/ea_ps2342_bridge.service ]; then
    sudo rm /etc/systemd/system/ea_ps2342_bridge.service
    echo "  Removed /etc/systemd/system/ea_ps2342_bridge.service"
else
    echo "  Not found (OK)."
fi
sudo systemctl daemon-reload

# 3. Remove old udev rules
echo "[3/4] Removing old udev rules..."
removed=0
for f in /etc/udev/rules.d/99-ps2342.rules /etc/udev/rules.d/99-ea-ps2342-usb.rules; do
    if [ -f "$f" ]; then
        sudo rm "$f"
        echo "  Removed $f"
        removed=$((removed+1))
    fi
done
[ $removed -eq 0 ] && echo "  None found (OK)."

# 4. Archive old script directory
echo "[4/4] Archiving old script directory /home/vh/ea_ps2342/..."
if [ -d /home/vh/ea_ps2342 ]; then
    sudo mv /home/vh/ea_ps2342 /home/vh/ea_ps2342.bak
    echo "  Moved to /home/vh/ea_ps2342.bak (safe to delete later)"
else
    echo "  Not found (OK)."
fi

echo ""
echo "  Teardown complete."
echo ""

# ── Phase 2: Install ──────────────────────────────────────────────────────────

echo "[ Phase 2: Install ]"
echo ""

# 5. pyserial
echo "[5/10] Checking pyserial..."
if python3 -c "import serial" 2>/dev/null; then
    echo "  pyserial already installed."
else
    echo "  Installing python3-serial via apt..."
    sudo apt-get update -qq
    sudo apt-get install -y python3-serial
fi

# 6. Copy files to /opt/ea-ps2k/
echo "[6/10] Installing files to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/ea_ps2k_driver.py"  "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/ea_ps2k_bridge.py"  "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/ea-ps2k-bridge.sh"  "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/ea-ps2k-monitor.py" "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/ea-ps2k-bridge.sh"
sudo chown -R vh:vh "$INSTALL_DIR"
echo "  Files installed to $INSTALL_DIR"

# 7. Udev rule
echo "[7/10] Installing udev rule (99-ea-ps2k-port.rules)..."
sudo cp "$SCRIPT_DIR/99-ea-ps2k-port.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
sleep 1
if [ -e /dev/ea-ps2k-port ]; then
    RESOLVED=$(readlink -f /dev/ea-ps2k-port)
    echo "  /dev/ea-ps2k-port -> $RESOLVED"
    # Verify autosuspend (|| true prevents set -e from triggering on missing files)
    for d in /sys/bus/usb/devices/*/; do
        vid=$(cat "$d/idVendor" 2>/dev/null || true)
        pid=$(cat "$d/idProduct" 2>/dev/null || true)
        if [ "$vid" = "232e" ] && [ "$pid" = "0018" ]; then
            pwr=$(cat "$d/power/control" 2>/dev/null || echo "unknown")
            echo "  Autosuspend: $pwr  (want: on)"
        fi
    done
else
    echo "  WARNING: /dev/ea-ps2k-port not found — is the PSU connected and powered?"
fi

# 8. Bridge service
echo "[8/10] Installing ea-ps2k-bridge.service..."
sudo cp "$SCRIPT_DIR/ea-ps2k-bridge.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ea-ps2k-bridge
sudo systemctl start  ea-ps2k-bridge
sleep 2
STATUS=$(systemctl is-active ea-ps2k-bridge 2>/dev/null || echo "unknown")
echo "  Service status: $STATUS"
if [ "$STATUS" != "active" ]; then
    echo "  ERROR: Service did not start. Log:"
    sudo journalctl -u ea-ps2k-bridge -n 20 --no-pager
    exit 1
fi

# 9. Monitor service + timer
echo "[9/10] Installing ea-ps2k-monitor service + timer..."
sudo cp "$SCRIPT_DIR/ea-ps2k-monitor.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/ea-ps2k-monitor.timer"   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ea-ps2k-monitor.timer
echo "  Timer enabled:"
systemctl list-timers ea-ps2k-monitor.timer --no-pager

# 10. Quick bridge smoke test
echo "[10/10] Bridge smoke test (*IDN? via Python socket)..."
sleep 1
IDN=$(python3 -c "
import socket, sys
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect(('127.0.0.1', 5025))
    s.sendall(b'*IDN?\n')
    r = s.recv(1024).decode().strip()
    s.close()
    print(r)
except Exception as e:
    print(f'FAILED: {e}')
" 2>/dev/null || echo "FAILED")
echo "  *IDN? → $IDN"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Deploy complete"
echo ""
echo "  Bridge  : $(systemctl is-active ea-ps2k-bridge)"
echo "  Monitor : $(systemctl is-active ea-ps2k-monitor.timer) (timer)"
echo "  Device  : $(ls -la /dev/ea-ps2k-port 2>/dev/null || echo 'not found')"
echo ""
echo "  Useful commands:"
echo "    sudo journalctl -u ea-ps2k-bridge -f"
echo "    journalctl -t ea-ps2k-monitor -n 20"
echo "    sudo systemctl status ea-ps2k-bridge"
echo ""
echo "  Old scripts backed up at: /home/vh/ea_ps2342.bak/"
echo "  Safe to delete once everything is verified working."
echo "════════════════════════════════════════════════════════"
echo ""
