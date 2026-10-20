"""Raw starts clean up only their own attempted writes, without hardware."""
import asyncio
import threading
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.experiment.parameter_models import MicrowaveStartRequest
from src.protocols.microwave_params import CONTROL_MICROWAVE_START, CONTROL_WORD, auto_power_segment_start
from src.web.api.devices import start_microwave
from src.web.api import devices, experiments, guided, microwave_program
from src.web.device_manager import DeviceManager
from test_microwave_api_ws import make_request
from test_microwave_start_diagnostics import configured


@pytest.mark.parametrize('cleanup_ok', [True, False])
@pytest.mark.parametrize('failure', ['reload', 'write_exception'])
def test_raw_start_failure_cleans_up_and_keeps_original_error(failure, cleanup_ok):
    device, protocol = configured()
    device.STOP_READBACK_ATTEMPTS = 1
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    write = protocol.write_single_register

    def fail(slave, address, value):
        result = write(slave, address, value)
        if value & CONTROL_MICROWAVE_START:
            if failure == 'write_exception':
                raise IOError('start acknowledgement lost')
            protocol.registers[auto_power_segment_start(1)+3] = 5
        return result if value or cleanup_ok else False

    protocol.write_single_register = fail
    with pytest.raises(HTTPException) as caught:
        asyncio.run(start_microwave('mw1', MicrowaveStartRequest(mode='auto_power'), make_request(dm)))
    error = 'post-start configuration mismatch' if failure == 'reload' else 'start acknowledgement lost'
    assert error in caught.value.detail
    assert ('cleanup unconfirmed' in caught.value.detail) is (not cleanup_ok)
    assert protocol.single_writes[-1] == (1, CONTROL_WORD, 0)
    result = device.last_command_result
    assert result['command'] == 'start' and result['success'] is False
    assert result['failure_cleanup']['success'] is cleanup_ok
    events = dm.get_microwave_events('mw1', 0)[1]
    assert [event['action'] for event in events] == ['start', 'stop']
    assert error in events[0]['error']
    assert events[-1]['source'] == 'failure_cleanup'
    assert events[-1]['success'] is cleanup_ok
    frozen = deepcopy(events[0])
    assert dm.stop_microwave('mw1') is cleanup_ok
    assert events[0] == frozen


def test_raw_start_preflight_rejection_does_not_stop_an_existing_run():
    device, protocol = configured()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    assert dm.start_microwave('mw1', 'auto_power')
    prior_writes = list(protocol.single_writes)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(start_microwave('mw1', MicrowaveStartRequest(mode='auto_power'), make_request(dm)))
    assert 'idle' in caught.value.detail
    assert protocol.single_writes == prior_writes
    assert 'failure_cleanup' not in device.last_command_result
    assert not device.last_command_result['mode_selection_write_attempted']


def test_raw_mode_selection_failure_still_cleans_up_without_start():
    device, protocol = configured()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    write = protocol.write_single_register

    def fail_mode(slave, address, value):
        write(slave, address, value)
        return value == 0

    protocol.write_single_register = fail_mode
    assert not dm.start_microwave('mw1', 'auto_power', cleanup_on_failure=True)
    assert [value for _, _, value in protocol.single_writes] == [0x4000, 0]
    assert not device.last_command_result['start_write_attempted']
    assert device.last_command_result['failure_cleanup']['success'] is True
    assert 'mode-selection' in dm.get_last_command_error('mw1')


@pytest.fixture
def asgi_control_app(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('real serial forbidden')))
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(guided, '_batches', {})
    monkeypatch.setattr(microwave_program, '_runs', {})
    device, protocol = configured()
    device.STOP_READBACK_ATTEMPTS = 1
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    app = FastAPI()
    app.state.device_manager = dm
    app.include_router(devices.router, prefix='/api')
    app.include_router(experiments.router, prefix='/api')
    return app, dm, device, protocol


@pytest.mark.parametrize('phase', ['mode-selection', 'parameter-read'])
@pytest.mark.parametrize('cleanup_ok', [True, False])
def test_http_stop_preempts_start_while_source_lock_is_held(asgi_control_app, monkeypatch, phase, cleanup_ok):
    app, dm, device, protocol = asgi_control_app
    blocked, release, intent_seen = threading.Event(), threading.Event(), threading.Event()
    read, write = protocol.read_holding_registers, protocol.write_single_register
    stop_writes = 0

    def blocked_read(slave, address, count):
        mode_selected = protocol.registers.get(CONTROL_WORD) == 0x4000
        target = CONTROL_WORD if phase == 'mode-selection' else auto_power_segment_start(1)
        if mode_selected and address == target and not blocked.is_set():
            blocked.set()
            assert release.wait(5), 'test did not release startup verification'
        return read(slave, address, count)

    def cleanup_write(slave, address, value):
        nonlocal stop_writes
        result = write(slave, address, value)
        if address == CONTROL_WORD and value == 0:
            stop_writes += 1
            if stop_writes == 1 and not cleanup_ok:
                return False
        return result

    protocol.read_holding_registers = blocked_read
    protocol.write_single_register = cleanup_write
    publish_intent = dm.request_microwave_stop
    def observe_intent(device_id):
        publish_intent(device_id)
        intent_seen.set()
    monkeypatch.setattr(dm, 'request_microwave_stop', observe_intent)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
            start = asyncio.create_task(client.post('/api/microwave/mw1/start', json={'mode': 'auto_power'}))
            stop = None
            try:
                assert await asyncio.to_thread(blocked.wait, 2)
                assert experiments._source_lock.locked()
                generation = dm._microwave_generation('mw1')
                stop = asyncio.create_task(client.post('/api/microwave/mw1/stop'))
                assert await asyncio.to_thread(intent_seen.wait, 2), 'stop intent waited behind source lock'
                assert dm._microwave_generation('mw1') > generation
                assert not start.done() and not stop.done()
                assert not any(value & CONTROL_MICROWAVE_START for _, _, value in protocol.single_writes)
            finally:
                release.set()
                responses = await asyncio.wait_for(asyncio.gather(start, *([stop] if stop else [])), 3)
            return responses

    start_response, stop_response = asyncio.run(scenario())
    assert start_response.status_code == 400
    assert 'stop request' in start_response.json()['detail']
    assert ('cleanup unconfirmed' in start_response.json()['detail']) is (not cleanup_ok)
    assert stop_response.status_code == 200 and stop_response.json()['success'] is True
    assert not any(value & CONTROL_MICROWAVE_START for _, _, value in protocol.single_writes)
    assert [value for _, _, value in protocol.single_writes] == [0x4000, 0, 0]
    events = dm.get_microwave_events('mw1', 0)[1]
    assert [event['action'] for event in events] == ['start', 'stop', 'stop']
    assert events[0]['success'] is False and 'stop request' in events[0]['error']
    assert events[0]['result']['start_write_attempted'] is False
    assert events[1]['source'] == 'failure_cleanup' and events[1]['success'] is cleanup_ok
    assert events[2]['source'] == 'manual_stop' and events[2]['success'] is True


def test_http_unknown_stop_is_404_without_generation_or_io(asgi_control_app):
    app, dm, device, protocol = asgi_control_app
    before_writes, before_generations = list(protocol.single_writes), dict(dm._microwave_stop_generations)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test') as client:
            return await client.post('/api/microwave/unknown/stop')
    response = asyncio.run(scenario())
    assert response.status_code == 404
    assert 'not found' in response.json()['detail']
    assert dm._microwave_stop_generations == before_generations
    assert protocol.single_writes == before_writes


def test_manual_write_and_experiment_registration_still_wait_for_source_lock(asgi_control_app, monkeypatch):
    app, dm, device, protocol = asgi_control_app
    registered = []
    async def register(filename, body, request):
        assert experiments._source_lock.locked()
        registered.append(filename)
        return {'registered': filename}
    monkeypatch.setattr(experiments, '_start_experiment_locked', register)
    before_writes = list(protocol.multi_writes)

    async def scenario():
        arrived = set()
        both_arrived = asyncio.Event()
        async def on_request(request):
            arrived.add(request.url.path)
            if len(arrived) == 2:
                both_arrived.set()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://heat.test',
                                     event_hooks={'request': [on_request]}) as client:
            await experiments._source_lock.acquire()
            writes = asyncio.create_task(client.post('/api/microwave/mw1/configure/auto_power', json={
                'segments': [dict(segment=1, heating_temperature=60, holding_temperature=60, minutes=1)]}))
            registration = asyncio.create_task(client.post('/api/experiments/fake.yaml/start', json={}))
            try:
                await asyncio.wait_for(both_arrived.wait(), 1)
                await asyncio.sleep(0)
                assert not writes.done() and not registration.done()
                assert protocol.multi_writes == before_writes
                assert registered == []
            finally:
                experiments._source_lock.release()
            return await asyncio.wait_for(asyncio.gather(writes, registration), 3)

    write_response, register_response = asyncio.run(scenario())
    assert write_response.status_code == 200 and register_response.status_code == 200
    assert len(protocol.multi_writes) == len(before_writes) + 1
    assert registered == ['fake.yaml']
