"""Turntable/experiment exclusion and desktop STOP access; no serial hardware."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, Request

from src.desktop.lifecycle import DesktopShutdownMiddleware
from src.experiment import guided as guided_core, microwave_program as program, parser
from src.web.api import devices, experiments, guided, microwave_program, turntables
from src.utils.config import TurntableConfig
from src.web.device_manager import DeviceManager
from src.web.turntable_control import TurntableController
from test_guided import spec as guided_spec
from test_turntable_controller import FakeDevice


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No physical serial access')))
    registry, lock = {}, asyncio.Lock()
    for module in (experiments, guided, microwave_program):
        monkeypatch.setattr(module, '_engines', registry)
        monkeypatch.setattr(module, '_source_lock', lock)
    monkeypatch.setattr(guided, '_batches', {})
    monkeypatch.setattr(microwave_program, '_runs', {})
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr('src.experiment.yaml_recovery.RECOVERY_DIR', tmp_path / 'recovery')
    monkeypatch.setattr(guided_core, 'BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr(program, 'PROGRAM_DIR', tmp_path / 'programs')
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path)
    monkeypatch.setattr('src.experiment.experiment_logger.LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr('src.science.sample_record.SAMPLES_DIR', tmp_path / 'samples')
    monkeypatch.setattr('src.science.sample_record.SAMPLES_CSV', tmp_path / 'samples' / 'samples.csv')


def app_with_manager(dm):
    app = FastAPI()
    app.state.device_manager = dm
    for router in (experiments.router, guided.router, microwave_program.router):
        app.include_router(router, prefix='/api')
    return app


async def post(app, path, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
        return await client.post(path, json=body)


def program_spec():
    return program.ProgramRequest(request_id='a' * 32, mode='auto_power',
        stages=[dict(temperature=30, hold_seconds=0)], hardware_confirmed=True).model_dump()


def guarded_manager(error=None):
    def check():
        assert experiments._source_lock.locked()
        if error:
            raise RuntimeError(error)
    return SimpleNamespace(require_turntables_idle=Mock(side_effect=check))


@pytest.fixture
def manual_turntable_app():
    dm = DeviceManager()
    control = TurntableController(TurntableConfig(), device=FakeDevice())
    control.read()
    dm.turntables['turntable1'] = control
    app = app_with_manager(dm)
    app.include_router(turntables.router, prefix='/api')
    app.include_router(devices.router, prefix='/api')
    return app, control


def write_batch_record(record):
    batch_id = 'guided_' + 'd' * 32
    guided_core.BATCH_DIR.mkdir(parents=True, exist_ok=True)
    path = guided_core.BATCH_DIR / (batch_id + '.json')
    path.write_text(json.dumps(dict(batch_id=batch_id, **record)), encoding='utf-8')
    return batch_id, path


async def read_and_stop_turntable(client, control):
    response = await client.get('/api/turntable/turntable1/status')
    assert response.status_code == 200 and response.json()['read_ok'] is True
    response = await client.post('/api/turntable/turntable1/command', json={'action': 'stop'})
    assert response.status_code == 200 and response.json()['state']['stop_confirmed'] is True
    assert [command['action'] for command in control.device.commands] == ['stop']


@pytest.mark.parametrize('state,cleanup', [('running', False), ('failed', True)])
def test_persistent_guided_recovery_blocks_manual_motion_after_restart_but_allows_read_and_stop(
        manual_turntable_app, state, cleanup):
    app, control = manual_turntable_app
    _, record_path = write_batch_record(dict(state=state, cleanup_required=cleanup))
    original_record = record_path.read_bytes()
    assert not experiments._engines and not guided._batches

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
            response = await client.post('/api/turntable/turntable1/command',
                                         json=dict(action='run', direction='positive', speed=400))
            assert response.status_code == 409, response.text
            assert '引导' in response.json()['detail']
            assert not control.device.commands
            await read_and_stop_turntable(client, control)
    asyncio.run(scenario())
    assert record_path.read_bytes() == original_record


@pytest.mark.parametrize('content', ['{', '{}', '[]'])
def test_damaged_guided_record_blocks_manual_motion_but_keeps_read_and_stop(
        manual_turntable_app, content):
    app, control = manual_turntable_app
    _, record_path = write_batch_record(dict(state='completed'))
    record_path.write_text(content, encoding='utf-8')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
            response = await client.post('/api/turntable/turntable1/command',
                                         json=dict(action='run', direction='positive', speed=400))
            assert response.status_code == 503, response.text
            assert not control.device.commands
            await read_and_stop_turntable(client, control)
    asyncio.run(scenario())
    assert record_path.read_text(encoding='utf-8') == content


def test_confirmed_guided_recovery_releases_manual_motion_without_replaying_batch(manual_turntable_app):
    app, control = manual_turntable_app
    batch_id, _ = write_batch_record(dict(state='failed', cleanup_required=True))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
            body = dict(action='run', direction='positive', speed=400)
            response = await client.post('/api/turntable/turntable1/command', json=body)
            assert response.status_code == 409
            assert not control.device.commands
            response = await client.post(f'/api/guided/{batch_id}/acknowledge-interrupted',
                                         json={'devices_stopped_confirmed': True})
            assert response.status_code == 200 and response.json()['recovery_required'] is False
            response = await client.post('/api/turntable/turntable1/command', json=body)
            assert response.status_code == 200, response.text
            assert [command['action'] for command in control.device.commands] == ['run']
    asyncio.run(scenario())
    assert not experiments._engines and not guided._batches


def test_persistent_guided_recovery_also_protects_existing_manual_device_routes(manual_turntable_app):
    app, _ = manual_turntable_app
    write_batch_record(dict(state='running'))
    start = Mock(side_effect=AssertionError('Recovery must reject before device access'))
    app.state.device_manager.start_heater = start
    response = asyncio.run(post(app, '/api/heater/heater1/start', {}))
    assert response.status_code == 409, response.text
    start.assert_not_called()


@pytest.mark.parametrize('state', ['active', 'unknown', 'stop_unconfirmed'])
@pytest.mark.parametrize('path', [
    '/api/experiments/demo.yaml/start', '/api/guided/prime', '/api/guided/start',
    '/api/microwave-program/microwave1/start', '/api/guided/start_ready',
])
def test_unsafe_turntable_blocks_every_new_start_before_side_effects(state, path, monkeypatch):
    dm = guarded_manager('turntable1: ' + state)
    app = app_with_manager(dm)
    constructors = [Mock(side_effect=AssertionError('Start must be rejected before construction')) for _ in range(3)]
    monkeypatch.setattr(experiments, 'ExperimentEngine', constructors[0])
    monkeypatch.setattr(guided_core, 'GuidedBatch', constructors[1])
    monkeypatch.setattr(program, 'MicrowaveProgramRun', constructors[2])
    begin = AsyncMock()
    body = {}
    if path.startswith('/api/guided/'):
        body = guided_spec().model_dump()
        if path.endswith('start_ready'):
            path = '/api/guided/start'
            body['priming_batch_id'] = 'guided_' + 'b' * 32
            guided._batches[body['priming_batch_id']] = SimpleNamespace(begin_experiments=begin)
    elif path.startswith('/api/microwave-program/'):
        body = program_spec()
    response = asyncio.run(post(app, path, body))
    assert response.status_code == 409
    assert response.json()['detail'] == 'turntable1: ' + state
    dm.require_turntables_idle.assert_called_once()
    for constructor in constructors:
        constructor.assert_not_called()
    begin.assert_not_awaited()
    assert not experiments._engines


@pytest.mark.parametrize('legacy_manager', [False, True])
def test_yaml_without_turntables_still_runs(tmp_path, legacy_manager):
    from src.web.device_manager import DeviceManager

    dm = SimpleNamespace() if legacy_manager else DeviceManager()
    (tmp_path / 'demo.yaml').write_text('name: demo\nsteps:\n- id: note\n  type: log\n  params: {message: hello}\n', encoding='utf-8')

    async def scenario():
        response = await post(app_with_manager(dm), '/api/experiments/demo.yaml/start', {'save_log': False})
        assert response.status_code == 200, response.text
        for engine in list(experiments._engines.values()):
            await engine._task
            assert engine.state.value == 'completed'
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['guided', 'microwave'])
def test_turntable_guard_rechecks_after_preflight_before_registration(kind, monkeypatch):
    dm = guarded_manager()
    app = app_with_manager(dm)
    runner = SimpleNamespace(dm=dm, batch_id='guided_' + 'c' * 32, start=AsyncMock(), snapshot=Mock())

    async def preflight(*args, **kwargs):
        dm.require_turntables_idle.side_effect = RuntimeError('turntable1: status became unknown')

    if kind == 'guided':
        monkeypatch.setattr(guided_core, 'GuidedBatch', Mock(return_value=runner))
        monkeypatch.setattr(guided_core, 'preflight', preflight)
        path, body = '/api/guided/start', guided_spec().model_dump()
    else:
        monkeypatch.setattr(program, 'MicrowaveProgramRun', Mock(return_value=runner))
        monkeypatch.setattr(program, 'preflight', preflight)
        path, body = '/api/microwave-program/microwave1/start', program_spec()
    response = asyncio.run(post(app, path, body))
    assert response.status_code == 409
    assert 'became unknown' in response.json()['detail']
    assert dm.require_turntables_idle.call_count == 2
    assert not experiments._engines and not guided._batches and not microwave_program._runs
    runner.start.assert_not_awaited()


@pytest.mark.parametrize('path', ['/api/guided/start', '/api/guided/prime'])
@pytest.mark.parametrize('phase', ['initial', 'after-preflight'])
@pytest.mark.parametrize('failure', [None, 'read', 'busy', 'reset', 'stop-unconfirmed', 'timeout', 'emergency'])
def test_guided_start_refreshes_stale_turntable_without_bypassing_guards(path, phase, failure, monkeypatch):
    from src.web.api.ws import DeviceReadCoordinator

    dm = DeviceManager()
    control = TurntableController(TurntableConfig(), device=FakeDevice())
    control.read()
    control._read_at -= 10
    dm.turntables['turntable1'] = control
    app = app_with_manager(dm)
    coordinator = DeviceReadCoordinator()
    app.state.device_read_coordinator = coordinator
    def inject_failure():
        if failure == 'read':
            control.device.reads.append(OSError('serial read failed'))
        elif failure in ('busy', 'reset'):
            control.device.work_state = 4 if failure == 'busy' else 0
        elif failure == 'stop-unconfirmed':
            control._requires_stop = True
        elif failure == 'timeout':
            coordinator.read = AsyncMock(side_effect=asyncio.TimeoutError())
        elif failure == 'emergency':
            read = control.read

            def read_then_stop():
                result = read()
                experiments._stop_generation += 1
                return result

            control.read = read_then_stop

    if phase == 'initial':
        inject_failure()
    runner = SimpleNamespace(dm=dm, batch_id='guided_' + 'e' * 32, cleanup_pending=False,
                             start=AsyncMock(), snapshot=lambda: {'state': 'running'})

    async def slow_preflight(*args, **kwargs):
        # Other device reads can consume more than the six-second validity window.
        control._read_at -= 10
        if phase == 'after-preflight':
            inject_failure()

    monkeypatch.setattr(guided_core, 'GuidedBatch', Mock(return_value=runner))
    monkeypatch.setattr(guided_core, 'preflight', slow_preflight)
    response = asyncio.run(post(app, path, guided_spec().model_dump()))
    assert not control.device.commands
    if failure in (None, 'reset'):
        assert response.status_code == 200, response.text
        runner.start.assert_awaited_once_with(prime_only=path.endswith('/prime'))
        assert control.device.read_count == 3
    else:
        assert response.status_code == 409, response.text
        runner.start.assert_not_awaited()
        assert not experiments._engines and not guided._batches


@pytest.mark.parametrize('blocking', ['owned', 'pending', 'stop_failed'])
def test_startup_reset_never_bypasses_previous_motion_or_ownership(blocking):
    dm = DeviceManager()
    control = TurntableController(TurntableConfig(), device=FakeDevice())
    control.device.work_state = 0
    control.read()
    if blocking == 'owned':
        control.owner = object()
    elif blocking == 'pending':
        control.action = {'result': 'unknown', 'action': 'home'}
    else:
        control._requires_stop = True
    dm.turntables['turntable1'] = control
    response = asyncio.run(post(app_with_manager(dm), '/api/guided/start', guided_spec().model_dump()))
    assert response.status_code == 409
    assert not control.device.commands


def test_ready_batch_rechecks_after_preflight_before_beginning(monkeypatch):
    dm = guarded_manager()
    started = []

    async def begin(spec, before_start):
        dm.require_turntables_idle.side_effect = RuntimeError('turntable1: status became unknown')
        before_start()
        started.append(True)

    batch_id = 'guided_' + 'b' * 32
    guided._batches[batch_id] = SimpleNamespace(begin_experiments=begin)
    response = asyncio.run(post(app_with_manager(dm), '/api/guided/start',
                               guided_spec(priming_batch_id=batch_id).model_dump()))
    assert response.status_code == 409
    assert not started and not experiments._engines
    assert dm.require_turntables_idle.call_count == 2


def test_ready_batch_refreshes_stale_turntable_before_beginning():
    dm = DeviceManager()
    control = TurntableController(TurntableConfig(), device=FakeDevice())
    control.read()
    control._read_at -= 10
    dm.turntables['turntable1'] = control
    started = []

    async def begin(spec, before_start):
        before_start()
        started.append(True)

    batch_id = 'guided_' + 'b' * 32
    guided._batches[batch_id] = SimpleNamespace(begin_experiments=begin, snapshot=lambda: {'state': 'running'})
    response = asyncio.run(post(app_with_manager(dm), '/api/guided/start',
                               guided_spec(priming_batch_id=batch_id).model_dump()))
    assert response.status_code == 200, response.text
    assert started == [True]
    assert not control.device.commands


def test_existing_microwave_request_is_returned_without_guard_or_replay(monkeypatch):
    dm = guarded_manager('turntable1: active')
    body = program_spec()
    existing = dict(program_id='mwprogram_' + body['request_id'], device_id='microwave1',
                    request=body, state='completed')
    monkeypatch.setattr(microwave_program, 'records', lambda: [existing])
    constructor = Mock(side_effect=AssertionError('Existing request must not replay'))
    monkeypatch.setattr(program, 'MicrowaveProgramRun', constructor)
    response = asyncio.run(post(app_with_manager(dm), '/api/microwave-program/microwave1/start', body))
    assert response.status_code == 200 and response.json() == existing
    dm.require_turntables_idle.assert_not_called()
    constructor.assert_not_called()


@pytest.mark.parametrize('action', ['run', 'move_relative', 'move_absolute', 'home', 'connect', None])
def test_desktop_exit_rejects_turntable_motion_but_replays_explicit_stop(action):
    app, commands = FastAPI(), []
    app.add_middleware(DesktopShutdownMiddleware)
    app.state.desktop_shutdown = SimpleNamespace(exiting=True)

    @app.post('/api/turntable/{device_id}/command')
    async def command(device_id: str, request: Request):
        payload = await request.json()
        commands.append((device_id, payload))
        return {'success': True}

    async def scenario():
        blocked = await post(app, '/api/turntable/turntable1/command', {'action': action})
        assert blocked.status_code == 409
        assert not commands
        stopped = await post(app, '/api/turntable/turntable1/command', {'action': 'stop'})
        assert stopped.status_code == 200
        assert commands == [('turntable1', {'action': 'stop'})]
    asyncio.run(scenario())
