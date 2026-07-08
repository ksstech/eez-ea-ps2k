#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  install_rpi.sh  —  One-shot installer for RPi/Ubuntu hosted deployment
#
#  Run once as the 'pi' user (or your normal user) — uses sudo only where needed
#
#  What it does:
#    1. Installs Python 3 if not present
#    2. Installs pyserial via apt (python3-serial)
#    3. Adds current user to the 'dialout' group (serial port access)
#    4. Copies bridge files to ~/ea_ps2342/
#    5. Installs a udev rule for a stable /dev/ps2342 symlink (by VID:PID)
#    6. Installs and enables the systemd service
#    7. Starts the service
# ─────────────────────────────────────────────────────────────────────────────

set -e   # exit on any error

# ── Configuration — edit if needed ───────────────────────────────────────────
INSTALL_DIR="$HOME/ea_ps2342"
SERVICE_NAME="ea_ps2342_bridge"
TCP_PORT="5025"
BIND_HOST="0.0.0.0"
# Serial port — uses a stable udev symlink (/dev/ps2342) by default,
# set up automatically in step 5 below. Leave blank.
SERIAL_PORT=""
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  EA-PS2342-06B Bridge — RPi/Ubuntu Installer"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Python ────────────────────────────────────────────────────────────────
echo "[1/7] Checking Python 3..."
if ! command -v python3 &>/dev/null; then
    echo "  Installing python3..."
    sudo apt-get update -qq
    sudo apt-get install -y python3
fi
PY_VER=$(python3 --version)
echo "  Found: $PY_VER"

# ── 2. pyserial ───────────────────────────────────────────────────────────────
# Install via apt (python3-serial) — avoids the PEP 668 externally-managed-
# environment error that pip3 raises on Ubuntu 22.04+ / Debian Bookworm+.
# apt is also the right choice for a server: packages stay in sync with OS updates.
echo "[2/7] Installing pyserial via apt..."
sudo apt-get update -qq
sudo apt-get install -y python3-serial
echo "  python3-serial installed."

# ── 3. dialout group ─────────────────────────────────────────────────────────
echo "[3/7] Checking serial port permissions..."
if groups "$USER" | grep -q dialout; then
    echo "  User '$USER' is already in the dialout group."
else
    echo "  Adding '$USER' to dialout group..."
    sudo usermod -aG dialout "$USER"
    echo "  NOTE: Group change takes effect on next login."
    echo "        The service will run as this user — it will work after reboot."
fi

# ── 4. Copy files ─────────────────────────────────────────────────────────────
echo "[4/7] Installing bridge files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/ea_ps2342.py"  "$INSTALL_DIR/"
cp "$SCRIPT_DIR/ea_bridge.py"  "$INSTALL_DIR/"
cp "$SCRIPT_DIR/start_bridge.sh" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/start_bridge.sh"
echo "  Files copied."

# ── 5. Install udev rule for stable device naming ────────────────────────────
# Rather than guessing a /dev/ttyACMx number (which can shift if the PS2342
# is on a USB hub and enumeration order changes across reboots or replug
# events), install a udev rule that creates a stable /dev/ps2342 symlink
# based on the device's USB VID:PID, which never changes.
echo "[5/7] Installing udev rule for stable device naming..."

UDEV_RULE="/etc/udev/rules.d/99-ps2342.rules"
if [ -f "$SCRIPT_DIR/99-ps2342.rules" ]; then
    sudo cp "$SCRIPT_DIR/99-ps2342.rules" "$UDEV_RULE"
else
    sudo bash -c "cat > $UDEV_RULE" << 'UDEVRULE'
SUBSYSTEM=="tty", ATTRS{idVendor}=="232e", ATTRS{idProduct}=="0018", SYMLINK+="ps2342"
UDEVRULE
fi
sudo udevadm control --reload-rules
sudo udevadm trigger

# Give udev a moment to process, then check the symlink appeared
sleep 1
if [ -e /dev/ps2342 ]; then
    RESOLVED=$(readlink -f /dev/ps2342)
    echo "  /dev/ps2342 -> $RESOLVED"
    SERIAL_PORT="/dev/ps2342"
else
    echo "  WARNING: /dev/ps2342 not found yet."
    echo "  This is expected if the PS2342 is not currently connected/powered."
    echo "  Once connected, the symlink will appear automatically — no further"
    echo "  action needed. The bridge service is configured to use /dev/ps2342."
    SERIAL_PORT="/dev/ps2342"
fi

# ── 6. Install systemd service ───────────────────────────────────────────────
echo "[6/7] Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo bash -c "cat > $SERVICE_FILE" << UNIT
[Unit]
Description=EA-PS2342-06B TCP/SCPI Bridge
After=network.target udev.service dev-ps2342.device
Wants=dev-ps2342.device
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/ea_bridge.py --serial $SERIAL_PORT --host $BIND_HOST --tcp-port $TCP_PORT
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
echo "  Service installed and enabled."

# ── 7. Start the service ──────────────────────────────────────────────────────
echo "[7/7] Starting service..."

# Serial port access may require the dialout group — use a small delay
# If the group was just added this session may not have it yet, so we
# temporarily allow group-less access for the initial start via newgrp
if groups "$USER" | grep -q dialout; then
    sudo systemctl start "$SERVICE_NAME"
else
    echo "  Starting via sudo (dialout group not yet active this session)..."
    sudo systemctl start "$SERVICE_NAME"
fi

sleep 2
STATUS=$(sudo systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown")

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Installation complete"
echo "  Service status : $STATUS"
echo "  Serial port    : $SERIAL_PORT"
echo "  TCP address    : $BIND_HOST:$TCP_PORT"
echo ""
echo "  EEZ Studio → Add instrument → Ethernet"
echo "    Address: $(hostname -I | awk '{print $1}')   Port: $TCP_PORT"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status  $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    bash $INSTALL_DIR/start_bridge.sh   (manual/debug mode)"
echo "═══════════════════════════════════════════════════"
echo ""

if [ "$STATUS" != "active" ]; then
    echo "  WARNING: Service did not start. Check the log:"
    echo "    sudo journalctl -u $SERVICE_NAME -n 30"
fi
