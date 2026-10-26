"""Recipe integration over the real coordinator, with no physical serial access."""
import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger
from src.experiment.parser import parse_experiment_data
from src.experiment.recipe_turntable import check_turntable_connections
from test_guided_turntable_control import rig, clock, no_hardware
from test_experiment_editor import setup, request


def raw(action, **kwargs):
    return dict(type='turntable.' + action, params={'device_id': 'turntable1'}, **kwargs)


def recipe(*actions, validate_devices=False):
    steps = [raw(a) if isinstance(a, str) else deepcopy(a) for a in actions]
    for i, step in enumerate(steps):
        step['id'] = str(i)
    return parse_experiment_data({'steps': steps}, validate_devices=validate_devices)['steps']


@pytest.fixture
def apparatus(rig, monkeypatch):
    monkeypatch.setattr('src.experiment.turntable_sequence.POLL_SECONDS', 0)
    dm = rig.dm
    rig.route = {'read_ok': True, 'relay_energized': True}
    rig.pump_status = {'channels': {str(n): {'read_ok': True, 'running': False, 'run_status': 'STOP'} for n in (3, 4)}}
    dm._pumps['pump1'] = SimpleNamespace(is_connected=lambda: True)
    dm.valves['valve1'] = SimpleNamespace(is_connected=lambda: True)
    dm._valve_locks['valve1'] = threading.RLock()
    dm._valve_stop_generations['valve1'] = 0
    dm.read_pump_status = Mock(side_effect=lambda _: deepcopy(rig.pump_status))
    dm.valve_operation = Mock(side_effect=lambda *args, **kwargs: deepcopy(rig.route))
    rig.syringes = {}
    for did in ('syringe_pump1', 'syringe_pump2'):
        control = SimpleNamespace(owner=None, device=SimpleNamespace(is_connected=lambda: True))
        control.read = Mock(return_value={'read_ok': True, 'busy': False})
        def claim(owner, c=control):
            if c.owner is not None and c.owner is not owner:
                raise RuntimeError('owned')
            c.owner = owner
        def release(owner, c=control):
            assert c.owner is owner
            c.owner = None
        control.claim, control.release = claim, release
        rig.syringes[did] = control
    dm.syringe = lambda did: rig.syringes[did]
    rig.executor = StepExecutor(dm)
    rig.logger = ExperimentLogger(save_log=False)
    rig.engine = ExperimentEngine(rig.executor, rig.logger)
    # Existing per-run sample semantics remain, but tests must never write lab data.
    monkeypatch.setattr('src.experiment.experiment_logger.write_sample_record', Mock())
    return rig


def test_parser_three_actions_and_rehome_after_stop():
    steps = recipe('home_bottle', 'next_bottle', 'stop', 'home_bottle', 'next_bottle')
    assert len(steps) == 5
    assert all(s.wait.type.value == 'none' and s.on_error == 'stop' for s in steps)


@pytest.mark.parametrize('steps', [
    ['next_bottle'], ['home_bottle', 'stop', 'next_bottle'],
    [raw('home_bottle', enabled=False), 'next_bottle'],
    ['home_bottle', {'type': 'emergency_stop'}, 'next_bottle'],
    [dict(raw('home_bottle'), params={'device_id': 'turntable1', 'speed': 4000})],
    [raw('home_bottle', on_error='skip')],
    [raw('home_bottle', wait={'type': 'duration', 'seconds': 1})],
    [dict(raw('home_bottle'), params={'device_id': ''})],
])
def test_parser_rejects_unsafe_recipe(steps):
    with pytest.raises(ValueError):
        recipe(*steps)


def test_parser_configured_capacity_and_unknown_device(rig, monkeypatch):
    monkeypatch.setattr('src.utils.config.ConfigManager.load', lambda _: SimpleNamespace(turntables=[rig.control.config]))
    assert len(recipe('home_bottle', *(['next_bottle'] * 11), validate_devices=True)) == 12
    with pytest.raises(ValueError):
        recipe('home_bottle', *(['next_bottle'] * 12), validate_devices=True)
    with pytest.raises(ValueError):
        recipe(dict(raw('home_bottle'), params={'device_id': 'other'}), validate_devices=True)
    assert rig.device.commands == []


def test_editor_reports_capacity_at_offending_step(rig, monkeypatch):
    from src.experiment.editor import validate_source
    from src.utils.config import SystemConfig
    monkeypatch.setattr('src.utils.config.ConfigManager.load', lambda _: SystemConfig(turntables=[rig.control.config]))
    steps = [dict(raw(a), id=str(i)) for i, a in enumerate(['home_bottle'] + ['next_bottle'] * 12)]
    result = validate_source(yaml.safe_dump({'steps': steps}))
    assert not result['valid']
    assert result['errors'][0]['step_id'] == '12'
    assert result['errors'][0]['path'] == ['steps', 12]
    assert not rig.device.commands


def test_authoring_roundtrip_and_progress_are_read_only(setup):
    root, app = setup
    content = yaml.safe_dump({'steps': [dict(raw(a), id=str(i)) for i, a in enumerate(('home_bottle', 'next_bottle', 'stop'))]})
    async def run():
        assert (await request(app, 'POST', '/validate', json={'content': content})).status_code == 200
        assert (await request(app, 'PUT', '/bottles.yaml/source', json={'content': content})).status_code == 200
        assert (await request(app, 'GET', '/bottles.yaml/source')).json()['content'] == content
        assert (await request(app, 'GET', '/bottles.yaml/progress')).status_code == 200
    asyncio.run(run())
    assert not app.state.device_manager.mock_calls


async def reserve(rig, steps):
    await rig.executor.reserve_valves(steps)
    await rig.executor.reserve_syringes(steps)
    await rig.executor.reserve_turntables(steps)


def test_complete_run_records_bottles_and_releases_without_final_home(apparatus):
    r = apparatus
    async def run():
        r.engine.load_steps(recipe('home_bottle', 'next_bottle'))
        await r.engine.start()
        await r.engine._task
        assert r.engine.state.value == 'completed'
        assert not r.engine.cleanup_pending
        assert [c['action'] for c in r.device.commands] == ['home', 'move_absolute']
        assert r.device.commands[1]['position'] == 12000
        result = r.executor.last_device_result
        assert result['from_bottle'] == 1 and result['current_bottle'] == 2
        assert result['action']['target_bottle'] == 2 and result['stop_confirmed']
        assert r.engine.progress.activity['devices']['turntable1']['current_bottle'] == 2
        assert r.control.owner is None and not r.dm._valve_owners
        assert all(s.owner is None for s in r.syringes.values())
        assert r.dm.read_pump_status.call_count == 2
        assert all(c.args == ('valve1', 'status') for c in r.dm.valve_operation.call_args_list)
        assert len(r.logger.active_run.steps) == 2
    asyncio.run(run())


def test_stop_rehome_and_fresh_run_reference(apparatus):
    r = apparatus
    async def run():
        steps = recipe('home_bottle', 'next_bottle', 'stop', 'home_bottle', 'next_bottle')
        await reserve(r, steps)
        for step in steps:
            assert await r.executor.execute(step)
        assert [c['action'] for c in r.device.commands] == ['home', 'move_absolute', 'stop', 'home', 'move_absolute']
        assert await r.executor.stop_active_devices(source='normal_cleanup')
        # The controller still knows bottle 2; a new run must not inherit it.
        await reserve(r, steps)
        assert not await r.executor.execute(steps[1])
        assert len(r.device.commands) == 5
        assert await r.executor.stop_active_devices()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['pump3', 'pump4', 'pump_read', 'syringe1', 'syringe2', 'syringe_read', 'valve', 'valve_read'])
def test_liquid_guard_fails_before_any_motion(apparatus, failure):
    r = apparatus
    if failure.startswith('pump'):
        ch = '4' if failure == 'pump4' else '3'
        r.pump_status['channels'][ch]['running' if failure != 'pump_read' else 'read_ok'] = failure != 'pump_read'
    elif failure.startswith('syringe'):
        did = 'syringe_pump2' if failure == 'syringe2' else 'syringe_pump1'
        r.syringes[did].read.return_value = {'read_ok': failure != 'syringe_read', 'busy': True}
    else:
        r.route['relay_energized' if failure == 'valve' else 'read_ok'] = False
    async def run():
        steps = recipe('home_bottle')
        await reserve(r, steps)
        assert not await r.executor.execute(steps[0])
        assert not r.device.commands
        # STOP is independent of the failed liquid interlock.
        assert await r.executor.execute(recipe('stop')[0])
        assert [c['action'] for c in r.device.commands] == ['stop']
        assert await r.executor.stop_active_devices()
    asyncio.run(run())


def test_stop_only_and_old_recipe_do_not_require_liquid_devices(rig):
    async def run():
        ex = StepExecutor(rig.dm)
        check_turntable_connections(rig.dm, [])
        rig.control.config.home_enabled = False
        steps = recipe('stop')
        await ex.reserve_turntables(steps)
        assert await ex.execute(steps[0])
        assert await ex.stop_active_devices()
    asyncio.run(run())


@pytest.mark.parametrize('missing', ['pump1', 'valve1', 'syringe_pump1', 'turntable1'])
def test_missing_or_disconnected_devices_reject_preflight_without_writes(apparatus, missing):
    r = apparatus
    if missing == 'pump1':
        r.dm._pumps.clear()
    elif missing == 'valve1':
        r.dm.valves.clear()
    elif missing == 'turntable1':
        r.device.connected = False
    else:
        r.syringes[missing].device.is_connected = lambda: False
    with pytest.raises((ValueError, RuntimeError)):
        check_turntable_connections(r.dm, recipe('home_bottle'))
    assert not r.device.commands


def test_runtime_last_bottle_never_wraps_and_explicit_home_can_return(apparatus):
    r = apparatus
    async def run():
        steps = recipe('home_bottle', *(['next_bottle'] * 12))
        await reserve(r, steps)
        for step in steps[:-1]:
            assert await r.executor.execute(step)
        assert r.control.summary()['current_bottle'] == 12
        assert not await r.executor.execute(steps[-1])
        assert len(r.device.commands) == 12
        assert await r.executor.execute(steps[0])
        assert r.control.summary()['current_bottle'] == 1
        assert await r.executor.stop_active_devices(source='normal_cleanup')
    asyncio.run(run())


def test_final_read_failure_retains_claim_and_recovery_record(apparatus, monkeypatch):
    from src.experiment import yaml_recovery as recovery
    r = apparatus
    engine = recovery.PersistentExperimentEngine(r.executor, exp_logger=r.logger)
    engine.record = recovery.new_record('bottles.yaml', 'test source')
    original = r.executor.stop_active_devices
    async def cleanup(**kwargs):
        if kwargs.get('source') == 'normal_cleanup':
            r.device.reads.append(OSError('lost final confirmation'))
        return await original(**kwargs)
    monkeypatch.setattr(r.executor, 'stop_active_devices', cleanup)
    async def run():
        engine.load_steps(recipe('home_bottle'))
        await engine.start()
        await engine.wait_finished()
        assert engine.state.value == 'failed' and engine.cleanup_pending
        assert r.control.owner is not None and r.dm._valve_owners
        record = recovery.records({'bottles.yaml': engine})[0]
        assert record['recovery_required'] and record['cleanup_required']
        await engine.stop()
        assert r.control.owner is None
        # Confirmed cleanup alone cannot erase the failed run's recovery lock.
        assert engine.record['recovery_required']
        assert [c['action'] for c in r.device.commands] == ['home', 'stop']
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['timeout', 'target', 'read', 'stop'])
def test_failures_never_retry_motion_and_stop_failure_keeps_resources(apparatus, monkeypatch, failure):
    r = apparatus
    if failure in ('timeout', 'stop'):
        r.device.complete = False
        r.control.config.bottle_home_timeout = .3
        r.device.stop_ok = failure != 'stop'
    elif failure == 'target':
        r.device.offset = 1
    else:
        original = r.device.send_command
        def send(command):
            original(command)
            if command.action == 'home':
                r.device.reads.append(OSError('lost read'))
        monkeypatch.setattr(r.device, 'send_command', send)
    async def run():
        r.engine.load_steps(recipe('home_bottle', 'next_bottle'))
        await r.engine.start()
        await r.engine._task
        assert r.engine.state.value == 'failed'
        assert sum(c['action'] == 'home' for c in r.device.commands) == 1
        assert all(c['action'] != 'move_absolute' for c in r.device.commands)
        assert r.engine.cleanup_pending == (failure == 'stop')
        if failure == 'stop':
            assert r.control.owner is not None and r.dm._valve_owners
            assert all(s.owner is not None for s in r.syringes.values())
            r.device.stop_ok = True
            await r.engine.stop()
            assert not r.engine.cleanup_pending
        assert r.control.owner is None
    asyncio.run(run())


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(poll(), 3)


def test_pause_finishes_sent_home_then_resumes_next_once(apparatus, monkeypatch):
    r = apparatus
    monkeypatch.setattr('src.experiment.turntable_sequence.POLL_SECONDS', .01)
    async def run():
        r.engine.load_steps(recipe('home_bottle', 'next_bottle'))
        await r.engine.start()
        await until(lambda: bool(r.device.commands))
        await r.engine.pause()
        await until(lambda: r.control.summary().get('current_bottle') == 1)
        assert r.engine.state.value == 'paused'
        assert [c['action'] for c in r.device.commands] == ['home']
        await r.engine.resume()
        await r.engine._task
        assert r.engine.state.value == 'completed'
        assert [c['action'] for c in r.device.commands] == ['home', 'move_absolute']
    asyncio.run(run())


def test_stop_fences_delayed_command_and_duplicate_start_does_not_replay(apparatus, monkeypatch):
    r = apparatus
    reached, proceed = threading.Event(), threading.Event()
    original = r.dm.turntable_command
    def delayed(*args, **kwargs):
        reached.set()
        assert proceed.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(r.dm, 'turntable_command', delayed)
    async def run():
        r.engine.load_steps(recipe('home_bottle', 'next_bottle'))
        await r.engine.start()
        assert await asyncio.to_thread(reached.wait, 2)
        await r.engine.start()
        r.engine.request_stop()
        proceed.set()
        await r.engine.stop()
        assert not r.engine.cleanup_pending and r.control.owner is None
        assert all(c['action'] == 'stop' for c in r.device.commands)
    asyncio.run(run())


@pytest.mark.parametrize('cancel', [False, True])
def test_start_failure_and_cancelled_claim_release_all_resources(apparatus, monkeypatch, cancel):
    r = apparatus
    reached, proceed = threading.Event(), threading.Event()
    original = r.syringes['syringe_pump2'].claim
    def claim(owner):
        if cancel:
            reached.set()
            assert proceed.wait(3)
            original(owner)
        else:
            raise RuntimeError('claim failure')
    r.syringes['syringe_pump2'].claim = claim
    async def run():
        r.engine.load_steps(recipe('home_bottle'))
        task = asyncio.create_task(r.engine.start())
        if cancel:
            assert await asyncio.to_thread(reached.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            proceed.set()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert all(s.owner is None for s in r.syringes.values())
        assert not r.dm._valve_owners and r.control.owner is None
        assert not r.device.commands
    asyncio.run(run())
