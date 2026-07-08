#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  ea-ps2k-bridge.sh  —  Manual fallback launcher for ea_ps2k_bridge.py
#
#  Use this for:
#    - Testing before enabling the systemd service
#    - Running temporarily without systemd
#    - Debugging (output goes directly to terminal)
#
#  For production use: sudo systemctl start ea-ps2k-bridge
#  (the systemd service starts automatically at boot and restarts on crash)
# ─────────────────────────────────────────────────────────────────────────────

# ── Edit these if needed ──────────────────────────────────────────────────────
SERIAL_PORT="/dev/ea-ps2k-port"  # stable udev symlink — see 99-ea-ps2k-port.rules
TCP_PORT="5025"
BIND_HOST="0.0.0.0"              # 0.0.0.0 = accessible from LAN
                                  # 127.0.0.1 = local only
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo " EA-PS2000B TCP Bridge (manual mode)"
echo " Serial port : $SERIAL_PORT"
echo " TCP address : $BIND_HOST:$TCP_PORT"
echo " Script dir  : $SCRIPT_DIR"
echo ""
echo " NOTE: This is the manual fallback. For production use:"
echo "   sudo systemctl start ea-ps2k-bridge"
echo ""
echo " Press Ctrl-C to stop."
echo ""

# Check serial port exists before starting
if [ ! -e "$SERIAL_PORT" ]; then
    echo "ERROR: Serial port $SERIAL_PORT not found."
    echo "  Check the device is connected: ls -la /dev/ea-ps2k-port"
    echo "  If the udev symlink is missing: sudo udevadm trigger"
    exit 1
fi

# Check user has permission to access the serial port
if [ ! -r "$SERIAL_PORT" ] || [ ! -w "$SERIAL_PORT" ]; then
    echo "ERROR: No permission to access $SERIAL_PORT."
    echo "  Add your user to the dialout group:"
    echo "    sudo usermod -aG dialout $USER"
    echo "  Then log out and back in."
    exit 1
fi

cd "$SCRIPT_DIR"
python3 ea_ps2k_bridge.py \
    --serial  "$SERIAL_PORT" \
    --host    "$BIND_HOST" \
    --tcp-port "$TCP_PORT"
