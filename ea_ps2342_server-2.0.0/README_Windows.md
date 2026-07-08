# EA-PS2342-06B Bridge — Windows Workstation

Runs the TCP bridge locally on your Windows machine. The PS2342 connects
via USB to the Windows machine. EEZ Studio connects to localhost:5025.

## Prerequisites

Python 3.10+ from python.org (check "Add to PATH" during install).

```powershell
pip install pyserial
```

## Start the bridge

1. Find the COM port in Device Manager → Ports (COM & LPT)
2. Edit `start_bridge.bat` and set `COM_PORT=COM3` (or whichever)
3. Double-click `start_bridge.bat` — keep the window open

Or from PowerShell:
```powershell
python ea_bridge.py --serial COM3
```

For COM ports above COM9:
```powershell
python ea_bridge.py --serial \\.\COM12
```

## EEZ Studio connection

Add instrument → Ethernet → `127.0.0.1` port `5025`

## Files

| File | Purpose |
|------|---------|
| `ea_ps2342.py` | Binary protocol driver (shared with RPi version) |
| `ea_bridge.py` | TCP bridge server |
| `start_bridge.bat` | Double-click launcher |
| `requirements.txt` | Python dependencies |

## Bridge commands

```
*IDN?                     device identification
VOLT 1,12.5               set CH1 voltage
CURR 1,2.0                set CH1 current limit
OUTP 1,ON                 turn CH1 on
CONF:OUTP 1,12.0,2.0,ON   configure CH1 in one command
MEAS:ALL? 1               v,i,on,mode,tracking
SETP? 1                   setpoints readback
TRACK ON / TRACK OFF      enable/disable CH2 tracking CH1
TRACK?                    tracking state
LOG:START C:\data\log.csv,0.5   start CSV logging
LOG:STOP                  stop logging
INFO?                     device info JSON
```

Note: current limit (SETP?) differs from actual current draw (MEAS:CURR?).
