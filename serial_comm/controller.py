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

        # GRBL live state (updated by background poll and status reports)
        self._grbl_state = 'Unknown'
        self._mpos = {'X': 0.0, 'Y': 0.0}
        self._wpos = {'X': 0.0, 'Y': 0.0}
        self._feed = 0.0
        self._speed = 0
        self._dry_run = True   # Always ON after connection/homing
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

        # Phase completion flags (persistent across page refreshes)
        self._homed = False
        self._synced = False

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
                # Send session-start coordinate resets (best-effort)
                try:
                    for cmd in (b'G92.1\n', b'G49\n'):
                        self._serial.write(cmd)
                        self._serial.flush()
                        time.sleep(0.05)
                    self._serial.reset_input_buffer()
                except Exception:
                    pass
                self._status = 'connected'
                self._dry_run = True
                self._error_message = ''
                self._homed = False
                self._synced = False
                # Start background GRBL status polling
                self._poll_stop.clear()
                self._poll_thread = threading.Thread(
                    target=self._poll_loop, daemon=True
                )
                self._poll_thread.start()
                return True, f'Connected to {port} at {baud_rate} baud'
            except Exception as exc:
                self._serial = None
                self._status = 'error'
                self._error_message = str(exc)
                return False, str(exc)

    def disconnect(self) -> tuple[bool, str]:
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        self._poll_thread = None
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = None
        self._status = 'disconnected'
        self._homed = False
        self._synced = False
        self._grbl_state = 'Unknown'
        self._mpos = {'X': 0.0, 'Y': 0.0}
        self._wpos = {'X': 0.0, 'Y': 0.0}
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

    def cancel_job(self) -> tuple[bool, str]:
        """Cancel the currently running job and reset controller state to connected."""
        if self._status not in ('running', 'error'):
            return False, 'No active job to cancel'
        self._stop_event.set()
        # Give the execute thread up to 1 s to notice
        if self._job_thread and self._job_thread.is_alive():
            self._job_thread.join(timeout=1.0)
        # Force-mark DB record if thread didn't get there
        if self._current_job_id:
            try:
                from jobs.models import Job
                job = Job.objects.get(id=self._current_job_id)
                if job.execution_status in ('running', 'pending'):
                    job.execution_status = 'stopped'
                    job.error_message = 'Cancelled by operator'
                    job.save()
            except Exception:
                pass
        self._status = 'connected'
        self._error_message = ''
        self._current_job_id = None
        self._current_line = 0
        self._total_lines = 0
        self._stop_event.clear()
        return True, 'Job cancelled'

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
            'grbl_state': self._grbl_state,
            'mpos': dict(self._mpos),
            'wpos': dict(self._wpos),
            'feed': self._feed,
            'speed': self._speed,
            'dry_run': self._dry_run,
            'homed': self._homed,
            'synced': self._synced,
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

            # Dry-run mode: suppress spindle-on commands
            first_word = line.split()[0].upper() if line.split() else ''
            if self._dry_run and first_word in ('M3', 'M03', 'M4', 'M04'):
                executable_index += 1
                self._current_line = executable_index
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
            # M03/M04 (spindle on/speed change) are synchronising: GRBL drains the
            # motion buffer before changing speed and sending ok, so they need the
            # same generous timeout as M05/M30.
            upper = line.upper()
            is_sync = any(code in upper for code in ('M03', 'M3', 'M04', 'M4', 'M05', 'M30', 'M00', 'M01', 'M02'))
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
                        # GRBL reset banner — controller was physically reset
                        if response.lower().startswith('grbl'):
                            self._status = 'error'
                            self._error_message = 'GRBL controller was reset mid-job'
                            self._update_job_status('stopped')
                            return
                        # ALARM state — e.g. limit switch triggered
                        if response.startswith('ALARM'):
                            self._status = 'error'
                            self._error_message = f'GRBL ALARM: {response}'
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
        """Parse a GRBL status report: <State|MPos:x,y,z|WPos:x,y,z|FS:f,s>"""
        try:
            inner = report.strip('<>').split('|')
            if inner:
                self._grbl_state = inner[0]
            for part in inner[1:]:
                if part.startswith('MPos:'):
                    coords = part[5:].split(',')
                    x = float(coords[0]) if len(coords) > 0 else 0.0
                    y = float(coords[1]) if len(coords) > 1 else 0.0
                    self._mpos = {'X': x, 'Y': y}
                    # Legacy position field for backward compatibility
                    self._position['X'] = x
                    self._position['Z'] = y
                elif part.startswith('WPos:'):
                    coords = part[5:].split(',')
                    self._wpos = {
                        'X': float(coords[0]) if len(coords) > 0 else 0.0,
                        'Y': float(coords[1]) if len(coords) > 1 else 0.0,
                    }
                elif part.startswith('FS:'):
                    fs = part[3:].split(',')
                    self._feed = float(fs[0]) if len(fs) > 0 else 0.0
                    self._speed = int(float(fs[1])) if len(fs) > 1 else 0
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Phase control methods (spec §4.2)
    # ------------------------------------------------------------------

    def home(self) -> tuple[bool, str]:
        """Phase I: start GRBL homing cycle ($H) in a background thread."""
        if self._status == 'disconnected':
            return False, 'Machine is not connected'
        if self._job_thread and self._job_thread.is_alive():
            return False, 'Another operation is in progress'
        self._stop_event.clear()
        self._status = 'homing'
        self._error_message = ''
        self._job_thread = threading.Thread(target=self._run_home, daemon=True)
        self._job_thread.start()
        return True, 'Homing cycle started'

    def _run_home(self) -> None:
        """Background thread: send $H and wait for GRBL to report ok."""
        from machine.models import MachineLog
        with self._serial_lock:
            if not (self._serial and self._serial.is_open):
                self._status = 'error'
                self._error_message = 'Serial connection lost'
                return
            try:
                self._serial.write(b'$H\n')
                self._serial.flush()
            except Exception as exc:
                self._status = 'error'
                self._error_message = str(exc)
                return
        deadline = time.monotonic() + 120   # 2-minute homing timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                self._status = 'error'
                self._error_message = 'Homing stopped by user'
                return
            with self._serial_lock:
                if self._serial and self._serial.in_waiting:
                    response = self._serial.readline().decode('utf-8', errors='replace').strip()
                    if response == 'ok':
                        # Send $X to clear any lingering alarm state before
                        # marking homing complete (some GRBL configs need this)
                        try:
                            self._serial.write(b'$X\n')
                            self._serial.flush()
                            time.sleep(0.1)
                            self._serial.reset_input_buffer()
                        except Exception:
                            pass
                        self._status = 'connected'
                        self._homed = True
                        self._dry_run = True   # Always reset dry-run after homing
                        self._grbl_state = 'Idle'
                        try:
                            MachineLog.objects.create(
                                event_type='connection',
                                message='Homing cycle completed — axes at reference position',
                            )
                        except Exception:
                            pass
                        return
                    if response.startswith('ALARM') or response.startswith('error'):
                        self._status = 'error'
                        self._error_message = f'Homing failed: {response}'
                        return
                    if response.startswith('<'):
                        self._parse_status_report(response)
            time.sleep(0.05)
        self._status = 'error'
        self._error_message = 'Homing cycle timed out'

    def jog(self, axis: str, direction: int, distance: float, feed: float = 200.0) -> tuple[bool, str]:
        """
        Move one step using incremental G-code (G91 → G01 → G90).
        Compatible with all GRBL versions — avoids the $J= jog command
        which some GRBL builds reject with error:3.
        """
        if self._status not in ('connected',):
            return False, 'Machine must be idle and connected to jog'
        if self._job_thread and self._job_thread.is_alive():
            return False, 'Cannot jog while a job is running'
        axis = axis.upper()
        if axis not in ('X', 'Y'):
            return False, f'Unknown axis: {axis}'
        signed_dist = direction * abs(distance)
        # Three-line sequence: switch to incremental, move, restore absolute
        cmds = [
            b'G91\n',
            f'G01 {axis}{signed_dist:.3f} F{feed:.0f}\n'.encode(),
            b'G90\n',
        ]
        with self._serial_lock:
            if not (self._serial and self._serial.is_open):
                return False, 'Serial connection lost'
            for cmd in cmds:
                try:
                    self._serial.write(cmd)
                    self._serial.flush()
                except Exception as exc:
                    return False, str(exc)
                # Wait for 'ok' after each line
                deadline = time.monotonic() + 0.5
                while time.monotonic() < deadline:
                    if self._serial.in_waiting:
                        try:
                            resp = self._serial.readline().decode('utf-8', errors='replace').strip()
                        except Exception as exc:
                            return False, str(exc)
                        if resp == 'ok':
                            break
                        if resp.startswith('error'):
                            # Always restore absolute mode before returning
                            try:
                                self._serial.write(b'G90\n')
                                self._serial.flush()
                            except Exception:
                                pass
                            return False, f'GRBL rejected jog: {resp}'
                        if resp.startswith('<'):
                            continue   # status report — ignore
                    time.sleep(0.005)
        return True, f'Jogged {axis} {signed_dist:+.3f} mm'

    def cancel_jog(self) -> None:
        """Send GRBL jog-cancel byte (0x85) to stop a jog in progress."""
        with self._serial_lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.write(b'\x85')
                    self._serial.flush()
                except Exception:
                    pass

    def set_work_origin_and_retract(self, approach_x: float = 15.0) -> tuple[bool, str]:
        """
        Touch-off: set Y=0 at the current tool position (front face of workpiece),
        set the fixed X spindle-centre offset, activate G54, then retract to a
        safe staging position clear of the stock.

        The operator must manually jog the tool to the front face before calling
        this method.  approach_x should be stock_radius + 6 mm.
        """
        if self._status == 'disconnected':
            return False, 'Machine is not connected'
        if self._job_thread and self._job_thread.is_alive():
            return False, 'Another operation is in progress'
        lines = [
            'G10 L2 P1 X-69.000',          # Fix X work offset (spindle-centre alignment)
            'G10 L20 P1 Y0',                # Zero Y at current tool position (front face)
            'G54',                           # Activate G54 work coordinate system
            f'G00 X{approach_x:.3f} Y5.000',  # Retract: clearance X, 5 mm in front of face
        ]
        self._stop_event.clear()
        self._status = 'syncing'
        self._error_message = ''
        self._job_thread = threading.Thread(
            target=self._run_command_sequence,
            args=(lines, 'Work origin set at front face — tool retracted to safe position'),
            kwargs={'flag_synced': True},
            daemon=True,
        )
        self._job_thread.start()
        return True, 'Setting work origin and retracting…'

    def sync_workpiece(self, l_stickout: float) -> tuple[bool, str]:
        """Legacy automatic sync (kept for backward compatibility — prefer set_work_origin_and_retract)."""
        if self._status == 'disconnected':
            return False, 'Machine is not connected'
        if self._job_thread and self._job_thread.is_alive():
            return False, 'Another operation is in progress'
        work_y_offset = -120.0 + l_stickout
        lines = [
            f'G10 L2 P1 X-69.000 Y{work_y_offset:.3f}',
            'G54',
            'G00 X15.000 Y5.000',
        ]
        self._stop_event.clear()
        self._status = 'syncing'
        self._error_message = ''
        self._job_thread = threading.Thread(
            target=self._run_command_sequence,
            args=(lines, 'Workpiece synchronised — tool at safe staging position'),
            kwargs={'flag_synced': True},
            daemon=True,
        )
        self._job_thread.start()
        return True, 'Workpiece synchronisation started'

    def _run_command_sequence(self, lines: list[str], success_msg: str, flag_synced: bool = False) -> None:
        """Background thread: send G-code lines and wait for each ok."""
        from machine.models import MachineLog
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            with self._serial_lock:
                if not (self._serial and self._serial.is_open):
                    self._status = 'error'
                    self._error_message = 'Serial connection lost'
                    return
                try:
                    self._serial.write((line + '\n').encode())
                    self._serial.flush()
                except Exception as exc:
                    self._status = 'error'
                    self._error_message = str(exc)
                    return
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self._stop_event.is_set():
                    self._status = 'error'
                    self._error_message = 'Operation stopped'
                    return
                with self._serial_lock:
                    if self._serial and self._serial.in_waiting:
                        response = self._serial.readline().decode('utf-8', errors='replace').strip()
                        if response == 'ok':
                            break
                        if response.startswith('error'):
                            self._status = 'error'
                            self._error_message = f'GRBL error on "{line}": {response}'
                            return
                        if response.startswith('<'):
                            self._parse_status_report(response)
                time.sleep(0.01)
            else:
                self._status = 'error'
                self._error_message = f'Timeout waiting for response on: {line}'
                return
        self._status = 'connected'
        if flag_synced:
            self._synced = True
        try:
            MachineLog.objects.create(event_type='connection', message=success_msg)
        except Exception:
            pass

    def set_dry_run(self, enabled: bool) -> None:
        """Enable or disable dry-run mode (spindle suppression)."""
        self._dry_run = enabled

    def _poll_loop(self) -> None:
        """Background thread: query GRBL '?' every 200 ms when idle."""
        while not self._poll_stop.wait(0.2):
            if self._status != 'connected':
                continue
            # Send real-time query
            with self._serial_lock:
                if not (self._serial and self._serial.is_open):
                    continue
                try:
                    self._serial.write(b'?')
                    self._serial.flush()
                except Exception:
                    continue
            # Read response without holding the lock the whole time
            deadline = time.monotonic() + 0.1
            while time.monotonic() < deadline:
                with self._serial_lock:
                    if self._serial and self._serial.in_waiting:
                        try:
                            line = self._serial.readline().decode('utf-8', errors='replace').strip()
                            if line.startswith('<'):
                                self._parse_status_report(line)
                                break
                        except Exception:
                            break
                time.sleep(0.005)


# Module-level singleton
serial_controller = SerialController()
