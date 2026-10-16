"""Host-timed flow drainage: virtual time and fake devices only."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.experiment import executor as execution, progress, guided
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine, ExperimentState
from src.experiment.parser import parse_experiment_data
from src.experiment.editor import validate_source
from test_automation_safety_fixes import fake_clock
from test_guided import spec


def flow_step(seconds=3):
    return ExperimentStep('collect_product', ActionType.PUMP_START, params=dict(
        device_id='pump1', channel=4, mode='FLOW_MODE', flow_rate=15,
        flow_unit=1, flow_duration_seconds=seconds))


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No real hardware')))
    clock = fake_clock(monkeypatch)
    execution.asyncio.get_running_loop = asyncio.get_running_loop
    monkeypatch.setattr(progress, 'time', SimpleNamespace(monotonic=clock.monotonic, time=lambda: 123))
    calls = []
    def start(*args):
        calls.append(('start', clock.now, args))
        clock.now += 2  # Config/START acknowledgement precedes host timing.
        return True
    def stop(*args):
        calls.append(('stop', clock.now, args))
        return True
    dm = Mock(start_pump_channel=Mock(side_effect=start), stop_pump_channel=Mock(side_effect=stop),
        read_pump_status=Mock(return_value={'channels': {'4': dict(read_ok=True, running=True, run_status='START')}}),
        get_last_command_error=Mock(return_value=None))
    executor = execution.StepExecutor(dm)
    return clock, calls, dm, executor


def test_flow_uses_requested_rate_and_stops_after_start_ack(rig):
    clock, calls, dm, executor = rig
    assert asyncio.run(executor.execute(flow_step()))
    assert calls[0][2][2] == 15
    assert calls[0][2][4].name == 'FLOW_MODE'
    assert calls[0][2][5:7] == (None, None)  # No hardware time/volume.
    assert calls[1][0] == 'stop' and calls[1][1] == pytest.approx(5)
    assert dm.start_pump_channel.call_count == dm.stop_pump_channel.call_count == 1
    assert not executor._active_pumps and not executor._pump_start_confirmed
    snap = executor.activity_snapshot
    assert snap['state'] == 'completed' and snap['remaining_seconds'] == 0
    assert snap['wait_type'] == 'flow_duration'
    clock.now += 100
    assert executor.activity_snapshot == snap


def test_pause_does_not_extend_flow_and_engine_waits_before_next_action(rig):
    clock, calls, dm, executor = rig
    async def run():
        engine = ExperimentEngine(executor)
        engine.load_steps([flow_step(), ExperimentStep('next', ActionType.LOG)])
        original_sleep = clock.sleep
        async def sleep(seconds):
            await original_sleep(seconds)
            if clock.now >= 2.5 and engine.state == ExperimentState.RUNNING:
                await engine.pause()
        execution.asyncio.sleep = sleep
        await engine.start()
        for _ in range(1000):
            await asyncio.sleep(.001)
            if dm.stop_pump_channel.called:
                break
        assert calls[-1][0] == 'stop' and calls[-1][1] == pytest.approx(5)
        assert engine.state == ExperimentState.PAUSED and engine.progress.current_step == 0
        assert not engine._task.done()
        await engine.resume()
        await engine.wait_finished()
        assert engine.state == ExperimentState.COMPLETED
        assert dm.start_pump_channel.call_count == 1
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['stop', 'read_false', 'early_stop', 'wrong_mode', 'missing', 'exception', 'cancel'])
def test_failure_always_stops_and_does_not_complete(rig, failure):
    clock, calls, dm, executor = rig
    if failure == 'stop':
        executor.set_stop_checker(lambda: clock.now >= 2.5)
    elif failure == 'exception':
        dm.read_pump_status.side_effect = IOError('offline')
    elif failure == 'cancel':
        dm.read_pump_status.side_effect = asyncio.CancelledError()
    else:
        dm.read_pump_status.return_value = {'channels': {'4': dict(read_ok=failure != 'read_false', running=failure != 'early_stop', run_status='FULL_SPEED' if failure == 'wrong_mode' else 'START')}}
        if failure == 'missing':
            dm.read_pump_status.return_value = {'channels': {}}
    if failure == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(executor.execute(flow_step()))
    else:
        assert not asyncio.run(executor.execute(flow_step()))
    assert dm.stop_pump_channel.call_count == 1
    assert calls[-1][1] < 5
    assert executor.activity_snapshot['state'] == 'failed'
    assert not executor._active_pumps


@pytest.mark.parametrize('raises', [False, True])
def test_unconfirmed_stop_retains_cleanup_obligation(rig, raises):
    _, _, dm, executor = rig
    dm.stop_pump_channel.side_effect = IOError('stop timeout') if raises else None
    dm.stop_pump_channel.return_value = False
    assert not asyncio.run(executor.execute(flow_step(.1)))
    assert ('pump1', 4) in executor._active_pumps
    assert '停止' in executor.last_error
    assert executor.last_device_result['stop_confirmed'] is False
    dm.stop_pump_channel.side_effect = None
    dm.stop_pump_channel.return_value = True
    assert asyncio.run(executor.stop_active_devices())
    assert not executor._active_pumps


def test_start_failure_does_not_enter_timer_and_is_cleaned_up(rig):
    _, _, dm, executor = rig
    dm.start_pump_channel.side_effect = None
    dm.start_pump_channel.return_value = False
    assert not asyncio.run(executor.execute(flow_step()))
    assert not dm.read_pump_status.called
    assert ('pump1', 4) in executor._active_pumps
    assert asyncio.run(executor.stop_active_devices())
    assert dm.stop_pump_channel.called


@pytest.mark.parametrize('value', [0, -.1, 10000, float('nan'), float('inf'), True, '3', None])
def test_invalid_duration_rejected_before_any_device_call(rig, value):
    _, _, dm, executor = rig
    step = flow_step(value)
    assert not asyncio.run(executor.execute(step))
    assert not dm.start_pump_channel.called
    with pytest.raises(ValueError):
        parse_experiment_data({'steps': [dict(id=step.id, type='pump.start', params=step.params)]}, validate_devices=False)


@pytest.mark.parametrize('change', [dict(mode='TIME_SPEED'), dict(run_time=3), dict(dispense_volume=1), dict(repeat_count=1), dict(interval_time=1)])
def test_conflicting_parameters_rejected(rig, change):
    _, _, dm, executor = rig
    step = flow_step()
    step.params.update(change)
    assert not asyncio.run(executor.execute(step))
    assert not dm.start_pump_channel.called


def test_skip_disabled_and_additional_wait_rejected(rig):
    _, _, dm, executor = rig
    for change in ({'on_error': 'skip'}, {'enabled': False}, {'wait': WaitCondition(type=WaitType.DURATION, seconds=1)}):
        step = flow_step()
        for key, value in change.items():
            setattr(step, key, value)
        assert not asyncio.run(executor.execute(step))
    assert not dm.start_pump_channel.called


def test_guided_drains_flow_but_clean_inlet_stays_quantity():
    request = spec(prime_drain_flow=2, drain_flow=15, prime_drain_seconds=4,
                   product_drain_seconds=300, clean_drain_seconds=200)
    plans = [guided.priming_recipe(request, 'test'), *guided.compile_plan(request)]
    drains = []
    for plan in plans:
        assert validate_source(yaml.safe_dump(plan))['valid']
        for step in plan['steps']:
            if step['type'] == 'pump.start':
                params = step['params']
                if params['channel'] == 4:
                    drains.append(params)
                    assert params['mode'] == 'FLOW_MODE'
                    assert 'run_time' not in params and 'dispense_volume' not in params
                    assert 'wait' not in step
                else:
                    assert params['mode'] == 'TIME_QUANTITY'
                    assert step['wait']['type'] == 'pump_complete'
    assert [(p['flow_rate'], p['flow_duration_seconds']) for p in drains] == [(2, 4), (15, 300), (15, 200)]


def test_existing_non_timed_flow_and_old_quantity_stay_unchanged(rig):
    _, _, dm, executor = rig
    step = flow_step()
    del step.params['flow_duration_seconds']
    assert asyncio.run(executor.execute(step))
    assert not dm.stop_pump_channel.called and not dm.read_pump_status.called
    old = copy.deepcopy(step)
    old.params.update(mode='TIME_QUANTITY', run_time=3, dispense_volume=.75, time_unit=0, volume_unit=1)
    assert asyncio.run(executor.execute(old))
    assert dm.start_pump_channel.call_args.args[4].name == 'TIME_QUANTITY'
