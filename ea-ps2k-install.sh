#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  ea-ps2k-install.sh  —  One-shot installer for RPi5/Ubuntu hosted deployment
#
#  Run once as your normal user — uses sudo only where needed.
#  Tested on Ubuntu 22.04 / 24.04 on Raspberry Pi 5.
#
#  What it does:
#    1. Installs Python 3 if not present
#    2. Installs pyserial via apt (python3-serial)
#    3. Adds current user to the 'dialout' group (serial port access)
#    4. Copies bridge files to /opt/ea-ps2k/
#    5. Installs udev rule for autosuspend-off + stable /dev/ea-ps2k-port symlink
#    6. Installs and enables the systemd bridge service
#    7. Starts the service
# ─────────────────────────────────────────────────────────────────────────────

set -e   # exit on any error

# ── Configuration — edit if needed ───────────────────────────────────────────
INSTALL_DIR="/opt/ea-ps2k"
SERVICE_NAME="ea-ps2k-bridge"
TCP_PORT="5025"
BIND_HOST="0.0.0.0"
SERIAL_PORT="/dev/ea-ps2k-port"   # set by udev rule in step 5
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  EA-PS2000B Bridge — RPi5/Ubuntu Installer"
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
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/ea_ps2k_driver.py"  "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/ea_ps2k_bridge.py"  "$INSTALL_DIR/"
sudo cp "$SCRIPT_DIR/ea-ps2k-bridge.sh"  "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/ea-ps2k-bridge.sh"
sudo chown -R "$USER:$USER" "$INSTALL_DIR"
echo "  Files copied to $INSTALL_DIR."

# ── 5. Install udev rule for stable device naming + autosuspend disable ───────
echo "[5/7] Installing udev rule..."

UDEV_RULE="/etc/udev/rules.d/99-ea-ps2k-port.rules"

# Remove old split rules if present
[ -f /etc/udev/rules.d/99-ps2342.rules ]        && sudo rm /etc/udev/rules.d/99-ps2342.rules
[ -f /etc/udev/rules.d/99-ea-ps2342-usb.rules ] && sudo rm /etc/udev/rules.d/99-ea-ps2342-usb.rules

if [ -f "$SCRIPT_DIR/99-ea-ps2k-port.rules" ]; then
    sudo cp "$SCRIPT_DIR/99-ea-ps2k-port.rules" "$UDEV_RULE"
else
    sudo bash -c "cat > $UDEV_RULE" << 'UDEVRULE'
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="232e", ATTRS{idProduct}=="0018", \
    ATTR{power/control}="on"
SUBSYSTEM=="tty", ATTRS{idVendor}=="232e", ATTRS{idProduct}=="0018", \
    SYMLINK+="ea-ps2k-port"
UDEVRULE
fi
sudo udevadm control --reload-rules
sudo udevadm trigger

sleep 1
if [ -e /dev/ea-ps2k-port ]; then
    RESOLVED=$(readlink -f /dev/ea-ps2k-port)
    echo "  /dev/ea-ps2k-port -> $RESOLVED"
else
    echo "  WARNING: /dev/ea-ps2k-port not found yet."
    echo "  Expected if the PS2000B is not currently connected/powered."
    echo "  The symlink appears automatically when the device is plugged in."
fi

# ── 6. Install systemd service ───────────────────────────────────────────────
echo "[6/7] Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo bash -c "cat > $SERVICE_FILE" << UNIT
[Unit]
Description=EA-PS2000B TCP/SCPI Bridge
After=network.target udev.service dev-ea\x2dps2k\x2dport.device
Wants=dev-ea\x2dps2k\x2dport.device
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/ea_ps2k_bridge.py --serial $SERIAL_PORT --host $BIND_HOST --tcp-port $TCP_PORT
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
echo "  Service installed and enabled: $SERVICE_NAME"

# ── 7. Start the service ──────────────────────────────────────────────────────
echo "[7/7] Starting service..."
sudo systemctl start "$SERVICE_NAME"

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
echo "    bash $INSTALL_DIR/ea-ps2k-bridge.sh   (manual/debug mode)"
echo "═══════════════════════════════════════════════════"
echo ""

if [ "$STATUS" != "active" ]; then
    echo "  WARNING: Service did not start. Check the log:"
    echo "    sudo journalctl -u $SERVICE_NAME -n 30"
fi
