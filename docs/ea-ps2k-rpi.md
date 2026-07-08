# EA-PS2000B Bridge — Raspberry Pi 5 / Ubuntu LAN Server

Hosts the EA-PS2000B TCP bridge on a Raspberry Pi 5 running Ubuntu,
making the power supply accessible at `192.168.1.6:5025` from any device
on the LAN (or via a firewall NAT rule from anywhere on the internet).

---

## Architecture

```
EA-PS2000B USB
     │
     ▼
Raspberry Pi 5  (Ubuntu, /dev/ea-ps2k-port — stable udev symlink)
     │
     ├── ea_ps2k_driver.py  ← binary protocol driver
     ├── ea_ps2k_bridge.py  ← TCP/SCPI translation layer
     └── systemd service    ← starts at boot, restarts on crash
     │
     ▼  TCP port 5025
LAN (192.168.1.x)
     │
     ├── EEZ Studio on Windows/macOS/Linux
     ├── Python scripts on any machine
     └── Internet (via firewall NAT → 192.168.1.6:5025)
```

VirtualHere USB Server runs alongside this bridge but must **exclude** the
PS2000B from its device list — they cannot share the same USB device.
See [VirtualHere exclusion](#virtualhere-exclusion) below.

---

## Quick Install (RPi5 / Ubuntu)

Copy the files to the RPi, then run the installer:

```bash
# On the RPi — copy files first (scp, USB stick, or git clone)
chmod +x ea-ps2k-install.sh
./ea-ps2k-install.sh
```

The installer:
1. Installs Python 3 and `python3-serial` if not present
2. Adds your user to the `dialout` group (serial port access)
3. Copies bridge files to `/opt/ea-ps2k/`
4. Installs a udev rule creating a stable `/dev/ea-ps2k-port` symlink and
   disabling USB autosuspend — both immune to `ttyACMx` renumbering and
   the "idle period" failure mode
5. Installs and enables the `ea-ps2k-bridge` systemd service
6. Starts the service immediately

After installation the bridge starts automatically every boot.

---

## Manual Installation (step by step)

### 1. Install Python and pyserial

```bash
sudo apt update
sudo apt install python3 python3-serial
```

Note: use `python3-serial` via apt, not `pip3 install pyserial` — pip raises
a PEP 668 "externally-managed-environment" error on Ubuntu 22.04+/Debian
Bookworm+ system Python installs.

### 2. Serial port access

```bash
sudo usermod -aG dialout $USER
# Log out and back in for the group change to take effect
```

### 3. Install the udev rule for stable device naming + autosuspend disable

Rather than referencing `/dev/ttyACM0` directly — which can change if the
PS2000B is connected via a USB hub and enumeration order shifts across
reboots or replug events — install a udev rule that creates a stable
`/dev/ea-ps2k-port` symlink based on the device's USB VID:PID.

The same rule also disables USB autosuspend, which is the primary cause of
the "works for a while, fails after 2 days idle" failure: Linux puts the USB
device into a low-power state that the bridge cannot wake up from.

```bash
sudo cp 99-ea-ps2k-port.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# Plug in the PS2000B if not already connected, then verify:
ls -la /dev/ea-ps2k-port
# Should show: /dev/ea-ps2k-port -> ttyACM0  (or ttyACM1, etc.)

# Verify autosuspend is disabled:
cat /sys/bus/usb/devices/*/power/control
# The entry for your device should show "on" not "auto"
```

If you ever need to confirm the VID:PID of your unit (e.g. after a hardware
swap):
```bash
lsusb | grep -i "EA Elektro\|232e"
# Bus 003 Device 016: ID 232e:0018 EA Elektro-Automatik GmbH & Co. KG PS 2342-06B
```

### 4. Copy bridge files

```bash
sudo mkdir -p /opt/ea-ps2k
sudo cp ea_ps2k_driver.py ea_ps2k_bridge.py ea-ps2k-bridge.sh /opt/ea-ps2k/
sudo chown -R $USER:$USER /opt/ea-ps2k
chmod +x /opt/ea-ps2k/ea-ps2k-bridge.sh
```

### 5. Test manually before enabling the service

```bash
bash /opt/ea-ps2k/ea-ps2k-bridge.sh
```

Expected output:
```
[Bridge] Connected to /dev/ea-ps2k-port
[Bridge] PS 2342-06B  42 V / 6 A  fw V3.02
[Bridge] Listening on 0.0.0.0:5025
```

Test with netcat from another machine:
```bash
echo "*IDN?" | nc 192.168.1.6 5025
# Should return: EA Elektro-Automatik,PS 2342-06B,12345,V3.02
```

### 6. Install the systemd service

```bash
sudo cp ea-ps2k-bridge.service /etc/systemd/system/
# Edit the User= line to match your username:
sudo nano /etc/systemd/system/ea-ps2k-bridge.service

sudo systemctl daemon-reload
sudo systemctl enable ea-ps2k-bridge   # start at boot
sudo systemctl start  ea-ps2k-bridge   # start now
```

---

## Service Management

```bash
# Status
sudo systemctl status ea-ps2k-bridge

# Live log
sudo journalctl -u ea-ps2k-bridge -f

# Last 50 log lines
sudo journalctl -u ea-ps2k-bridge -n 50

# Restart (e.g. after config change)
sudo systemctl restart ea-ps2k-bridge

# Stop
sudo systemctl stop ea-ps2k-bridge

# Disable auto-start at boot
sudo systemctl disable ea-ps2k-bridge
```

---

## VirtualHere Exclusion

VirtualHere and the Python bridge both need exclusive access to the USB device.
They cannot run simultaneously — VH will claim the device at the kernel level
and the bridge will fail with `[Errno 5] Input/output error`.

### Find your actual config.ini location

VirtualHere logs the config path it's using at startup:
```bash
sudo journalctl -u virtualhere -n 20 --no-pager | grep "Using configuration"
# Example output: Using configuration /usr/local/etc/virtualhere/config.ini
```
The location varies by installation — common paths are next to the binary,
in `/usr/local/etc/virtualhere/`, or in `/root/`. Always check the log rather
than assuming.

### Find your device's VID:PID

```bash
lsusb | grep -i "EA Elektro\|232e"
# Example: Bus 003 Device 016: ID 232e:0018 EA Elektro-Automatik GmbH & Co. KG PS 2342-06B
```

### Exclude the device

```bash
sudo systemctl stop virtualhere
sudo nano /usr/local/etc/virtualhere/config.ini   # use YOUR actual path from above
```

Add this line under `[General]`:
```ini
IgnoredDevices=232e/18
```

**Critical formatting notes** (these are easy to get wrong):
- The key is `IgnoredDevices`, **not** `ExcludeDevices` — that key does not exist
  and VH will silently ignore it with no error
- Format is `vid/pid` with a **forward slash**, not a colon
- **No** `0x` prefix and **no** leading zeros — `232e/18`, not `232e/0018`

```bash
sudo systemctl start virtualhere
sudo journalctl -u virtualhere -n 10 --no-pager
# The PS2000B line should now be absent from the "Found" device list
sudo systemctl restart ea-ps2k-bridge
```

---

## EEZ Studio Connection

In EEZ Studio: **Add instrument → EA-PS2342-06B Bridge → Ethernet**
- Address: `192.168.1.6`  (or your RPi's actual IP)
- Port: `5025`

Find the RPi's IP: `hostname -I` or check your router's DHCP table.

For a stable address, assign a static IP or DHCP reservation to the RPi's
MAC address in your router.

---

## Internet Access (optional firewall NAT)

To access the bridge from outside your LAN, add a port-forward rule on your
router/firewall:

```
External port 5025 (TCP) → 192.168.1.6:5025
```

**Security note:** The bridge has no authentication. Anyone who can reach
port 5025 can control the power supply. Consider:
- Restricting source IPs in the firewall rule
- Running the bridge inside a VPN (WireGuard on the RPi is lightweight)
- Using a non-standard external port to reduce automated scanning

---

## Differences from the Local Workstation Version

| | Workstation (Windows) | RPi5 Server |
|---|---|---|
| Serial port | `COM3` | `/dev/ea-ps2k-port` (stable udev symlink) |
| Bind address | `127.0.0.1` (local only) | `0.0.0.0` (all interfaces) |
| Startup | `ea-ps2k-bridge.bat` (manual) | systemd (automatic at boot) |
| Restart on crash | no | yes (5 s delay) |
| USB autosuspend | N/A | disabled via udev rule |
| Tracking support | read-only (front panel only) | read-only (front panel only) |
| Python files | same | same |

---

## Known Hardware Limitations

### Tracking mode cannot be set remotely

The PS2342-06B (and the wider PS2000B Triple series) supports a front-panel
**Tracking** button that makes CH2 mirror CH1. This **cannot be controlled
through the serial protocol** on this hardware:

- Writing to the tracking bit (object 54, mask `0x02`) is rejected by the
  device firmware with error `0x30` (upper limit exceeded), confirmed by
  byte-level protocol testing
- The reference implementation this bridge is built from
  ([marcj71/ps2000](https://github.com/marcj71/ps2000), confirmed working)
  does not implement tracking control either — only remote and output bits
- EA Elektro-Automatik (now part of Tektronix) has confirmed the PS2000B
  series is discontinued with no further firmware updates planned

**What works:** `get_tracking()` / `TRACK?` reads the current tracking state
from the device status byte — this is read-only and works correctly.

**What doesn't work:** `set_tracking()` / `TRACK ON` raises an error
immediately rather than sending a telegram the device will reject.

**Workaround for symmetric dual-rail use cases:** set CH1 and CH2 to the same
voltage independently via `CONF:OUTP` — this achieves the same electrical
result without relying on the device's internal tracking mechanism at all.

---

## Troubleshooting

**Service fails to start — serial port not found**
```bash
sudo journalctl -u ea-ps2k-bridge -n 20
# Look for: "Device not found: /dev/ea-ps2k-port"
ls -la /dev/ea-ps2k-port
# If missing: the PS2000B isn't connected/powered, or the udev rule isn't
# installed. Check:
sudo udevadm control --reload-rules && sudo udevadm trigger
lsusb | grep -i "232e"   # confirm the device is visible to the kernel at all
```

**Permission denied on serial port**
```bash
sudo journalctl -u ea-ps2k-bridge -n 5
# Look for: "PermissionError: [Errno 13] Permission denied"
# Fix: confirm user is in dialout group
groups $USER
# If dialout not listed: sudo usermod -aG dialout $USER  then reboot
```

**`[Errno 5] Input/output error` (EIO) when connecting from EEZ**

This means the serial device exists but the kernel can't communicate with
it. Two distinct causes seen in practice, in order of likelihood:

1. **VirtualHere has claimed the device.** VH and the bridge cannot share
   USB access — see [VirtualHere Exclusion](#virtualhere-exclusion) above.
   Confirm with:
   ```bash
   sudo journalctl -u virtualhere -n 30 --no-pager | grep -i "232e"
   # If you see "Found ... PS 2342-06B" here, VH has it — exclude it
   ```

2. **The device node changed** (e.g. `/dev/ttyACM0` → `/dev/ttyACM1`) because
   the PS2000B is on a USB hub and enumeration order shifted after a reboot
   or hub replug. The `/dev/ea-ps2k-port` udev symlink solves this — if for
   any reason the bridge is pointing at a hardcoded ttyACMx path:
   ```bash
   sudo systemctl cat ea-ps2k-bridge | grep ExecStart
   sudo systemctl edit --full ea-ps2k-bridge   # fix it
   sudo systemctl daemon-reload
   sudo systemctl restart ea-ps2k-bridge
   ```

**PS2000B repeatedly connects and disconnects in `dmesg`**
```bash
dmesg -w | grep -i "232e\|disconnect"
# Repeated "New USB device found" / "USB disconnect" cycles within seconds
# point to a hardware issue:
#   - Reseat the USB cable at both ends, or try a different cable
#   - If on a hub: confirm the hub has its own power adapter
#   - Try a direct connection to bypass any hub/isolator
```

**PS2000B shows as VirtualHere device instead of `/dev/ea-ps2k-port`**
```
The VH server is claiming the device before cdc_acm binds.
Add the device to VH's IgnoredDevices list (see VirtualHere Exclusion above).
Key is IgnoredDevices (not ExcludeDevices), format is 232e/18 (not 232e:0018).
```

**EEZ connects but `*IDN?` times out**
```
The bridge is running but not responding fast enough.
Check: sudo journalctl -u ea-ps2k-bridge -f
Common cause: previous crashed session left the serial port in a bad state.
Fix: sudo systemctl restart ea-ps2k-bridge
```

**Works for a few days then stops responding (idle-period failure)**
```
Root cause: Linux USB autosuspend put the device into a low-power state.
Fix: ensure 99-ea-ps2k-port.rules is installed (see step 3 above).
Verify: cat /sys/bus/usb/devices/*/power/control — should show "on" not "auto"
for the EA device.
```
