"""Software-only regressions for guided timing, interlocks and traceability."""
import asyncio
import copy
import csv
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.experiment import executor as execution, guided, parser
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine
from src.experiment.experiment_logger import ExperimentLogger
from src.science import sample_record
from src.utils.config import ConfigManager
from src.web.api import experiments, guided as api
from src.web.device_manager import DeviceManager
from src.protocols.pump_params import PumpRunStatus
from src.protocols.microwave_params import auto_power_segment_start
from test_guided import FakeManager, spec, until
from test_microwave_atomic_config import make_device


def test_manual_drain_times_and_fixed_cleaning_route():
    request = spec(axes=[[30], [30], [.1, .5], [.2], [30], [0]],
                   product_drain_seconds=150, clean_drain_seconds=210, drain_flow=2,
                   clean_volume=.8, clean_flow=1, clean_cycles=2)
    for data in guided.compile_plan(request):
        steps = {s['id']: s for s in data['steps']}
        order = list(steps)
        assert not any(s['type'] == 'heater.stop' for s in data['steps'])
        product = steps['collect_product']
        assert product['params']['run_time'] == 150
        assert product['params']['dispense_volume'] == 5
        assert product['params']['flow_rate'] == 2
        assert product['wait']['timeout'] == 210
        assert steps['product_route']['params']['position'] == 'NO'
        row = data['metadata']['guided_parameters']
        assert data['metadata']['theoretical_product_volume_ml'] == pytest.approx(row[2]+row[3])
        for cycle in range(2):
            assert order.index(f'clean_{cycle}_route') < order.index(f'clean_{cycle}_in')
            assert steps[f'clean_{cycle}_route']['params']['position'] == 'NC'
            assert steps[f'clean_{cycle}_in']['params']['run_time'] == 48
            assert steps[f'clean_{cycle}_in']['params']['dispense_volume'] == .8
            drain = steps[f'clean_{cycle}_out']
            assert drain['params']['run_time'] == 210
            assert drain['params']['dispense_volume'] == 7
            assert drain['wait']['timeout'] == 270
    assert guided.priming_recipe(request, 'test')['metadata']['waste_port'] == 'NC'


@pytest.mark.parametrize('field,value', [('product_drain_seconds', 0),
    ('clean_drain_seconds', 10000), ('product_drain_seconds', float('inf')),
    ('clean_drain_seconds', None), ('product_drain_seconds', None), ('product_port', 'NC')])
def test_invalid_formal_drain_or_mapping_rejected_before_writes(field, value):
    app = FastAPI()
    dm = FakeManager()
    app.state.device_manager = dm
    app.include_router(api.router, prefix='/api')
    body = spec().model_dump()
    if value is None:
        del body[field]
    else:
        body[field] = value
    # JSON itself cannot encode infinity, but the strict request model rejects it.
    if value == float('inf'):
        with pytest.raises(ValueError):
            guided.GuidedRequest.model_validate(body)
    else:
        with TestClient(app) as client:
            for path in ('preview', 'prime', 'start'):
                assert client.post('/api/guided/'+path, json=body).status_code == 422
    assert not dm.calls


def test_formal_drains_reach_real_executor_with_entered_times():
    class RecordingManager(FakeManager):
        def __init__(self):
            super().__init__()
            self.motions = []

        def start_pump_channel(self, did, channel, *args):
            self.motions.append((channel, args))
            return super().start_pump_channel(did, channel, *args)

    async def scenario():
        dm = RecordingManager()
        batch = guided.GuidedBatch(dm, spec(product_drain_seconds=123, clean_drain_seconds=234))
        await batch.start()
        await batch.task
        assert batch.state.value == 'completed'
        # flow, direction, mode, run_time, dispense_volume, ...
        assert [(ch, args[3], args[4]) for ch, args in dm.motions] == [
            (4, 480, 8), (4, 123, 2.05), (3, 60, 1), (4, 234, 3.9)]
        assert [c for c in dm.calls if c[0] in ('valve', 'pump_start')] == [
            ('valve', True), ('pump_start', 4), ('valve', False), ('pump_start', 4),
            ('valve', True), ('pump_start', 3), ('pump_start', 4)]
    asyncio.run(scenario())


def test_heaters_remain_on_through_reaction_cleaning_and_next_group():
    class CheckingManager(FakeManager):
        def start_microwave(self, did, mode):
            assert not any(c[0] == 'heater_stop' for c in self.calls)
            return super().start_microwave(did, mode)

        def start_pump_channel(self, did, channel, *args):
            assert not any(c[0] == 'heater_stop' for c in self.calls)
            return super().start_pump_channel(did, channel, *args)

    async def scenario():
        dm = CheckingManager()
        batch = guided.GuidedBatch(dm, spec(axes=[[30, 35], [30], [.1], [.2], [30], [0]]))
        await batch.start()
        await batch.task
        assert batch.state.value == 'completed'
        assert len(batch.record['groups']) == 2
        assert dm.heating == {'heater1': 35, 'heater2': 30}
        assert sum(c == ('heater_stop', 'heater1') for c in dm.calls) == 1
        assert sum(c == ('heater_stop', 'heater2') for c in dm.calls) == 1
        assert all(c[0] == 'heater_stop' for c in dm.calls[-2:])
        assert not batch.executor._active_heaters
        assert not batch.record['cleanup_required']
    asyncio.run(scenario())


def test_paused_guided_heaters_stay_on_and_stop_turns_them_off():
    async def scenario():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(axes=[[30], [30], [.1], [.2], [60], [0]]))
        await batch.start()
        await until(lambda: batch.record.get('last_step') == 'cool_before_collection')
        await batch.pause()
        assert batch.state.value == 'paused'
        assert batch.executor._active_heaters == {'heater1', 'heater2'}
        assert not any(c[0] == 'heater_stop' for c in dm.calls)
        assert await batch.stop()
        assert batch.state.value == 'stopped'
        assert not batch.executor._active_heaters
        assert ('heater_stop', 'heater1') in dm.calls
        assert ('heater_stop', 'heater2') in dm.calls
    asyncio.run(scenario())


def test_final_heater_stop_failure_persists_restart_interlock():
    async def scenario():
        dm = FakeManager()
        dm.stop_heater = Mock(return_value=False)
        batch = guided.GuidedBatch(dm, spec())
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert len(batch.record['groups']) == 1
        assert batch.cleanup_pending and batch.record['cleanup_required']
        restored = api.read_record(batch.batch_id)
        assert restored['state'] == 'interrupted' and restored['recovery_required']
        dm.stop_heater.return_value = True
        assert await batch.stop()
        assert not batch.executor._active_heaters
        assert not batch.cleanup_pending
        assert not batch.record['cleanup_required']
    asyncio.run(scenario())


def test_formal_feed_failure_stops_retained_heaters_and_both_syringes():
    async def scenario():
        dm = FakeManager()
        dm.fail_feed = True
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        batch.record['priming']['status'] = 'completed'
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert len(batch.record['groups']) == 1
        assert not batch.executor._active_heaters
        for did in ('heater1', 'heater2'):
            assert ('heater_stop', did) in dm.calls
        for did in ('syringe_pump1', 'syringe_pump2'):
            assert ('syringe_stop', did) in dm.calls
        assert not any(c[0] in ('microwave_start', 'pump_start') for c in dm.calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('keep,release,fail_cleanup', [(False, True, False),
    (True, True, False), (True, False, False), (True, False, True)])
def test_group_cleanup_retention_is_scoped_and_failure_always_stops_heaters(keep, release, fail_cleanup):
    async def scenario():
        dm = FakeManager()
        executor = execution.StepExecutor(dm)
        executor.release_resources_on_cleanup = release
        executor._active_heaters.add('heater1')
        if fail_cleanup:
            executor._active_pumps.add(('pump1', 4))
            dm.stop_pump_channel = Mock(return_value=False)
        engine = ExperimentEngine(executor, ExperimentLogger(save_log=False),
                                  keep_heaters_on_completion=keep)
        engine.load_steps(parser.parse_experiment_data({'steps': [
            {'id': 'done', 'type': 'log', 'params': {'message': 'done'}}]})['steps'])
        await engine.start()
        await engine.wait_finished()
        retained = keep and not release and not fail_cleanup
        assert ('heater1' in executor._active_heaters) == retained
        assert engine.state.value == ('failed' if fail_cleanup else 'completed')
        if retained:
            assert engine._cleanup_result is None
            # A later stop must not treat selective cleanup as a full stop.
            assert await engine.stop()
            assert not executor._active_heaters
        if fail_cleanup:
            assert engine.cleanup_pending
            dm.stop_pump_channel.return_value = True
            assert await engine.stop()
    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No real hardware')))
    monkeypatch.setattr('src.experiment.experiment_logger.LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr(sample_record, 'SAMPLES_DIR', tmp_path / 'data')
    monkeypatch.setattr(sample_record, 'SAMPLES_CSV', tmp_path / 'data' / 'samples.csv')
    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(api, '_engines', experiments._engines)
    monkeypatch.setattr(api, '_batches', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())


def status(**changes):
    return dict(material_temperature=30, control_active=True, status_confirmed=True,
                fault_code=0, output_active=False, **changes)


class Clock:
    def __init__(self, stall=0):
        self.now, self.stall, self.sleeps = 0.0, stall, 0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds + self.stall
        self.sleeps += 1


def fake_clock(monkeypatch, stall=0):
    clock = Clock(stall)
    monkeypatch.setattr(execution, 'time', clock)  # No wall clock available to the waits.
    monkeypatch.setattr(execution, 'asyncio', SimpleNamespace(
        sleep=clock.sleep, to_thread=asyncio.to_thread, get_event_loop=asyncio.get_event_loop))
    return clock


def test_duration_uses_actual_elapsed_after_scheduler_delay(monkeypatch):
    clock = fake_clock(monkeypatch, stall=1)
    executor = execution.StepExecutor(Mock())
    assert asyncio.run(executor._wait_condition(WaitCondition(type=WaitType.DURATION, seconds=.4)))
    assert clock.sleeps == 1
    assert clock.now == 1.05


def test_duration_excludes_actual_pause_and_stop_interrupts(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(Mock())
    state = {'paused': False}
    executor.set_pause_checker(lambda: state['paused'])
    async def sleep(seconds):
        clock.now += seconds
        clock.sleeps += 1
        if clock.sleeps == 1:
            state['paused'] = True
            executor.notify_pause(True)
        elif state['paused']:
            clock.now += 10
            state['paused'] = False
            executor.notify_pause(False)
    monkeypatch.setattr(execution.asyncio, 'sleep', sleep)
    assert asyncio.run(executor._wait_condition(WaitCondition(type=WaitType.DURATION, seconds=.4)))
    assert 10.45 <= clock.now < 10.51
    executor.set_stop_checker(lambda: True)
    assert not asyncio.run(executor._wait_condition(WaitCondition(type=WaitType.DURATION, seconds=100)))


@pytest.mark.parametrize('changes', [dict(fault_code=7), dict(control_active=False),
    dict(control_active=None), dict(material_temperature=float('nan')), dict(read_ok=False)])
def test_at_target_fault_or_unknown_state_is_failure(changes):
    data = status()
    data.update(changes)
    dm = Mock(read_microwave_data=Mock(return_value=data))
    executor = execution.StepExecutor(dm)
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_REACHED, device_id='microwave1',
        target_temperature=30, timeout=5)))


@pytest.mark.parametrize('failure', [dict(fault_code=7), dict(read_ok=False),
    dict(material_temperature=None), IOError('read failed')])
def test_hold_fault_and_read_failure(monkeypatch, failure):
    fake_clock(monkeypatch)
    bad = status()
    if isinstance(failure, dict):
        bad.update(failure)
    else:
        bad = failure
    dm = Mock(read_microwave_data=Mock(side_effect=[status(), bad]))
    executor = execution.StepExecutor(dm)
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, device_id='microwave1', seconds=3)))
    assert dm.read_microwave_data.call_count == 2


@pytest.mark.parametrize('seconds,success', [(3, False), (1, True), (0, True)])
def test_hold_early_end_boundary_and_zero_power(monkeypatch, seconds, success):
    fake_clock(monkeypatch)
    data = status()
    data['control_active'] = False
    executor = execution.StepExecutor(Mock(read_microwave_data=Mock(return_value=data)))
    assert asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, device_id='microwave1', seconds=seconds))) is success


def test_hold_zero_output_is_not_fault(monkeypatch):
    clock = fake_clock(monkeypatch)
    dm = Mock(read_microwave_data=Mock(return_value=status()))
    executor = execution.StepExecutor(dm)
    assert asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, device_id='microwave1', seconds=3)))
    assert clock.now >= 3
    assert dm.read_microwave_data.call_count == 4


@pytest.mark.parametrize('minutes,parts', [(10, (0, 10, 0)), (60.5, (1, 0, 30)),
                                         (1/60, (0, 0, 1)), (1440, (24, 0, 0))])
def test_hold_duration_written_through_existing_device_interface(minutes, parts):
    request = spec(axes=[[30], [30], [.1], [.2], [30], [minutes]])
    steps = parser.parse_experiment_data(guided.compile_plan(request)[0])['steps']
    dm = DeviceManager()
    device, protocol = make_device()
    dm._microwaves['microwave1'] = device
    executor = execution.StepExecutor(dm)
    assert asyncio.run(executor.execute(next(s for s in steps if s.id == 'microwave_config')))
    assert (1, auto_power_segment_start(1), [30, 30, *parts]) in protocol.multi_writes
    hold = next(s for s in steps if s.id == 'hold')
    assert hold.wait.type == WaitType.MICROWAVE_MONITORED_HOLD
    assert hold.wait.seconds == parts[0]*3600 + parts[1]*60 + parts[2]


@pytest.mark.parametrize('changes', [dict(clean_volume=21), dict(reactor_available_ml=7),
    dict(axes=[[30], [30], [.1], [.2], [30], [.001]])])
def test_capacity_and_fractional_seconds_rejected(changes):
    with pytest.raises(ValueError):
        spec(**changes)


@pytest.mark.parametrize('changes', [dict(clean_volume=21),
    dict(axes=[[30], [30], [.1], [.2], [30], [.001]])])
def test_invalid_capacity_and_time_rejected_at_all_api_boundaries(changes):
    body = {**spec().model_dump(), **changes}
    dm = FakeManager()
    app = FastAPI()
    app.state.device_manager = dm
    app.include_router(api.router, prefix='/api')
    with TestClient(app) as client:
        for path in ('preview', 'prime', 'start'):
            assert client.post('/api/guided/'+path, json=body).status_code == 422
    assert dm.calls == []


@pytest.mark.parametrize('mutation', ['pump_disabled', 'valve_disabled', 'channel_disabled',
    'prime_flow', 'drain_flow', 'clean_flow', 'heater_disabled'])
def test_configuration_rejected_preview_prime_and_start_before_device_calls(monkeypatch, mutation):
    config = copy.deepcopy(ConfigManager().load())
    request = spec()
    dm = FakeManager()
    ready_batch = guided.GuidedBatch(dm, request)
    ready_batch.record['phase'] = 'ready'
    ready_batch.record['priming']['status'] = 'completed'
    ready_batch.state = guided.ExperimentState.PAUSED
    api._batches[ready_batch.batch_id] = ready_batch
    if mutation == 'pump_disabled':
        config.pumps[0].enabled = False
    elif mutation == 'valve_disabled':
        config.valves[0].enabled = False
    elif mutation == 'heater_disabled':
        config.heaters[0].enabled = False
    elif mutation == 'channel_disabled':
        next(c for c in config.pumps[0].channels if c.channel == 4).enabled = False
    else:
        field = {'prime_flow': 'prime_drain_flow', 'drain_flow': 'drain_flow', 'clean_flow': 'clean_flow'}[mutation]
        request = spec(**{field: 100.0})
    monkeypatch.setattr(ConfigManager, 'load', lambda self: config)
    with pytest.raises(ValueError):
        guided.compile_plan(request)
    with pytest.raises(ValueError):
        asyncio.run(guided.preflight(dm, request))
    assert dm.calls == []
    app = FastAPI()
    app.state.device_manager = dm
    app.include_router(api.router, prefix='/api')
    with TestClient(app) as client:
        assert client.post('/api/guided/preview', json=request.model_dump()).status_code == 422
        assert client.post('/api/guided/prime', json=request.model_dump()).status_code == 409
        body = request.model_dump()
        body['priming_batch_id'] = ready_batch.batch_id
        assert client.post('/api/guided/start', json=body).status_code == 409
    assert dm.calls == []


def test_priming_and_formal_samples_use_real_csv_without_rewriting_history():
    ids = []
    for metadata in (dict(batch_id='batch', run_kind='priming', condition_id='PRIMING', notes='maintenance'),
                     dict(batch_id='batch', sample_index=1), dict(batch_id='batch', sample_index=2)):
        logger = ExperimentLogger(save_log=True)
        run_id = logger.start_run('test', 'test.yaml', 0, metadata=metadata)
        ids.append(logger.active_run.metadata['sample_id'])
        logger.finish_run('completed')
        if metadata.get('run_kind') == 'priming':
            assert ids[0] == 'batch_PRIMING_' + run_id
    with sample_record.SAMPLES_CSV.open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    assert [r['sample_id'] for r in rows] == ids
    assert ids[1:] == ['batch_S001', 'batch_S002']
    assert rows[0]['condition_id'] == 'PRIMING'
    assert rows[0]['notes'] == 'maintenance'


def test_guided_reservation_does_not_block_unrelated_yaml_save(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path / 'experiments')
    batch = guided.GuidedBatch(FakeManager(), spec())
    experiments._engines[batch.batch_id] = batch
    app = FastAPI()
    app.include_router(experiments.router, prefix='/api')
    with TestClient(app) as client:
        response = client.put('/api/experiments/other.yaml/source', json={'content': 'steps: []'})
    assert response.status_code == 200


@pytest.mark.parametrize('enabled,on_error,seconds', [(False, 'stop', 1), (True, 'skip', 1), (True, 'stop', .2)])
def test_protected_wait_cannot_be_disabled_skipped_or_fractional(enabled, on_error, seconds):
    with pytest.raises(ValueError):
        parser.parse_experiment_data(dict(steps=[dict(id='hold', type='wait', enabled=enabled,
            on_error=on_error, wait=dict(type='microwave_monitored_hold', device_id='microwave1', seconds=seconds))]))


def test_short_pump_action_uses_only_current_start_evidence(monkeypatch):
    fake_clock(monkeypatch)
    dm = Mock(start_pump_channel=Mock(return_value=True))
    executor = execution.StepExecutor(dm)
    start = ExperimentStep('start', ActionType.PUMP_START, params=dict(device_id='pump1', channel=4))
    wait = WaitCondition(type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=.1)
    dm.read_pump_status.return_value = {'channels': {'4': dict(read_ok=True, running=False, run_status='STOP')}}
    assert asyncio.run(executor.execute(start))
    assert asyncio.run(executor._wait_condition(wait))
    assert not asyncio.run(executor._wait_condition(wait))  # Old evidence is consumed.
    dm.start_pump_channel.return_value = False
    assert not asyncio.run(executor.execute(start))
    assert not asyncio.run(executor._wait_condition(wait))


@pytest.mark.parametrize('data', [dict(read_ok=False, running=False, run_status='STOP'),
    dict(read_ok=True, running=None, run_status=None), dict(read_ok=True, running=False, run_status='PAUSE')])
def test_unknown_or_paused_pump_never_completes(monkeypatch, data):
    fake_clock(monkeypatch)
    dm = Mock(start_pump_channel=Mock(return_value=True),
              read_pump_status=Mock(return_value={'channels': {'4': data}}))
    executor = execution.StepExecutor(dm)
    assert asyncio.run(executor.execute(ExperimentStep('start', ActionType.PUMP_START,
        params=dict(device_id='pump1', channel=4))))
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=.1)))


def test_independent_pump_wait_requires_running_then_stopped(monkeypatch):
    fake_clock(monkeypatch)
    dm = Mock(read_pump_status=Mock(side_effect=[
        {'channels': {'4': dict(read_ok=True, running=True, run_status='START')}},
        {'channels': {'4': dict(read_ok=True, running=False, run_status='STOP')}}]))
    executor = execution.StepExecutor(dm)
    assert asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=2)))


def test_other_channel_and_failed_restart_cannot_reuse_evidence(monkeypatch):
    fake_clock(monkeypatch)
    dm = Mock(start_pump_channel=Mock(return_value=True), read_pump_status=Mock(return_value={
        'channels': {'3': dict(read_ok=True, running=False, run_status='STOP'),
                     '4': dict(read_ok=True, running=False, run_status='STOP')}}))
    executor = execution.StepExecutor(dm)
    start = ExperimentStep('start', ActionType.PUMP_START, params=dict(device_id='pump1', channel=4))
    assert asyncio.run(executor.execute(start))
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=3, timeout=.1)))
    dm.start_pump_channel.return_value = False
    assert not asyncio.run(executor.execute(start))
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=.1)))


@pytest.mark.parametrize('run_status,success', [(PumpRunStatus.STOP, True), (PumpRunStatus.PAUSE, False)])
def test_pump_completion_uses_real_manager_status_payload(monkeypatch, run_status, success):
    fake_clock(monkeypatch)
    pump = Mock()
    pump.is_connected.return_value = True
    pump.read_channel_status.return_value = SimpleNamespace(running=False, run_status=run_status,
        flow_rate=1, dispensed_volume=0, direction=None, flow_unit=None)
    dm = DeviceManager()
    dm._pumps['pump1'] = pump
    dm.start_pump_channel = Mock(return_value=True)
    executor = execution.StepExecutor(dm)
    assert asyncio.run(executor.execute(ExperimentStep('start', ActionType.PUMP_START,
        params=dict(device_id='pump1', channel=4))))
    assert asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=.1))) is success


def test_condition_timeout_uses_monotonic_elapsed_during_scheduler_stall(monkeypatch):
    clock = fake_clock(monkeypatch, stall=10)
    clock.time = Mock(side_effect=[-100000, 100000])  # Wall clock changes are irrelevant.
    dm = Mock(read_heater_data=Mock(return_value=dict(pv=10, sv=30)))
    executor = execution.StepExecutor(dm)
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.TEMPERATURE_REACHED, device_id='heater1', timeout=5)))
    clock.time.assert_not_called()
    assert dm.read_heater_data.call_count == 1
    assert clock.sleeps == 1


def reaction_steps(seconds=1):
    return parser.parse_experiment_data(dict(steps=[
        dict(id='start', type='microwave.start', params=dict(device_id='microwave1', mode='auto_power')),
        dict(id='hold', type='wait', wait=dict(type='microwave_monitored_hold', device_id='microwave1', seconds=seconds)),
        dict(id='stop', type='microwave.stop', params=dict(device_id='microwave1')),
        dict(id='collect', type='pump.start', params=dict(device_id='pump1', channel=4)),
    ]))['steps']


def test_reaction_pause_completes_stops_then_pauses_resume_does_not_replay():
    async def scenario():
        dm = FakeManager()
        executor = execution.StepExecutor(dm)
        engine = ExperimentEngine(executor, ExperimentLogger(save_log=True), finish_reaction_before_pause=True)
        engine.load_steps(reaction_steps())
        await engine.start()
        await until(lambda: engine.progress.step_id == 'hold')
        await engine.pause()
        assert engine.state.value == 'running' and engine.pause_pending
        await until(lambda: engine.state.value == 'paused')
        assert not dm.microwave_on and not engine.pause_pending
        assert ('pump_start', 4) not in dm.calls
        await engine.resume()
        await engine.wait_finished()
        assert engine.state.value == 'completed'
        assert dm.calls.count(('microwave_start', 'microwave1')) == 1
        assert dm.calls.count(('pump_start', 4)) == 1
    asyncio.run(scenario())


def test_pending_reaction_pause_can_be_cancelled_and_stop_interrupts():
    async def scenario():
        dm = FakeManager()
        executor = execution.StepExecutor(dm)
        engine = ExperimentEngine(executor, ExperimentLogger(save_log=True), finish_reaction_before_pause=True)
        engine.load_steps(reaction_steps(100))
        await engine.start()
        await until(lambda: engine.progress.step_id == 'hold')
        await engine.pause()
        await engine.resume()
        assert engine.state.value == 'running' and not engine.pause_pending
        await engine.pause()
        assert await asyncio.wait_for(engine.stop(), timeout=1)
        assert engine.state.value == 'stopped' and not dm.microwave_on
        assert ('pump_start', 4) not in dm.calls
    asyncio.run(scenario())


def test_batch_pause_during_heating_is_pending_until_stopped_then_no_collection_or_next_group():
    async def scenario():
        dm = FakeManager()
        dm.read_pump_status = lambda did: {'channels': {
            str(c): dict(read_ok=True, running=False, run_status='STOP') for c in (3, 4)}}
        ready, reads = False, 0
        read = dm.read_microwave_data
        def heat_status(did):
            nonlocal reads
            data = read(did)
            if dm.microwave_on:
                reads += 1
                if not ready:
                    data['material_temperature'] = 20
            return data
        dm.read_microwave_data = heat_status
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        batch.record['priming']['status'] = 'completed'
        await batch.start()
        await until(lambda: reads > 0)
        await batch.pause()
        assert batch.snapshot()['pause_pending'] and batch.state.value == 'running'
        assert batch.executor._active_heaters == {'heater1', 'heater2'}
        assert not any(c[0] == 'heater_stop' for c in dm.calls)
        ready = True
        await until(lambda: batch.state.value == 'paused')
        assert not dm.microwave_on and not batch.snapshot()['pause_pending']
        assert batch.executor._active_heaters == {'heater1', 'heater2'}
        assert not any(c[0] == 'heater_stop' for c in dm.calls)
        assert not any(c[0] == 'pump_start' for c in dm.calls)
        assert batch.record['current_group'] == 1
        await batch.resume()
        await asyncio.wait_for(batch.task, timeout=5)
        assert batch.state.value == 'completed'
        assert sum(c[0] == 'dispense' for c in dm.calls) == 4
        assert sum(c[0] == 'microwave_start' for c in dm.calls) == 2
    asyncio.run(scenario())


def test_fault_is_supervised_even_with_pause_pending():
    async def scenario():
        dm = FakeManager()
        executor = execution.StepExecutor(dm)
        engine = ExperimentEngine(executor, ExperimentLogger(save_log=True), finish_reaction_before_pause=True)
        engine.load_steps(reaction_steps(10))
        await engine.start()
        await until(lambda: engine.progress.step_id == 'hold')
        await engine.pause()
        assert engine.pause_pending
        data = status()
        data['fault_code'] = 7
        dm.read_microwave_data = lambda did: data
        await asyncio.wait_for(engine.wait_finished(), timeout=2)
        assert engine.state.value == 'failed' and not dm.microwave_on
        assert ('pump_start', 4) not in dm.calls
    asyncio.run(scenario())


def test_pause_at_group_boundary_is_preserved_until_resume():
    async def scenario():
        batch = guided.GuidedBatch(FakeManager(), spec())
        batch.state = guided.ExperimentState.RUNNING
        batch.record['phase'] = 'experiments'
        batch.engine = ExperimentEngine(batch.executor, ExperimentLogger(save_log=True))
        batch.engine._state = guided.ExperimentState.COMPLETED
        await batch.pause()
        assert batch.state.value == 'paused' and not batch.snapshot()['pause_pending']
        await batch.resume()
        assert batch.state.value == 'running'
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['heating', 'hold', 'hold_read_failure'])
def test_batch_microwave_failure_stops_and_never_collects_or_starts_next_group(stage):
    async def scenario():
        dm = FakeManager()
        reads = 0
        original = dm.read_microwave_data
        def read(did):
            nonlocal reads
            data = original(did)
            if dm.microwave_on:
                reads += 1
                if stage == 'heating' or reads >= 2:
                    if stage == 'hold_read_failure':
                        raise IOError('failed read')
                    data['fault_code'] = 7
            return data
        dm.read_microwave_data = read
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        batch.record['priming']['status'] = 'completed'
        await batch.start()
        await asyncio.wait_for(batch.task, timeout=5)
        assert batch.state.value == 'failed'
        assert not dm.microwave_on
        assert not batch.executor._active_heaters
        assert ('heater_stop', 'heater1') in dm.calls
        assert ('heater_stop', 'heater2') in dm.calls
        assert not any(c[0] == 'pump_start' for c in dm.calls)
        assert len(batch.record['groups']) == 1
    asyncio.run(scenario())
