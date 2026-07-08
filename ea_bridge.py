"""
ea_bridge.py  —  TCP/SCPI bridge for EA-PS2000B series power supplies

Runs a TCP server on the configured address and port.
EEZ Studio (or any TCP client) connects and sends newline-terminated ASCII commands.

Deployment modes
────────────────
  Local workstation (Windows):
      python ea_bridge.py --serial COM3

  LAN server (RPi/Ubuntu) — binds to all interfaces so remote clients can connect:
      python ea_bridge.py --serial /dev/ttyACM0 --host 0.0.0.0 --tcp-port 5025

  The systemd service on the RPi starts this automatically at boot with the
  correct arguments. start_bridge.sh is a manual fallback for testing.

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

import argparse
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ea_ps2342 import EaPs2342, EaProtocolError


class EaBridge:
    def __init__(self, serial_port: str):
        self.ps   = EaPs2342(serial_port)
        self.lock = threading.Lock()
        self._idn = 'EA Elektro-Automatik,PS 2342-06B,000000,V0.00'

    def connect(self):
        import os, serial
        if not os.path.exists(self.ps.port_name):
            print(f'[Bridge] Device not found: {self.ps.port_name} — will retry', flush=True)
            raise SystemExit(1)
        try:
            self.ps.connect()
        except serial.SerialException as exc:
            print(f'[Bridge] Could not open {self.ps.port_name}: {exc} — will retry', flush=True)
            raise SystemExit(1)
        print(f'[Bridge] Connected to {self.ps.port_name}')
        try:
            info = self.ps.get_info()
            self._idn = (f'{info["manufacturer"]},{info["type"]},'
                         f'{info["serial"]},{info["version"]}')
            print(f'[Bridge] {info["type"]}  '
                  f'{info["nom_voltage"]:.0f} V / {info["nom_current"]:.0f} A  '
                  f'fw {info["version"]}')
        except EaProtocolError as exc:
            print(f'[Bridge] Warning: could not read device info: {exc}')

    def disconnect(self):
        self.ps.disconnect()

    def dispatch(self, raw: str) -> str:
        cmd   = raw.strip()
        upper = cmd.upper()
        if not cmd:
            return ''

        try:
            # ── Identification ────────────────────────────────────────────
            if upper == '*IDN?':
                return self._idn

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

            if upper.startswith('CONF:OUTP '):
                a = _args(cmd)
                self.ps.configure(int(a[0]), float(a[1]), float(a[2]), _on(a[3]))
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

            if upper.startswith('OCP '):
                a = _args(cmd)
                self.ps.set_ocp(int(a[0]), float(a[1]))
                return '0'

            if upper.startswith('OVP?'):
                return f'{self.ps.get_ovp(int(_arg(cmd, 0))):.4f}'

            if upper.startswith('OCP?'):
                return f'{self.ps.get_ocp(int(_arg(cmd, 0))):.4f}'

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
    buf = ''
    try:
        conn.settimeout(5.0)
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
        '--serial', '-s', default='/dev/ttyACM0', metavar='PORT',
        help='Serial port  (Linux: /dev/ttyACM0  Windows: COM3)')
    parser.add_argument(
        '--tcp-port', '-p', type=int, default=5025, metavar='PORT',
        help='TCP port to listen on')
    parser.add_argument(
        '--host', default='0.0.0.0', metavar='ADDR',
        help='Bind address  (0.0.0.0 = all interfaces, 127.0.0.1 = local only)')
    args = parser.parse_args()

    print(f'[Bridge] EA-PS2000B TCP bridge')
    print(f'[Bridge] Serial port  : {args.serial}')
    print(f'[Bridge] TCP address  : {args.host}:{args.tcp_port}')
    print()

    bridge = EaBridge(args.serial)
    bridge.connect()
    run_server(bridge, args.host, args.tcp_port)


if __name__ == '__main__':
    main()
