# EA-PS2342-06B Bridge — Raspberry Pi / Ubuntu LAN Server

Hosts the EA-PS2342-06B TCP bridge on a Raspberry Pi 4 running Ubuntu,
making the power supply accessible at `192.168.1.6:5025` from any device
on the LAN (or via a firewall NAT rule from anywhere on the internet).

---

## Architecture

```
EA-PS2342 USB
     │
     ▼
Raspberry Pi 4  (Ubuntu, /dev/ps2342 — stable symlink, see below)
     │
     ├── ea_ps2342.py     ← binary protocol driver
     ├── ea_bridge.py     ← TCP/SCPI translation layer
     └── systemd service  ← starts at boot, restarts on crash
     │
     ▼  TCP port 5025
LAN (192.168.1.x)
     │
     ├── EEZ Studio on Windows/macOS/Linux
     ├── Python scripts on any machine
     └── Internet (via firewall NAT → 192.168.1.6:5025)
```

VirtualHere USB Server runs alongside this bridge but must **exclude** the
PS2342 from its device list — they cannot share the same USB device.
See [VirtualHere exclusion](#virtualhere-exclusion) below.

---

## Quick Install (RPi / Ubuntu)

Copy the four files to the RPi, then run the installer:

```bash
# On the RPi — copy files first (scp, USB stick, or git clone)
chmod +x install_rpi.sh
./install_rpi.sh
```

The installer:
1. Installs Python 3 and `python3-serial` if not present
2. Adds your user to the `dialout` group (serial port access)
3. Copies bridge files to `~/ea_ps2342/`
4. Installs a udev rule creating a stable `/dev/ps2342` symlink, immune to
   `ttyACMx` renumbering — important if the PS2342 is connected via a USB hub
5. Installs and enables the `ea_ps2342_bridge` systemd service
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

### 3. Install the udev rule for stable device naming

Rather than referencing `/dev/ttyACM0` directly — which can change if the
PS2342 is connected via a USB hub and enumeration order shifts across
reboots or replug events — install a udev rule that creates a stable
`/dev/ps2342` symlink based on the device's USB VID:PID:

```bash
sudo cp 99-ps2342.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# Plug in the PS2342 if not already connected, then verify:
ls -la /dev/ps2342
# Should show something like: /dev/ps2342 -> ttyACM0  (or ttyACM1, etc.)
```

If you ever need to confirm the VID:PID of your unit (e.g. after a hardware
swap):
```bash
lsusb | grep -i "EA Elektro\|PS 2342"
# Bus 001 Device 062: ID 232e:0018 EA Elektro-Automatik GmbH & Co. KG PS 2342-06B
```

### 4. Copy bridge files

```bash
mkdir -p ~/ea_ps2342
cp ea_ps2342.py ea_bridge.py ~/ea_ps2342/
```

### 5. Test manually before enabling the service

```bash
bash start_bridge.sh
```

Expected output:
```
[Bridge] Connected to /dev/ps2342
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
sudo cp ea_ps2342_bridge.service /etc/systemd/system/
# Edit the service file to confirm paths and serial port:
sudo nano /etc/systemd/system/ea_ps2342_bridge.service

sudo systemctl daemon-reload
sudo systemctl enable ea_ps2342_bridge   # start at boot
sudo systemctl start  ea_ps2342_bridge   # start now
```

---

## Service Management

```bash
# Status
sudo systemctl status ea_ps2342_bridge

# Live log
sudo journalctl -u ea_ps2342_bridge -f

# Last 50 log lines
sudo journalctl -u ea_ps2342_bridge -n 50

# Restart (e.g. after config change)
sudo systemctl restart ea_ps2342_bridge

# Stop
sudo systemctl stop ea_ps2342_bridge

# Disable auto-start at boot
sudo systemctl disable ea_ps2342_bridge
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
lsusb | grep -i "EA Elektro\|PS 2342"
# Example: Bus 003 Device 002: ID 232e:0018 EA Elektro-Automatik GmbH & Co. KG PS 2342-06B
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
# The PS2342 line should now be absent from the "Found" device list
sudo systemctl restart ea_ps2342_bridge
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

| | Workstation (Windows) | RPi Server |
|---|---|---|
| Serial port | `COM3` | `/dev/ps2342` (stable udev symlink) |
| Bind address | `127.0.0.1` (local only) | `0.0.0.0` (all interfaces) |
| Startup | `start_bridge.bat` (manual) | systemd (automatic at boot) |
| Restart on crash | no | yes (5 s delay) |
| Tracking support | read-only (front panel only) | read-only (front panel only) |
| Python files | same | same |
| EEZ IEXT | same zip | same zip |

The Python files (`ea_ps2342.py`, `ea_bridge.py`) are **identical** between
both deployments — only the startup method and bind address differ.

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
- An open-source alternate firmware project exists
  ([UnifiedEngineering/EA-PS2000B-open-firmware](https://github.com/UnifiedEngineering/EA-PS2000B-open-firmware))
  but its USB serial implementation is currently a stub (echoes data back to
  host) and does not yet support remote tracking control either

**What works:** `get_tracking()` / `TRACK?` reads the current tracking state
from the device status byte — this is read-only and works correctly. The
Configure dialog detects active tracking and shows a warning before you set
channel values, since CH2 will mirror CH1 regardless of what you configure.

**What doesn't work:** `set_tracking()` / `TRACK ON` raises an error
immediately rather than sending a telegram the device will reject.

**Workaround for symmetric dual-rail use cases:** set CH1 and CH2 to the same
voltage independently via `CONF:OUTP` — this achieves the same electrical
result without relying on the device's internal tracking mechanism at all.

---

## Troubleshooting

**Service fails to start — serial port not found**
```bash
sudo journalctl -u ea_ps2342_bridge -n 20
# Look for: "No such file or directory: '/dev/ps2342'"
ls -la /dev/ps2342
# If missing: the PS2342 isn't connected/powered, or the udev rule isn't
# installed. Check:
sudo udevadm control --reload-rules && sudo udevadm trigger
lsusb | grep -i "232e"   # confirm the device is visible to the kernel at all
```

**Permission denied on serial port**
```bash
sudo journalctl -u ea_ps2342_bridge -n 5
# Look for: "PermissionError: [Errno 13] Permission denied"
# Fix: confirm user is in dialout group
groups pi   # replace 'pi' with your username
# If dialout not listed: sudo usermod -aG dialout pi  then reboot
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
   the PS2342 is on a USB hub and enumeration order shifted after a reboot
   or hub replug. This is exactly what the `/dev/ps2342` udev symlink (see
   step 3 of Manual Installation) solves — if the bridge service still
   references a hardcoded `/dev/ttyACMx` path instead of `/dev/ps2342`,
   update it:
   ```bash
   sudo systemctl cat ea_ps2342_bridge | grep ExecStart
   # If it shows --serial /dev/ttyACMx, switch it to /dev/ps2342:
   sudo systemctl edit --full ea_ps2342_bridge
   sudo systemctl daemon-reload
   sudo systemctl restart ea_ps2342_bridge
   ```

**PS2342 repeatedly connects and disconnects in `dmesg`**
```bash
dmesg -w | grep -i "232e\|disconnect"
# Repeated "New USB device found" / "USB disconnect" cycles within seconds
# point to a hardware issue, not software:
#   - Reseat the USB cable at both ends, or try a different cable
#   - If on a hub: confirm the hub has its own power adapter connected
#     and showing a power LED — without it, ports may brown out under load
#   - If using a USB isolator: try removing it temporarily to rule it out
#     as the unstable link (isolators often limit current across the
#     isolation barrier and can be marginal for sustained connections)
#   - Try a direct connection to the host, bypassing any hub/isolator,
#     to confirm whether the PS2342 and host port are themselves fine
```

**PS2342 shows as VirtualHere device instead of `/dev/ps2342`**
```
The VH server is claiming the device before cdc_acm binds.
Add the device to VH's IgnoredDevices list as described in
VirtualHere Exclusion above — note the correct key is IgnoredDevices,
not ExcludeDevices, and the format is vid/pid (e.g. 232e/18), not vid:pid.
```

**EEZ connects but *IDN? times out**
```
The bridge is running but not responding fast enough.
Check: sudo journalctl -u ea_ps2342_bridge -f
Common cause: previous crashed session left the serial port in a bad state.
Fix: sudo systemctl restart ea_ps2342_bridge
```
