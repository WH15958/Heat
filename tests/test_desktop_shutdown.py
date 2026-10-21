"""Desktop exit coordination uses fake managers and isolated experiment files."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from src.desktop.lifecycle import DesktopShutdown, DesktopShutdownMiddleware
from src.web.api import devices, experiments, syringe_pumps


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No physical serial access')))
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr('src.experiment.yaml_recovery.RECOVERY_DIR', tmp_path / 'recovery')
    monkeypatch.setattr('src.experiment.experiment_logger.LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr('src.science.sample_record.SAMPLES_DIR', tmp_path / 'samples')
    monkeypatch.setattr('src.science.sample_record.SAMPLES_CSV', tmp_path / 'samples' / 'samples.csv')


def app_with_manager(**changes):
    app = FastAPI()
    app.add_middleware(DesktopShutdownMiddleware)
    dm = SimpleNamespace(_begin_global_stop=Mock(), cleanup=Mock(return_value=True), **changes)
    app.state.device_manager = dm
    app.state.desktop_shutdown = DesktopShutdown(app)
    return app, dm


@pytest.mark.parametrize('kind', ['ordinary.yaml', 'guided-batch', 'microwave-program'])
def test_all_registered_runner_contracts_stop_and_finalize_before_cleanup(kind):
    async def scenario():
        app, dm = app_with_manager()
        runner = SimpleNamespace(request_stop=Mock(), stop=AsyncMock(return_value=True),
                                 record={'persistence_status': 'ok'})
        experiments._engines[kind] = runner

        def cleanup():
            runner.stop.assert_awaited_once()
            return True

        dm.cleanup.side_effect = cleanup
        assert await app.state.desktop_shutdown.shutdown() == {'success': True, 'errors': []}
        assert app.state.desktop_shutdown.succeeded
        assert experiments._stopping == 0
        dm._begin_global_stop.assert_called_once()
        assert await app.state.desktop_shutdown.shutdown() == {'success': True, 'errors': []}
        dm.cleanup.assert_called_once()
    asyncio.run(scenario())


def test_real_ordinary_engine_finishes_log_sample_and_recovery_before_cleanup():
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
    from src.experiment.experiment_logger import ExperimentLogger
    from src.experiment.executor import StepExecutor
    from src.experiment.yaml_recovery import PersistentExperimentEngine, new_record, records

    async def scenario():
        app, dm = app_with_manager()
        runner = PersistentExperimentEngine(StepExecutor(SimpleNamespace()), exp_logger=ExperimentLogger())
        runner.record = new_record('wait.yaml', 'steps: []')
        runner.load_steps([ExperimentStep(id='wait', type=ActionType.WAIT,
            wait=WaitCondition(type=WaitType.DURATION, seconds=600))], filename='wait.yaml')
        experiments._engines['wait.yaml'] = runner
        await runner.start()
        await asyncio.sleep(0)

        def cleanup():
            assert runner._task.done()
            assert runner.state.value == 'stopped'
            assert runner.exp_logger.active_run.persistence_status == 'ok'
            assert not records(experiments._engines)[0]['cleanup_required']
            return True

        dm.cleanup.side_effect = cleanup
        result = await app.state.desktop_shutdown.shutdown()
        assert result['success'], result
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [False, TimeoutError('device timed out')])
def test_device_failure_keeps_backend_and_allows_explicit_retry(failure):
    async def scenario():
        app, dm = app_with_manager()
        dm.cleanup.side_effect = [failure, True]
        coordinator = app.state.desktop_shutdown
        first = await coordinator.shutdown()
        assert first['success'] is False and first['errors']
        assert coordinator.exiting and not coordinator.succeeded
        assert await coordinator.shutdown() == {'success': True, 'errors': []}
        dm._begin_global_stop.assert_called_once()
        assert dm.cleanup.call_count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [False, RuntimeError('serial failed'), TimeoutError('serial timed out')])
@pytest.mark.parametrize('safety_action', [None, 'stop', 'emergency_stop'])
def test_runner_stop_failure_keeps_retry_connection_and_stops_manual_devices(failure, safety_action, monkeypatch):
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
    from src.experiment.experiment_logger import ExperimentLogger
    from src.experiment.executor import StepExecutor
    from src.experiment.yaml_recovery import PersistentExperimentEngine, new_record
    from src.web.device_manager import DeviceManager

    def heater(device_id, outcomes):
        device = SimpleNamespace(connected=True, config=SimpleNamespace(device_id=device_id))
        device.is_connected = lambda: device.connected
        device.stop = Mock(side_effect=outcomes)
        device.emergency_stop = Mock(return_value=True)

        def disconnect():
            device.connected = False
            return True

        device.disconnect = Mock(side_effect=disconnect)
        return device

    async def scenario():
        dm = DeviceManager()
        owned = heater('heater1', [failure, True, True, True, True])
        manual = heater('heater2', [True, True, True])
        dm._heaters.update(heater1=owned, heater2=manual)
        executor = StepExecutor(dm)
        runner = PersistentExperimentEngine(executor, exp_logger=ExperimentLogger())
        runner.record = new_record('wait.yaml', 'steps: []')
        runner.load_steps([ExperimentStep(id='wait', type=ActionType.WAIT,
            wait=WaitCondition(type=WaitType.DURATION, seconds=600))], filename='wait.yaml')
        experiments._engines['wait.yaml'] = runner
        await runner.start()
        executor._active_heaters.add('heater1')
        await asyncio.sleep(0)
        stop = AsyncMock(wraps=runner.stop)
        monkeypatch.setattr(runner, 'stop', stop)
        app = FastAPI()
        app.add_middleware(DesktopShutdownMiddleware)
        app.include_router(devices.router, prefix='/api')
        app.state.device_manager = dm
        coordinator = app.state.desktop_shutdown = DesktopShutdown(app)

        first = await coordinator.shutdown()
        assert first['success'] is False and first['errors']
        assert not coordinator.succeeded and coordinator.exiting
        assert owned.connected and manual.connected
        owned.disconnect.assert_not_called()
        manual.disconnect.assert_not_called()
        assert owned.stop.call_count == 2
        manual.stop.assert_called_once()
        stop.assert_awaited_once()  # Generic STOP cannot turn this attempt into success.
        assert executor._active_heaters == {'heater1'}
        assert runner.cleanup_pending and runner.record['cleanup_required']
        assert experiments._engines['wait.yaml'] is runner
        assert dm._global_stop_depth == 1

        if safety_action:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat') as client:
                path = '/api/heater/heater1/stop' if safety_action == 'stop' else '/api/emergency_stop'
                response = await client.post(path)
                assert response.status_code == 200 and response.json()['success'] is True

        retry = await coordinator.shutdown()
        assert retry == {'success': True, 'errors': []}
        assert not executor._active_heaters and not runner.record['cleanup_required']
        assert not owned.connected and not manual.connected
        owned.disconnect.assert_called_once()
        manual.disconnect.assert_called_once()

    asyncio.run(scenario())


def test_stop_only_cleanup_stops_manual_devices_and_retains_all_connections(monkeypatch):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    pump, microwave, syringe, valve = [Mock() for _ in range(4)]
    pump.is_connected.return_value = microwave.is_connected.return_value = True
    syringe.device.is_connected.return_value = True
    pump.stop_all.return_value = syringe.stop.return_value = True
    syringe.lock = threading.RLock()
    dm._pumps['pump1'] = pump
    dm._microwaves['microwave1'] = microwave
    dm.syringe_pumps['syringe1'] = syringe
    dm.valves['valve1'] = valve
    dm._valve_locks['valve1'] = threading.Lock()
    dm._valve_stop_generations['valve1'] = 0
    microwave_stop = Mock(return_value=True)
    monkeypatch.setattr(dm, '_stop_microwave_command', microwave_stop)

    assert dm.cleanup(disconnect=False) is True
    pump.stop_all.assert_called_once()
    syringe.stop.assert_called_once()
    microwave_stop.assert_called_once_with('microwave1', 'service_cleanup')
    for device in (pump, microwave, syringe.device, valve):
        device.disconnect.assert_not_called()
    assert dm._global_stop_depth == 0


@pytest.mark.parametrize('kind', ['stop-false', 'stop-timeout', 'record', 'log', 'pending-log'])
def test_engine_or_persistence_failure_is_not_reported_as_success(kind):
    async def scenario():
        app, dm = app_with_manager()
        runner = SimpleNamespace(request_stop=Mock(), stop=AsyncMock(return_value=kind != 'stop-false'),
                                 record={'persistence_status': 'ok'}, exp_logger=None)
        if kind == 'stop-timeout':
            runner.stop.side_effect = TimeoutError('serial timeout')
        if kind == 'record':
            runner.record['persistence_status'] = 'error'
        if kind in {'log', 'pending-log'}:
            runner.exp_logger = SimpleNamespace(active_run=SimpleNamespace(
                persistence_status='error' if kind == 'log' else 'pending'))
        experiments._engines['run'] = runner
        result = await app.state.desktop_shutdown.shutdown()
        assert result['success'] is False and result['errors']
        assert app.state.desktop_shutdown.exiting
        dm.cleanup.assert_called_once()  # Still stop devices after a log failure.
        assert experiments._engines['run'] is runner
    asyncio.run(scenario())


def test_timeout_does_not_cancel_stop_and_does_not_hold_source_lock():
    async def scenario():
        app, dm = app_with_manager()
        coordinator = app.state.desktop_shutdown
        coordinator.timeout = 0.01
        entered, release = asyncio.Event(), asyncio.Event()

        async def stop():
            entered.set()
            await release.wait()
            return True

        runner = SimpleNamespace(request_stop=Mock(), stop=AsyncMock(side_effect=stop))
        experiments._engines['slow'] = runner
        first = await coordinator.shutdown()
        assert entered.is_set() and first['success'] is False
        assert not coordinator._task.done()
        assert not experiments._source_lock.locked()
        assert experiments._stopping == 0
        release.set()
        coordinator.timeout = 2
        assert (await coordinator.shutdown())['success'] is True
        runner.stop.assert_awaited_once()
        dm.cleanup.assert_called_once()
    asyncio.run(scenario())


def test_shutdown_cancels_start_queued_on_source_lock():
    async def scenario():
        app, dm = app_with_manager()
        async with experiments._source_lock:
            starting = asyncio.create_task(experiments.start_experiment(
                'not-loaded.yaml', experiments.StartExperimentRequest(),
                SimpleNamespace(app=app)))
            await asyncio.sleep(0)
            stopping = asyncio.create_task(app.state.desktop_shutdown.shutdown())
            await asyncio.sleep(0)
        with pytest.raises(Exception) as caught:
            await starting
        assert caught.value.status_code == 409
        assert (await stopping)['success'] is True
        assert not experiments._engines
    asyncio.run(scenario())


def test_manager_fence_cancels_inflight_start_and_retains_stop_after_failure():
    from src.web.device_manager import DeviceManager
    from test_device_manager_control_races import _FakeControlDevice

    async def scenario():
        dm = DeviceManager()
        device = _FakeControlDevice('heater1')
        device.stop = Mock(return_value=False)
        dm._heaters['heater1'] = device
        app = FastAPI()
        app.state.device_manager = dm
        coordinator = DesktopShutdown(app)
        results = []
        starting = threading.Thread(target=lambda: results.append(dm.start_heater('heater1')),
                                    name='pending-device-start')
        starting.start()
        try:
            assert await asyncio.to_thread(device.pending_start_checked.wait, 1)
            assert (await coordinator.shutdown())['success'] is False
            assert dm._global_stop_depth == 1
            assert dm.start_heater('heater1') is False
            device.release_pending_start.set()
            await asyncio.to_thread(starting.join, 1)
            assert not starting.is_alive() and results == [False]
            assert device.start_calls == 0
            device.stop.return_value = True
            assert dm.stop_heater('heater1') is True
            assert (await coordinator.shutdown())['success'] is True
        finally:
            device.release_pending_start.set()
            await asyncio.to_thread(starting.join, 1)
    asyncio.run(scenario())


def test_after_failed_exit_real_stop_and_syringe_stop_remain_callable():
    async def scenario():
        app, dm = app_with_manager(stop_heater=Mock(return_value=True),
            syringe=Mock(return_value=SimpleNamespace()),
            syringe_command=Mock(return_value={'result': 'stopped'}))
        app.include_router(devices.router, prefix='/api')
        app.include_router(syringe_pumps.router, prefix='/api')
        dm.cleanup.return_value = False
        assert not (await app.state.desktop_shutdown.shutdown())['success']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat') as client:
            response = await client.post('/api/heater/heater1/stop')
            assert response.status_code == 200 and response.json()['success'] is True
            response = await client.post('/api/syringe_pump/pump1/command', json={'action': 'stop'})
            assert response.status_code == 200, response.text
            response = await client.post('/api/heater/heater1/start')
            assert response.status_code == 409
            response = await client.post('/api/syringe_pump/pump1/command', json={'action': 'initialize'})
            assert response.status_code == 409
        dm.stop_heater.assert_called_once_with('heater1')
        dm.syringe_command.assert_called_once_with('pump1', {'action': 'stop'})
    asyncio.run(scenario())


@pytest.mark.parametrize('path', [
    '/api/emergency_stop', '/api/guided/batch/stop', '/api/microwave-program/micro/stop',
    '/api/experiments/wait.yaml/stop', '/api/experiments/recovery/id/acknowledge',
    '/api/guided/batch/acknowledge-interrupted', '/api/microwave-program/micro/acknowledge-interrupted',
])
def test_exit_gate_keeps_safety_and_recovery_routes_available(path):
    app, dm = app_with_manager()
    app.state.desktop_shutdown.exiting = True

    @app.post(path)
    async def allowed():
        return {'allowed': True}

    with TestClient(app) as client:
        assert client.post(path).json() == {'allowed': True}


def test_exit_gate_blocks_writes_but_page_refresh_and_websocket_never_stop_devices():
    app, dm = app_with_manager()

    @app.get('/')
    async def page():
        return {'status': 'visible'}

    @app.post('/api/config')
    async def configure():
        return {'changed': True}

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_json({'status': 'read'})
        await ws.close()

    with TestClient(app) as client:
        for _ in range(2):
            assert client.get('/').status_code == 200
            with client.websocket_connect('/ws') as ws:
                assert ws.receive_json() == {'status': 'read'}
        dm.cleanup.assert_not_called()
        dm._begin_global_stop.assert_not_called()
        app.state.desktop_shutdown.exiting = True
        assert client.put('/api/config').status_code == 409
        assert client.patch('/api/config').status_code == 409
        assert client.post('/api/config').status_code == 409
        assert client.delete('/api/config').status_code == 409
        assert client.get('/').status_code == 200
        dm.cleanup.assert_not_called()


def test_lifespan_skips_hardware_cleanup_already_confirmed_by_desktop(monkeypatch):
    from src.web import app as web

    async def background(*args):
        await asyncio.Event().wait()

    monkeypatch.setenv('HEAT_DESKTOP_MODE', '1')
    monkeypatch.setattr(web, 'setup_logging', Mock())
    monkeypatch.setattr(web, 'data_push_loop', background)
    monkeypatch.setattr(web, 'syringe_supervisor', background)
    dm = SimpleNamespace(_begin_global_stop=Mock(), cleanup=Mock(return_value=True))
    monkeypatch.setattr(web, 'create_device_manager', lambda: dm)

    async def scenario():
        app = SimpleNamespace(state=SimpleNamespace())
        async with web.lifespan(app):
            assert (await app.state.desktop_shutdown.shutdown())['success']
        dm.cleanup.assert_called_once()
    asyncio.run(scenario())
