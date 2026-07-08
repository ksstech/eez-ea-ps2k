"""
ea-ps2k-monitor.py  —  Health-check monitor for the EA-PS2000B bridge stack

Tests the full stack from USB device presence through to actual V/I readings
via the TCP bridge. Logs pass/fail at each stage to syslog.

Test stages (in order — stops at first failure):
  1. USB device visible   — /dev/ea-ps2k-port symlink exists
  2. Bridge port open     — TCP connect to bridge host:port succeeds
  3. IDN response         — *IDN? returns a non-empty string
  4. CH1 V/I read         — MEAS:ALL? 1 returns parseable values
  5. CH2 V/I read         — MEAS:ALL? 2 returns parseable values

Usage:
  # Run once (exit 0 = all OK, exit 1 = failure):
  python3 ea-ps2k-monitor.py

  # Run with custom host (when bridge is remote):
  python3 ea-ps2k-monitor.py --host 192.168.1.6 --port 5025

  # Suppress console output (syslog only):
  python3 ea-ps2k-monitor.py --quiet

Deployment:
  Installed to /opt/ea-ps2k/ and triggered every 30 minutes via
  ea-ps2k-monitor.timer → ea-ps2k-monitor.service.

  Results are viewable with:
    journalctl -t ea-ps2k-monitor -f
    journalctl -t ea-ps2k-monitor -n 50
"""

import argparse
import os
import socket
import syslog
import sys
import time

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_HOST      = '127.0.0.1'   # bridge on same machine
DEFAULT_PORT      = 5025
DEFAULT_TIMEOUT   = 5.0           # seconds per TCP operation
DEVICE_SYMLINK    = '/dev/ea-ps2k-port'
SYSLOG_TAG        = 'ea-ps2k-monitor'


# ── Logging ───────────────────────────────────────────────────────────────────

_quiet = False

def _log(level: int, msg: str):
    """Write to syslog and optionally to stdout."""
    syslog.syslog(level, msg)
    if not _quiet:
        prefix = {
            syslog.LOG_ERR:    'ERROR',
            syslog.LOG_WARNING:'WARN ',
            syslog.LOG_NOTICE: 'OK   ',
            syslog.LOG_INFO:   'INFO ',
        }.get(level, 'INFO ')
        print(f'[{SYSLOG_TAG}] {prefix} {msg}', flush=True)

def ok(stage: str, detail: str = ''):
    _log(syslog.LOG_NOTICE, f'PASS stage={stage}' + (f' {detail}' if detail else ''))

def fail(stage: str, reason: str):
    _log(syslog.LOG_ERR, f'FAIL stage={stage} reason={reason}')


# ── TCP helper ────────────────────────────────────────────────────────────────

def _query(sock: socket.socket, cmd: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Send a newline-terminated command and return the response line."""
    sock.sendall((cmd.strip() + '\n').encode('ascii'))
    sock.settimeout(timeout)
    buf = b''
    deadline = time.monotonic() + timeout
    while b'\n' not in buf:
        if time.monotonic() > deadline:
            raise TimeoutError(f'No response to {cmd!r} within {timeout:.0f}s')
        try:
            chunk = sock.recv(1024)
        except socket.timeout:
            raise TimeoutError(f'Socket timeout waiting for {cmd!r}')
        if not chunk:
            raise ConnectionError('Connection closed by bridge')
        buf += chunk
    return buf.split(b'\n')[0].decode('ascii', errors='replace').strip()


# ── Main health check ─────────────────────────────────────────────────────────

def run_check(host: str, port: int, timeout: float) -> bool:
    """
    Execute all health-check stages in sequence.
    Returns True if all stages pass, False on first failure.
    """
    syslog.openlog(SYSLOG_TAG, syslog.LOG_PID, syslog.LOG_DAEMON)

    _log(syslog.LOG_INFO, f'Health check starting  host={host}:{port}  device={DEVICE_SYMLINK}')

    # ── Stage 1: USB device symlink exists ────────────────────────────────────
    stage = 'usb-device'
    if not os.path.exists(DEVICE_SYMLINK):
        fail(stage, f'{DEVICE_SYMLINK} not found — device disconnected or udev rule missing')
        return False
    try:
        real = os.path.realpath(DEVICE_SYMLINK)
        ok(stage, f'{DEVICE_SYMLINK} -> {real}')
    except OSError as exc:
        fail(stage, str(exc))
        return False

    # ── Stage 2: TCP connection to bridge ────────────────────────────────────
    stage = 'tcp-connect'
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        ok(stage, f'connected to {host}:{port}')
    except (ConnectionRefusedError, OSError, TimeoutError) as exc:
        fail(stage, f'cannot connect to {host}:{port} — {exc}')
        try:
            sock.close()
        except Exception:
            pass
        return False

    try:
        # ── Stage 3: *IDN? response ───────────────────────────────────────────
        stage = 'idn'
        try:
            idn = _query(sock, '*IDN?', timeout)
            if not idn or idn.startswith('ERR'):
                fail(stage, f'unexpected response: {idn!r}')
                return False
            ok(stage, f'{idn}')
        except (TimeoutError, ConnectionError, OSError) as exc:
            fail(stage, str(exc))
            return False

        # ── Stage 4: CH1 V/I read ─────────────────────────────────────────────
        stage = 'ch1-read'
        try:
            resp = _query(sock, 'MEAS:ALL? 1', timeout)
            if resp.startswith('ERR'):
                fail(stage, f'bridge error: {resp}')
                return False
            parts = resp.split(',')
            if len(parts) < 4:
                fail(stage, f'malformed response: {resp!r}')
                return False
            v1 = float(parts[0])
            i1 = float(parts[1])
            on1 = parts[2] == '1'
            mode1 = parts[3]
            ok(stage, f'{v1:.3f}V  {i1:.4f}A  {"ON" if on1 else "OFF"}  {mode1}')
        except (TimeoutError, ConnectionError, OSError, ValueError) as exc:
            fail(stage, str(exc))
            return False

        # ── Stage 5: CH2 V/I read ─────────────────────────────────────────────
        stage = 'ch2-read'
        try:
            resp = _query(sock, 'MEAS:ALL? 2', timeout)
            if resp.startswith('ERR'):
                fail(stage, f'bridge error: {resp}')
                return False
            parts = resp.split(',')
            if len(parts) < 4:
                fail(stage, f'malformed response: {resp!r}')
                return False
            v2 = float(parts[0])
            i2 = float(parts[1])
            on2 = parts[2] == '1'
            mode2 = parts[3]
            ok(stage, f'{v2:.3f}V  {i2:.4f}A  {"ON" if on2 else "OFF"}  {mode2}')
        except (TimeoutError, ConnectionError, OSError, ValueError) as exc:
            fail(stage, str(exc))
            return False

    finally:
        try:
            sock.close()
        except Exception:
            pass

    _log(syslog.LOG_NOTICE, 'Health check PASSED  all stages OK')
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global _quiet

    parser = argparse.ArgumentParser(
        description='EA-PS2000B bridge health check — tests full stack and logs to syslog',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--host', default=DEFAULT_HOST,
                        help='Bridge TCP host')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='Bridge TCP port')
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                        help='TCP operation timeout in seconds')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress console output (syslog only)')
    args = parser.parse_args()

    _quiet = args.quiet
    success = run_check(args.host, args.port, args.timeout)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
