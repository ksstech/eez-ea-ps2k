# EA-PS2k Project Audit & Change Plan

**Date:** 2026-07-08  
**Status:** Pending execution  
**Naming convention:** `ea-ps2k-{function}` / `ea_ps2k_{function}` (Python uses underscores)

---

## Summary of Findings

| Area | Files found | Issues |
|------|-------------|--------|
| `z-repo/ea-ps2k/` (repo) | 3 | All wrongly named; 6 files missing |
| `eez/` folder (Proton Drive) | 3 zip archives | Wrong location, wrong names |
| RPi5 `/etc/udev/rules.d/` | 3 `.rules` files | 2 old-name EA files need merging/renaming |
| RPi5 `/dev/` | `ps2342` symlink | Wrong name |
| RPi5 systemd | No `.service` file | Bridge service file missing entirely |
| RPi5 script location | Unknown | Should be `/opt/ea-ps2k/` |
| Documentation | 0 EA-PS2k docs in DevSpace | All missing |

---

## A. z-repo/ea-ps2k/ — Repository Files

### Renames required

| Current filename | New filename | Reason |
|----------------|-------------|--------|
| `ea_ps2342.py` | `ea_ps2k_driver.py` | Model-agnostic naming; this driver supports all PS2000B models |
| `ea_bridge.py` | `ea_ps2k_bridge.py` | Standard naming convention |
| `start_bridge.sh` | `ea-ps2k-bridge.sh` | Standard naming; shell scripts use hyphens |

### Content changes required in existing files

**`ea_ps2k_driver.py`** (was `ea_ps2342.py`):
- Line 110: `port: str = '/dev/ttyACM0'` → `'/dev/ea-ps2k-port'`
- Class name `EaPs2342` → `EaPs2k` (model-agnostic)
- Docstring: update class name reference

**`ea_ps2k_bridge.py`** (was `ea_bridge.py`):
- Line 64: `from ea_ps2342 import EaPs2342, EaProtocolError` → `from ea_ps2k_driver import EaPs2k as EaPs2342, EaProtocolError`  
  *(alias preserves internal code until full rename pass)*
- Line 69: `self.ps = EaPs2342(serial_port)` → `self.ps = EaPs2k(serial_port)`
- Line 71: `self._idn = 'EA Elektro-Automatik,PS 2342-06B,...'` → read dynamically from device (already done in `connect()`, just remove hardcode)
- Line 347: `default='/dev/ttyACM0'` → `default='/dev/ea-ps2k-port'`

**`ea-ps2k-bridge.sh`** (was `start_bridge.sh`):
- Line 15: `SERIAL_PORT="/dev/ttyACM0"` → `SERIAL_PORT="/dev/ea-ps2k-port"`
- Line 30: `sudo systemctl start ea_ps2342_bridge` → `sudo systemctl start ea-ps2k-bridge`
- Header comments: update service name references
- Import reference: `ea_bridge.py` → `ea_ps2k_bridge.py`

### Files missing — must be created

| File | Type | Purpose |
|------|------|---------|
| `ea-ps2k-bridge.service` | systemd service | Run bridge at boot, restart on crash |
| `99-ea-ps2k-port.rules` | udev rules | USB autosuspend off + `/dev/ea-ps2k-port` symlink (consolidated) |
| `ea-ps2k-monitor.py` | Python script | Health check — tests full stack via TCP bridge |
| `ea-ps2k-monitor.service` | systemd service | Run monitor as oneshot |
| `ea-ps2k-monitor.timer` | systemd timer | Schedule monitor every 30 min |
| `ea-ps2k-reference.md` | Documentation | Project reference (replaces scratch doc from this session) |

### Target directory structure

```
z-repo/ea-ps2k/
├── ea_ps2k_driver.py          # EA-PS2000B binary protocol driver
├── ea_ps2k_bridge.py          # TCP/SCPI bridge (EEZStudio connects here)
├── ea-ps2k-bridge.sh          # Manual launcher / test script
├── ea-ps2k-bridge.service     # systemd: auto-start bridge at boot
├── ea-ps2k-monitor.py         # Health check script
├── ea-ps2k-monitor.service    # systemd: run monitor
├── ea-ps2k-monitor.timer      # systemd: schedule monitor
├── 99-ea-ps2k-port.rules      # udev: USB autosuspend + /dev/ea-ps2k-port symlink
├── ea-ps2k-reference.md       # Project reference documentation
└── releases/
    ├── ea-ps2k-server-2.0.0.zip
    ├── ea-ps2k-bridge-1.0.7.zip
    └── ea-ps2k-rpi-2.0.5.zip
```

---

## B. eez/ Folder — Wrong Location, Wrong Names

These three zip archives are in `DevSpace/eez/` and belong in `z-repo/ea-ps2k/releases/`.

| Current path | Action | New path |
|-------------|--------|---------|
| `eez/ea_ps2342_server-2.0.0.zip` | Move + rename | `z-repo/ea-ps2k/releases/ea-ps2k-server-2.0.0.zip` |
| `eez/ea_ps2342_bridge-1.0.7.zip` | Move + rename | `z-repo/ea-ps2k/releases/ea-ps2k-bridge-1.0.7.zip` |
| `eez/ea_ps2342_rpi-2.0.5.zip` | Move + rename | `z-repo/ea-ps2k/releases/ea-ps2k-rpi-2.0.5.zip` |

> If the `eez/` folder contained other non-EA-PS2k content, check before deleting it.

---

## C. RPi5 Server — udev / systemd / File Locations

*SSH access not yet available — changes inferred from script content and earlier shell sessions.*

### udev rules (`/etc/udev/rules.d/`)

| Current file | Action |
|-------------|--------|
| `99-ea-ps2342-usb.rules` | **Delete** (autosuspend rule — merged into new file) |
| `99-ps2342.rules` | **Delete** (symlink rule — merged into new file) |
| `99-com.rules` | **Leave as-is** (RPi system GPIO/SPI/I2C rules — not ours) |
| `99-ea-ps2k-port.rules` *(missing)* | **Create** — consolidated rule below |

**New consolidated rule** (`99-ea-ps2k-port.rules`):
```udev
# EA Elektro-Automatik PS 2000B series — USB device: 232e:0018
# Disable autosuspend so device stays responsive after idle periods
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="232e", ATTRS{idProduct}=="0018", \
    ATTR{power/control}="on"
# Create stable named symlink: /dev/ea-ps2k-port
SUBSYSTEM=="tty", ATTRS{idVendor}=="232e", ATTRS{idProduct}=="0018", \
    SYMLINK+="ea-ps2k-port"
```

Deploy commands:
```bash
sudo cp 99-ea-ps2k-port.rules /etc/udev/rules.d/
sudo rm /etc/udev/rules.d/99-ea-ps2342-usb.rules
sudo rm /etc/udev/rules.d/99-ps2342.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# Verify new symlink:
ls -la /dev/ea-ps2k-port
```

### Device symlink

| Current | New |
|---------|-----|
| `/dev/ps2342` | `/dev/ea-ps2k-port` |

The old symlink disappears automatically when `99-ps2342.rules` is removed and udev is reloaded.

### Script location on RPi5

Scripts should live in `/opt/ea-ps2k/`. Verify and deploy:
```bash
sudo mkdir -p /opt/ea-ps2k
sudo cp ea_ps2k_driver.py ea_ps2k_bridge.py /opt/ea-ps2k/
sudo chmod +x /opt/ea-ps2k/*.py
```

### systemd service — bridge

No `.service` file exists on the RPi. The `start_bridge.sh` references `ea_ps2342_bridge` which has never been installed.

Create and deploy `ea-ps2k-bridge.service`:
```bash
sudo cp ea-ps2k-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ea-ps2k-bridge
sudo systemctl status ea-ps2k-bridge
```

### systemd service + timer — monitor

```bash
sudo cp ea-ps2k-monitor.service ea-ps2k-monitor.timer /etc/systemd/system/
sudo cp ea-ps2k-monitor.py /opt/ea-ps2k/
sudo systemctl daemon-reload
sudo systemctl enable --now ea-ps2k-monitor.timer
sudo systemctl list-timers ea-ps2k-monitor.timer
```

---

## D. Documentation — All Missing

No EA-PS2000 documentation found anywhere in DevSpace.

### Documents to obtain and add to `z-repo/ea-ps2k/docs/`

| Document | Source | Priority |
|----------|--------|----------|
| EA-PS 2000 B Programming Guide (2014) | EA website / device CD | **Critical** — binary protocol spec |
| EA-PS 2342-06B datasheet / product sheet | EA website | High |
| EA-PS 2342-06B quick start guide | EA website | Medium |
| EEZStudio TCP connection setup notes | Internal — create from session notes | High |
| VirtualHere setup notes | Internal — create from session notes | Medium |

### Documents to create (internal)

| File | Content |
|------|---------|
| `ea-ps2k-reference.md` | Architecture, known issues, SCPI command ref, deploy procedures |
| `docs/eezstudio-setup.md` | How to configure EEZStudio to connect to bridge on port 5025 |
| `docs/rpi5-setup.md` | Full RPi5 setup: packages, udev, systemd, VirtualHere |

---

## E. Execution Order

1. **Proton Drive / repo** — rename and update files locally (can do now)
2. **Move eez/ releases** — move zips to `releases/` subfolder (can do now)
3. **Create missing files** — service units, monitor script, udev rules, reference doc (can do now)
4. **RPi5 deploy** — once SSH access is available:
   - Deploy renamed scripts to `/opt/ea-ps2k/`
   - Replace udev rules
   - Install systemd units
   - Reload and verify
5. **Documentation** — obtain EA programming guide PDF; write internal setup docs

---

## F. What This Does NOT Change

- The binary protocol implementation in `ea_ps2k_driver.py` — correct and complete
- The bridge TCP protocol and command set in `ea_ps2k_bridge.py` — correct and complete  
- TCP port 5025 — leave as-is (standard SCPI-over-TCP port)
- EEZStudio config — connection target stays `rpi5-ip:5025`
