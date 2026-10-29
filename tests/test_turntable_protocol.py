"""CL-01A framing tests use fake byte streams; no hardware access."""
from types import SimpleNamespace

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
        self.flushes = 0

    def flush(self):
        self.flushes += 1

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


@pytest.fixture
def paced_wire(monkeypatch):
    from src.protocols import turntable

    clock = SimpleNamespace(now=10.0, sleeps=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(turntable, 'time', SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep))

    class PacedWire(Wire):
        # Model a controller that drops a query while processing the previous
        # exchange. This reproduces a timing risk, not the proven hardware cause.
        is_open = True
        port = 'TEST'

        def __init__(self):
            super().__init__(bytes.fromhex('00 00 00 00 00 00 fc 20'))
            self.ready_at = clock.now
            self.sent_at = []

        def write(self, data):
            self.writes.append(data)
            self.sent_at.append(clock.now)
            if data == STATUS_FRAME and clock.now + 1e-9 >= self.ready_at:
                self.buffer.extend(self.response)
            self.ready_at = clock.now + .1
            return len(data)

        def read(self, count):
            clock.now += .005
            result = super().read(count)
            if not self.buffer:
                self.ready_at = clock.now + .1
            return result

    return clock, PacedWire()


@pytest.mark.parametrize('command', [
    {'action': 'move_absolute', 'position': 12000, 'speed': 4000},
    {'action': 'home', 'direction': 'negative', 'speed': 1000},
    {'action': 'stop'},
])
def test_first_query_waits_for_command_processing_without_replay(paced_wire, command, caplog):
    clock, wire = paced_wire
    protocol = TurntableProtocol(wire, .2)
    protocol.send_command(command)
    caplog.set_level('INFO', logger='src.protocols.turntable')
    assert protocol.read_status()['work_state'] == 0x20
    assert wire.sent_at[1] - wire.sent_at[0] == pytest.approx(.1)
    assert wire.writes == [protocol.frame(command), STATUS_FRAME]
    assert 'command_age=0.100' in caplog.text
    assert 'raw=00 00 00 00 00 00 fc 20' in caplog.text


def test_consecutive_queries_wait_after_response_completion(paced_wire):
    clock, wire = paced_wire
    protocol = TurntableProtocol(wire, .2)
    protocol.read_status()
    finished = clock.now
    protocol.read_status()
    assert wire.sent_at[-1] - finished == pytest.approx(.1)
    # An already idle link should not acquire an extra fixed delay.
    clock.now += .2
    sleeps = list(clock.sleeps)
    protocol.read_status()
    assert clock.sleeps == sleeps


def test_stop_write_bypasses_query_spacing(paced_wire):
    clock, wire = paced_wire
    protocol = TurntableProtocol(wire, .2)
    protocol.send_command({'action': 'move_absolute', 'position': 12000, 'speed': 4000})
    sent = clock.now
    protocol.send_command({'action': 'stop'})
    assert clock.now == sent and clock.sleeps == []
    assert [frame[2] for frame in wire.writes] == [0x07, 0x02]


def test_failed_query_also_leaves_processing_gap(paced_wire):
    clock, wire = paced_wire
    protocol = TurntableProtocol(wire, .2)
    wire.response = bytes.fromhex('00 00 20 3e 00 00 fc 10')
    with pytest.raises(OSError, match='Undefined'):
        protocol.read_status()
    finished = clock.now
    wire.response = bytes.fromhex('00 00 20 3e 00 00 fc 20')
    assert protocol.read_status()['position'] == 8254
    assert wire.sent_at[-1] - finished == pytest.approx(.1)


def test_connection_settling_waits_for_late_bytes_and_never_writes(paced_wire, caplog):
    clock, wire = paced_wire
    from src.protocols import turntable
    protocol = TurntableProtocol(wire, .2)
    sleep = turntable.time.sleep
    injected = []
    def late_bytes(seconds):
        sleep(seconds)
        if clock.now >= 10.06 and not injected:
            wire.buffer.extend(b'late')
            injected.append(clock.now)
    turntable.time.sleep = late_bytes
    caplog.set_level('INFO', logger='src.protocols.turntable')
    protocol.prepare_connection()
    assert clock.now >= injected[0] + .1
    assert not wire.buffer and not wire.writes
    assert 'raw=6c 61 74 65' in caplog.text


def test_connection_never_queries_a_continuously_noisy_link(paced_wire):
    clock, wire = paced_wire
    from src.protocols import turntable
    sleep = turntable.time.sleep
    def noisy(seconds):
        sleep(seconds)
        wire.buffer.extend(b'x')
    turntable.time.sleep = noisy
    with pytest.raises(TimeoutError, match='quiet'):
        TurntableProtocol(wire).prepare_connection()
    assert clock.now < 10.55 and not wire.writes


@pytest.mark.parametrize('response,error', [
    (b'', 'received 0/8'),
    (bytes.fromhex('00 00 20 3e'), 'received 4/8'),
    (bytes.fromhex('00 00 20 3e 00 00 fc 10'), 'Undefined'),
    (bytes.fromhex('00 00 20 3e 00 00 fc 20 ff'), 'trailing'),
])
def test_paced_query_errors_keep_strict_validation_and_raw_diagnostics(paced_wire, response, error, caplog):
    clock, wire = paced_wire
    wire.response = response
    protocol = TurntableProtocol(wire, .2)
    protocol.send_command({'action': 'move_absolute', 'position': 12000, 'speed': 4000})
    started = clock.now
    with pytest.raises(OSError, match=error):
        protocol.read_status()
    assert clock.now - started <= .305
    assert len(wire.writes) == 2
    assert f'raw={response[:8].hex(" ")}' in caplog.text
    assert 'command_age=0.100' in caplog.text


def test_controller_still_stops_after_no_response_and_does_not_complete_bottle(paced_wire, monkeypatch):
    from src.protocols import turntable
    from src.web import turntable_control
    from src.devices.turntable import TurntableDevice
    from src.utils.config import TurntableConfig

    clock, wire = paced_wire
    monkeypatch.setattr(turntable_control, 'time', turntable.time)
    config = TurntableConfig(position_encoding_verified=True, home_enabled=True, bottle_count=12)
    device = TurntableDevice(config)
    device.handle = wire
    device.protocol = TurntableProtocol(wire, .2)
    control = turntable_control.TurntableController(config, device=device)
    control.read()
    control.command({'action': 'move_absolute', 'position': 12000, 'speed': 4000})
    wire.response = b''
    state = control.read()
    assert state['read_ok'] is False and state['action']['result'] == 'unknown'
    assert state['bottle_ready'] is False
    wire.response = bytes.fromhex('00 00 20 3e 00 00 fc 20')  # position 8254
    control.enforce_timeout()
    state = control.summary()
    assert state['stop_confirmed'] is True and state['position'] == 8254
    assert state['action']['result'] == 'failed' and state['bottle_ready'] is False
    assert [frame[2] for frame in wire.writes if frame != STATUS_FRAME] == [0x07, 0x02]


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
    assert wire.flushes == 1


def test_duration_is_host_only():
    command = {"action": "run", "direction": "negative", "speed": 1000}
    assert TurntableCommand.model_validate(command).duration_seconds == 10
    assert TurntableProtocol.frame({**command, "duration_seconds": 1}) == TurntableProtocol.frame(
        {**command, "duration_seconds": 60})


def test_flush_failure_never_retries_motion():
    wire = Wire()
    def fail():
        raise OSError('transmit failed')
    wire.flush = fail
    with pytest.raises(OSError, match='transmit failed'):
        TurntableProtocol(wire).send_command({'action': 'home', 'direction': 'negative', 'speed': 1000})
    assert len(wire.writes) == 1 and wire.reads == 0


def test_buffered_motion_finishes_transmission_before_status_query():
    class BufferedWire(Wire):
        pending = False

        def write(self, data):
            assert not self.pending, 'Previous frame has not finished transmission'
            self.pending = True
            return super().write(data)

        def flush(self):
            super().flush()
            self.pending = False

    wire = BufferedWire()
    protocol = TurntableProtocol(wire)
    protocol.send_command({'action': 'home', 'direction': 'negative', 'speed': 1000})
    wire.response = bytes.fromhex('00 00 00 00 00 00 fc 08')
    assert protocol.read_status()['state_name'] == 'homing'
    assert len(wire.writes) == 2 and wire.flushes == 2


@pytest.mark.parametrize('reply', [b'', b'\x12\x34'])
def test_timeout_records_partial_response_without_replaying_command(reply, caplog):
    wire = Wire()
    protocol = TurntableProtocol(wire, .001)
    protocol.send_command({'action': 'home', 'direction': 'negative', 'speed': 1000})
    wire.response = reply
    with pytest.raises(TimeoutError, match=f'received {len(reply)}/8'):
        protocol.read_status()
    assert len(wire.writes) == 2 and wire.writes[-1] == STATUS_FRAME
    assert f'received={len(reply)}/8' in caplog.text
    assert 'last_command=55 aa 0b' in caplog.text


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
