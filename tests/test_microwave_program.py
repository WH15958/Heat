"""Host orchestration tests with fake hardware and isolated persistent records."""
import asyncio
import copy
import threading
import time
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.experiment import microwave_program as program
from src.science import sample_record
from src.web.api import microwave_program as api, experiments, guided, devices
from test_guided import FakeManager, until
from test_microwave_atomic_config import make_device
from src.protocols.microwave_params import auto_power_segment_start, manual_segment_start, manual_hold_time_start


class Manager(FakeManager):
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.config_ok = self.start_ok = self.stop_ok = True
        self.fail_read = False

    def read_microwave_data(self, did):
        if self.fail_read:
            raise IOError("read failed")
        return dict(read_ok=True, material_temperature=self.temperature,
            fault_code=0, status_confirmed=True, control_active=self.microwave_on,
            output_active=self.microwave_on, stop_confirmed=not self.microwave_on)

    def configure_microwave_auto_power(self, did, segments):
        assert not self.microwave_on, 'configure while heating'
        self.configurations.append(segments)
        return super().configure_microwave_auto_power(did, segments) and self.config_ok

    configure_microwave_manual = configure_microwave_auto_power

    def start_microwave(self, did, mode):
        return super().start_microwave(did, mode) and self.start_ok

    def stop_microwave(self, did):
        self.calls.append(('microwave_stop', did))
        if self.stop_ok:
            self.microwave_on = False
        return self.stop_ok


def spec(**kwargs):
    return program.ProgramRequest(request_id='a'*32, mode='auto_power',
        stages=[dict(temperature=30, hold_seconds=0), dict(temperature=40, hold_seconds=0)],
        hardware_confirmed=True, **kwargs)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No real serial access')))
    monkeypatch.setattr(program, 'PROGRAM_DIR', tmp_path / 'programs')
    monkeypatch.setattr('src.experiment.experiment_logger.LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr(sample_record, 'SAMPLES_DIR', tmp_path / 'samples')
    monkeypatch.setattr(sample_record, 'SAMPLES_CSV', tmp_path / 'samples' / 'samples.csv')
    monkeypatch.setattr('src.experiment.guided.BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr(api, '_runs', {})
    registry = {}
    monkeypatch.setattr(api, '_engines', registry)
    monkeypatch.setattr(experiments, '_engines', registry)
    monkeypatch.setattr(guided, '_engines', registry)
    monkeypatch.setattr(guided, '_batches', {})
    lock = asyncio.Lock()
    for module in (api, experiments, guided):
        monkeypatch.setattr(module, '_source_lock', lock)


def app(dm):
    result = FastAPI()
    result.state.device_manager = dm
    for router in (api.router, devices.router, experiments.router, guided.router):
        result.include_router(router, prefix='/api')
    return result


@pytest.mark.parametrize('mode', ['auto_power', 'manual_power'])
def test_host_stages_stop_between_targets_and_replace_all_five_slots(mode):
    async def scenario():
        dm = Manager()
        body = spec().model_dump()
        body['mode'] = mode
        body['stages'][0]['power_percent'] = 20
        run = program.MicrowaveProgramRun(dm, 'microwave1', program.ProgramRequest(**body))
        await program.preflight(dm, 'microwave1')
        await run.start()
        await run.task
        assert run.state.value == 'completed'
        assert not run.cleanup_pending and not dm.microwave_on
        assert [c[0] for c in dm.calls] == ['microwave_config', 'microwave_start', 'microwave_stop'] * 2
        assert [[s.segment for s in config] for config in dm.configurations] == [list(range(1, 6))] * 2
        assert [{s.heating_temperature for s in config} for config in dm.configurations] == [{30}, {40}]
        assert all(s.hours == 0 and s.minutes == 11 and s.seconds == 0 for config in dm.configurations for s in config)
        record = program.stored_records({run.record['program_id']: run})[0]
        assert record['current_stage'] == 2
        assert record['state'] == 'completed'
        assert record['request']['stages'][0]['hold_seconds'] == 0
        assert record['run_id'] == run.exp_logger.active_run.run_id
        if mode == 'manual_power':
            assert all(s.heating_power_percent == 20 for s in dm.configurations[0])
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['config', 'start', 'stop', 'read'])
def test_failure_stops_and_blocks_next_stage(failure):
    async def scenario():
        dm = Manager()
        if failure != 'read':
            setattr(dm, failure + '_ok', False)
        else:
            original = dm.start_microwave
            def start(*args):
                result = original(*args)
                dm.fail_read = True
                return result
            dm.start_microwave = start
        run = program.MicrowaveProgramRun(dm, 'microwave1', spec())
        await run.start()
        await run.task
        assert run.state.value == 'failed'
        assert run.record['recovery_required']
        assert len(dm.configurations) == 1
        assert ('microwave_stop', 'microwave1') in dm.calls
        if failure != 'stop':
            assert not dm.microwave_on
        else:
            assert run.engine.cleanup_pending
            dm.stop_ok = True
            assert await run.stop()
            assert not dm.microwave_on
    asyncio.run(scenario())


def test_stop_during_hold_interrupts_no_second_stage():
    async def scenario():
        dm = Manager()
        body = spec().model_dump()
        body['stages'][0]['hold_seconds'] = 100
        run = program.MicrowaveProgramRun(dm, 'microwave1', program.ProgramRequest(**body))
        await run.start()
        await until(lambda: run.record['phase'] == 'hold')
        assert await asyncio.wait_for(run.stop(), timeout=2)
        assert run.state.value == 'stopped' and not dm.microwave_on
        assert len(dm.configurations) == 1
    asyncio.run(scenario())


def test_persistent_intent_required_before_any_writes(monkeypatch):
    dm = Manager()
    monkeypatch.setattr(program, 'write_record', Mock(side_effect=IOError('disk full')))
    run = program.MicrowaveProgramRun(dm, 'microwave1', spec())
    with pytest.raises(IOError):
        asyncio.run(run.start())
    assert not dm.calls


def test_previews_reads_and_invalid_requests_never_write_hardware():
    dm = Manager()
    with TestClient(app(dm)) as client:
        assert client.post('/api/microwave-program/microwave1/preview', json=spec().model_dump()).status_code == 200
        assert client.get('/api/microwave-program/microwave1/current').json()['state'] == 'idle'
        for mutation in [dict(mode='constant_rate'), dict(stages=[]), dict(hardware_confirmed=False),
                         dict(stages=[dict(temperature=301, hold_seconds=1)]),
                         dict(stages=[dict(temperature=30, hold_seconds=.5)])]:
            body = {**spec().model_dump(), **mutation}
            assert client.post('/api/microwave-program/microwave1/start', json=body).status_code in (409, 422)
    assert not dm.calls


def test_duplicate_start_id_not_replayed_and_other_controls_locked():
    dm = Manager()
    body = spec().model_dump()
    body['stages'][0]['hold_seconds'] = 100
    with TestClient(app(dm)) as client:
        first = client.post('/api/microwave-program/microwave1/start', json=body)
        assert first.status_code == 200
        assert client.post('/api/microwave-program/microwave1/start', json=body).json()['program_id'] == first.json()['program_id']
        changed = copy.deepcopy(body)
        changed['stages'][0]['temperature'] = 31
        assert client.post('/api/microwave-program/microwave1/start', json=changed).status_code == 409
        assert client.post('/api/microwave/microwave1/configure/auto_power', json={'segments': [dict(segment=1)]}).status_code == 409
        assert client.post('/api/guided/prime', json=__import__('test_guided').spec().model_dump()).status_code == 409
        program_id = first.json()['program_id']
        assert client.post('/api/experiments/'+program_id+'/pause').status_code == 409
        assert client.post('/api/experiments/'+program_id+'/resume').status_code == 409
        assert client.post('/api/microwave-program/microwave1/stop').json()['success']
        starts = dm.calls.count(('microwave_start', 'microwave1'))
        client.post('/api/microwave-program/microwave1/start', json=body)
        assert dm.calls.count(('microwave_start', 'microwave1')) == starts


def test_restart_requires_explicit_recovery_and_never_resumes():
    record = dict(program_id='mwprogram_'+'b'*32, device_id='microwave1', state='running',
        request=spec().model_dump(), created_at='2026-10-10T00:00:00Z', cleanup_required=True,
        recovery_required=False, phase='hold')
    program.write_record(record)
    dm = Manager()
    with TestClient(app(dm)) as client:
        assert client.get('/api/microwave-program/microwave1/current').json()['state'] == 'interrupted'
        assert client.post('/api/microwave-program/microwave1/start', json=spec().model_dump()).status_code == 409
        assert client.post('/api/experiments/any.yaml/start', json={}).status_code == 409
        assert client.post('/api/guided/prime', json=__import__('test_guided').spec().model_dump()).status_code == 409
        assert client.post('/api/microwave/microwave1/start', json={'mode':'auto_power'}).status_code == 409
        assert client.post('/api/microwave-program/microwave1/acknowledge-interrupted', json={'devices_stopped_confirmed':False}).status_code == 409
        assert client.post('/api/microwave-program/microwave1/acknowledge-interrupted', json={'devices_stopped_confirmed':True}).json()['success']
        assert not dm.calls
        assert not api.records()[0]['recovery_required']


@pytest.mark.parametrize('count', [1, 5])
def test_supported_stage_counts_and_custom_guard(count):
    body = spec().model_dump()
    body.update(stages=[dict(temperature=30, hold_seconds=123, power_percent=30)] * count,
                heating_timeout=37)
    steps = program.compile_steps('microwave1', program.ProgramRequest(**body))
    assert len(steps) == count * 4
    assert steps[0].params['segments'][0]['minutes'] == 3
    assert steps[0].params['segments'][0]['seconds'] == 40
    assert steps[1].wait.timeout == 37
    assert steps[2].wait.seconds == 123


@pytest.mark.parametrize('mutation', [dict(status_confirmed=False), dict(stop_confirmed=False),
    dict(fault_code=3), dict(material_temperature=float('nan')), dict(read_ok=False),
    dict(control_active=True), dict(output_active=True)])
def test_unknown_or_active_preflight_rejected_without_writes(mutation):
    dm = Manager()
    original = dm.read_microwave_data
    dm.read_microwave_data = lambda did: {**original(did), **mutation}
    with pytest.raises(ValueError):
        asyncio.run(program.preflight(dm, 'microwave1'))
    assert not dm.calls


def test_hold_clock_starts_after_target_reached():
    async def scenario():
        dm = Manager()
        dm.configure_microwave_auto_power = lambda did, segments: True
        dm.temperature = 20
        body = spec().model_dump()
        body['stages'] = [dict(temperature=30, hold_seconds=1)]
        run = program.MicrowaveProgramRun(dm, 'microwave1', program.ProgramRequest(**body))
        await run.start()
        await until(lambda: run.record['phase'] == 'heat')
        await asyncio.sleep(.25)
        assert run.record['phase'] == 'heat' and dm.microwave_on
        reached = time.monotonic()
        dm.temperature = 30
        await run.task
        assert time.monotonic() - reached >= 1
        assert run.state.value == 'completed' and not dm.microwave_on
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['fault', 'read', 'early_stop'])
def test_hold_failure_locks_and_does_not_start_next_target(failure):
    async def scenario():
        dm = Manager()
        body = spec().model_dump()
        body['stages'][0]['hold_seconds'] = 10
        run = program.MicrowaveProgramRun(dm, 'microwave1', program.ProgramRequest(**body))
        await run.start()
        await until(lambda: run.record['phase'] == 'hold')
        if failure == 'read':
            dm.fail_read = True
        elif failure == 'early_stop':
            dm.microwave_on = False
        else:
            original = dm.read_microwave_data
            dm.read_microwave_data = lambda did: {**original(did), 'fault_code': 3}
        await asyncio.wait_for(run.task, 3)
        assert run.state.value == 'failed' and run.record['recovery_required']
        assert len(dm.configurations) == 1 and not dm.microwave_on
    asyncio.run(scenario())


def test_heating_timeout_stops_and_locks():
    async def scenario():
        dm = Manager()
        original = dm.configure_microwave_auto_power
        def configure(*args):
            result = original(*args)
            dm.temperature = 20
            return result
        dm.configure_microwave_auto_power = configure
        run = program.MicrowaveProgramRun(dm, 'microwave1', spec(heating_timeout=1))
        await run.start()
        await asyncio.wait_for(run.task, 3)
        assert run.state.value == 'failed' and run.record['recovery_required']
        assert len(dm.configurations) == 1 and not dm.microwave_on
    asyncio.run(scenario())


def test_checkpoint_storage_failure_stops_and_preserves_restart_lock(monkeypatch):
    async def scenario():
        dm = Manager()
        original = program.write_record
        def write(record):
            if record['phase'] == 'hold' or record['state'] == 'failed':
                raise IOError('disk full')
            original(record)
        monkeypatch.setattr(program, 'write_record', write)
        run = program.MicrowaveProgramRun(dm, 'microwave1', spec())
        await run.start()
        await run.task
        assert run.state.value == 'failed' and run.record['recovery_required']
        assert len(dm.configurations) == 1 and not dm.microwave_on
        assert program.stored_records({})[0]['recovery_required']
        monkeypatch.setattr(program, 'write_record', original)
        assert await run.stop()
        assert program.stored_records({run.record['program_id']:run})[0]['persistence_status'] == 'ok'
    asyncio.run(scenario())


def test_stop_while_configuring_never_starts():
    async def scenario():
        dm = Manager()
        entered, release = threading.Event(), threading.Event()
        original = dm.configure_microwave_auto_power
        def configure(*args):
            entered.set()
            assert release.wait(2)
            return original(*args)
        dm.configure_microwave_auto_power = configure
        run = program.MicrowaveProgramRun(dm, 'microwave1', spec())
        await run.start()
        await until(entered.is_set)
        stopping = asyncio.create_task(run.stop())
        await asyncio.sleep(0)
        release.set()
        assert await stopping
        assert not any(c[0] == 'microwave_start' for c in dm.calls)
        assert len(dm.configurations) == 1
    asyncio.run(scenario())


def test_shutdown_stops_live_host_program():
    async def scenario():
        dm = Manager()
        body = spec().model_dump()
        body['stages'][0]['hold_seconds'] = 100
        run = program.MicrowaveProgramRun(dm, 'microwave1', program.ProgramRequest(**body))
        api._runs[run.record['program_id']] = run
        await run.start()
        await until(lambda: run.record['phase'] == 'hold')
        await api.shutdown()
        assert run.state.value == 'stopped' and not dm.microwave_on
        assert len(dm.configurations) == 1
    asyncio.run(scenario())


def test_failed_stop_and_failed_recovery_persistence_keep_lock(monkeypatch):
    dm = Manager()
    dm.start_ok = dm.stop_ok = False
    with TestClient(app(dm)) as client:
        client.post('/api/microwave-program/microwave1/start', json=spec().model_dump())
        for _ in range(100):
            status = client.get('/api/microwave-program/microwave1/current').json()
            if status['state'] == 'failed':
                break
        path = '/api/microwave-program/microwave1/acknowledge-interrupted'
        assert client.post(path, json={'devices_stopped_confirmed':True}).status_code == 409
        dm.stop_ok = True
        original = program.write_record
        def write(record):
            if not record['recovery_required']:
                raise IOError('disk full')
            original(record)
        monkeypatch.setattr(program, 'write_record', write)
        assert client.post(path, json={'devices_stopped_confirmed':True}).status_code == 503
        assert client.get('/api/microwave-program/microwave1/current').json()['recovery_required']
        monkeypatch.setattr(program, 'write_record', original)
        assert client.post(path, json={'devices_stopped_confirmed':True}).status_code == 200
        assert not client.get('/api/microwave-program/microwave1/current').json()['recovery_required']


def test_unreadable_storage_blocks_start():
    program.PROGRAM_DIR.mkdir()
    (program.PROGRAM_DIR / ('mwprogram_'+'a'*32+'.json')).write_text('{broken')
    dm = Manager()
    with TestClient(app(dm)) as client:
        assert client.post('/api/microwave-program/microwave1/start', json=spec().model_dump()).status_code == 503
    assert not dm.calls


@pytest.mark.parametrize('mode', ['auto_power', 'manual_power'])
def test_host_parameters_reach_known_registers_with_readback(mode):
    device, protocol = make_device()
    body = spec().model_dump()
    body['mode'] = mode
    step = program.compile_steps('microwave1', program.ProgramRequest(**body))[0]
    method = device.configure_auto_power if mode == 'auto_power' else device.configure_manual
    assert method(step.params['segments'])
    if mode == 'auto_power':
        assert [addr for _, addr, _ in protocol.multi_writes] == [auto_power_segment_start(n) for n in range(1, 6)]
        assert all(values == [30, 30, 0, 11, 0] for _, _, values in protocol.multi_writes)
    else:
        assert [addr for _, addr, _ in protocol.multi_writes] == [
            addr for n in range(1, 6) for addr in (manual_segment_start(n), manual_hold_time_start(n))]
    assert not protocol.single_writes  # No control/range/status register writes.


def test_raw_stop_also_prevents_following_logical_stage():
    dm = Manager()
    body = spec().model_dump()
    body['stages'][0]['hold_seconds'] = 100
    with TestClient(app(dm)) as client:
        client.post('/api/microwave-program/microwave1/start', json=body)
        for _ in range(100):
            status = client.get('/api/microwave-program/microwave1/current').json()
            if status['phase'] == 'hold':
                break
        assert client.post('/api/microwave/microwave1/stop').json()['success']
        # Wait for the backend owner to finish its cleanup, without page control.
        client.post('/api/microwave-program/microwave1/stop')
        assert not dm.microwave_on and len(dm.configurations) == 1
        assert dm.calls.count(('microwave_start', 'microwave1')) == 1


def test_initial_storage_failure_remains_visible_and_recoverable(monkeypatch):
    dm = Manager()
    original = program.write_record
    monkeypatch.setattr(program, 'write_record', Mock(side_effect=IOError('disk full')))
    with TestClient(app(dm)) as client:
        assert client.post('/api/microwave-program/microwave1/start', json=spec().model_dump()).status_code == 503
        assert not dm.calls
        assert client.get('/api/microwave-program/microwave1/current').json()['recovery_required']
        monkeypatch.setattr(program, 'write_record', original)
        path = '/api/microwave-program/microwave1/acknowledge-interrupted'
        assert client.post(path, json={'devices_stopped_confirmed':True}).status_code == 200
        assert not client.get('/api/microwave-program/microwave1/current').json()['recovery_required']
        assert client.get('/api/microwave-program/microwave1/current').json()['state'] == 'stopped'
        assert not api._runs and not api._engines
        client.post('/api/microwave-program/microwave1/start', json=spec().model_dump())
        assert not dm.calls
