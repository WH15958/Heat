"""Guided preparation and simultaneous stability: virtual time, no serial hardware."""
import asyncio
import copy
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.experiment import executor as execution, guided, parser
from src.experiment.actions import WaitCondition, WaitType
from src.experiment.editor import validate_source
from src.web.api import experiments, guided as api
from test_guided import FakeManager, spec
from test_automation_safety_fixes import fake_clock

real_stability_wait = execution.StepExecutor._wait_heater_pair_stable

def stable_wait(**changes):
    return WaitCondition(**{**dict(type=WaitType.HEATER_PAIR_STABLE, seconds=30, tolerance=3, timeout=600,
        targets=[dict(device_id='heater1', target_temperature=30),
                 dict(device_id='heater2', target_temperature=40)]), **changes})


@pytest.mark.parametrize('profile,first_stable', [('boundary', 0), ('overshoot', 10),
                                                ('alternating', 12), ('reset', 21)])
def test_both_heaters_need_one_continuous_window(monkeypatch, profile, first_stable):
    clock = fake_clock(monkeypatch)
    samples = []
    def read(did):
        second = round(clock.now, 2)
        samples.append((second, did))
        target = 30 if did == 'heater1' else 40
        delta = 3 if did == 'heater1' else -3
        if profile == 'overshoot' and 1 <= second < 10:
            delta = 4
        if profile == 'alternating' and second < 12:
            delta = 4 if (did == 'heater1') == (int(second) % 2 == 0) else 0
        if profile == 'reset' and 20 <= second < 21 and did == 'heater2':
            delta = -4
        return dict(pv=target+delta, sv=target)
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert asyncio.run(executor._wait_condition(stable_wait()))
    assert first_stable + 30 <= clock.now < first_stable + 31.1
    assert [did for _, did in samples[:2]] == ['heater1', 'heater2']


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), True, '30', -1])
def test_invalid_temperature_blocks_feed(monkeypatch, bad):
    fake_clock(monkeypatch)
    executor = execution.StepExecutor(Mock(read_heater_data=Mock(return_value=dict(pv=bad))))
    assert not asyncio.run(executor._wait_condition(stable_wait()))


@pytest.mark.parametrize('failure', [IOError('read failed'), dict(pv=30, read_ok=False), dict(pv=30, fault_code=1)])
def test_stability_read_failure_stops(monkeypatch, failure):
    fake_clock(monkeypatch)
    read = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert not asyncio.run(executor._wait_condition(stable_wait()))
    assert '读取失败' in executor.last_error


def test_stability_timeout_and_stop(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(Mock(read_heater_data=Mock(return_value=dict(pv=0))))
    assert not asyncio.run(executor._wait_condition(stable_wait(timeout=2)))
    assert clock.now < 3.1
    executor.set_stop_checker(lambda: True)
    before = clock.now
    assert not asyncio.run(executor._wait_condition(stable_wait()))
    assert clock.now == before


def test_pause_discards_previous_stability_window(monkeypatch):
    clock = fake_clock(monkeypatch)
    paused = False
    did_pause = False
    executor = execution.StepExecutor(Mock(read_heater_data=lambda did: dict(pv=30 if did == 'heater1' else 40)))
    executor.set_pause_checker(lambda: paused)
    async def sleep(seconds):
        nonlocal paused, did_pause
        clock.now += seconds
        if not did_pause and clock.now >= 20:
            paused = True
            did_pause = True
            executor.notify_pause(True)
        elif paused:
            clock.now += 100
            paused = False
            executor.notify_pause(False)
    monkeypatch.setattr(execution.asyncio, 'sleep', sleep)
    assert asyncio.run(executor._wait_condition(stable_wait(timeout=60)))
    assert clock.now >= 150
    assert 50 <= executor._wait_clock() < 51.1


def test_pause_during_read_never_completes_stability(monkeypatch):
    clock = fake_clock(monkeypatch)
    interrupted = False
    executor = execution.StepExecutor(Mock())
    def read(did):
        nonlocal interrupted
        if clock.now >= 30 and not interrupted:
            interrupted = True
            executor.notify_pause(True)
            clock.now += 50
            executor.notify_pause(False)
        return dict(pv=30 if did == 'heater1' else 40)
    executor._dm.read_heater_data = read
    assert asyncio.run(executor._wait_condition(stable_wait()))
    assert clock.now >= 110


def test_generated_wait_and_parser_contract():
    data = guided.recipe(spec().rows()[0], spec(), 'test', 0)
    step = next(s for s in data['steps'] if s['id'] == 'heat_both_stable')
    assert step['wait']['tolerance'] == 3
    assert step['wait']['seconds'] == 30
    assert step['wait']['timeout'] == 600
    assert validate_source(yaml.safe_dump(data))['valid']
    for change in (dict(targets=[]), dict(seconds=0), dict(timeout=0), dict(tolerance=True),
                   dict(targets=[dict(device_id='heater1', target_temperature=30)]*2),
                   dict(targets=[dict(device_id='pump1', target_temperature=30), dict(device_id='heater2', target_temperature=30)])):
        bad = copy.deepcopy(step)
        bad['wait'].update(change)
        with pytest.raises(ValueError):
            parser.parse_experiment_data(dict(steps=[bad]))
    for change in (dict(enabled=False), dict(on_error='skip')):
        with pytest.raises(ValueError):
            parser.parse_experiment_data(dict(steps=[{**step, **change}]))
    unknown = copy.deepcopy(step)
    unknown['wait']['targets'][0]['device_id'] = 'unknown'
    result = validate_source(yaml.safe_dump(dict(steps=[unknown])))
    assert result['valid'] and any('unknown' in w['message'] for w in result['warnings'])


@pytest.fixture
def prepared_env(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('Real hardware forbidden')))
    monkeypatch.setattr('src.experiment.experiment_logger.LOGS_DIR', tmp_path/'logs')
    monkeypatch.setattr('src.experiment.experiment_logger.write_sample_record', Mock(return_value=True))
    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path/'batches')
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(api, '_engines', experiments._engines)
    monkeypatch.setattr(api, '_batches', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(execution.StepExecutor, '_wait_heater_pair_stable', AsyncMock(return_value=True))


def test_initialization_parameters_order_once_per_batch(prepared_env):
    async def run():
        dm = FakeManager()
        command = dm.syringe_command
        calls = []
        def record(did, params, owner):
            calls.append((did, params.copy()))
            return command(did, params, owner)
        dm.syringe_command = record
        request = spec(repeats=2, initialization_a=dict(direction='Y', initialization_code=17))
        batch = guided.GuidedBatch(dm, request)
        await batch.start(prime_only=True)
        await batch.task
        assert batch.record['phase'] == 'ready'
        assert [(did, p['action']) for did, p in calls[:2]] == [('syringe_pump1', 'initialize'), ('syringe_pump2', 'initialize')]
        assert calls[0][1]['direction'] == 'Y' and calls[0][1]['initialization_code'] == 17
        assert calls[0][1]['confirm'] is True
        assert calls[2][1]['action'] == 'aspirate'
        await batch.begin_experiments(request)
        await batch.task
        assert batch.state.value == 'completed'
        assert len([p for _, p in calls if p['action'] == 'initialize']) == 2
        assert len(batch.record['groups']) == 2
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['read_error', 'timeout'])
def test_stability_failure_blocks_formal_feed_in_real_batch(prepared_env, monkeypatch, failure):
    fake_clock(monkeypatch)
    monkeypatch.setattr(execution.asyncio, 'get_running_loop', asyncio.get_running_loop, raising=False)
    monkeypatch.setattr(execution.StepExecutor, '_wait_heater_pair_stable', real_stability_wait)
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(heating_timeout=2))
        await batch.start(prime_only=True)
        await batch.task
        assert batch.record['phase'] == 'ready'
        start = len(dm.calls)
        dm.read_heater_data = Mock(side_effect=IOError('sensor failed')) if failure == 'read_error' else Mock(return_value=dict(pv=0))
        await batch.begin_experiments(spec(heating_timeout=2))
        await batch.task
        assert batch.state.value == 'failed'
        assert not any(c[0] in ('aspirate', 'dispense', 'microwave_start', 'pump_start') for c in dm.calls[start:])
        assert all(('heater_stop', did) in dm.calls[start:] for did in ('heater1', 'heater2'))
    asyncio.run(run())


@pytest.mark.parametrize('failed_pump', ['syringe_pump1', 'syringe_pump2'])
@pytest.mark.parametrize('failure', ['exception', 'bad_zero'])
@pytest.mark.parametrize('prime_only', [True, False])
def test_initialization_failure_prevents_aspiration(prepared_env, failed_pump, failure, prime_only):
    async def run():
        dm = FakeManager()
        command = dm.syringe_command
        def fail(did, params, owner):
            if did == failed_pump and params['action'] == 'initialize' and failure == 'exception':
                raise IOError('initialization failed')
            result = command(did, params, owner)
            if did == failed_pump and params['action'] == 'initialize' and failure == 'bad_zero':
                dm.syringes[did].position = 100
            return result
        dm.syringe_command = fail
        batch = guided.GuidedBatch(dm, spec())
        await batch.start(prime_only=prime_only)
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['recovery_required']
        assert not any(c[0] in ('aspirate', 'dispense', 'heat', 'microwave_start') for c in dm.calls)
        assert all(('syringe_stop', did) in dm.calls for did in dm.syringes)
    asyncio.run(run())


def test_automatic_start_rechecks_trusted_zero_after_priming(prepared_env):
    async def run():
        dm = FakeManager()
        stop = dm.stop_pump_channel
        def changed_zero(did, channel):
            result = stop(did, channel)
            dm.syringes['syringe_pump1'].position = 100
            return result
        dm.stop_pump_channel = changed_zero
        batch = guided.GuidedBatch(dm, spec())
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['recovery_required']
        assert not batch.record['groups']
        assert not any(c[0] in ('heat', 'microwave_start') for c in dm.calls)
    asyncio.run(run())


def test_stop_during_automatic_priming_never_starts_formal_experiment(prepared_env):
    async def run():
        dm = FakeManager()
        command = dm.syringe_command
        batch = guided.GuidedBatch(dm, spec())
        def stop_after_initialization(did, params, owner):
            result = command(did, params, owner)
            batch.request_stop()
            return result
        dm.syringe_command = stop_after_initialization
        await batch.start()
        await batch.task
        assert batch.record['recovery_required']
        assert not batch.record['groups']
        assert not any(c[0] in ('aspirate', 'heat', 'microwave_start') for c in dm.calls)
    asyncio.run(run())


@pytest.mark.parametrize('fault,allowed', [(0, True), (7, True), (1, False), (9, False), (10, False)])
def test_preflight_only_preparation_allows_uninitialized(prepared_env, fault, allowed):
    dm = FakeManager()
    dm.syringes['syringe_pump1'].read = lambda: dict(read_ok=True, busy=False, fault_code=fault,
        initialized=False, position_trusted=False, position=100)
    if allowed:
        asyncio.run(guided.preflight(dm, spec(), before_initialization=True))
    else:
        with pytest.raises(ValueError):
            asyncio.run(guided.preflight(dm, spec(), before_initialization=True))
    with pytest.raises(ValueError):
        asyncio.run(guided.preflight(dm, spec()))
    assert not dm.calls


def test_signature_and_explicit_initialization_confirmation(prepared_env):
    request = spec()
    original = guided.priming_signature(request)
    assert original != guided.priming_signature(spec(initialization_b=dict(direction='Y', initialization_code=17)))
    assert original == guided.priming_signature(spec(initialization_confirmed=False))
    with pytest.raises(ValueError):
        spec(initialization_a=dict(direction='Z', initialization_code=True))
    with pytest.raises(ValueError):
        spec(initialization_a=dict(direction='Z', initialization_code=3))
    app = FastAPI()
    dm = FakeManager()
    app.state.device_manager = dm
    app.include_router(api.router, prefix='/api')
    with TestClient(app) as client:
        body = request.model_dump()
        body.pop('initialization_a')
        assert client.post('/api/guided/prime', json=body).status_code == 422
        body = spec(initialization_confirmed=False).model_dump()
        assert client.post('/api/guided/prime', json=body).status_code == 409
    assert not dm.calls
