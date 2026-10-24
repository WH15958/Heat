"""CL-01A framing tests use fake byte streams; no hardware access."""
import pytest
from pydantic import ValidationError

from src.devices.turntable_commands import TurntableCommand
from src.protocols.turntable import STATUS_FRAME, TurntableProtocol


class Wire:
    def __init__(self, response=b"", write_count=None):
        self.response = response
        self.buffer = bytearray()
        self.writes = []
        self.reads = 0
        self.write_count = write_count

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        self.writes.append(data)
        self.buffer.extend(self.response)
        return len(data) if self.write_count is None else self.write_count

    def read(self, count):
        self.reads += 1
        fragment = bytes(self.buffer[:1])
        del self.buffer[:1]
        return fragment


@pytest.mark.parametrize("command,frame", [
    ({"action": "move_absolute", "position": 10, "speed": 400}, "55 aa 07 90 01 0a 00 00 00 c3"),
    ({"action": "move_relative", "steps": -1, "speed": 1000}, "55 aa 08 e8 03 ff ff ff ff c3"),
    ({"action": "run", "direction": "positive", "speed": 40000}, "55 aa 06 09 40 9c 00 00 00 c3"),
    ({"action": "home", "direction": "negative", "speed": 400}, "55 aa 0b 0a 90 01 00 00 00 c3"),
    ({"action": "stop"}, "55 aa 02 00 00 00 00 00 00 c3"),
])
def test_exact_frames_without_ack_or_read(command, frame):
    wire = Wire()
    protocol = TurntableProtocol(wire)
    assert protocol.send_command(command) is None
    assert wire.writes == [bytes.fromhex(frame)]
    assert wire.reads == 0


def test_duration_is_host_only():
    command = {"action": "run", "direction": "negative", "speed": 1000}
    assert TurntableCommand.model_validate(command).duration_seconds == 10
    assert TurntableProtocol.frame({**command, "duration_seconds": 1}) == TurntableProtocol.frame(
        {**command, "duration_seconds": 60})


@pytest.mark.parametrize("state,name,busy", [
    (0, "reset", False), (1, "positioning", True), (4, "manual", True),
    (8, "homing", True), (0x20, "stopped", False),
])
def test_fragmented_status_big_endian_and_active_low_inputs(state, name, busy):
    # The input word has home and input4 active, positive/negative limits inactive.
    wire = Wire(bytes.fromhex("ff ff ff fe 12 34 14") + bytes([state]))
    wire.buffer.extend(b"stale")
    result = TurntableProtocol(wire, .01).read_status()
    assert wire.writes == [STATUS_FRAME]
    assert result["position"] == -2
    assert result["speed_raw"] == 0x1234
    assert "speed" not in result
    assert result["input_raw"] == 0x14
    assert result["inputs"] == {"positive_limit": False, "home": True,
                                 "negative_limit": False, "input4": True}
    assert result["work_state"] == state and result["busy"] is busy
    assert result["state_name"] == name


@pytest.mark.parametrize("reply", [b"", bytes(7), bytes(9), bytes(7) + b"\x02"])
def test_bad_status_never_retries(reply):
    wire = Wire(reply)
    with pytest.raises((OSError, TimeoutError)):
        TurntableProtocol(wire, .001).read_status()
    assert wire.writes == [STATUS_FRAME]


@pytest.mark.parametrize("command", [{"action": "stop"}, {"action": "run", "direction": "positive", "speed": 400}])
def test_short_write_never_retries_or_reads(command):
    wire = Wire(write_count=4)
    with pytest.raises(OSError, match="outcome unknown"):
        TurntableProtocol(wire).send_command(command)
    assert len(wire.writes) == 1 and wire.reads == 0


@pytest.mark.parametrize("command", [
    {"action": "move_relative", "steps": True, "speed": 400},
    {"action": "move_relative", "steps": "10", "speed": 400},
    {"action": "move_relative", "steps": -10000000, "speed": 400},
    {"action": "move_absolute", "position": 100000000, "speed": 400},
    {"action": "move_absolute", "position": 0},
    {"action": "move_absolute", "position": 0, "speed": 399},
    {"action": "move_absolute", "position": 0, "speed": 40001},
    {"action": "move_absolute", "position": 0, "speed": True},
    {"action": "move_absolute", "position": 0, "speed": "400"},
    {"action": "move_absolute", "position": 0, "speed": 400.0},
    {"action": "run", "speed": 400},
    {"action": "run", "direction": "positive", "speed": 400, "duration_seconds": True},
    {"action": "run", "direction": "positive", "speed": 400, "duration_seconds": "10"},
    {"action": "run", "direction": "positive", "speed": 400, "duration_seconds": 0},
    {"action": "run", "direction": "positive", "speed": 400, "duration_seconds": 61},
    {"action": "run", "direction": "positive", "speed": 400, "duration_seconds": float("nan")},
    {"action": "home", "direction": "negative", "speed": 400, "duration_seconds": 10},
    {"action": "stop", "speed": None},
    {"action": "stop", "position": 0},
    {"action": "stop", "unknown": 1},
])
def test_invalid_requests_do_not_write(command):
    wire = Wire()
    with pytest.raises(ValidationError):
        TurntableProtocol(wire).send_command(command)
    assert wire.writes == []


@pytest.mark.parametrize("position", [-9999999, 99999999])
def test_documented_position_boundaries_use_signed_encoding(position):
    frame = TurntableProtocol.frame({"action": "move_absolute", "position": position, "speed": 400})
    assert int.from_bytes(frame[5:9], "little", signed=True) == position
