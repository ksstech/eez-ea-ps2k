"""
ea_ps2k_bridge.py  —  TCP/SCPI bridge for EA-PS2000B series power supplies

Runs a TCP server on the configured address and port.
EEZ Studio (or any TCP client) connects and sends newline-terminated ASCII commands.

Deployment modes
────────────────
  Local workstation (Windows):
      python ea_ps2k_bridge.py --serial COM3

  LAN server (RPi/Ubuntu) — binds to all interfaces so remote clients can connect:
      python ea_ps2k_bridge.py --serial /dev/ea-ps2k-port --host 0.0.0.0 --tcp-port 5025

  The systemd service on the RPi starts this automatically at boot with the
  correct arguments. ea-ps2k-bridge.sh is a manual fallback for testing.

Supported commands
──────────────────
  *IDN?
  *RST                               both channels → 0V / 0A / output off

  SYST:REM <ch>                      enter remote mode
  SYST:LOC <ch>                      leave remote mode

  VOLT <ch>,<v>                      e.g.  VOLT 1,12.5
  CURR <ch>,<a>                      e.g.  CURR 2,2.0
  OUTP <ch>,<ON|OFF|1|0>
  CONF <ch>,<v>,<a>
  CONF:OUTP <ch>,<v>,<a>,<ON|OFF>
  CONF:BOTH <v1>,<a1>,<ON|OFF>,<v2>,<a2>,<ON|OFF>  both channels, one round-trip
  OUTP:BOTH <ON|OFF>,<ON|OFF>                       both outputs, one round-trip
  OVP:BOTH  <v1>,<v2>                               set OVP both channels
  OCP:BOTH  <i1>,<i2>                               set OCP both channels

  SETP:BOTH?                         v1_set,i1_set,on1,trk1|v2_set,i2_set,on2,trk2
  PROT:BOTH?                         ovp1,ocp1|ovp2,ocp2

  TRACK ON|OFF                       enable/disable CH2 tracking CH1
  TRACK?                             → 1 (tracking) or 0

  MEAS:VOLT? <ch>                    actual voltage
  MEAS:CURR? <ch>                    actual current draw (not the limit)
  MEAS:ALL? <ch>                     v,i,on,mode,tracking
  STAT? <ch>                         full status as JSON
  SETP? <ch>                         v_set,i_set,on,tracking
  VOLT:SET? <ch>                     programmed voltage setpoint
  CURR:SET? <ch>                     programmed current limit setpoint

  OVP <ch>,<v>                       set OVP threshold
  OCP <ch>,<a>                       set OCP threshold
  OVP? <ch>                          read OVP threshold
  OCP? <ch>                          read OCP threshold

  LOG:START <path>[,<interval>[,<duration>[,<ch>...]]]
  LOG:STOP
  LOG:STATUS?

  INFO?                              device info as JSON
"""

__version__ = '1.0.5'

import argparse
import json
import os
import socket
import sys
import threading
import time

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ea_ps2k_driver import EaPs2k, EaProtocolError, is_scpi_capable

# Minimum seconds between serial reconnect attempts.
# Prevents hammering the port while the device is still coming up.
_RECONNECT_COOLDOWN = 5.0


class EaBridge:
    def __init__(self, serial_port: str):
        self.ps   = EaPs2k(serial_port)
        self.lock = threading.Lock()
        self._idn = 'EA Elektro-Automatik,PS 2342-06B,000000,V0.00'
        self._last_reconnect_attempt = 0.0

    def connect(self):
        if not os.path.exists(self.ps.port_name):
            print(f'[Bridge] Device not found: {self.ps.port_name} — will retry', flush=True)
            raise SystemExit(1)
        try:
            self.ps.connect()
        except (serial.SerialException, EaProtocolError) as exc:
            print(f'[Bridge] Could not open {self.ps.port_name}: {exc} — will retry', flush=True)
            raise SystemExit(1)
        print(f'[Bridge] Connected to {self.ps.port_name}')
        try:
            info = self.ps.get_info()
            self._idn = (f'{info["manufacturer"]},{info["type"]},'
                         f'{info["serial"]},{info["version"]}')
            print(f'[Bridge] {info["type"]}  '
                  f'{info["nom_voltage"]:.0f} V / {info["nom_current"]:.0f} A  '
                  f'fw {info["version"]}', flush=True)
            if is_scpi_capable(info['version']):
                print(
                    f'[Bridge] NOTE: Firmware {info["version"]!r} supports native '
                    f'SCPI (v>=3.06, build year>=2020). This binary bridge still '
                    f'works, but you can also connect EEZStudio directly to '
                    f'{self.ps.port_name} via SCPI without the bridge.',
                    flush=True,
                )
        except EaProtocolError as exc:
            print(f'[Bridge] Warning: could not read device info: {exc}')
        # Attempt to disable tracking at startup.
        # Manual requires both channels OFF first — if outputs are already on
        # this will be rejected; we ignore the failure and leave tracking as-is.
        try:
            self.ps.set_tracking(False)
            print('[Bridge] Tracking OFF at startup', flush=True)
        except Exception as exc:
            print(f'[Bridge] Note: could not disable tracking at startup: {exc}', flush=True)

    def _reconnect(self) -> bool:
        """
        Single reconnect attempt, rate-limited by _RECONNECT_COOLDOWN.

        Called from dispatch() when the serial port is not connected (i.e.
        self.ps._ser is None after a previous EIO event closed it).

        Non-blocking: returns False immediately if the device isn't visible
        yet or the cooldown hasn't elapsed — the caller returns an error to
        the client and the next command will try again.  The Live shortcut's
        100 ms poll cycle provides natural retry cadence.

        Returns True if the port was successfully reopened.
        """
        now = time.monotonic()
        if now - self._last_reconnect_attempt < _RECONNECT_COOLDOWN:
            return False   # too soon — let the cooldown elapse
        self._last_reconnect_attempt = now

        print(f'[Bridge] Serial lost — attempting reconnect to {self.ps.port_name}...',
              flush=True)

        if not os.path.exists(self.ps.port_name):
            print(f'[Bridge] Device not found: {self.ps.port_name}', flush=True)
            return False

        try:
            self.ps.connect()
        except (serial.SerialException, EaProtocolError, OSError) as exc:
            print(f'[Bridge] Reconnect failed: {exc}', flush=True)
            return False

        # Refresh cached IDN from the (now live) device
        try:
            info = self.ps.get_info()
            self._idn = (f'{info["manufacturer"]},{info["type"]},'
                         f'{info["serial"]},{info["version"]}')
            print(f'[Bridge] Reconnected: {info["type"]}  fw {info["version"]}',
                  flush=True)
        except EaProtocolError as exc:
            print(f'[Bridge] Reconnected (could not refresh device info: {exc})',
                  flush=True)
        return True

    def disconnect(self):
        self.ps.disconnect()

    def dispatch(self, raw: str) -> str:
        cmd   = raw.strip()
        upper = cmd.upper()
        if not cmd:
            return ''

        try:
            # ── Identification ────────────────────────────────────────────
            # *IDN? returns the cached value — no serial I/O, always works.
            if upper == '*IDN?':
                return self._idn

            # All commands below require a live serial connection.
            # If the port was closed by a previous I/O error, attempt reconnect.
            if not self.ps.is_connected:
                if not self._reconnect():
                    return 'ERR:Device disconnected — reconnecting, retry shortly'

            if upper == '*RST':
                # Disable tracking first so CH2 commands are not blocked
                try:
                    self.ps.set_tracking(False)
                except Exception:
                    pass
                for ch in (1, 2):
                    self.ps.set_voltage(ch, 0.0)
                    self.ps.set_current(ch, 0.0)
                    self.ps.set_output(ch, False)
                return '0'

            # ── Remote ────────────────────────────────────────────────────
            if upper.startswith('SYST:REM'):
                self.ps._set_remote(int(_arg(cmd, 0)), True)
                return '0'

            if upper.startswith('SYST:LOC'):
                self.ps._set_remote(int(_arg(cmd, 0)), False)
                return '0'

            # ── Tracking ──────────────────────────────────────────────────
            if upper.startswith('TRACK '):
                on = _on(_arg(cmd, 0))
                self.ps.set_tracking(on)
                # Allow device time to release tracking state before
                # subsequent CH2 commands — extra delay beyond _MIN_DELAY
                if not on:
                    time.sleep(0.2)
                return '0'

            if upper == 'TRACK?':
                return '1' if self.ps.get_tracking() else '0'

            # ── Setpoints ─────────────────────────────────────────────────
            if upper.startswith('VOLT '):
                a = _args(cmd)
                self.ps.set_voltage(int(a[0]), float(a[1]))
                return '0'

            if upper.startswith('CURR '):
                a = _args(cmd)
                self.ps.set_current(int(a[0]), float(a[1]))
                return '0'

            if upper.startswith('OUTP '):
                a = _args(cmd)
                self.ps.set_output(int(a[0]), _on(a[1]))
                return '0'

            if upper.startswith('OUTP:BOTH '):
                # Set both channel outputs in one TCP round-trip.
                # Args: on1,on2
                a = _args(cmd)
                self.ps.set_output(1, _on(a[0]))
                self.ps.set_output(2, _on(a[1]))
                return '0'

            if upper.startswith('CONF:OUTP '):
                a = _args(cmd)
                self.ps.configure(int(a[0]), float(a[1]), float(a[2]), _on(a[3]))
                return '0'

            if upper.startswith('CONF:BOTH '):
                # Configure both channels in one TCP round-trip.
                # Args: v1,i1,out1,v2,i2,out2
                a = _args(cmd)
                self.ps.configure(1, float(a[0]), float(a[1]), _on(a[2]))
                self.ps.configure(2, float(a[3]), float(a[4]), _on(a[5]))
                return '0'

            if upper.startswith('CONF '):
                a = _args(cmd)
                self.ps.configure(int(a[0]), float(a[1]), float(a[2]))
                return '0'

            # ── Protection ────────────────────────────────────────────────
            if upper.startswith('OVP '):
                a = _args(cmd)
                self.ps.set_ovp(int(a[0]), float(a[1]))
                return '0'

            if upper.startswith('OVP:BOTH '):
                a = _args(cmd)
                self.ps.set_ovp(1, float(a[0]))
                self.ps.set_ovp(2, float(a[1]))
                return '0'

            if upper.startswith('OCP '):
                a = _args(cmd)
                self.ps.set_ocp(int(a[0]), float(a[1]))
                return '0'

            if upper.startswith('OCP:BOTH '):
                a = _args(cmd)
                self.ps.set_ocp(1, float(a[0]))
                self.ps.set_ocp(2, float(a[1]))
                return '0'

            if upper.startswith('OVP?'):
                return f'{self.ps.get_ovp(int(_arg(cmd, 0))):.4f}'

            if upper.startswith('OCP?'):
                return f'{self.ps.get_ocp(int(_arg(cmd, 0))):.4f}'

            if upper == 'PROT:BOTH?':
                # OVP and OCP for both channels in one TCP round-trip.
                # Returns: ovp1,ocp1|ovp2,ocp2
                return (f'{self.ps.get_ovp(1):.4f},{self.ps.get_ocp(1):.4f}'
                        f'|{self.ps.get_ovp(2):.4f},{self.ps.get_ocp(2):.4f}')

            # ── Measurements ──────────────────────────────────────────────
            if upper.startswith('MEAS:VOLT?'):
                return f'{self.ps.get_actual(int(_arg(cmd, 0)))["v"]:.4f}'

            if upper.startswith('MEAS:CURR?'):
                return f'{self.ps.get_actual(int(_arg(cmd, 0)))["i"]:.4f}'

            if upper.startswith('MEAS:ALL?'):
                d    = self.ps.get_actual(int(_arg(cmd, 0)))
                mode = 'CC' if d['CC'] else 'CV'
                trk  = '1' if d['tracking'] else '0'
                return (f'{d["v"]:.4f},{d["i"]:.4f},'
                        f'{"1" if d["on"] else "0"},{mode},{trk}')

            if upper == 'MEAS:BOTH?':
                # Both channels in one TCP round-trip — used by the Live shortcut
                # to halve the number of EEZ Studio connection.query() calls.
                d1, d2 = self.ps.get_actual_both()
                def _fmt(d: dict) -> str:
                    mode = 'CC' if d['CC'] else 'CV'
                    trk  = '1' if d['tracking'] else '0'
                    return (f'{d["v"]:.4f},{d["i"]:.4f},'
                            f'{"1" if d["on"] else "0"},{mode},{trk}')
                return f'{_fmt(d1)}|{_fmt(d2)}'

            if upper.startswith('STAT?'):
                d = self.ps.get_actual(int(_arg(cmd, 0)))
                return json.dumps(
                    {k: (f'{v:.4f}' if isinstance(v, float) else v)
                     for k, v in d.items()})

            if upper.startswith('SETP?'):
                d   = self.ps.get_setpoints(int(_arg(cmd, 0)))
                trk = '1' if d['tracking'] else '0'
                return (f'{d["v_set"]:.4f},{d["i_set"]:.4f},'
                        f'{"1" if d["on"] else "0"},{trk}')

            if upper == 'SETP:BOTH?':
                # Setpoints for both channels in one TCP round-trip.
                # Returns: v1_set,i1_set,on1,trk1|v2_set,i2_set,on2,trk2
                def _fmt_setp(d: dict) -> str:
                    trk = '1' if d['tracking'] else '0'
                    return (f'{d["v_set"]:.4f},{d["i_set"]:.4f},'
                            f'{"1" if d["on"] else "0"},{trk}')
                return f'{_fmt_setp(self.ps.get_setpoints(1))}|{_fmt_setp(self.ps.get_setpoints(2))}'

            if upper.startswith('VOLT:SET?'):
                return f'{self.ps.get_setpoints(int(_arg(cmd, 0)))["v_set"]:.4f}'

            if upper.startswith('CURR:SET?'):
                return f'{self.ps.get_setpoints(int(_arg(cmd, 0)))["i_set"]:.4f}'

            # ── Logging ───────────────────────────────────────────────────
            if upper.startswith('LOG:START'):
                rest  = cmd[len('LOG:START'):].strip().lstrip(',').lstrip()
                parts = [p.strip() for p in rest.split(',')]
                path  = os.path.normpath(parts[0])
                interv= float(parts[1]) if len(parts) > 1 and parts[1] else 0.5
                dur_s = parts[2] if len(parts) > 2 else ''
                dur   = float(dur_s) if dur_s and float(dur_s) > 0 else None
                chs   = [int(x) for x in parts[3:] if x.strip().isdigit()] or [1, 2]
                self.ps.start_logging(path, interv, chs, dur)
                return '0'

            if upper == 'LOG:STOP':
                self.ps.stop_logging()
                return '0'

            if upper == 'LOG:STATUS?':
                running = (self.ps._log_thread is not None
                           and self.ps._log_thread.is_alive())
                return '1' if running else '0'

            if upper == 'INFO?':
                return json.dumps(self.ps.get_info())

            return f'ERR:Unknown command "{cmd}"'

        except EaProtocolError as exc:
            return f'ERR:{exc}'
        except (IndexError, ValueError) as exc:
            return f'ERR:Bad arguments — {exc}'
        except Exception as exc:
            return f'ERR:{type(exc).__name__}: {exc}'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _args(cmd: str) -> list[str]:
    _, _, rest = cmd.partition(' ')
    return [a.strip() for a in rest.split(',')]

def _arg(cmd: str, index: int) -> str:
    return _args(cmd)[index]

def _on(s: str) -> bool:
    return s.strip().upper() in ('1', 'ON', 'TRUE', 'YES')


# ── TCP server ────────────────────────────────────────────────────────────────

def _handle_client(conn: socket.socket, addr: tuple, bridge: EaBridge):
    print(f'[Bridge] Client connected: {addr[0]}:{addr[1]}')
    # Disable Nagle so responses are flushed immediately (no batching delay).
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    buf = ''
    try:
        # 100 ms timeout: if a command arrives without a trailing \n (some SCPI
        # clients omit it), we dispatch via the timeout fallback after 100 ms
        # rather than the old 5 000 ms — which was the main cause of the
        # 6-second round-trip observed in EEZ Studio.
        conn.settimeout(0.1)
        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                if buf.strip():
                    with bridge.lock:
                        resp = bridge.dispatch(buf.strip())
                    buf = ''
                    if resp:
                        try:
                            conn.sendall((resp + '\n').encode('ascii'))
                        except OSError:
                            break
                continue
            if not chunk:
                break
            buf += chunk.decode('ascii', errors='ignore')
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip('\r').strip()
                if line:
                    with bridge.lock:
                        resp = bridge.dispatch(line)
                    if resp:
                        try:
                            conn.sendall((resp + '\n').encode('ascii'))
                        except OSError:
                            return
    except Exception as exc:
        print(f'[Bridge] Client {addr} error: {exc}')
    finally:
        try:
            conn.close()
        except OSError:
            pass
        print(f'[Bridge] Client disconnected: {addr[0]}:{addr[1]}')


def run_server(bridge: EaBridge, host: str, port: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    srv.settimeout(1.0)
    print(f'[Bridge] Listening on {host}:{port}')
    if host == '0.0.0.0':
        print(f'[Bridge] Accessible from LAN — ensure firewall allows port {port}')
    print('[Bridge] Press Ctrl-C to stop\n')
    try:
        while True:
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            t = threading.Thread(
                target=_handle_client, args=(conn, addr, bridge), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print('\n[Bridge] Ctrl-C received, shutting down...')
    finally:
        try:
            srv.close()
        except OSError:
            pass
        bridge.disconnect()
        print('[Bridge] Stopped.')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='TCP/SCPI bridge for EA-PS2000B power supply',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--serial', '-s', default='/dev/ea-ps2k-port', metavar='PORT',
        help='Serial port  (Linux: /dev/ea-ps2k-port  Windows: COM3)')
    parser.add_argument(
        '--tcp-port', '-p', type=int, default=5025, metavar='PORT',
        help='TCP port to listen on')
    parser.add_argument(
        '--host', default='0.0.0.0', metavar='ADDR',
        help='Bind address  (0.0.0.0 = all interfaces, 127.0.0.1 = local only)')
    args = parser.parse_args()

    print(f'[Bridge] EA-PS2000B TCP bridge  v{__version__}')
    print(f'[Bridge] Serial port  : {args.serial}')
    print(f'[Bridge] TCP address  : {args.host}:{args.tcp_port}')
    print()

    bridge = EaBridge(args.serial)
    bridge.connect()
    run_server(bridge, args.host, args.tcp_port)


if __name__ == '__main__':
    main()
