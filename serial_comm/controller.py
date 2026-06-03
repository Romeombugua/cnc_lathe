"""
Thread-safe singleton serial controller for GRBL-based Arduino CNC.

Usage
-----
from serial_comm.controller import serial_controller

serial_controller.connect('COM3', 115200)
serial_controller.send_gcode(['G21', 'G90', 'G00 X0 Z0', 'M30'], job_id=1)
serial_controller.emergency_stop()
"""
import threading
import time

try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False


class SerialController:
    """Singleton that owns the serial connection and job execution thread."""

    _instance = None
    _class_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialised = False
                    cls._instance = obj
        return cls._instance

    def __init__(self):
        if self._initialised:
            return
        self._initialised = True

        self._serial = None
        self._serial_lock = threading.Lock()

        # Machine state
        self._status = 'disconnected'   # disconnected | connected | running | error
        self._current_line = 0
        self._total_lines = 0
        self._position = {'X': 0.0, 'Z': 0.0}
        self._error_message = ''
        self._current_job_id = None

        # Job control
        self._stop_event = threading.Event()
        self._job_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_available_ports(self) -> list[dict]:
        if not _SERIAL_AVAILABLE:
            return []
        return [
            {'port': p.device, 'description': p.description}
            for p in serial.tools.list_ports.comports()
        ]

    def connect(self, port: str, baud_rate: int = 115200) -> tuple[bool, str]:
        if not _SERIAL_AVAILABLE:
            return False, 'PySerial is not installed. Run: pip install pyserial'

        with self._serial_lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            try:
                self._serial = serial.Serial(port, baud_rate, timeout=5)
                time.sleep(2)          # Wait for Arduino bootloader
                self._serial.reset_input_buffer()
                self._status = 'connected'
                self._error_message = ''
                return True, f'Connected to {port} at {baud_rate} baud'
            except Exception as exc:
                self._serial = None
                self._status = 'error'
                self._error_message = str(exc)
                return False, str(exc)

    def disconnect(self) -> tuple[bool, str]:
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = None
        self._status = 'disconnected'
        self._error_message = ''
        return True, 'Disconnected'

    def emergency_stop(self) -> bool:
        """Immediately halt all motion and cancel the running job."""
        self._stop_event.set()
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(b'\x18')   # GRBL soft-reset (Ctrl-X)
                    self._serial.flush()
                except Exception:
                    pass
        self._status = 'error'
        self._error_message = 'Emergency stop activated'
        return True

    def send_gcode(self, gcode_lines: list[str], job_id: int | None = None) -> tuple[bool, str]:
        if self._status == 'disconnected':
            return False, 'Machine is not connected'
        if self._job_thread and self._job_thread.is_alive():
            return False, 'A job is already running'

        self._stop_event.clear()
        self._current_line = 0
        self._total_lines = len(
            [l for l in gcode_lines if l.strip() and not l.strip().startswith(';')]
        )
        self._current_job_id = job_id

        self._job_thread = threading.Thread(
            target=self._execute_gcode,
            args=(gcode_lines,),
            daemon=True,
        )
        self._job_thread.start()
        return True, 'Job started'

    def get_status(self) -> dict:
        return {
            'status': self._status,
            'current_line': self._current_line,
            'total_lines': self._total_lines,
            'position': dict(self._position),
            'error_message': self._error_message,
            'current_job_id': self._current_job_id,
        }

    def is_connected(self) -> bool:
        with self._serial_lock:
            return self._serial is not None and self._serial.is_open

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _execute_gcode(self, gcode_lines: list[str]) -> None:
        # Import Django models inside the thread (always called after app ready)
        from jobs.models import Job
        from machine.models import MachineLog
        from django.utils import timezone

        self._status = 'running'
        executable_index = 0

        for raw_line in gcode_lines:
            if self._stop_event.is_set():
                self._status = 'error'
                self._error_message = 'Job stopped by user'
                self._update_job_status('stopped')
                return

            line = raw_line.strip()
            if not line or line.startswith(';'):
                continue

            # --- Send line ---
            with self._serial_lock:
                if not (self._serial and self._serial.is_open):
                    self._status = 'error'
                    self._error_message = 'Serial connection lost'
                    self._update_job_status('failed')
                    return
                try:
                    self._serial.write((line + '\n').encode())
                    self._serial.flush()
                except Exception as exc:
                    self._status = 'error'
                    self._error_message = f'Serial write error: {exc}'
                    self._update_job_status('failed')
                    return

            # --- Wait for 'ok' acknowledgement ---
            # Synchronized M-codes (M05, M30) wait for all buffered motion to
            # complete before GRBL responds, so they need a much longer timeout.
            upper = line.upper()
            is_sync = any(code in upper for code in ('M05', 'M30', 'M00', 'M01', 'M02'))
            timeout_s = 300 if is_sync else 30
            deadline = time.monotonic() + timeout_s
            while True:
                if self._stop_event.is_set():
                    self._status = 'error'
                    self._error_message = 'Job stopped by user'
                    self._update_job_status('stopped')
                    return

                if time.monotonic() > deadline:
                    self._status = 'error'
                    self._error_message = f'Timeout waiting for GRBL response on: {line}'
                    self._update_job_status('failed')
                    return

                with self._serial_lock:
                    if self._serial and self._serial.in_waiting:
                        response = self._serial.readline().decode('utf-8', errors='replace').strip()
                        if response == 'ok':
                            break
                        if response.startswith('error'):
                            self._status = 'error'
                            self._error_message = f'GRBL error on line "{line}": {response}'
                            self._update_job_status('failed')
                            return
                        if response.startswith('<'):
                            self._parse_status_report(response)

                time.sleep(0.01)

            executable_index += 1
            self._current_line = executable_index

        # Job finished normally
        self._status = 'connected'
        self._update_job_status('completed')
        try:
            MachineLog.objects.create(
                event_type='job_complete',
                message=f'Job #{self._current_job_id} completed successfully',
            )
        except Exception:
            pass

    def _update_job_status(self, status: str) -> None:
        try:
            from jobs.models import Job
            from django.utils import timezone
            if self._current_job_id:
                job = Job.objects.get(id=self._current_job_id)
                job.execution_status = status
                if status == 'completed':
                    job.completed_at = timezone.now()
                elif self._error_message:
                    job.error_message = self._error_message
                job.save()
        except Exception:
            pass

    def _parse_status_report(self, report: str) -> None:
        """Parse a GRBL status report like <Idle|MPos:1.000,2.000,3.000|...>."""
        try:
            if 'MPos:' in report:
                mpos = report.split('MPos:')[1].split('|')[0]
                coords = mpos.split(',')
                self._position['X'] = float(coords[0])
                # On a lathe the Z axis is coords[2] (GRBL uses X,Y,Z order)
                self._position['Z'] = float(coords[2]) if len(coords) > 2 else 0.0
        except Exception:
            pass


# Module-level singleton
serial_controller = SerialController()
