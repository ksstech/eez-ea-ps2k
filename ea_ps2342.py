"""
ea_ps2342.py  —  Driver for EA-PS2000B series power supplies (binary protocol)

Supports all EA-PS2000B Triple models:
  EA-PS2342-06B  42 V / 6 A      EA-PS2342-10B  42 V / 10 A
  EA-PS2384-05B  84 V / 5 A      EA-PS2384-20B  84 V / 20 A
  (nominal values read automatically from device at connect time)

Triple model layout:
  CH1 (DN=0) — variable output, remotely controllable
  CH2 (DN=1) — variable output, remotely controllable
  CH3        — fixed 5 V, NO remote interface (hardware limitation)

Tracking mode:
  When enabled, CH2 mirrors CH1 voltage and current.
  Setting CH2 while tracking is active raises EaProtocolError.

Protocol: PS 2000 B Programming Guide, 2014
Requires: pip install pyserial

Platform: Linux (Ubuntu/Raspberry Pi OS), macOS, Windows
"""

import csv
import os
import struct
import threading
import time
from datetime import datetime

import serial


# ── Protocol constants ────────────────────────────────────────────────────────

_PS_QUERY  = 0x40   # query type  (bits 7-6 = 01)
_PS_SEND   = 0xC0   # send type   (bits 7-6 = 11)
_BASE_SD   = 0x30   # broadcast(0x20) + from-PC(0x10)
_MIN_DELAY = 0.055  # 55 ms — spec requires 50 ms minimum between commands

# Object numbers (programming guide section 3.8)
_OBJ_TYPE        = 0x00
_OBJ_SERIAL      = 0x01
_OBJ_NOM_VOLTAGE = 0x02
_OBJ_NOM_CURRENT = 0x03
_OBJ_NOM_POWER   = 0x04
_OBJ_ARTICLE     = 0x06
_OBJ_MANUF       = 0x08
_OBJ_VERSION     = 0x09
_OBJ_OVP         = 0x26
_OBJ_OCP         = 0x27
_OBJ_SET_VOLTAGE = 0x32
_OBJ_SET_CURRENT = 0x33
_OBJ_CONTROL     = 0x36  # bits: 0=output, 1=tracking, 4=remote
_OBJ_ACTUAL      = 0x47  # status1, status2, V_hi, V_lo, I_hi, I_lo
_OBJ_SETPOINTS   = 0x48

_SCALE = 25600.0

# Control byte bit masks
_MASK_OUTPUT   = 0x01
_MASK_TRACKING = 0x02
_MASK_REMOTE   = 0x10

# Status byte 2 bits
_S2_OUTPUT   = 0x01
_S2_CC       = 0x06
_S2_OVP      = 0x10
_S2_OCP      = 0x20
_S2_OPP      = 0x40
_S2_OTP      = 0x80

# Status byte 1 bits
_S1_REMOTE   = 0x03
_S1_TRACKING = 0x02   # bit 1 of status byte 1 reflects tracking state

_ERROR_CODES = {
    0x00: 'No error',
    0x03: 'Checksum incorrect',
    0x04: 'Start delimiter incorrect',
    0x05: 'Wrong address for output',
    0x07: 'Object not defined',
    0x08: 'Object length incorrect',
    0x09: 'Access denied (read-only or not in remote mode)',
    0x0F: 'Device locked — not in remote mode',
    0x30: 'Upper limit exceeded',
    0x31: 'Lower limit exceeded',
}


class EaProtocolError(Exception):
    """Device returned a non-zero error code or a protocol violation occurred."""


class EaPs2342:
    """
    Driver for EA-PS2000B Triple series power supplies.

    Channel mapping:
        channel=1  →  device node DN=0
        channel=2  →  device node DN=1
        channel=3  →  fixed 5 V, not accessible via protocol

    Tracking:
        When tracking is enabled via set_tracking(True), CH2 mirrors CH1.
        Any attempt to set CH2 voltage, current, or output while tracking
        is active raises EaProtocolError with a clear message.
    """

    def __init__(self, port: str = '/dev/ttyACM0', timeout: float = 0.5):
        """
        Parameters
        ----------
        port    : Serial port.
                  Linux/RPi:  '/dev/ttyACM0'  or  '/dev/ttyUSB0'
                  macOS:      '/dev/cu.usbmodem...'
                  Windows:    'COM3'  (or '\\\\.\\COM12' for ports above COM9)
        timeout : Serial read timeout in seconds.
        """
        self.port_name = port
        self.timeout   = timeout
        self._ser: serial.Serial | None = None
        self._lock     = threading.Lock()
        self._last_tx  = 0.0

        # Nominal values — overwritten at connect() from device query
        self._u_nom: dict[int, float] = {1: 42.0, 2: 42.0}
        self._i_nom: dict[int, float] = {1: 6.0,  2: 6.0}

        # Tracking state cache — updated by set_tracking() and get_actual()
        self._tracking: bool = False

        # Logging state
        self._log_thread: threading.Thread | None = None
        self._log_stop   = threading.Event()
        self._log_fd     = None
        self._log_writer = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> 'EaPs2342':
        """
        Open serial port and read nominal V/I from the device.
        Serial parameters fixed by firmware: 115200, 8, odd, 1.
        """
        port = self.port_name
        # Windows COM>9 needs the \\\\.\\COMx prefix
        if (port.upper().startswith('COM')
                and port[3:].isdigit()
                and int(port[3:]) > 9):
            port = r'\\.\COM' + port[3:]

        self._ser = serial.Serial(
            port     = port,
            baudrate = 115200,
            bytesize = serial.EIGHTBITS,
            parity   = serial.PARITY_ODD,
            stopbits = serial.STOPBITS_ONE,
            timeout  = self.timeout,
            xonxoff  = False,
            rtscts   = False,
            dsrdtr   = False,
        )
        time.sleep(0.1)

        u = self._get_float(1, _OBJ_NOM_VOLTAGE)
        i = self._get_float(1, _OBJ_NOM_CURRENT)
        self._u_nom[1] = self._u_nom[2] = u
        self._i_nom[1] = self._i_nom[2] = i
        return self

    def disconnect(self):
        """Stop logging, exit remote mode on both channels, close port."""
        self.stop_logging()
        for ch in (1, 2):
            try:
                self._set_remote(ch, False)
            except Exception:
                pass
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    def __enter__(self) -> 'EaPs2342':
        self.connect()
        self._set_remote(1, True)
        self._set_remote(2, True)
        return self

    def __exit__(self, *_):
        self.disconnect()

    @property
    def is_connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    # ── Telegram layer ────────────────────────────────────────────────────────

    @staticmethod
    def _build(msg_type: int, node: int, obj: int, data: bytes) -> bytes:
        sd = _BASE_SD + msg_type + (max(0, len(data) - 1) if data else 0)
        frame = bytearray([sd, node, obj]) + bytearray(data)
        cs = sum(frame) & 0xFFFF
        frame += bytes([cs >> 8, cs & 0xFF])
        return bytes(frame)

    @staticmethod
    def _validate(resp: bytes) -> bytes:
        if len(resp) < 5:
            raise EaProtocolError(
                f'Response too short ({len(resp)} bytes): {resp.hex().upper()}')
        cs_calc = sum(resp[:-2]) & 0xFFFF
        cs_recv = (resp[-2] << 8) | resp[-1]
        if cs_calc != cs_recv:
            raise EaProtocolError(
                f'Checksum mismatch: expected {cs_calc:04X} got {cs_recv:04X}')
        if resp[2] == 0xFF:
            code = resp[3] if len(resp) > 3 else 0xFF
            if code != 0x00:
                raise EaProtocolError(
                    _ERROR_CODES.get(code, f'Device error 0x{code:02X}'))
        return bytes(resp[3:-2])

    def _transfer(self, msg_type: int, channel: int,
                  obj: int, data: bytes) -> bytes:
        if not self.is_connected:
            raise EaProtocolError('Not connected')
        node  = channel - 1
        frame = self._build(msg_type, node, obj, data)
        with self._lock:
            wait = _MIN_DELAY - (time.monotonic() - self._last_tx)
            if wait > 0:
                time.sleep(wait)
            self._ser.reset_input_buffer()
            self._ser.write(frame)
            self._last_tx = time.monotonic()
            resp = self._ser.read(32)
        return self._validate(resp)

    # ── Typed accessors ───────────────────────────────────────────────────────

    def _get_string(self, ch: int, obj: int) -> str:
        return self._transfer(_PS_QUERY, ch, obj, b'') \
                   .rstrip(b'\x00').decode('ascii', errors='replace').strip()

    def _get_float(self, ch: int, obj: int) -> float:
        return struct.unpack('>f', self._transfer(_PS_QUERY, ch, obj, b'')[:4])[0]

    def _get_int(self, ch: int, obj: int) -> int:
        p = self._transfer(_PS_QUERY, ch, obj, b'')
        return (p[0] << 8) | p[1]

    def _set_int(self, ch: int, obj: int, value: int):
        self._transfer(_PS_SEND, ch, obj, bytes([value >> 8, value & 0xFF]))

    def _set_ctrl(self, ch: int, mask: int, ctrl: int):
        self._transfer(_PS_SEND, ch, _OBJ_CONTROL, bytes([mask, ctrl]))

    # ── Remote mode ───────────────────────────────────────────────────────────

    def _set_remote(self, ch: int, on: bool):
        self._set_ctrl(ch, _MASK_REMOTE, _MASK_REMOTE if on else 0x00)

    def ensure_remote(self, ch: int):
        self._set_remote(ch, True)

    # ── Tracking ──────────────────────────────────────────────────────────────

    def set_tracking(self, on: bool):
        """
        Enable or disable output tracking (CH2 mirrors CH1).

        When tracking is on:
          - CH2 voltage and current automatically follow CH1
          - Any attempt to set CH2 independently raises EaProtocolError
          - Only set_voltage/current/output on CH1

        Parameters
        ----------
        on : True to enable tracking, False to disable
        """
        self.ensure_remote(1)
        self._set_ctrl(1, _MASK_TRACKING, _MASK_TRACKING if on else 0x00)
        self._tracking = on

    def get_tracking(self) -> bool:
        """
        Query current tracking state from the device.
        Also updates the internal cache used by set_voltage/current guards.
        """
        d = self.get_actual(1)
        self._tracking = d.get('tracking', False)
        return self._tracking

    def _check_tracking_block(self, channel: int, operation: str):
        """
        Raise EaProtocolError if channel 2 is blocked by active tracking.
        Uses cached state — call get_tracking() first if you need a live check.
        """
        if channel == 2 and self._tracking:
            raise EaProtocolError(
                f'CH2 is in tracking mode — {operation} on CH1 only, '
                f'or disable tracking first with set_tracking(False)')

    # ── Voltage / current / output ────────────────────────────────────────────

    def set_voltage(self, channel: int, volts: float):
        """Set output voltage. Raises EaProtocolError if CH2 tracking is active."""
        self._check_channel(channel)
        self._check_tracking_block(channel, 'set voltage')
        raw = self._to_raw(volts, self._u_nom[channel])
        self.ensure_remote(channel)
        self._set_int(channel, _OBJ_SET_VOLTAGE, raw)

    def set_current(self, channel: int, amps: float):
        """Set current limit. Raises EaProtocolError if CH2 tracking is active."""
        self._check_channel(channel)
        self._check_tracking_block(channel, 'set current limit')
        raw = self._to_raw(amps, self._i_nom[channel])
        self.ensure_remote(channel)
        self._set_int(channel, _OBJ_SET_CURRENT, raw)

    def set_output(self, channel: int, on: bool):
        """Enable/disable output. Raises EaProtocolError if CH2 tracking is active."""
        self._check_channel(channel)
        self._check_tracking_block(channel, 'set output')
        self.ensure_remote(channel)
        self._set_ctrl(channel, _MASK_OUTPUT, _MASK_OUTPUT if on else 0x00)

    def configure(self, channel: int, volts: float, amps: float,
                  output_on: bool = True):
        """
        One-call: set voltage, current limit, and output state.

        Sequence per programming guide section 3.5:
          1. Remote ON (must be active before any set value)
          2. Voltage setpoint
          3. Current limit setpoint
          4. Output ON/OFF (separate object 54 call)

        If output_on is True but volts is 0, output is left OFF —
        the device rejects enabling output with a 0 V setpoint.
        """
        self._check_channel(channel)
        # Step 1: explicitly enable remote on this channel first
        # Then wait one full inter-command cycle before proceeding
        self._set_remote(channel, True)
        time.sleep(_MIN_DELAY)

        # Step 2+3: voltage then current
        self._check_tracking_block(channel, 'configure')
        raw_v = self._to_raw(volts, self._u_nom[channel])
        self._set_int(channel, _OBJ_SET_VOLTAGE, raw_v)
        raw_i = self._to_raw(amps, self._i_nom[channel])
        self._set_int(channel, _OBJ_SET_CURRENT, raw_i)

        # Step 4: output state (0V guard)
        if output_on and volts == 0.0:
            # Cannot enable output with 0 V setpoint
            self._set_ctrl(channel, _MASK_OUTPUT, 0x00)
        else:
            self._set_ctrl(channel, _MASK_OUTPUT,
                           _MASK_OUTPUT if output_on else 0x00)

    def set_ovp(self, channel: int, volts: float):
        self._check_channel(channel)
        self.ensure_remote(channel)
        self._set_int(channel, _OBJ_OVP, self._to_raw(volts, self._u_nom[channel]))

    def set_ocp(self, channel: int, amps: float):
        self._check_channel(channel)
        self.ensure_remote(channel)
        self._set_int(channel, _OBJ_OCP, self._to_raw(amps, self._i_nom[channel]))

    def get_ovp(self, channel: int) -> float:
        self._check_channel(channel)
        return self._from_raw(self._get_int(channel, _OBJ_OVP), self._u_nom[channel])

    def get_ocp(self, channel: int) -> float:
        self._check_channel(channel)
        return self._from_raw(self._get_int(channel, _OBJ_OCP), self._i_nom[channel])

    # ── Readback ──────────────────────────────────────────────────────────────

    def get_actual(self, channel: int) -> dict:
        """
        Read measured values and status from channel.

        Returns dict:
            v        : float — actual voltage (V)
            i        : float — actual current draw (A)
            on       : bool  — output enabled
            CC       : bool  — constant-current mode active
            CV       : bool  — constant-voltage mode active
            remote   : bool  — remote control active
            tracking : bool  — tracking mode active (CH2 mirrors CH1)
            OVP      : bool  — over-voltage protection triggered
            OCP      : bool  — over-current protection triggered
            OPP      : bool  — over-power protection triggered
            OTP      : bool  — over-temperature protection triggered
        """
        self._check_channel(channel)
        p  = self._transfer(_PS_QUERY, channel, _OBJ_ACTUAL, b'')
        s1, s2   = p[0], p[1]
        v_raw    = (p[2] << 8) | p[3]
        i_raw    = (p[4] << 8) | p[5]
        tracking = bool(s1 & _S1_TRACKING)
        self._tracking = tracking   # keep cache in sync
        return {
            'v':        self._from_raw(v_raw, self._u_nom[channel]),
            'i':        self._from_raw(i_raw, self._i_nom[channel]),
            'on':       bool(s2 & _S2_OUTPUT),
            'CC':       bool(s2 & _S2_CC),
            'CV':       not bool(s2 & _S2_CC),
            'remote':   bool(s1 & _S1_REMOTE),
            'tracking': tracking,
            'OVP':      bool(s2 & _S2_OVP),
            'OCP':      bool(s2 & _S2_OCP),
            'OPP':      bool(s2 & _S2_OPP),
            'OTP':      bool(s2 & _S2_OTP),
        }

    def get_setpoints(self, channel: int) -> dict:
        """Read programmed setpoints and status (object 0x48)."""
        self._check_channel(channel)
        p     = self._transfer(_PS_QUERY, channel, _OBJ_SETPOINTS, b'')
        v_raw = (p[2] << 8) | p[3]
        i_raw = (p[4] << 8) | p[5]
        return {
            'v_set':    self._from_raw(v_raw, self._u_nom[channel]),
            'i_set':    self._from_raw(i_raw, self._i_nom[channel]),
            'on':       bool(p[1] & _MASK_OUTPUT),
            'remote':   bool(p[0] & _S1_REMOTE),
            'tracking': bool(p[0] & _S1_TRACKING),
        }

    def get_info(self) -> dict:
        """Read device identification (queries node 0 — global objects)."""
        return {
            'type':         self._get_string(1, _OBJ_TYPE),
            'serial':       self._get_string(1, _OBJ_SERIAL),
            'article':      self._get_string(1, _OBJ_ARTICLE),
            'manufacturer': self._get_string(1, _OBJ_MANUF),
            'version':      self._get_string(1, _OBJ_VERSION),
            'nom_voltage':  self._u_nom[1],
            'nom_current':  self._i_nom[1],
        }

    # ── CSV logging ───────────────────────────────────────────────────────────

    def start_logging(self, filepath: str, interval: float = 0.5,
                      channels: list | None = None,
                      duration: float | None = None):
        """
        Start background CSV logging of actual V, I, mode, and status.

        Parameters
        ----------
        filepath : output CSV path. Use forward slashes on all platforms.
        interval : sample interval in seconds (minimum ~0.12 s for two channels)
        channels : channel numbers to log (default [1, 2])
        duration : stop automatically after this many seconds (None = manual stop)
        """
        if channels is None:
            channels = [1, 2]

        min_interval = _MIN_DELAY * 2 * len(channels)
        if interval < min_interval:
            interval = min_interval
            print(f'[EA Logger] Interval raised to {interval:.2f}s')

        if self._log_thread and self._log_thread.is_alive():
            raise RuntimeError('Logging already running — call stop_logging() first')

        self._log_stop.clear()
        filepath = os.path.normpath(filepath)
        write_header = not os.path.exists(filepath)

        self._log_fd = open(filepath, 'a', newline='', encoding='utf-8')
        self._log_writer = csv.writer(self._log_fd)

        if write_header:
            header = ['timestamp', 'elapsed_s']
            for ch in channels:
                header += [f'ch{ch}_v', f'ch{ch}_i', f'ch{ch}_on',
                           f'ch{ch}_mode', f'ch{ch}_tracking']
            self._log_writer.writerow(header)
            self._log_fd.flush()

        self._log_thread = threading.Thread(
            target  = self._log_worker,
            args    = (channels, interval, duration),
            daemon  = True,
            name    = 'EaPs2342Logger',
        )
        self._log_thread.start()
        print(f'[EA Logger] Started → {filepath}  '
              f'interval={interval:.2f}s  channels={channels}'
              + (f'  duration={duration:.0f}s' if duration else '  (manual stop)'))

    def stop_logging(self):
        """Signal the logging thread to stop and wait up to 5 seconds."""
        if self._log_thread and self._log_thread.is_alive():
            self._log_stop.set()
            self._log_thread.join(timeout=5.0)
        if self._log_fd:
            try:
                self._log_fd.close()
            except Exception:
                pass
        self._log_fd     = None
        self._log_writer = None
        self._log_thread = None
        print('[EA Logger] Stopped')

    def _log_worker(self, channels: list, interval: float,
                    duration: float | None):
        t_start = time.monotonic()
        try:
            while not self._log_stop.is_set():
                elapsed = time.monotonic() - t_start
                if duration is not None and elapsed >= duration:
                    break
                ts  = datetime.now().isoformat(timespec='milliseconds')
                row = [ts, f'{elapsed:.3f}']
                for ch in channels:
                    try:
                        d    = self.get_actual(ch)
                        mode = 'CC' if d['CC'] else 'CV'
                        trk  = '1' if d['tracking'] else '0'
                        row += [f'{d["v"]:.4f}', f'{d["i"]:.4f}',
                                '1' if d['on'] else '0', mode, trk]
                    except Exception as exc:
                        row += ['ERR', 'ERR', 'ERR', str(exc)[:30], 'ERR']
                if self._log_writer:
                    self._log_writer.writerow(row)
                    self._log_fd.flush()
                t_next = time.monotonic() + interval
                while time.monotonic() < t_next and not self._log_stop.is_set():
                    time.sleep(0.05)
        except Exception as exc:
            print(f'[EA Logger] Fatal error: {exc}')
        finally:
            self._log_stop.set()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_raw(value: float, nominal: float) -> int:
        return max(0, min(int(_SCALE), int(round(value * _SCALE / nominal))))

    @staticmethod
    def _from_raw(raw: int, nominal: float) -> float:
        return nominal * raw / _SCALE

    @staticmethod
    def _check_channel(channel: int):
        if channel not in (1, 2):
            raise ValueError(
                f'Channel must be 1 or 2 (got {channel!r}). '
                'CH3 is fixed 5 V with no remote interface.')
