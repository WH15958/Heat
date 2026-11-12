"""Paired manual controls tested against fake devices; never open serial ports."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.utils.config import ConfigManager, SystemConfig, TurntableConfig
from src.web.collection_control import CollectionAxisController
from src.web.turntable_control import TurntableController
from src.web.turntable_commands import CollectionCommand
from test_turntable_controller import FakeDevice, clock, no_hardware


class Platform(FakeDevice):
    speed = 0

    def read_status(self):
        state = super().read_status()
        state['speed_raw'] = self.speed
        self.snapshot = state
        return state

    def send_command(self, request):
        super().send_command(request)
        if request.action == 'stop' and self.stop_ok:
            self.speed = 0


@pytest.fixture
def pair(clock, monkeypatch):
    from src.web import collection_control, turntable_control
    monkeypatch.setattr(collection_control, 'time', turntable_control.time)
    rotation = CollectionAxisController(TurntableConfig(device_id='r', collection_axis='rotation',
        collection_peer='p', home_enabled=True, position_encoding_verified=True, action_timeout=180), FakeDevice())
    radial = CollectionAxisController(TurntableConfig(device_id='p', collection_axis='radial',
        collection_peer='r', position_encoding_verified=True, action_timeout=180), Platform())
    radial.lock = rotation.lock
    rotation.peer, radial.peer = radial, rotation
    for _ in range(3):
        clock.advance(.6)
        rotation.read(force=True); radial.read(force=True)
    return rotation, radial


def settle(c, clock, position):
    c.device.position = position
    c.device.work_state = 0x20
    for _ in range(3):
        clock.advance(.6); c.read(force=True)


def test_configuration_pair_and_legacy_isolation():
    config = ConfigManager('config/system_config.yaml').load()
    assert config.validate() == []
    assert [a.collection_axis for a in config.turntables] == ['rotation', 'radial']
    assert all(a.bottle_count == 0 for a in config.turntables)
    config.turntables[1].home_enabled = True
    assert config.validate()
    config.turntables[1].home_enabled = False
    config.turntables[1].collection_peer = 'missing'
    assert config.validate()


def test_current_configuration_rejects_legacy_automation(monkeypatch):
    from src.experiment import guided
    from src.experiment.parser import parse_experiment_data
    from test_guided import spec
    config = ConfigManager('config/system_config.yaml').load()
    monkeypatch.setattr(ConfigManager, 'load', lambda _: config)
    with pytest.raises(ValueError):
        guided.compile_plan(spec())
    with pytest.raises(ValueError):
        parse_experiment_data({'steps': [{'type': 'turntable.home_bottle',
            'params': {'device_id': 'turntable1'}}]}, validate_devices=True)


def test_platform_state20_with_speed_is_moving(pair, clock):
    r, p = pair
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    p.device.work_state = 0x20; p.device.speed = 1000
    clock.advance(.6)
    state = p.read(force=True)
    assert state['busy'] and not state['stop_confirmed']
    assert state['work_state'] == 0x20
    assert p.action['result'] == 'running'
    p.device.speed = 0
    settle(p, clock, -147246)
    assert p.action['result'] == 'completed' and p.stop_confirmed


def test_three_reads_required(pair, clock):
    r, p = pair
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    p.device.position = -147246; p.device.work_state = 32
    for _ in range(2):
        clock.advance(.6); p.read(force=True)
        assert p.action['result'] != 'completed'
    clock.advance(.6); p.read(force=True)
    assert p.action['result'] == 'completed'


def test_pair_excludes_second_motion(pair):
    r, p = pair
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    with pytest.raises(RuntimeError):
        p.command(dict(action='select_ring', ring=2, expected_position=0))
    assert not p.device.commands


def test_simultaneous_requests_only_one_moves(pair):
    r, p = pair
    barrier = threading.Barrier(2)
    def run(c, request):
        barrier.wait()
        try: c.command(request); return True
        except RuntimeError: return False
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(run, r, dict(action='select_bottle', bottle=2, expected_position=0))
        b = pool.submit(run, p, dict(action='select_ring', ring=2, expected_position=0))
        assert sum([a.result(), b.result()]) == 1
    assert len(r.device.commands) + len(p.device.commands) == 1


def test_coordinate_change_and_wrong_ring_rejected(pair):
    r, p = pair
    with pytest.raises(RuntimeError):
        r.command(dict(action='select_bottle', bottle=2, expected_position=100))
    with pytest.raises(ValueError):
        r.command(dict(action='select_bottle', bottle=29, expected_position=0))
    assert not r.device.commands


def test_round_from_origin_not_accumulated_step(pair, clock):
    r, p = pair
    r.command(dict(action='select_bottle', bottle=28, expected_position=0))
    assert r.device.commands[-1]['position'] == 138857
    settle(r, clock, 138857)
    r.command(dict(action='select_bottle', bottle=1, expected_position=138857))
    assert r.device.commands[-1]['position'] == 144000


def test_ring_move_allowed_at_nonzero_angle(pair, clock):
    r, p = pair
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    settle(r, clock, 5143)
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    assert p.device.commands[-1]['position'] == -147246
    assert r.device.position == 5143


def test_unsafe_and_legacy_commands_rejected(pair):
    r, p = pair
    for req in [dict(action='home', direction='negative', speed=1000),
                dict(action='move_absolute', position=0, speed=1000),
                dict(action='run', direction='positive', speed=1000),
                dict(action='next_bottle', expected_position=0, expected_bottle_token='x')]:
        with pytest.raises(ValueError): p.command(req)
    for c in pair:
        with pytest.raises(RuntimeError): c.claim(object())
    with pytest.raises(ValueError):
        TurntableController(TurntableConfig(), FakeDevice()).command(dict(action='select_ring', ring=1, expected_position=0))
    assert not p.device.commands


def test_jog_bounds(pair):
    r, p = pair
    with pytest.raises(ValueError): p.command(dict(action='move_relative', steps=50, speed=1000))
    with pytest.raises(ValueError): p.command(dict(action='move_relative', steps=-501, speed=1000))
    assert not p.device.commands


def test_timeout_requests_stop_does_not_replay(pair, clock):
    r, p = pair
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    p.device.reads.append(TimeoutError('0/8 bytes'))
    clock.advance(.6); p.enforce_timeout()
    assert [x['action'] for x in p.device.commands] == ['move_absolute', 'stop']
    assert p.action['result'] == 'failed'
    assert p.stop_confirmed
    # Recovery allows an explicit new request, never automatic replay.
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    assert len(p.device.commands) == 3


def test_stop_nonzero_speed_not_success(pair):
    r, p = pair
    p.device.speed = 1000; p.device.stop_ok = False
    assert not p.stop()
    assert p._requires_stop
    with pytest.raises(RuntimeError): r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    assert not r.device.commands


def test_removed_reference_command_rejected_and_extra_fields_rejected():
    with pytest.raises(ValueError): CollectionCommand(action='confirm_reference', expected_position=0)
    with pytest.raises(ValueError): CollectionCommand(action='select_ring', ring=2, bottle=29, expected_position=0)


def test_idle_read_failure_recovers_without_home_or_confirmation(pair, clock):
    r, p = pair
    p.device.reads.extend([TimeoutError('0/8 bytes'), TimeoutError('0/8 bytes')])
    clock.advance(.6)
    assert not p.read()['read_ok']
    settle(p, clock, 0)
    assert not r.homed
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    assert r.device.commands[-1]['position'] == 5143
    assert not p.device.commands


def test_peer_stop_invalidates_pending_request(pair):
    r, p = pair
    generation = r.generation
    r.begin_stop()
    with pytest.raises(RuntimeError): r.command(dict(action='select_bottle', bottle=2, expected_position=0), generation)
    r.end_stop()
    assert not r.device.commands


def test_peer_stop_cancels_queued_home(pair):
    r, p = pair
    generation = r.generation
    p.stop()
    with pytest.raises(RuntimeError, match='取消'):
        r.command(dict(action='home', direction='negative', speed=1000), generation)
    assert not r.device.commands


def test_global_stop_reaches_both_even_if_first_fails(pair):
    from src.web.device_manager import DeviceManager
    r, p = pair
    dm = DeviceManager(); dm.turntables = {'r': r, 'p': p}
    r.device.stop_ok = False; r.device.work_state = 1
    assert not dm.emergency_stop_all()
    assert r.device.commands[-1]['action'] == 'stop'
    assert p.device.commands[-1]['action'] == 'stop'
    assert p.stop_confirmed and not r.stop_confirmed


def test_manual_api_and_experiment_guard(pair, monkeypatch, tmp_path):
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.web.api import experiments, turntables
    from src.web.device_manager import DeviceManager
    from types import SimpleNamespace
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr('src.experiment.yaml_recovery.RECOVERY_DIR', tmp_path / 'yaml')
    monkeypatch.setattr('src.experiment.guided.BATCH_DIR', tmp_path / 'guided')
    monkeypatch.setattr('src.experiment.microwave_program.PROGRAM_DIR', tmp_path / 'micro')
    app = FastAPI(); app.include_router(turntables.router, prefix='/api')
    dm = DeviceManager(); r, p = pair; dm.turntables = {'r': r, 'p': p}; app.state.device_manager = dm
    with TestClient(app) as client:
        response = client.post('/api/turntable/r/command', json=dict(action='select_bottle', bottle=2, expected_position=0))
        assert response.status_code == 200
        assert response.json()['result']['result'] == 'accepted'
        assert client.post('/api/turntable/p/command', json=dict(action='select_ring', ring=2, expected_position=0)).status_code == 409
        assert client.post('/api/turntable/r/command', json=dict(action='stop')).status_code == 200
        monkeypatch.setattr(experiments, '_engines', {'test': SimpleNamespace(state=SimpleNamespace(value='running'), cleanup_pending=False)})
        assert client.post('/api/turntable/p/command', json=dict(action='select_ring', ring=2, expected_position=0)).status_code == 409


def test_short_home_is_observed_before_next_supervisor_tick(pair, clock):
    r, p = pair
    original = r.device.send_command
    def send(request):
        original(request)
        if request.action == 'home':
            r.device.reads.append((0, 8))
    r.device.send_command = send
    result = r.command(dict(action='home', direction='negative', speed=1000))
    assert result['result'] == 'running'
    assert r.action['saw_homing']
    r.device.position, r.device.work_state = 0, 32
    for _ in range(3):
        clock.advance(.1)
        r.read()
    assert r.homed and r.action['result'] == 'completed'
    assert not p.device.commands


def test_zero_alone_still_cannot_confirm_home(pair, clock):
    r, p = pair
    original = r.device.send_command
    def send(request):
        original(request)
        r.device.position, r.device.work_state = 0, 32
    r.device.send_command = send
    r.command(dict(action='home', direction='negative', speed=1000))
    for _ in range(3):
        clock.advance(.1)
        r.read()
    assert not r.homed
    assert r.action['result'] == 'unknown'
    assert r._requires_stop


def test_platform_retains_query_spacing(pair, clock):
    r, p = pair
    before = p.device.read_count
    clock.advance(.1)
    p.read()
    assert p.device.read_count == before
    clock.advance(.4)
    p.read()
    assert p.device.read_count == before + 1


@pytest.mark.parametrize('action,value', [('platform_absolute', -123456), ('platform_relative', -123456)])
def test_advanced_move_then_return_to_calibrated_ring(pair, clock, action, value):
    r, p = pair
    field = 'position' if action == 'platform_absolute' else 'steps'
    p.command(dict(action=action, expected_position=0, **{field: value}))
    assert p.device.commands[-1]['position'] == -123456
    settle(p, clock, -123456)
    p.command(dict(action='select_ring', ring=2, expected_position=-123456))
    assert p.device.commands[-1]['position'] == -147246
    assert not r.device.commands


@pytest.mark.parametrize('action,field,value', [
    ('platform_absolute', 'position', 1), ('platform_absolute', 'position', -444104),
    ('platform_relative', 'steps', 1), ('platform_relative', 'steps', -444104),
    ('platform_relative', 'steps', 0), ('platform_absolute', 'position', 1.5)])
def test_advanced_rejects_invalid_target_without_writes(pair, action, field, value):
    r, p = pair
    with pytest.raises(ValueError):
        p.command(dict(action=action, expected_position=0, **{field: value}))
    assert not p.device.commands


def test_advanced_requires_fresh_coordinate_but_not_start_angle(pair, clock):
    r, p = pair
    with pytest.raises(RuntimeError, match='坐标'):
        p.command(dict(action='platform_relative', steps=-1000, expected_position=-1))
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    settle(r, clock, 5143)
    p.command(dict(action='platform_absolute', position=-1000, expected_position=0))
    assert p.device.commands[-1]['position'] == -1000
    assert r.device.position == 5143


def test_return_start_works_between_rings_without_moving_platform(pair, clock):
    r, p = pair
    p.command(dict(action='platform_absolute', position=-123456, expected_position=0))
    settle(p, clock, -123456)
    r.command(dict(action='move_relative', steps=100, speed=1000))
    settle(r, clock, 100)
    before = len(p.device.commands)
    r.command(dict(action='return_start', expected_position=100))
    assert r.device.commands[-1]['position'] == 0
    assert len(p.device.commands) == before
    settle(r, clock, 0)
    p.command(dict(action='select_ring', ring=2, expected_position=-123456))
    assert p.device.commands[-1]['position'] == -147246


def test_advanced_minimum_and_maximum_and_relative_from_nonzero(pair, clock):
    r, p = pair
    p.command(dict(action='platform_absolute', position=-444103, expected_position=0))
    settle(p, clock, -444103)
    p.command(dict(action='platform_relative', steps=444103, expected_position=-444103))
    assert p.device.commands[-1]['position'] == 0
    settle(p, clock, 0)
    p.command(dict(action='platform_absolute', position=0, expected_position=0))
    assert p.device.commands[-1]['position'] == 0


def test_advanced_cancelled_by_peer_stop(pair):
    r, p = pair
    generation = p.generation
    r.stop()
    with pytest.raises(RuntimeError, match='取消'):
        p.command(dict(action='platform_absolute', position=-1000, expected_position=0), generation)
    assert not p.device.commands


def test_stop_then_explicit_move_needs_no_rehome(pair):
    r, p = pair
    assert r.stop() and p.stop()
    assert not r.homed
    r.command(dict(action='select_bottle', bottle=3, expected_position=0))
    assert r.device.commands[-1]['position'] == 10286


def test_idle_timeout_retries_once_without_writes(pair, clock):
    r, p = pair
    before = p.device.read_count
    p.device.reads.append(TimeoutError('0/8 bytes'))
    clock.advance(.6)
    state = p.read()
    assert state['read_ok'] and state['stop_confirmed']
    assert p.device.read_count == before + 2
    assert not p.device.commands


def test_idle_timeout_retry_failure_is_not_hidden(pair, clock):
    r, p = pair
    before = p.device.read_count
    p.device.reads.extend([TimeoutError('first'), TimeoutError('second')])
    clock.advance(.6)
    state = p.read()
    assert not state['read_ok'] and not state['stop_confirmed']
    assert p.device.read_count == before + 2
    assert not p.device.commands


def test_retry_changed_coordinate_requires_new_stability(pair, clock):
    r, p = pair
    p.device.reads.extend([TimeoutError('first'), (-100, 32)])
    clock.advance(.6)
    state = p.read()
    assert state['read_ok'] and not state['stop_confirmed']
    assert state['motion_blocked']
    assert not p.device.commands


def test_invalid_reply_not_retried_as_timeout(pair, clock):
    r, p = pair
    before = p.device.read_count
    p.device.reads.append(OSError('invalid frame'))
    clock.advance(.6)
    assert not p.read()['read_ok']
    assert p.device.read_count == before + 1


def test_stop_request_suppresses_idle_retry(pair, clock):
    r, p = pair
    original = p.device.read_status
    before = p.device.read_count
    def interrupted():
        r.begin_stop()
        return original()
    p.device.reads.append(TimeoutError('first'))
    p.device.read_status = interrupted
    clock.advance(.6)
    try:
        assert not p.read()['read_ok']
        assert p.device.read_count == before + 1
    finally:
        r.end_stop()


@pytest.mark.parametrize('ring', [1, 2, 3, 4])
@pytest.mark.parametrize('error', [-11, -10, -1, 0, 1, 10, 11])
def test_platform_tolerance_and_bottle_selection(pair, clock, ring, error):
    r, p = pair
    target = p.config.ring_positions[ring - 1]
    p.command(dict(action='select_ring', ring=ring, expected_position=0))
    actual = target + error
    settle(p, clock, actual)
    assert p.device.position == actual
    assert len(p.device.commands) == 1  # Never send a corrective move.
    if abs(error) <= 10:
        assert p.action['result'] == 'completed'
        assert p.action['actual_position'] == actual
        assert p.action['position_error'] == error
        assert p._ring_index(actual) == ring - 1
        first = 1 + sum(p.config.ring_counts[:ring - 1])
        r.command(dict(action='select_bottle', bottle=first, expected_position=0))
        assert r.device.commands[-1]['position'] == 0
    else:
        assert p.action['result'] == 'unknown'
        assert str(target) in p.action['error'] and str(actual) in p.action['error']
        assert p._ring_index(actual) == -1
        with pytest.raises(RuntimeError):
            r.command(dict(action='select_bottle', bottle=1, expected_position=0))


def test_tolerance_does_not_relax_stability_or_speed(pair, clock):
    r, p = pair
    p.command(dict(action='select_ring', ring=2, expected_position=0))
    p.device.work_state = 32
    for position in [-147245, -147244, -147245]:
        p.device.position = position
        clock.advance(.6); p.read(force=True)
        assert p.action['result'] != 'completed'
    p.device.speed = 1
    settle(p, clock, -147245)
    assert p.action['result'] == 'running'
    p.device.speed = 0
    for _ in range(2):
        clock.advance(.6); p.read(force=True)
        assert p.action['result'] != 'completed'
    clock.advance(.6); p.read(force=True)
    assert p.action['result'] == 'completed'


def test_rotation_remains_exact_and_expected_position_is_not_tolerant(pair, clock):
    r, p = pair
    assert r.summary()['position_tolerance'] == 0
    assert p.summary()['position_tolerance'] == 10
    with pytest.raises(RuntimeError, match='坐标'):
        p.command(dict(action='select_ring', ring=2, expected_position=1))
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    settle(r, clock, 5144)
    assert r.action['result'] == 'unknown'


def test_return_start_allowed_at_tolerated_endpoint(pair, clock):
    r, p = pair
    p.command(dict(action='select_ring', ring=1, expected_position=0))
    settle(p, clock, 10)
    r.command(dict(action='return_start', expected_position=0))
    assert r.device.commands[-1]['position'] == 0


@pytest.mark.parametrize("ring", [1, 2, 3, 4])
def test_ring_buttons_use_faster_speed(pair, ring):
    _, p = pair
    p.command(dict(action='select_ring', ring=ring, expected_position=0))
    assert p.device.commands[-1]['speed'] == 5000
    assert p.device.commands[-1]['position'] == p.config.ring_positions[ring - 1]


@pytest.mark.parametrize("command", [
    dict(action='platform_absolute', position=-1000, expected_position=0),
    dict(action='platform_relative', steps=-1000, expected_position=0),
])
def test_platform_advanced_moves_keep_low_speed(pair, command):
    _, p = pair
    p.command(command)
    assert p.device.commands[-1]['speed'] == 1000


def test_rotation_bottle_keeps_low_speed(pair):
    r, _ = pair
    r.command(dict(action='select_bottle', bottle=2, expected_position=0))
    assert r.device.commands[-1]['speed'] == 1000


@pytest.mark.parametrize("position,target", [
    (20571, 0), (123429, 144000), (71999, 0),
    (72000, 144000), (72001, 144000), (0, 0),
    (144000, 144000), (164571, 144000), (267429, 288000),
    (-100, 0), (-143900, -144000), (-72000, 0),
    (-144000, -144000), (-164571, -144000),
])
def test_return_start_chooses_shortest_direction(pair, clock, position, target):
    r, p = pair
    settle(r, clock, position)
    before = len(p.device.commands)
    r.command(dict(action='return_start', expected_position=position))
    assert r.device.commands[-1]['position'] == target
    assert r.device.commands[-1]['speed'] == 1000
    assert abs(target - position) <= 72000
    assert len(p.device.commands) == before
    settle(r, clock, target)
    assert r.action['result'] == 'completed'
