"""Bottle indexing through real coordination/API guards, using fake hardware only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from src.protocols.turntable import TurntableProtocol
from src.devices.turntable_commands import MAX_POSITION
from src.utils.config import TurntableConfig
from src.web.turntable_control import TurntableController
from test_turntable_controller import FakeDevice, api_app, clock, no_hardware, stable_read


@pytest.fixture
def controller(clock):
    config = TurntableConfig(home_enabled=True, position_encoding_verified=True,
        bottle_count=12, pulses_per_bottle=12000, bottle_speed=1000,
        bottle_home_timeout=180)
    control = TurntableController(config, device=FakeDevice())
    control.read()
    return control


def home(control, clock):
    control.command({'action': 'home_bottle'})
    control.read()  # The fake observes the real home protocol command as 0x08.
    return stable_read(control, clock, 0)


def next_request(control):
    state = control.summary()
    return dict(action='next_bottle', expected_position=state['position'],
                expected_bottle_token=state['bottle_token'])


def assert_unknown(control):
    state = control.summary()
    assert state['current_bottle'] is None
    assert state['next_bottle'] is None
    assert state['bottle_token'] is None
    assert state['bottle_ready'] is False


def test_legacy_config_keeps_bottle_indexing_disabled(clock):
    control = TurntableController(TurntableConfig(home_enabled=True,
        position_encoding_verified=True), device=FakeDevice())
    control.read()
    assert control.summary()['bottle_count'] == 0
    with pytest.raises(RuntimeError):
        control.command({'action': 'home_bottle'})
    assert not control.device.commands


def test_coordinate_zero_at_startup_does_not_claim_bottle_one(controller):
    assert controller.summary()['position'] == 0
    assert_unknown(controller)
    with pytest.raises(RuntimeError):
        controller.command(dict(action='next_bottle', expected_position=0,
                                expected_bottle_token='not-a-confirmation'))
    assert not controller.device.commands


def test_home_one_uses_calibrated_direction_speed_and_own_deadline(controller, clock):
    result = controller.command({'action': 'home_bottle'})
    assert result['duration_seconds'] == 180
    assert controller.device.commands == [dict(action='home', direction='negative', speed=1000)]
    assert_unknown(controller)
    controller.read()
    state = stable_read(controller, clock, 0)
    assert state['action']['result'] == 'completed'
    assert state['current_bottle'] == 1 and state['next_bottle'] == 2
    assert state['bottle_ready'] and state['bottle_token']


def test_bottle_speed_increase_preserves_slow_homing(controller, clock):
    controller.config.bottle_speed = 4000
    controller.config.connection.port = 'TEST'
    assert not controller.config.validate()
    home(controller, clock)
    assert controller.device.commands[-1] == dict(action='home', direction='negative', speed=1000)
    controller.command(next_request(controller))
    assert controller.device.commands[-1] == dict(action='move_absolute', position=12000, speed=4000)
    assert stable_read(controller, clock, 12000)['current_bottle'] == 2


def test_fast_indexing_does_not_allow_short_home_timeout():
    config = TurntableConfig(bottle_count=12, bottle_speed=4000,
                            bottle_home_speed=1000, bottle_home_timeout=60)
    config.connection.port = 'TEST'
    assert config.validate()
    config.bottle_home_timeout = 180
    assert not config.validate()


@pytest.mark.parametrize('position,observe_homing', [(0, False), (1, True)])
def test_home_one_requires_homing_observation_and_exact_zero(controller, clock, position, observe_homing):
    controller.command({'action': 'home_bottle'})
    if observe_homing:
        controller.read()
    stable_read(controller, clock, position)
    assert controller.action['result'] == 'unknown'
    assert_unknown(controller)


def test_home_timeout_cannot_establish_bottle_reference(controller, clock):
    controller.command({'action': 'home_bottle'})
    controller.read()
    clock.advance(180)
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert_unknown(controller)
    assert [r['action'] for r in controller.device.commands] == ['home', 'stop']


def test_next_bottle_waits_for_target_confirmation_and_rejects_duplicates(controller, clock):
    home(controller, clock)
    body = next_request(controller)
    controller.command(body)
    assert controller.device.commands[-1] == dict(action='move_absolute', position=12000, speed=1000)
    assert_unknown(controller)
    with pytest.raises(RuntimeError):
        controller.command(body)
    state = stable_read(controller, clock, 12000)
    assert state['action']['result'] == 'completed'
    assert state['current_bottle'] == 2 and state['next_bottle'] == 3
    assert state['bottle_token'] != body['expected_bottle_token']
    writes = len(controller.device.commands)
    with pytest.raises(RuntimeError):
        controller.command(body)
    assert len(controller.device.commands) == writes


def test_twelve_to_one_continues_positive_without_coordinate_reset(controller, clock):
    home(controller, clock)
    for bottle in range(2, 13):
        controller.command(next_request(controller))
        state = stable_read(controller, clock, (bottle - 1) * 12000)
        assert state['current_bottle'] == bottle
    assert state['next_bottle'] == 1
    controller.command(next_request(controller))
    assert controller.device.commands[-1] == dict(action='move_absolute', position=144000, speed=1000)
    state = stable_read(controller, clock, 144000)
    assert state['current_bottle'] == 1 and state['next_bottle'] == 2
    assert state['position'] == 144000


def test_old_request_is_rejected_after_rehoming_to_same_zero(controller, clock):
    home(controller, clock)
    old = next_request(controller)
    home(controller, clock)
    assert old['expected_position'] == controller.summary()['position']
    assert old['expected_bottle_token'] != controller.summary()['bottle_token']
    before = len(controller.device.commands)
    with pytest.raises(RuntimeError):
        controller.command(old)
    assert len(controller.device.commands) == before


def test_old_request_is_rejected_by_new_controller_session(controller, clock):
    home(controller, clock)
    old = next_request(controller)
    fresh = TurntableController(controller.config, device=FakeDevice())
    fresh.read()
    home(fresh, clock)
    before = len(fresh.device.commands)
    with pytest.raises(RuntimeError):
        fresh.command(old)
    assert len(fresh.device.commands) == before


@pytest.mark.parametrize('cause', ['stop', 'read_error', 'reset', 'coordinate_drift', 'cable_loss'])
def test_loss_of_reference_cannot_recover_from_plain_stable_reads(controller, clock, cause):
    home(controller, clock)
    if cause == 'stop':
        assert controller.stop()
    elif cause == 'read_error':
        controller.device.reads.append(OSError('status lost'))
        controller.read()
    elif cause == 'reset':
        controller.device.work_state = 0
        controller.read()
    elif cause == 'coordinate_drift':
        controller.device.position = 12000
        controller.read()
    else:
        controller.device.connected = False
        controller.read()
        controller.device.connected = True
    assert_unknown(controller)
    stable_read(controller, clock, 0)
    assert_unknown(controller)


@pytest.mark.parametrize('body', [
    dict(action='move_relative', steps=100, speed=400),
    dict(action='move_absolute', position=0, speed=400),
    dict(action='run', direction='positive', speed=400, duration_seconds=1),
    dict(action='home', direction='negative', speed=400),
])
def test_advanced_motion_discards_bottle_reference(controller, clock, body):
    home(controller, clock)
    controller.command(body)
    assert_unknown(controller)
    controller.stop()
    stable_read(controller, clock, 0)
    assert_unknown(controller)


def test_target_mismatch_does_not_increment_bottle(controller, clock):
    home(controller, clock)
    controller.command(next_request(controller))
    stable_read(controller, clock, 11999)
    assert controller.action['result'] == 'unknown'
    assert_unknown(controller)
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert_unknown(controller)


def test_stale_status_hides_bottle_until_fresh_read_without_motion(controller, clock):
    home(controller, clock)
    before = len(controller.device.commands)
    clock.advance(7)
    assert controller.summary()['current_bottle'] is None
    assert not controller.summary()['bottle_ready']
    controller.read()
    assert len(controller.device.commands) == before


def test_stop_cancels_waiting_next_bottle_before_serial_lock(controller, clock):
    home(controller, clock)
    body = next_request(controller)
    before = len(controller.device.commands)
    stop_intent = threading.Event()
    original = controller.begin_stop
    def begin_stop():
        original()
        stop_intent.set()
    controller.begin_stop = begin_stop
    generation = controller.generation
    with ThreadPoolExecutor(max_workers=2) as workers:
        with controller.lock:
            moving = workers.submit(controller.command, body, expected_generation=generation)
            stopping = workers.submit(controller.stop)
            assert stop_intent.wait(2)
        with pytest.raises(RuntimeError):
            moving.result(timeout=2)
        assert stopping.result(timeout=2)
    assert [r['action'] for r in controller.device.commands[before:]] == ['stop']
    assert_unknown(controller)


@pytest.mark.parametrize('action', ['home_bottle', 'next_bottle'])
def test_api_read_is_passive_and_experiment_blocks_bottle_motion(api_app, controller, clock, action):
    from src.web.api import experiments

    home(controller, clock)
    body = next_request(controller) if action == 'next_bottle' else {'action': action}
    before = len(controller.device.commands)
    runner = SimpleNamespace(state=SimpleNamespace(value='running'), cleanup_pending=False, request_stop=Mock())
    experiments._engines['experiment.yaml'] = runner
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            response = await client.get('/api/turntable/turntable1/status')
            assert response.status_code == 200
            assert len(controller.device.commands) == before
            response = await client.post('/api/turntable/turntable1/command', json=body)
            assert response.status_code == 409
            assert len(controller.device.commands) == before
            response = await client.post('/api/turntable/turntable1/command', json={'action': 'stop'})
            assert response.status_code == 200
            runner.request_stop.assert_called_once()
    asyncio.run(scenario())


def test_api_next_bottle_and_stop_keep_shared_registration_fence(api_app, controller, clock):
    from src.web.api import experiments

    home(controller, clock)
    body = next_request(controller)
    before = len(controller.device.commands)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            await experiments._source_lock.acquire()
            try:
                moving = asyncio.create_task(client.post('/api/turntable/turntable1/command', json=body))
                await asyncio.sleep(0)
                stopping = asyncio.create_task(client.post('/api/turntable/turntable1/command', json={'action': 'stop'}))
                await asyncio.sleep(0)
                assert controller.stopping == 1
            finally:
                experiments._source_lock.release()
            moved, stopped = await asyncio.wait_for(asyncio.gather(moving, stopping), 2)
            assert moved.status_code == 409
            assert stopped.status_code == 200
            assert [r['action'] for r in controller.device.commands[before:]] == ['stop']
    asyncio.run(scenario())


@pytest.mark.parametrize('body', [
    dict(action='next_bottle', expected_position=True, expected_bottle_token='token'),
    dict(action='next_bottle', expected_position=0),
    dict(action='next_bottle', expected_position=0, expected_bottle_token='token', speed=1000),
    dict(action='next_bottle', expected_position=0, expected_bottle_token='token', steps=12000),
    dict(action='home_bottle', direction='positive'),
    dict(action='home_bottle', expected_position=0),
])
def test_invalid_bottle_requests_do_not_write(controller, body):
    with pytest.raises(ValueError):
        controller.command(body)
    assert not controller.device.commands


@pytest.mark.parametrize('body', [dict(action='home_bottle'),
    dict(action='next_bottle', expected_position=0, expected_bottle_token='token')])
def test_high_level_bottle_actions_cannot_reach_protocol(body):
    with pytest.raises(ValueError):
        TurntableProtocol.frame(body)


@pytest.mark.parametrize('updates', [
    dict(bottle_count=True), dict(bottle_count=-1), dict(pulses_per_bottle=0),
    dict(bottle_speed=399), dict(bottle_home_timeout=100),
    dict(bottle_home_speed=400, bottle_home_timeout=180),
    dict(bottle_home_speed=True), dict(bottle_home_speed=399),
    dict(bottle_home_speed=40001), dict(bottle_home_speed=1000.5),
])
def test_invalid_calibration_or_insufficient_home_timeout_is_rejected(updates):
    config = TurntableConfig(bottle_count=12, pulses_per_bottle=12000,
                            bottle_speed=1000, bottle_home_timeout=180)
    config.connection.port = 'TEST'
    assert not config.validate()
    for name, value in updates.items():
        setattr(config, name, value)
    assert config.validate()


def test_next_bottle_at_coordinate_limit_requires_rehoming_without_writing(controller, clock):
    home(controller, clock)
    # Arrange a confirmed bottle after many complete forward revolutions.
    position = (MAX_POSITION // controller.config.pulses_per_bottle) * controller.config.pulses_per_bottle
    controller._bottle_position = controller._stable_position = controller.device.position = position
    controller.read()
    before = len(controller.device.commands)
    with pytest.raises(ValueError, match='回到1号瓶'):
        controller.command(next_request(controller))
    assert len(controller.device.commands) == before
    assert controller.summary()['bottle_ready']
