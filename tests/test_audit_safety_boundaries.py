"""Software-only regressions from the 2026-10-26 whole-project audit."""
import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from src.experiment import guided as guided_core, microwave_program as program
from src.web.api import devices, experiments, guided, microwave_program, syringe_pumps, valves


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    lock, registry = asyncio.Lock(), {}
    for module in (experiments, guided, microwave_program):
        monkeypatch.setattr(module, '_source_lock', lock)
        monkeypatch.setattr(module, '_engines', registry)
    monkeypatch.setattr(guided, '_batches', {})
    monkeypatch.setattr(microwave_program, '_runs', {})
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_desktop_exiting', False)


@pytest.mark.parametrize('endpoint,body,method', [
    ('heater/heater1/start', {}, 'start_heater'),
    ('pump/pump1/stop', {}, 'stop_pump_channel'),
    ('microwave/microwave1/start', {'mode': 'auto_power'}, 'start_microwave'),
    ('valve/valve1/switch', {'energized': True}, 'valve_operation'),
    ('syringe_pump/syringe_pump1/command', {'action': 'stop'}, 'syringe_command'),
])
@pytest.mark.parametrize('worker_fails', [False, True])
def test_cancelled_manual_request_retains_registration_lock(endpoint, body, method, worker_fails):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def operation(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(3), 'Fake device was not released'
            if worker_fails:
                raise OSError('Fake communication failure')
            return {} if method == 'valve_operation' else True
        finally:
            finished.set()

    manager = SimpleNamespace(valves={'valve1': object()}, syringe=lambda _: object())
    setattr(manager, method, operation)
    app = FastAPI()
    app.state.device_manager = manager
    for router in (devices.router, valves.router, syringe_pumps.router):
        app.include_router(router, prefix='/api')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://audit') as client:
            request = asyncio.create_task(client.post('/api/' + endpoint, json=body))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                request.cancel()
                await asyncio.sleep(0.02)
                request.cancel()  # Repeated cancellation must not release the lock either.
                await asyncio.sleep(0.02)
                assert experiments._source_lock.locked(), 'Hardware worker outlived its registration lock'
                assert not request.done()
                assert not finished.is_set()
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await request
            assert finished.is_set()
            assert not experiments._source_lock.locked()

    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['guided', 'microwave'])
def test_unreadable_recovery_directory_blocks_start_but_allows_stop(monkeypatch, kind):
    directory = guided_core.BATCH_DIR if kind == 'guided' else program.PROGRAM_DIR
    directory.mkdir(parents=True, exist_ok=True)
    def deny_listing(original):
        def denied(path):
            if os.path.normcase(os.fspath(path)) == os.path.normcase(str(directory)):
                raise PermissionError('Recovery directory unavailable')
            return original(path)
        return denied

    monkeypatch.setattr(os, 'scandir', deny_listing(os.scandir))
    monkeypatch.setattr(Path, 'iterdir', deny_listing(Path.iterdir))
    start, stop = Mock(return_value=True), Mock(return_value=True)
    app = FastAPI()
    app.state.device_manager = SimpleNamespace(start_heater=start, stop_heater=stop)
    app.include_router(devices.router, prefix='/api')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://audit') as client:
            response = await client.post('/api/heater/heater1/start')
            assert response.status_code == 503, response.text
            start.assert_not_called()
            response = await client.post('/api/heater/heater1/stop')
            assert response.status_code == 200 and response.json()['success']
            stop.assert_called_once()

    asyncio.run(scenario())
