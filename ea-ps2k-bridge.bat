@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  ea-ps2k-bridge.bat  —  EA-PS2000B Bridge Launcher — Windows workstation
REM  Edit COM_PORT below to match your device (check Device Manager)
REM ─────────────────────────────────────────────────────────────────────────

set COM_PORT=COM3
set TCP_PORT=5025

echo.
echo  EA-PS2000B TCP Bridge
echo  Serial port : %COM_PORT%
echo  TCP address : 127.0.0.1:%TCP_PORT%  (local only)
echo.
echo  Keep this window open.  Press Ctrl-C to stop.
echo.

python ea_ps2k_bridge.py --serial %COM_PORT% --tcp-port %TCP_PORT% --host 127.0.0.1

echo.
echo  Bridge stopped.
pause
