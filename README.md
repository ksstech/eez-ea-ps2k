# eez-ea-ps2k

Python driver, TCP/SCPI-style bridge, and EEZ Studio extension for the
**EA Elektro-Automatik PS2000B Triple series** dual-output power supply
(binary serial protocol — not the proprietary VISA/LAN option).

Supports all PS2000B Triple models — nominal voltage/current are read from
the device at connect time, not hardcoded:

| Model | CH1 / CH2 | CH3 |
|---|---|---|
| PS2342‑06B | 42 V / 6 A | fixed 5 V, front panel only |
| PS2342‑10B | 42 V / 10 A | fixed 5 V, front panel only |
| PS2384‑05B | 84 V / 5 A | fixed 5 V, front panel only |
| PS2384‑20B | 84 V / 20 A | fixed 5 V, front panel only |

Three ways to use it, in increasing order of "no EEZ Studio required" —
see [Using it without EEZ Studio](#using-it-without-eez-studio) below:
1. **EEZ Studio extension** — dialogs, live readout toast, one-click shortcuts.
2. **Raw TCP bridge** — newline-terminated ASCII commands from any tool that
   can open a socket (`nc`, a test harness, LabVIEW, another instrument's
   control script, etc.).
3. **Python library** — `import ea_ps2k_driver`, talk to the device directly,
   no TCP layer or bridge process at all.

New to this repo and just want the EEZ Studio extension installed? See
[ksstech/eez: docs/installing-extensions.md](https://github.com/ksstech/eez/blob/main/docs/installing-extensions.md)
for the download/install steps (and two easy mistakes to avoid — grabbing
the wrong zip, and Safari auto-unzipping it).

---

## Architecture

```
EA-PS2000B (USB, binary serial protocol, 115200 8-O-1)
     │
     ▼
ea_ps2k_driver.py   ── EaPs2k class: telegram framing, checksums, typed
     │                  accessors (set_voltage, get_actual, ...), CSV
     │                  logging, thread-safe transfer + reconnect
     ▼
ea_ps2k_bridge.py   ── EaBridge class: translates newline-terminated ASCII
     │                  commands (VOLT 1,12.5 / MEAS:ALL? 1 / ...) into
     │                  driver calls; runs a TCP server; background
     │                  watchdog thread keeps the serial connection alive
     ▼  TCP (default port 5025)
     │
     ├── EEZ Studio  ── eezstudio/package.json: extension with toolbar
     │                  shortcuts (Configure, Live, Output, Logger, ...)
     │                  that send the same ASCII commands over the wire
     ├── Anything else that speaks the ASCII command set (see below)
     └── LAN / internet, via router NAT (optional — see docs/ea-ps2k-rpi.md)
```

Three independent layers, each usable on its own:
- **Driver** (`ea_ps2k_driver.py`) has no networking in it at all — it's a
  plain Python class wrapping the serial protocol. Usable standalone in any
  Python script or test harness.
- **Bridge** (`ea_ps2k_bridge.py`) adds the TCP server and ASCII command
  parser on top of the driver. This is what makes the device reachable from
  non-Python tools, and from other machines on the network.
- **EEZ Studio extension** (`eezstudio/`) is a thin client of the bridge —
  it's just JavaScript shortcuts sending the same ASCII commands any other
  TCP client would send. It adds nothing the bridge doesn't already expose.

## Repository structure

| Path | Purpose |
|---|---|
| `ea_ps2k_driver.py` | Core driver — `EaPs2k` class. No networking; pure serial protocol + typed Python API. |
| `ea_ps2k_bridge.py` | TCP server translating ASCII commands to driver calls. `EaBridge` class + `main()` CLI entry point. |
| `ea-ps2k-monitor.py` | Standalone health-check script — tests USB device → bridge TCP → IDN → both channels' readback, logs pass/fail to syslog. Run manually or via the packaged systemd timer. |
| `ea-ps2k-bridge.sh` / `ea-ps2k-bridge.bat` | Manual/debug launchers (Linux / Windows) — for testing before enabling the systemd service, or for simple always-manual use. |
| `ea-ps2k-install.sh` | One-shot RPi/Ubuntu installer — Python deps, udev rule, systemd service, starts it. |
| `ea-ps2k-rpi-deploy.sh` | Fuller RPi deploy script — additionally tears down a previous `ea_ps2342`-named install (old naming, pre-rename) and installs the monitor timer too. |
| `99-ea-ps2k-port.rules` | udev rule: stable `/dev/ea-ps2k-port` symlink by VID:PID + disables USB autosuspend. See [Reliability & Performance](#reliability--performance). |
| `ea-ps2k-bridge.service`, `ea-ps2k-monitor.service`, `ea-ps2k-monitor.timer` | systemd units for the bridge and its periodic health check. |
| `eezstudio/` | EEZ Studio extension source — `package.json` (shortcuts + metadata), `.idf`/`.sdl` (instrument definition), `image.png`. Built into a distributable zip by `build-extension-zip.py` and published as a [GitHub Release](https://github.com/ksstech/eez-ea-ps2k/releases) (not committed — see `.gitignore`). |
| `build-extension-zip.py` | Builds the `eezstudio/` folder into a release zip. Cross-platform (Python 3, stdlib only) — see [Development](#development). |
| `docs/ea-ps2k-rpi.md` | Full RPi/Ubuntu server deployment guide — install, VirtualHere exclusion, troubleshooting. |
| `docs/ea-ps2k-windows.md` | Windows workstation setup + EEZ Studio extension shortcut reference. |
| `requirements.txt` | `pyserial>=3.5` — the only dependency. |

Cross-instrument reference material (patterns shared with the Keysight
34465A and Rigol scope extensions) lives in the separate
[ksstech/eez](https://github.com/ksstech/eez) repo, not duplicated here.

## Quick start

Full platform-specific instructions are in the docs — this is the two-line version:

**RPi / Ubuntu (LAN server, starts at boot):**
```bash
chmod +x ea-ps2k-install.sh && ./ea-ps2k-install.sh
```
See [docs/ea-ps2k-rpi.md](docs/ea-ps2k-rpi.md) for manual steps, VirtualHere
device-sharing conflicts, and troubleshooting.

**Windows workstation (local only):**
```powershell
pip install pyserial
python ea_ps2k_bridge.py --serial COM3
```
See [docs/ea-ps2k-windows.md](docs/ea-ps2k-windows.md) for the full setup
and the EEZ Studio extension shortcut reference.

## Bridge command reference

All commands are newline-terminated ASCII, sent over TCP (default port
5025). Channel numbers are `1` or `2` (CH3 is fixed 5V, no remote interface
on this hardware).

**Identification / reset**
```
*IDN?                              cached device identification string
*RST                                both channels → 0V / 0A / output off
INFO?                               device info as JSON (nom voltage/current/type/firmware)
```

**Single-channel**
```
SYST:REM <ch>                      enter remote mode
SYST:LOC <ch>                      leave remote mode
VOLT <ch>,<v>                      e.g. VOLT 1,12.5
CURR <ch>,<a>                      e.g. CURR 2,2.0
OUTP <ch>,<ON|OFF|1|0>
CONF <ch>,<v>,<a>                  set voltage + current limit
CONF:OUTP <ch>,<v>,<a>,<ON|OFF>    set voltage + current limit + output in one call
OVP <ch>,<v>  /  OVP? <ch>         over-voltage protection: set / read
OCP <ch>,<a>  /  OCP? <ch>         over-current protection: set / read
MEAS:VOLT? <ch>                    actual voltage
MEAS:CURR? <ch>                    actual current draw (not the limit)
MEAS:ALL? <ch>                     v,i,on,mode,tracking
STAT? <ch>                         full status as JSON
SETP? <ch>                         v_set,i_set,on,tracking
VOLT:SET? <ch>  /  CURR:SET? <ch>  programmed setpoint readback
```

**Both-channel, one round trip** (see [Reliability & Performance](#reliability--performance) for why these exist)
```
CONF:BOTH <v1>,<a1>,<ON|OFF>,<v2>,<a2>,<ON|OFF>
OUTP:BOTH <ON|OFF>,<ON|OFF>
OVP:BOTH <v1>,<v2>   /   OCP:BOTH <i1>,<i2>
MEAS:BOTH?                         v1,i1,on1,mode1,trk1|v2,i2,on2,mode2,trk2
SETP:BOTH?                         v1_set,i1_set,on1,trk1|v2_set,i2_set,on2,trk2
PROT:BOTH?                         ovp1,ocp1|ovp2,ocp2
```

**Tracking** (read-only via this protocol — see [Known Limitations](#known-hardware-limitations))
```
TRACK?                              1 (tracking) or 0
```

**CSV logging**
```
LOG:START <path>[,<interval>[,<duration>[,<ch>...]]]
LOG:STOP
LOG:STATUS?                        1 if running, 0 if not
```

Errors are returned as `ERR:<message>` rather than raising a network-level
fault — a client can always expect exactly one response line per command.

## Using it without EEZ Studio

The bridge doesn't know or care that EEZ Studio exists — it's a plain TCP
server speaking newline-terminated ASCII, so anything that can open a socket
can drive the power supply.

**From a shell, with netcat:**
```bash
echo "*IDN?" | nc 192.168.1.6 5025
# EA Elektro-Automatik,PS 2342-06B,12345,V3.02

echo "CONF:OUTP 1,12.0,2.0,ON" | nc 192.168.1.6 5025
# 0
```

**From any language with a TCP socket — Python example:**
```python
import socket

s = socket.create_connection(("192.168.1.6", 5025), timeout=5)
s.sendall(b"CONF:OUTP 1,12.0,2.0,ON\n")
print(s.recv(1024).decode().strip())      # 0

s.sendall(b"MEAS:ALL? 1\n")
v, i, on, mode, trk = s.recv(1024).decode().strip().split(",")
print(f"{v} V  {i} A  {'ON' if on == '1' else 'OFF'}  {mode}")
```
This is the same command set a test harness, a CI rig, LabVIEW (via raw TCP),
or any other lab automation tool can use — the bridge is a general-purpose
SCPI-*like* front end for this instrument, EEZ Studio is just one client of it.

**Skipping the bridge entirely — pure Python, direct serial:**

If you're writing a Python tool and don't need TCP/remote access at all, use
`EaPs2k` directly — no bridge process, no network layer:
```python
from ea_ps2k_driver import EaPs2k

with EaPs2k("/dev/ea-ps2k-port") as ps:      # or "COM3" on Windows
    ps.configure(channel=1, volts=12.0, amps=2.0, output_on=True)
    reading = ps.get_actual(1)
    print(reading["v"], reading["i"], reading["CC"])
```
The context manager handles connect, remote-mode entry on both channels, and
clean disconnect (remote-mode exit + port close) automatically. This is the
right choice for a standalone test script, a pytest fixture, or embedding
PSU control directly in a larger Python application — the bridge/TCP layer
exists specifically for cases where the controlling process *isn't* Python,
or isn't on the same machine as the USB connection.

## Reliability & Performance

Several non-obvious fixes were required to make this reliable as an
always-on, unattended service — particularly around USB power management,
serial error recovery, and TCP-level latency with EEZ Studio as a client.
Summary (see [git history](https://github.com/ksstech/eez-ea-ps2k/commits/main)
for the full story of each):

| Problem | Fix | Where |
|---|---|---|
| Device stopped responding after idle days | USB autosuspend disabled via udev rule | `99-ea-ps2k-port.rules` |
| `/dev/ttyACMx` renumbers on hub replug/reboot | Stable `/dev/ea-ps2k-port` symlink by VID:PID | `99-ea-ps2k-port.rules` |
| `termios.error` on EIO not caught by `except OSError` | Explicit `_TERMIOS_ERROR` handling (not a subclass of `OSError`) | `ea_ps2k_driver.py` |
| Port never reconnected when idle (no client polling) | Background watchdog thread, independent of client activity | `ea_ps2k_bridge.py` |
| EEZ Studio showing ~6s round-trips on some commands | Short (100ms) socket timeout + dispatch-on-timeout fallback, instead of waiting a long timeout for a missing trailing `\n` | `ea_ps2k_bridge.py` |
| Response latency from TCP batching | `TCP_NODELAY` on every accepted client socket | `ea_ps2k_bridge.py` |
| Live toast polling both channels = 2x round trips | `MEAS:BOTH?`/`CONF:BOTH`/etc. — one round trip for both channels | `ea_ps2k_bridge.py` |
| VirtualHere and the bridge both claim the USB device | Documented `IgnoredDevices` exclusion (exact syntax matters) | [docs/ea-ps2k-rpi.md](docs/ea-ps2k-rpi.md#virtualhere-exclusion) |

The ones above that aren't specific to this instrument's protocol —
autosuspend, reconnect strategy, `TCP_NODELAY`, round-trip batching,
VirtualHere coexistence, and several more — are written up in detail,
generalized for any USB-serial-to-TCP bridge, in
**[ksstech/eez: docs/bridge-reliability-patterns.md](https://github.com/ksstech/eez/blob/main/docs/bridge-reliability-patterns.md)**.
If you're building a bridge for a different instrument, start there before
re-discovering these the hard way.

## Known hardware limitations

**Tracking mode cannot be set remotely.** The PS2342-06B (and the wider
PS2000B Triple series) firmware rejects remote tracking control — writing
the tracking bit returns error `0x30`. `TRACK?` reads the current state
(works fine, read-only), but `set_tracking()` / `TRACK ON` raises an error
immediately rather than sending a command the device will reject anyway.
**Workaround:** set CH1 and CH2 independently to the same values via
`CONF:OUTP` — same electrical result without relying on the device's
internal tracking mechanism. Full detail in
[docs/ea-ps2k-rpi.md](docs/ea-ps2k-rpi.md#known-hardware-limitations).

**CH3 has no remote interface at all** (fixed 5V, front panel only) — a
hardware limitation of the Triple series, not a driver gap.

## Development

This repo ships two independently-versioned, independently-deployable
artifacts — don't conflate their version numbers, they track different
things and change on different schedules:

- **The bridge** (`ea_ps2k_bridge.py`, `ea_ps2k_driver.py`) — runs standalone,
  no EEZ Studio required (see [Using it without EEZ Studio](#using-it-without-eez-studio)).
  Versioned by `__version__` in `ea_ps2k_bridge.py`, printed in its startup
  banner. Bump it whenever `ea_ps2k_bridge.py` or `ea_ps2k_driver.py` changes,
  tag `bridge-vX.Y.Z`:
  ```bash
  git tag bridge-vX.Y.Z && git push origin bridge-vX.Y.Z
  ```
- **The EEZ Studio extension** (`eezstudio/`) — a thin client of the bridge.
  Versioned by `eezstudio/package.json`'s `version` field. Bump it whenever
  anything under `eezstudio/` changes, rebuild and publish:
  ```bash
  python3 build-extension-zip.py
  git tag vX.Y.Z && git push origin vX.Y.Z
  gh release create vX.Y.Z ea-ps2000-series-X.Y.Z.zip --title "vX.Y.Z" --notes "..."
  ```

A commit touching only one side only needs that side's version bumped and
tag cut — e.g. a bridge-only reliability fix doesn't need a new extension
release, and vice versa.

## License

MIT — see [LICENSE](LICENSE).
