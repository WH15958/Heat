"""Software-only tests. Serial.open is forbidden for real serial instances."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
import serial
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.protocols.syringe_pump import SyringeProtocol, Reply, check_program
from src.devices.syringe_pump import SyringePumpDevice
from src.devices.syringe_commands import SyringeCommand
from src.utils.config import SyringePumpConfig, DeviceConnectionConfig, ConfigManager
from src.web.syringe_control import SyringeController
from src.web.device_manager import DeviceManager
from src.web.api.syringe_pumps import router
from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.executor import StepExecutor


@pytest.fixture(autouse=True)
def forbid_hardware(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real serial access forbidden")
    monkeypatch.setattr(serial.Serial, "open", forbidden)


class Wire:
    def __init__(self, response):
        self.response, self.buffer, self.writes = response, bytearray(), []

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        self.writes.append(data)
        self.buffer.extend(self.response)
        return len(data)

    def flush(self):
        pass

    def read(self, count):
        if not self.buffer:
            return b""
        value = bytes(self.buffer[:1]); del self.buffer[:1]
        return value


@pytest.mark.parametrize("mode,reply,frame", [
    ("OEM", bytes.fromhex("02 30 60 03 51"), bytes.fromhex("02 32 31 51 03 53")),
    ("DT", b"/0`\x03\r\n", b"/2Q\r"),
])
def test_framing_and_fragmented_reply(mode, reply, frame):
    wire = Wire(reply); protocol = SyringeProtocol(wire, 1, mode, .01)
    result = protocol.exchange("Q")
    assert wire.writes == [frame]
    assert result.ready and result.error == 0


@pytest.mark.parametrize("mode,response", [
    ("OEM", bytes.fromhex("02 30 60 03 50")),
    ("OEM", bytes.fromhex("02 31 60 03 50")),
    ("DT", b"/1`\x03\r\n"), ("DT", b"/0\x00\x03\r\n"),
    ("DT", b"/0`\x03"), ("OEM", b""),
])
def test_bad_responses_never_retry(mode, response):
    wire = Wire(response)
    with pytest.raises((OSError, TimeoutError)):
        SyringeProtocol(wire, 1, mode, .002).exchange("IP300R")
    assert len(wire.writes) == 1


def test_oem_sequence_rotates_without_repeat_bit():
    p = SyringeProtocol(Wire(b""))
    assert [p.frame("Q")[2] for _ in range(9)] == [49, 50, 51, 52, 53, 54, 55, 49, 50]


@pytest.mark.parametrize("program", ["gP1G0", "gP1", "P3001", "D1", "BP1",
    "IP1R", "e1", "s1A0", "N1", "g" * 5 + "M5" + "G1" * 5, "gM5G30000", "J8", "H3", "M1", "Z"])
def test_invalid_programs(program):
    with pytest.raises(ValueError):
        check_program(program, 0, 3000)


def test_bounded_nested_program():
    p = check_program("gIgP10OD10G3G2H1J7", 0, 3000)
    assert p.target == 0 and p.waits_input and p.valve == "O"


@pytest.mark.parametrize('program', ['M5' * 61, 'v49', 'V5001', 'c2701', 'L21', 'S41', 'K32', 'k81'])
def test_program_length_and_setting_ranges(program):
    with pytest.raises(ValueError): check_program(program, 0, 3000)


def test_offline_program_checks_feasible_stroke_and_all_operations():
    assert check_program('D100P100', None, 3000).target is None
    for program in ('gP3000G2', 'D100BP1', 'D100gM5G30000'):
        with pytest.raises(ValueError): check_program(program, None, 3000)


class FakeProtocol:
    def __init__(self):
        self.calls = []
        self.position = self.target = 0
        self.valve = 0
        self.error = 0
        self.busy = 0
        self.fail_command = None
        self.stuck = False

    def exchange(self, cmd):
        import re
        self.calls.append(cmd)
        if cmd == self.fail_command:
            raise TimeoutError("lost reply")
        if cmd == "Q":
            busy = self.busy > 0
            self.busy = max(0, self.busy - 1)
            if not busy and not self.stuck:
                self.position = self.target
            return Reply((0x40 if busy else 0x60) | self.error, "")
        if cmd.startswith("?"):
            value = {"?": self.target, "?4": self.position, "?6": self.valve,
                     "?10": 96, "?1": 50, "?2": 100, "?3": 50, "?23": "fake"}.get(cmd, 0)
            return Reply(0x60 | self.error, str(value))
        if cmd == "T":
            self.busy = 0; self.target = self.position
        elif cmd.startswith(("Z", "Y")):
            self.error = 0; self.target = 0; self.busy = 1
            self.valve = 0 if cmd[0] == "Z" else 4
        elif cmd.endswith("R") and not cmd.startswith("s"):
            for op, number in re.findall(r"([APDIO])([0-9]*)", cmd):
                if op == "I": self.valve = 4
                elif op == "O": self.valve = 0
                elif op == "A": self.target = int(number)
                elif op == "P": self.target += int(number)
                elif op == "D": self.target -= int(number)
            self.busy = 1
        return Reply(0x40 if self.busy else 0x60, "")


@pytest.fixture
def pump(tmp_path):
    cfg = SyringePumpConfig(connection=DeviceConnectionConfig(port="FAKE", address=1))
    d = SyringePumpDevice(cfg)
    d.handle = SimpleNamespace(is_open=True)
    d.protocol = FakeProtocol()
    d.mode, d.orientation, d.trusted = 0, "Z", True
    c = SyringeController(cfg, tmp_path, d)
    return c


def finish(c):
    for _ in range(5):
        state = c.read()
        if not state["busy"]:
            return state
    pytest.fail("did not complete")


def test_aspirate_and_dispense_verify_target(pump):
    result = pump.command({"action": "aspirate", "volume": 250})
    assert result["target"] == 300
    assert "v50c50V100IA300R" in pump.device.protocol.calls
    assert finish(pump)["action"]["result"] == "completed"
    pump.command({"action": "dispense", "volume": .25, "unit": "mL"})
    state = finish(pump)
    assert state["position"] == 0 and state["valve_position"] == 0


def test_overload_invalidates_position_and_no_automatic_initialize(pump):
    pump.device.protocol.error = 9
    state = pump.read()
    assert state["fault_code"] == 9 and not state["position_trusted"]
    assert state["theoretical_volume_ul"] is None
    with pytest.raises(RuntimeError):
        pump.command({"action": "move", "position": 1000})
    assert all(c.startswith(("Q", "?")) for c in pump.device.protocol.calls)


def test_unknown_fault_is_not_success(pump):
    pump.device.protocol.error = 6
    assert pump.read()["fault_description"] == "未知错误"
    with pytest.raises(RuntimeError): pump.command({"action": "valve"})


def test_lost_movement_reply_is_not_replayed(pump):
    p = pump.device.protocol
    p.fail_command = "v50c50V100IA300R"
    with pytest.raises(TimeoutError): pump.command({"action": "move", "position": 300})
    assert p.calls.count(p.fail_command) == 1
    assert pump.read()["action"]["result"] == "unknown"
    with pytest.raises(RuntimeError): pump.command({"action": "move", "position": 300})


def test_actual_position_mismatch_fails(pump):
    pump.device.protocol.stuck = True
    pump.command({"action": "move", "position": 300})
    state = finish(pump)
    assert state["action"]["result"] == "failed" and not state["position_trusted"]


def test_read_failure_returns_unknown(pump):
    pump.read(); pump.device.protocol.fail_command = "Q"
    state = pump.read()
    assert not state["read_ok"] and state["position"] is None and state["fault_code"] is None


@pytest.mark.parametrize("params", [{"action": "move", "position": True},
    {"action": "aspirate", "volume": float('nan')}, {"action": "io", "output": 8},
    {"action": "initialize"}, {"action": "configure", "settings": {"bogus": 5}},
    {"action": "move", "position": 300, "program": "Z"}])
def test_bad_api_parameters(params):
    with pytest.raises(ValueError): SyringeCommand.model_validate(params)


def test_microstep_change_at_zero_and_rounding(pump):
    pump.command({"action": "configure", "settings": {"microstep": 2}})
    finish(pump)
    assert pump.command({"action": "aspirate", "volume": 100})["target"] == 960
    finish(pump)
    with pytest.raises(ValueError): pump.command({"action": "configure", "settings": {"microstep": 0}})


def test_program_storage_failure_blocks_slot(pump, monkeypatch):
    monkeypatch.setattr(pump, '_store', lambda req: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        pump.command({"action": "program_store", "program": "IP120OD120", "name": "test", "slot": 1, "confirm": True})
    with pytest.raises(ValueError): pump.command({"action": "program_run", "slot": 1})


def test_program_registry_and_unknown_slot(pump):
    with pytest.raises(ValueError): pump.command({"action": "program_run", "slot": 2})
    pump.command({"action": "program_store", "program": "IP120OD120", "name": "test", "slot": 1, "confirm": True})
    assert pump.programs()['1']['verification'] == 'sent_unverified'
    assert 's1IP120OD120R' in pump.device.protocol.calls


def test_read_does_not_stop_overdue_motion(pump):
    pump.command({"action": "move", "position": 300})
    pump.device.protocol.busy = 100
    pump.device.action['deadline'] = 0
    pump.read()
    assert 'T' not in pump.device.protocol.calls
    pump.enforce_timeout()
    assert 'T' in pump.device.protocol.calls
    assert pump.device.action['result'] == 'failed'


def test_experiment_owner_blocks_manual_commands_but_not_stop(pump):
    pump.claim('experiment')
    with pytest.raises(RuntimeError): pump.command({'action': 'move', 'position': 10})
    assert pump.command({'action': 'stop'})['result'] == 'stopped'


def test_placeholder_and_configuration():
    configs = ConfigManager().load().syringe_pumps
    assert len(configs) == 2 and configs[1].connection.port == ''
    c = SyringeController(configs[1])
    with pytest.raises(ValueError): c.connect()
    assert not c.summary()['connected']


def test_api_typed_request_and_status(pump):
    app = FastAPI(); dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    app.state.device_manager = dm; app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        assert client.post('/api/syringe_pump/syringe_pump1/command', json={'action':'move','position':True}).status_code == 422
        assert client.get('/api/syringe_pump/wrong/status').status_code == 404
        result = client.post('/api/syringe_pump/syringe_pump1/command', json={'action':'move','position':120})
        assert result.status_code == 200
        assert result.json()['result'] == 'accepted'


def test_experiment_completes_even_while_paused_without_replaying(pump):
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    executor = StepExecutor(dm); executor.set_pause_checker(lambda: True)
    step = ExperimentStep('asp', ActionType.SYRINGE_ASPIRATE, {'device_id':'syringe_pump1', 'volume':100})
    async def scenario():
        assert await executor.execute(step)
        assert pump.device.protocol.calls.count('v50c50V100IA120R') == 1
        assert await executor.stop_active_devices()
        assert pump.owner is None
    asyncio.run(scenario())


def test_experiment_stop_failure_keeps_ownership(pump):
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    e = StepExecutor(dm); pump.claim(e._syringe_owner); e._active_syringes.add('syringe_pump1')
    pump.device.protocol.fail_command = 'T'
    assert not asyncio.run(e.stop_active_devices())
    assert pump.owner is e._syringe_owner


@pytest.mark.parametrize('error', [1, 7, 9, 10, 11])
def test_faults_block_motion(pump, error):
    pump.device.protocol.error = error
    with pytest.raises(RuntimeError): pump.command({'action': 'aspirate', 'volume': 100})
    assert not any(c.endswith('R') for c in pump.device.protocol.calls)


@pytest.mark.parametrize('command', [
    {'action': 'move', 'position': -1}, {'action': 'move', 'position': 3001},
    {'action': 'dispense', 'volume': 1}, {'action': 'aspirate', 'volume': .01},
    {'action': 'aspirate', 'volume': 1e308, 'unit': 'mL'},
])
def test_stroke_and_resolution_limits(pump, command):
    with pytest.raises(ValueError): pump.command(command)
    assert not any(c.endswith('R') for c in pump.device.protocol.calls)


def test_q_ready_does_not_complete_pending_buffer(pump, monkeypatch):
    p = pump.device.protocol
    original = p.exchange
    monkeypatch.setattr(p, 'exchange', lambda cmd: Reply(0x60, '64') if cmd == '?10' else original(cmd))
    pump.command({'action': 'move', 'position': 100})
    finish(pump)
    assert pump.device.action['result'] == 'running'
    with pytest.raises(RuntimeError): pump.command({'action': 'move', 'position': 200})


def test_configure_waits_for_q_and_checks_readback(pump):
    pump.command({'action': 'configure', 'settings': {'speed': 100, 'microstep': 1}})
    assert '?2' not in pump.device.protocol.calls
    state = finish(pump)
    assert state['action']['verified'] == {'speed': 100}
    assert state['action']['unverified'] == ['microstep']
    assert state['microstep'] == 1
    pump.command({'action': 'configure', 'settings': {'speed': 200}})
    state = finish(pump)
    assert not state['read_ok'] and not state['position_trusted']


def test_unknown_mode_blocks_motion_and_init_establishes_it(pump):
    pump.device.mode = None
    with pytest.raises(RuntimeError): pump.command({'action': 'move', 'position': 120})
    pump.command({'action': 'initialize', 'confirm': True})
    assert not pump.device.trusted
    state = finish(pump)
    assert state['microstep'] == 0 and state['position_trusted']


def test_two_pumps_are_isolated(pump, tmp_path):
    cfg = SyringePumpConfig(device_id='syringe_pump2')
    device = SyringePumpDevice(cfg)
    device.handle = SimpleNamespace(is_open=True)
    device.protocol = FakeProtocol()
    device.mode, device.orientation, device.trusted = 0, 'Z', True
    second = SyringeController(cfg, tmp_path, device)
    pump.command({'action': 'move', 'position': 120})
    second.command({'action': 'move', 'position': 240})
    assert pump.stop()
    assert finish(second)['position'] == 240
    assert 'T' not in second.device.protocol.calls


def test_duplicate_submit_is_rejected_while_busy(pump):
    pump.command({'action': 'move', 'position': 120})
    pump.device.protocol.busy = 20
    with pytest.raises(RuntimeError): pump.command({'action': 'move', 'position': 120})
    assert pump.device.protocol.calls.count('v50c50V100IA120R') == 1


def test_stop_generation_cancels_queued_command(pump):
    generation = pump.generation
    assert pump.stop()
    with pytest.raises(RuntimeError):
        pump.command({'action': 'move', 'position': 120}, expected_generation=generation)


def test_stop_during_preflight_prevents_motion_write(pump, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = pump.device.protocol.exchange
    def exchange(cmd):
        if cmd == '?6':
            entered.set()
            assert release.wait(2)
        return original(cmd)
    monkeypatch.setattr(pump.device.protocol, 'exchange', exchange)
    failures = []
    def submit():
        try: pump.command({'action': 'move', 'position': 120})
        except RuntimeError as exc: failures.append(str(exc))
    worker = threading.Thread(target=submit)
    worker.start()
    assert entered.wait(2)
    pump.invalidate_pending()
    release.set(); worker.join(2)
    assert failures and not worker.is_alive()
    assert 'v50c50V100IA120R' not in pump.device.protocol.calls


def test_stop_does_not_wait_for_motion_completion(pump):
    pump.command({'action': 'move', 'position': 120})
    pump.device.protocol.busy = 1000
    assert pump.stop()
    assert pump.device.stop_confirmed and not pump.device.trusted


def test_global_stop_blocks_commands(pump):
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    dm._begin_global_stop()
    try:
        with pytest.raises(RuntimeError): dm.syringe_command('syringe_pump1', {'action': 'move', 'position': 120})
        assert dm.syringe_command('syringe_pump1', {'action': 'stop'})['result'] == 'stopped'
    finally:
        dm._end_global_stop()


def test_failed_overwrite_revokes_previously_stored_slot(pump):
    req = {'action': 'program_store', 'program': 'M5', 'name': 'test', 'slot': 1, 'confirm': True}
    pump.command(req)
    pump.device.protocol.fail_command = 's1M5R'
    with pytest.raises(TimeoutError): pump.command(req)
    assert 1 not in pump.verified_slots


def test_modified_registry_cannot_execute(pump):
    pump.command({'action': 'program_store', 'program': 'M5', 'name': 'test', 'slot': 1, 'confirm': True})
    records = pump.programs(); records['1']['program'] = 'M10'
    pump._path().write_text(json.dumps(records), encoding='utf-8')
    with pytest.raises(ValueError): pump.command({'action': 'program_run', 'slot': 1})


def test_external_input_program_timeout_stops(pump):
    pump.command({'action': 'program_load', 'program': 'H1M5', 'timeout': .01})
    pump.command({'action': 'program_run', 'timeout': .01})
    pump.device.protocol.busy = 1000
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    e = StepExecutor(dm)
    assert not asyncio.run(e._wait_syringe('syringe_pump1', .01))
    assert 'T' in pump.device.protocol.calls and 'timeout' in e.last_error


def test_manual_resume_releases_h_wait_without_replay(pump):
    pump.command({'action': 'program_load', 'program': 'H1M5'})
    pump.command({'action': 'program_run'})
    pump.device.protocol.busy = 100
    before = list(pump.device.protocol.calls)
    pump.command({'action': 'resume'})
    assert pump.device.protocol.calls[len(before):] == ['Q', 'R']
    assert 'X' not in pump.device.protocol.calls


def test_fault_blocks_resume_before_write(pump):
    pump.command({'action': 'move', 'position': 120})
    pump.device.protocol.error = 10
    with pytest.raises(RuntimeError): pump.command({'action': 'resume'})
    assert 'r' not in pump.device.protocol.calls


def test_sensor_history_keeps_unknown_gaps_and_old_records(pump):
    from src.experiment.experiment_logger import ExperimentLogger
    log = ExperimentLogger(save_log=False)
    log.start_run('test', 'test.yaml', 1)
    log.record_sensor_data({'heaters': {}})
    assert log.active_run.sensor_data['syringe_pumps'] == {}
    log.record_sensor_data({'syringe_pumps': {'syringe_pump1': pump.read()}})
    pump.device.protocol.fail_command = 'Q'
    log.record_sensor_data({'syringe_pumps': {'syringe_pump1': pump.read()}})
    series = log.active_run.sensor_data['syringe_pumps']['syringe_pump1']
    assert series['position'][-1]['v'] is None
    assert series['theoretical_volume_ul'][-1]['v'] is None
    assert series['states'][-1]['read_ok'] is False


def test_get_and_ws_do_not_control_hardware(pump):
    from src.web.api.ws import build_realtime_payload, DeviceReadCoordinator
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    payload = asyncio.run(build_realtime_payload(dm, DeviceReadCoordinator()))
    assert payload['syringe_pumps']['syringe_pump1']['read_ok']
    assert all(c.startswith(('Q', '?')) for c in pump.device.protocol.calls)


def test_connect_is_read_only_and_uses_serial_manager(monkeypatch):
    import src.devices.syringe_pump as module
    calls = []
    class Manager:
        def acquire_port(self, port, force): calls.append(('acquire', port)); return True
        def register_handle(self, port, handle): calls.append(('register', port))
        def release_port(self, port): calls.append(('release', port)); return True
    handle = SimpleNamespace(is_open=False)
    handle.open = lambda: setattr(handle, 'is_open', True)
    monkeypatch.setattr(module, 'get_serial_manager', lambda: Manager())
    protocol = FakeProtocol()
    monkeypatch.setattr(module, 'SyringeProtocol', lambda *a: protocol)
    device = SyringePumpDevice(SyringePumpConfig(), serial_factory=lambda **k: handle)
    assert device.connect('FAKE')
    assert not device.trusted and device.mode is None
    assert all(c.startswith(('Q', '?')) for c in protocol.calls)
    assert device.disconnect()
    assert calls == [('acquire', 'FAKE'), ('register', 'FAKE'), ('release', 'FAKE')]


def test_fault_monitor_continues_during_pause(pump):
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    e = StepExecutor(dm); e._active_syringes.add('syringe_pump1')
    e.set_pause_checker(lambda: True)
    pump.device.protocol.error = 9
    assert not asyncio.run(e.check_syringe_health())
    assert e.last_device_result['fault_code'] == 9


def test_short_action_logged_without_sensor_tick(pump):
    from src.experiment.engine import ExperimentEngine
    from src.experiment.experiment_logger import ExperimentLogger
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    log = ExperimentLogger(save_log=False)
    engine = ExperimentEngine(StepExecutor(dm), log)
    engine.load_steps([ExperimentStep('asp', ActionType.SYRINGE_ASPIRATE,
                      {'device_id': 'syringe_pump1', 'volume': 100})])
    records = []
    original = log.finish_run
    def capture(*a, **kw):
        records.extend(log.active_run.steps)
        return original(*a, **kw)
    log.finish_run = capture
    async def scenario():
        await engine.start()
        await engine._task
    asyncio.run(scenario())
    result = records[0]['device_result']
    assert result['action']['result'] == 'completed'
    assert result['action']['theoretical_delta_ul'] == 100


@pytest.mark.parametrize('filename', ['syringe_single_water.yaml', 'syringe_dual_water.yaml'])
def test_examples_parse(filename):
    from src.experiment.parser import parse_experiment
    assert parse_experiment(filename)['steps']


def test_parser_rejects_wrong_device_type(tmp_path, monkeypatch):
    import src.experiment.parser as parser
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path)
    (tmp_path / 'bad.yaml').write_text('name: bad\nsteps:\n- id: x\n  type: syringe_pump.move\n  params: {device_id: heater1, position: 100}\n')
    with pytest.raises(ValueError, match='syringe_pump type'): parser.parse_experiment('bad.yaml')


def test_unconfigured_second_pump_preflight_fails_before_first_move(pump):
    from src.web.api import experiments
    app = FastAPI(); dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    dm.syringe_pumps['syringe_pump2'] = SyringeController(SyringePumpConfig(device_id='syringe_pump2'))
    app.state.device_manager = dm; app.include_router(experiments.router, prefix='/api')
    with TestClient(app) as client:
        response = client.post('/api/experiments/syringe_dual_water.yaml/start', json={'save_log': False})
    assert response.status_code == 409
    assert not pump.device.protocol.calls


def test_engine_reserves_all_pumps_before_any_action(pump):
    from src.experiment.engine import ExperimentEngine
    from src.experiment.experiment_logger import ExperimentLogger
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    dm.syringe_pumps['syringe_pump2'] = SyringeController(SyringePumpConfig(device_id='syringe_pump2'))
    executor = StepExecutor(dm)
    engine = ExperimentEngine(executor, ExperimentLogger(save_log=False))
    engine.load_steps([ExperimentStep(did, ActionType.SYRINGE_MOVE, {'device_id': did, 'position': 100})
                       for did in dm.syringe_pumps])
    with pytest.raises(RuntimeError): asyncio.run(engine.start())
    assert pump.owner is None and not pump.device.protocol.calls


def test_reserved_pump_blocks_manual_before_its_first_step(pump):
    dm = DeviceManager(); dm.syringe_pumps['syringe_pump1'] = pump
    executor = StepExecutor(dm)
    steps = [ExperimentStep('later', ActionType.SYRINGE_MOVE, {'device_id': 'syringe_pump1', 'position': 100})]
    asyncio.run(executor.reserve_syringes(steps))
    with pytest.raises(RuntimeError): pump.command({'action': 'move', 'position': 100})
    assert asyncio.run(executor.stop_active_devices())
    assert pump.owner is None and not pump.device.protocol.calls
