"""CL-01A binary framing (manual printed pp.12-14), without write retries.

Commands have no documented acknowledgement. Status is an unframed eight-byte
reply; its speed word is exposed raw because its physical conversion is unknown.
"""
import time
import logging

from src.devices.turntable_commands import TurntableCommand


WORK_STATES = {
    0x00: ("reset", False),
    0x01: ("positioning", True),
    0x04: ("manual", True),
    0x08: ("homing", True),
    0x20: ("stopped", False),
}
INPUT_BITS = {"positive_limit": 2, "home": 3, "negative_limit": 4, "input4": 5}
STATUS_FRAME = bytes.fromhex("55 aa 0c 00 00 00 00 00 00 c3")
# Initial host-side processing gap, pending lab verification; not a manual value.
STATUS_QUERY_GAP_SECONDS = 0.1
logger = logging.getLogger(__name__)


class TurntableProtocol:
    def __init__(self, serial_handle, timeout=1.0):
        self.serial = serial_handle
        self.timeout = timeout
        self._last_command = None
        self._last_command_at = None
        self._next_query_at = 0.0
        self._first_status_after_command = False

    @staticmethod
    def frame(request):
        req = request if isinstance(request, TurntableCommand) else TurntableCommand.model_validate(request)
        if req.action == "stop":
            opcode, payload = 0x02, bytes(6)
        elif req.action in ("move_absolute", "move_relative"):
            opcode = 0x07 if req.action == "move_absolute" else 0x08
            position = req.position if req.action == "move_absolute" else req.steps
            payload = req.speed.to_bytes(2, "little") + position.to_bytes(4, "little", signed=True)
        else:
            opcode = 0x06 if req.action == "run" else 0x0B
            direction = 0x09 if req.direction == "positive" else 0x0A
            payload = bytes([direction]) + req.speed.to_bytes(2, "little") + bytes(3)
        return b"\x55\xaa" + bytes([opcode]) + payload + b"\xc3"

    def _write(self, frame):
        try:
            if self.serial.write(frame) != len(frame):
                raise IOError("Incomplete CL-01A write; command outcome unknown")
            self.serial.flush()
        finally:
            self._next_query_at = time.monotonic() + STATUS_QUERY_GAP_SECONDS

    def send_command(self, request):
        # No ACK is documented, so successful write only means sent, not executed.
        frame = self.frame(request)
        self._write(frame)
        self._last_command = frame.hex(" ")
        self._last_command_at = time.monotonic()
        self._first_status_after_command = True

    def _log_status(self, level, event, reply, started, queried_at, trailing, error=None):
        command_age = (None if self._last_command_at is None
                       else f"{queried_at - self._last_command_at:.3f}")
        logger.log(level, "CL-01A status %s: port=%s received=%s/8 raw=%s trailing=%s "
                   "elapsed=%.3fs query_delay=%.3fs response_elapsed=%.3fs "
                   "last_command=%s command_age=%s error=%s",
                   event, getattr(self.serial, "port", None), len(reply), reply.hex(" "), trailing,
                   time.monotonic() - started, queried_at - started, time.monotonic() - queried_at,
                   self._last_command, command_age, error)

    def read_status(self):
        started = time.monotonic()
        # All callers share the existing device lock. Pace queries here so Web
        # monitoring cannot bypass the gap after a motion or another response.
        # Commands (especially STOP) never wait for this query-only gap.
        delay = self._next_query_at - started
        if delay > 0:
            time.sleep(delay)
        queried_at = time.monotonic()
        reply = bytearray()
        trailing = 0
        try:
            self.serial.reset_input_buffer()
            self._write(STATUS_FRAME)
            deadline = time.monotonic() + self.timeout
            while len(reply) < 8 and time.monotonic() < deadline:
                reply.extend(self.serial.read(8 - len(reply)))
            if len(reply) != 8:
                elapsed = time.monotonic() - started
                raise TimeoutError(f"No complete eight-byte CL-01A status response (received {len(reply)}/8 bytes, elapsed {elapsed:.3f}s)")
            trailing = getattr(self.serial, "in_waiting", 0)
            if trailing:
                raise IOError("Unexpected trailing CL-01A status bytes")
            status = self.decode_status(bytes(reply))
            self._log_status(logging.INFO if self._first_status_after_command else logging.DEBUG,
                             "received", reply, started, queried_at, trailing)
            return status
        except OSError as exc:
            self._log_status(logging.WARNING, "timeout" if isinstance(exc, TimeoutError) else "failed",
                             reply, started, queried_at, trailing, exc)
            raise
        finally:
            self._first_status_after_command = False
            self._next_query_at = time.monotonic() + STATUS_QUERY_GAP_SECONDS

    @staticmethod
    def decode_status(reply):
        if len(reply) != 8:
            raise IOError("CL-01A status must contain exactly eight bytes")
        work_state = reply[7]
        if work_state not in WORK_STATES:
            raise IOError(f"Undefined CL-01A work state: 0x{work_state:02x}")
        state_name, busy = WORK_STATES[work_state]
        input_raw = reply[6]
        return {
            "position": int.from_bytes(reply[:4], "big", signed=True),
            "speed_raw": int.from_bytes(reply[4:6], "big"),
            "input_raw": input_raw,
            "inputs": {name: not bool(input_raw & (1 << bit)) for name, bit in INPUT_BITS.items()},
            "work_state": work_state,
            "state_name": state_name,
            "busy": busy,
        }
