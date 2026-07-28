# EA-PS2000B Bridge — Windows Workstation

Runs the TCP bridge locally on your Windows machine. The PS2000B connects
via USB directly to the Windows machine. EEZ Studio connects to localhost:5025.

## Prerequisites

Python 3.10+ from python.org (check "Add to PATH" during install).

```powershell
pip install pyserial
```

## Start the bridge

1. Find the COM port in Device Manager → Ports (COM & LPT)
2. Edit `ea-ps2k-bridge.bat` and set `COM_PORT=COM3` (or whichever)
3. Double-click `ea-ps2k-bridge.bat` — keep the window open

Or from PowerShell:
```powershell
python ea_ps2k_bridge.py --serial COM3
```

For COM ports above COM9:
```powershell
python ea_ps2k_bridge.py --serial \\.\COM12
```

Expected startup output (bridge v1.0.7+):
```
[Bridge] EA-PS2000B TCP bridge  v1.0.7
[Bridge] Connected to COM3
[Bridge] PS 2342-06B  42 V / 6 A  fw V3.02
[Bridge] Tracking OFF at startup
[Bridge] Watchdog started (interval 20s)
[Bridge] Listening on 127.0.0.1:5025
```

## EEZ Studio connection

Add instrument → Ethernet → `127.0.0.1` port `5025`

Install the extension: Home → Extensions → Install → select `ea-ps2000-series-1.0.29.zip`

## Files

| File | Purpose |
|------|---------|
| `ea_ps2k_driver.py` | Binary protocol driver (shared with RPi version) |
| `ea_ps2k_bridge.py` | TCP bridge server (v1.0.7) |
| `ea-ps2k-bridge.bat` | Double-click launcher |
| `requirements.txt` | Python dependencies (`pip install pyserial`) |
| `eezstudio/package.json` | EEZ Studio extension source (v1.0.29) |
| `make-eez-zip.bat` | Builds the installable extension zip |

## Bridge commands

Full command reference (including the dual-channel `BOTH` commands and the
non-EEZ-Studio usage examples) is in the
[main README](../README.md#bridge-command-reference) — canonical location,
not duplicated here.

Quick reminders specific to this workstation setup: `TRACK ON`/`TRACK OFF`
are not supported — the PS2000B firmware rejects remote tracking control,
use the front panel Tracking button (`TRACK?` read is fine). Current limit
(`SETP?`) differs from actual current draw (`MEAS:ALL?`).

## EEZ Studio extension shortcuts (v1.0.29)

| Shortcut | Toolbar | Description |
|----------|---------|-------------|
| Configure | ✓ | Dialog: set V/I/output/OVP/OCP for both channels. Reads current state first (SETP:BOTH?, PROT:BOTH?). Sends CONF:BOTH or CONF:OUTP depending on tracking state. |
| Live | ✓ | Continuous MEAS:BOTH? readout at 100 ms, displayed in a persistent updating toast. Close toast to reveal Stop button. |
| Output | ✓ | Dialog: set CH1/CH2 output ON/OFF independently. Uses OUTP:BOTH for one round-trip when both channels change. |
| Logger | ✓ | Dialog: start/stop CSV logging with configurable file path, interval, channels, and optional duration. |
| Both On | — | OUTP:BOTH ON,ON then MEAS:BOTH? readback. |
| Both Off | — | OUTP:BOTH OFF,OFF then MEAS:BOTH? readback. |
| CH1 On/Off | — | Simple OUTP 1,ON/OFF SCPI commands. |
| CH2 On/Off | — | OUTP 2,ON/OFF then MEAS:BOTH? readback. Skips if tracking is ON. |
| Diag | — | Runs *IDN?, INFO?, SETP:BOTH?, MEAS:BOTH? and displays results as individual toasts. |
| Reset | — | Sends *RST (requires confirmation). |
| Log Stop | — | Sends LOG:STOP. |

### Tracking behaviour in shortcuts

- Tracking state is read from `SETP:BOTH?` field [3] — no separate `TRACK?` query needed.
- Configure: when tracking is ON, CH2 fields are hidden and only CH1 is sent via `CONF:OUTP 1,...`.
- CH2 On/Off: skips the output command and shows an info toast instead.
- Live: shows `⇔TRK` suffix on the channel line when tracking is active.

## EEZ Studio toast notifications — multi-line display

EEZ Studio's toast library doesn't render `\n` as a line break by default, so
every shortcut here that shows multi-line output (Live, Configure, Output,
Both On/Off) injects a small CSS fix on first run of the session:

```javascript
if (!document.getElementById('ea-ps2k-toast-fix')) {
    var _s = document.createElement('style');
    _s.id = 'ea-ps2k-toast-fix';
    _s.textContent = '.Toastify__toast-body{white-space:pre-line}';
    document.head.appendChild(_s);
}
```

Full background (why it's needed, what was tried, upstream issue status) is
cross-instrument reference material, not specific to this bridge — see
[eez/docs/eez-live-toast-pattern.md](https://github.com/ksstech/eez/blob/main/docs/eez-live-toast-pattern.md).
