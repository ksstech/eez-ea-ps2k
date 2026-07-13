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

Single-channel commands (replace `x` with `1` or `2`):

```
*IDN?                         device identification
INFO?                         device info JSON (nom voltage/current/type/fw)
VOLT x,12.5                   set CHx voltage
CURR x,2.0                    set CHx current limit
OUTP x,ON                     turn CHx output on/off
CONF:OUTP x,12.0,2.0,ON       configure CHx voltage, current, output in one command
MEAS:ALL? x                   actual v,i,on,mode,tracking for CHx
SETP? x                       setpoints readback for CHx
OVP x,46.0                    set CHx over-voltage protection level
OCP x,6.5                     set CHx over-current protection level
TRACK?                        tracking state (read-only — use front panel button)
LOG:START C:\data\log.csv,0.5 start CSV logging (interval seconds)
LOG:STOP                      stop logging
LOG:STATUS?                   1 if logging active, 0 if not
```

Dual-channel BOTH commands (single TCP round-trip for both channels):

```
MEAS:BOTH?                    actual readings for both channels
                              returns: v,i,on,mode,trk|v,i,on,mode,trk
SETP:BOTH?                    setpoints for both channels
                              returns: v,i,on,trk|v,i,on,trk
PROT:BOTH?                    OVP and OCP levels for both channels
                              returns: ovp,ocp|ovp,ocp
CONF:BOTH v1,i1,out1,v2,i2,out2   configure both channels in one command
OUTP:BOTH on1,on2             set output state for both channels  (e.g. ON,OFF)
OVP:BOTH ovp1,ovp2            set OVP level for both channels
OCP:BOTH ocp1,ocp2            set OCP level for both channels
```

Note: `TRACK ON` / `TRACK OFF` are not supported — the PS2000B firmware
does not allow remote tracking control. Use the front panel Tracking button.
The bridge attempts `TRACK OFF` at startup (silently ignored if firmware rejects it).
Current limit (`SETP?`) differs from actual current draw (`MEAS:ALL?`).

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

EEZ Studio uses react-toastify for in-app notifications. By default,
`white-space` on `.Toastify__toast-body` is not set to `pre-line`, so
`\n` characters in toast strings are collapsed to spaces and CH1/CH2
data appears on a single line.

**Investigation findings:**

| Approach | Result |
|----------|--------|
| `\n` in render string, no CSS change | Single line — newline collapsed |
| `<br>` in render string | Literal text `<br>` — not rendered as HTML |
| `white-space: pre-line` via DevTools injection | Two lines — works |
| `document.createElement('style')` from script | Two lines — works (document accessible in sandbox) |

**Workaround (implemented in v1.0.29):** Each shortcut that uses `\n` injects
the CSS fix into `document.head` on first run of the EEZ Studio session:

```javascript
if (!document.getElementById('ea-ps2k-toast-fix')) {
    var _s = document.createElement('style');
    _s.id = 'ea-ps2k-toast-fix';
    _s.textContent = '.Toastify__toast-body{white-space:pre-line}';
    document.head.appendChild(_s);
}
```

The guard (`getElementById` check) ensures the style tag is only added once
per session regardless of how many shortcuts are run.

**Upstream fix:** A GitHub issue has been filed against `eez-open/studio`
requesting `white-space: pre-line` be added to `.Toastify__toast-body` in
`packages/eez-studio-ui/_stylesheets/app.less`. Once merged the CSS injection
block in each shortcut becomes a harmless no-op and can be removed.
