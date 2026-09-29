"""MSP1-CX serial framing and checked programs (manual, printed pp.19-44).

No I/O retries: replaying an acknowledged-or-lost movement can double a dose.
"""
from dataclasses import dataclass
import re
import time


ERRORS = {0: "无错误", 1: "初始化错误", 2: "错误命令", 3: "参数错误",
          7: "设备未初始化", 9: "活塞驱动过载", 10: "阀过载",
          11: "活塞不允许移动", 15: "命令溢出"}
FULL_STEPS = {0: 3000, 1: 48000, 2: 24000}
SETTINGS = {"start_speed": ("v", 50, 1000), "speed": ("V", 5, 5000),
            "stop_speed": ("c", 50, 2700), "acceleration": ("L", 1, 20),
            "speed_code": ("S", 0, 40), "microstep": ("N", 0, 2),
            "backlash": ("K", 0, 31), "dead_volume": ("k", 0, 80)}
QUERIES = {"target": "?", "position": "?4", "valve": "?6",
           "start_speed": "?1", "speed": "?2", "stop_speed": "?3",
           "acceleration": "?5", "drive_force": "?8", "buffer": "?10",
           "backlash": "?12", "input1": "?13", "input2": "?14",
           "address": "?15", "error_detail": "?16", "firmware": "?23",
           "dead_volume": "?24"}


def integer(value, low, high, name="value"):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name}: expected integer {low}..{high}")
    return value


@dataclass(frozen=True)
class Reply:
    status: int
    data: str

    @property
    def error(self):
        return self.status & 15

    @property
    def ready(self):
        return bool(self.status & 32)


class SyringeProtocol:
    def __init__(self, serial_handle, address=0, mode="OEM", timeout=2):
        self.serial = serial_handle
        self.address = integer(address, 0, 14, "dial address") + 0x31
        if mode not in ("OEM", "DT"):
            raise ValueError("Protocol must be OEM or DT")
        self.mode, self.timeout = mode, timeout
        self.sequence = 0

    def frame(self, command):
        data = command.encode("ascii")
        if not data or len(data) > 128 or any(b < 32 or b > 126 for b in data):
            raise ValueError("Invalid command length/characters")
        if self.mode == "DT":
            return b"/" + bytes([self.address]) + data + b"\r"
        self.sequence = self.sequence % 7 + 1
        frame = bytes([2, self.address, 0x30 + self.sequence]) + data + b"\x03"
        checksum = 0
        for b in frame:
            checksum ^= b
        return frame + bytes([checksum])

    def exchange(self, command):
        frame = self.frame(command)
        self.serial.reset_input_buffer()
        if self.serial.write(frame) != len(frame):
            raise IOError("Incomplete serial write; command outcome unknown")
        self.serial.flush()
        deadline, data = time.monotonic() + self.timeout, bytearray()
        while time.monotonic() < deadline and len(data) < 512:
            b = self.serial.read(1)
            if not b:
                continue
            data.extend(b)
            if self.mode == "DT" and data.endswith(b"\x03\r\n"):
                if len(data) < 6 or data[:2] != b"/0":
                    raise IOError("Invalid DT response address/frame")
                return self._reply(data[2], data[3:-3])
            if self.mode == "OEM" and len(data) >= 5 and data[-2] == 3:
                checksum = 0
                for value in data:
                    checksum ^= value
                if data[:2] != b"\x02\x30" or checksum:
                    raise IOError("Invalid OEM response address/checksum")
                return self._reply(data[2], data[3:-2])
        raise TimeoutError("No complete pump response; command outcome unknown")

    @staticmethod
    def _reply(status, data):
        if status & 0xD0 != 0x40:
            raise IOError("Invalid status byte")
        return Reply(status, bytes(data).decode("ascii"))


@dataclass
class CheckedProgram:
    text: str
    target: int | None
    valve: str
    count: int
    waits_input: bool


def check_program(text, position, full_steps, valve="O"):
    """Bounded program subset; initialize/settings are separate typed actions.

    EEPROM calls are resolved by the controller from its verified registry,
    rather than permitting unseen/recursive programs in uploaded text.
    """
    if not isinstance(text, str) or not text or len(text.encode("ascii")) > 120:
        raise ValueError("Program requires 1..120 ASCII bytes (room reserved for storage framing)")
    tokens = re.findall(r"[APDVGgMHIOBJvcSLKk][0-9]*", text)
    if "".join(tokens) != text:
        raise ValueError("Unknown command; R, initialization, mode changes and EEPROM calls are separate operations")
    stack, root = [], []
    current = root
    ranges = {v[0]: (v[1], v[2]) for v in SETTINGS.values() if v[0] != "N"}
    ranges.update({"A": (0, full_steps), "P": (0, full_steps), "D": (0, full_steps),
                   "M": (5, 30000), "H": (0, 2), "J": (0, 7)})
    for token in tokens:
        op, arg = token[0], token[1:]
        if op == "g":
            if arg or len(stack) >= 4:
                raise ValueError("Loop nesting exceeds four levels")
            child = []
            stack.append((current, child)); current = child
        elif op == "G":
            if not stack or not arg or not 1 <= int(arg) <= 30000:
                raise ValueError("Unbalanced or infinite loop")
            parent, child = stack.pop()
            if not child:
                raise ValueError("Empty loop")
            parent.append(("loop", (int(arg), child))); current = parent
        elif op in "IOB":
            if arg:
                raise ValueError("Three-port Y valve commands take no index")
            current.append((op, None))
        else:
            if op not in ranges or not arg:
                raise ValueError("Missing/unsupported program argument")
            low, high = ranges[op]
            current.append((op, integer(int(arg), low, high, op)))
    if stack:
        raise ValueError("Unclosed loop")
    count, waits = 0, False

    def walk(nodes, pos, port):
        nonlocal count, waits
        for op, arg in nodes:
            count += 1
            if count > 10000:
                raise ValueError("Expanded program exceeds 10000 operations")
            if op == "loop":
                for _ in range(arg[0]):
                    pos, port = walk(arg[1], pos, port)
            elif op in "IOB":
                port = op
            elif op in "APD":
                if port == "B":
                    raise ValueError("Movement forbidden in bypass")
                if op == "A":
                    pos = (arg, arg)
                else:
                    delta = arg if op == "P" else -arg
                    pos = (max(0, pos[0] + delta), min(full_steps, pos[1] + delta))
                if pos[0] > pos[1]:
                    raise ValueError("Program exceeds syringe stroke")
            elif op == "H":
                waits = True
        return pos, port

    # Offline parsing starts with all possible positions; runtime uses a singleton.
    start = (0, full_steps) if position is None else (integer(position, 0, full_steps, "position"), position)
    target, final_valve = walk(root, start, valve)
    return CheckedProgram(text, target[0] if target[0] == target[1] else None, final_valve, count, waits)
