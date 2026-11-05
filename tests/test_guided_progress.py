"""Progress observes existing execution; fake time, no serial devices."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.experiment import executor as execution, progress
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine, ExperimentState
from test_automation_safety_fixes import fake_clock
from test_guided_preparation import stable_wait


def test_stability_snapshot_uses_reads_resets_and_freezes(monkeypatch):
    clock = fake_clock(monkeypatch)
    seen, calls = [], []
    def read(did):
        calls.append((clock.now, did))
        seen.append(executor.activity.snapshot())
        target = 30 if did == 'heater1' else 40
        return dict(pv=target + (4 if 10 <= clock.now < 11 else 0))
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    step = ExperimentStep('heat_both_stable', ActionType.WAIT, wait=stable_wait())
    assert asyncio.run(executor.execute(step))
    snap = executor.activity_snapshot
    assert snap['stable_seconds'] >= 30
    assert progress.guided_activity(step, snap)['stage'] == 'stabilizing'
    assert any(s['stable_seconds'] >= 9 for s in seen)
    assert any(s['stable_seconds'] == 0 for s in seen[22:26])
    assert 41 <= clock.now < 42
    assert len(calls) == 84  # Same two reads per existing 1-second iteration.
    clock.now += 100
    assert executor.activity_snapshot == snap
    snap['readings'][0]['value'] = 999
    assert executor.activity_snapshot['readings'][0]['value'] == 30


def test_wait_clock_freezes_dwell_but_pump_reference_keeps_running(monkeypatch):
    clock = fake_clock(monkeypatch)
    monkeypatch.setattr(progress, 'time', SimpleNamespace(monotonic=clock.monotonic, time=lambda: 123))
    executor = execution.StepExecutor(Mock())
    executor.activity.wait(WaitCondition(type=WaitType.DURATION, seconds=30))
    clock.now = 10
    executor.notify_pause(True)
    clock.now = 20
    assert executor.activity.snapshot()['remaining_seconds'] == 20
    executor.notify_pause(False)
    executor.activity.pump_started(5)
    clock.now = 23
    executor.notify_pause(True)
    clock.now = 27
    snap = executor.activity.snapshot()
    assert snap['remaining_seconds'] == 0 and snap['state'] == 'waiting'
    assert snap['reference'] is True
    executor.activity.stable_seconds = 12
    executor.notify_pause(False)
    executor.notify_pause(True)
    assert executor.activity.snapshot()['stable_seconds'] == 0


@pytest.mark.parametrize('mode', ['timeout', 'read_error', 'stop'])
def test_failed_waits_do_not_report_completion(monkeypatch, mode):
    clock = fake_clock(monkeypatch)
    read = Mock(return_value=dict(pv=0))
    if mode == 'read_error':
        read.side_effect = IOError('offline')
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    if mode == 'stop':
        executor.set_stop_checker(lambda: True)
    assert not asyncio.run(executor.execute(ExperimentStep('heat_both_stable', ActionType.WAIT,
        wait=stable_wait(timeout=2))))
    snap = executor.activity_snapshot
    assert snap['state'] == 'failed'
    if mode == 'read_error':
        assert all(r['value'] is None for r in snap['readings'])
    clock.now += 30
    assert executor.activity_snapshot == snap


def test_new_step_and_new_engine_clear_previous_activity(monkeypatch):
    fake_clock(monkeypatch)
    executor = execution.StepExecutor(Mock())
    step = ExperimentStep('clean_0_dwell', ActionType.WAIT,
        wait=WaitCondition(type=WaitType.DURATION, seconds=2))
    assert asyncio.run(executor.execute(step))
    assert executor.activity_snapshot['remaining_seconds'] == 0
    engine = ExperimentEngine(executor)
    engine.load_steps([step])
    assert engine.progress.activity is None
    asyncio.run(executor.execute(step))
    engine._steps.append(ExperimentStep('heat_both_stable', ActionType.WAIT, wait=stable_wait()))
    engine._state = ExperimentState.PAUSED
    engine._current_step = 1
    assert engine.progress.activity is None


def test_hold_snapshot_uses_existing_clock_and_reads(monkeypatch):
    clock = fake_clock(monkeypatch)
    read = Mock(return_value=dict(read_ok=True, fault_code=0, material_temperature=60,
        control_active=True, output_active=True, status_confirmed=True))
    executor = execution.StepExecutor(Mock(read_microwave_data=read))
    step = ExperimentStep('hold', ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, seconds=3, device_id='microwave1'))
    assert asyncio.run(executor.execute(step))
    assert executor.activity_snapshot['remaining_seconds'] == 0
    assert read.call_count == 4
    assert 3 <= clock.now < 3.1


def test_pump_reference_starts_after_ack_and_zero_does_not_complete(monkeypatch):
    clock = fake_clock(monkeypatch)
    monkeypatch.setattr(progress, 'time', SimpleNamespace(monotonic=clock.monotonic, time=lambda: 123))
    seen = []
    def start(*args):
        clock.now += 5  # Driver configuration and START readback take time.
        assert executor.activity.snapshot()['duration_seconds'] is None
        return True
    def read(*args):
        seen.append(executor.activity.snapshot())
        stopped = clock.now >= 7
        return {'channels': {'4': dict(read_ok=True, running=not stopped, run_status='STOP' if stopped else 'START')}}
    dm = Mock(start_pump_channel=Mock(side_effect=start), read_pump_status=Mock(side_effect=read))
    executor = execution.StepExecutor(dm)
    step = ExperimentStep('collect_product', ActionType.PUMP_START,
        params=dict(device_id='pump1', channel=4, mode='TIME_SPEED', run_time=1, time_unit=0),
        wait=WaitCondition(type=WaitType.PUMP_COMPLETE, device_id='pump1', channel=4, timeout=10))
    assert asyncio.run(executor.execute(step))
    assert seen[0]['elapsed_seconds'] == 0
    assert seen[1]['remaining_seconds'] == 0 and seen[1]['state'] == 'waiting'
    assert dm.start_pump_channel.call_count == 1 and dm.read_pump_status.call_count == 3
    assert executor.activity_snapshot['state'] == 'completed'


def test_microwave_confirmed_status_is_not_unknown():
    activity = progress.ActivityProgress(lambda: 0)
    activity.device('microwave1', dict(status_confirmed=True, running=False,
        control_word=16384, current_segment=4, runtime_seconds=0))
    device = activity.snapshot()['devices']['microwave1']
    assert device['read_ok'] is True and device['running'] is False
    assert device['control_word'] == 16384
    activity.device('microwave1', dict(status_confirmed=True, read_ok=False))
    assert activity.snapshot()['devices']['microwave1']['read_ok'] is False
    activity.device('microwave1', dict(status_confirmed=False))
    assert activity.snapshot()['devices']['microwave1']['read_ok'] is False


def test_water_test_early_exit_retains_failure_and_diagnostics(monkeypatch):
    clock = fake_clock(monkeypatch)
    def read(_):
        active = clock.now < 180
        return dict(status_confirmed=True, fault_code=0, material_temperature=61.171875,
            control_active=active, running=active, control_word=22528 if active else 16384,
            current_segment=1 if active else 4, runtime_seconds=119 if active else 0)
    executor = execution.StepExecutor(Mock(read_microwave_data=read))
    step = ExperimentStep('hold', ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, seconds=600, device_id='microwave1'))
    assert not asyncio.run(executor.execute(step))
    assert 180 <= clock.now < 181
    assert '剩余 420.0 秒' in executor._last_error
    assert '控制字=16384' in executor._last_error
    assert executor.activity_snapshot['devices']['microwave1']['read_ok'] is True
    assert executor.activity_snapshot['state'] == 'failed'


@pytest.mark.parametrize('step_id', ['prime_temperature', 'prime_recheck_temperature',
                                    'cool_before_collection', 'recheck_temperature'])
@pytest.mark.parametrize('target', [45, 55, None])
def test_cooling_description_follows_step_without_mutation(step_id, target):
    step = ExperimentStep(step_id, ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_BELOW, device_id='microwave1',
        target_temperature=target))
    observation = dict(state='waiting', readings=[dict(value=60)], devices={})
    before = copy.deepcopy((step, observation))
    activity = progress.guided_activity(step, observation)
    if target is None:
        assert '45' not in activity['description'] and '55' not in activity['description']
        assert '设定降温条件' in activity['description']
    else:
        assert f'{target}℃' in activity['description']
        assert activity['parameters']['target_temperature'] == target
    assert (step, observation) == before


@pytest.mark.parametrize('tolerance,seconds', [(3, 30), (5, 15)])
def test_legacy_priming_stability_description_uses_saved_parameters(tolerance, seconds):
    step = ExperimentStep('prime_heat_both_stable', ActionType.WAIT,
        wait=WaitCondition(type=WaitType.HEATER_PAIR_STABLE, tolerance=tolerance, seconds=seconds))
    description = progress.guided_activity(step, {})['description']
    assert f'±{tolerance}℃' in description and f'{seconds} 秒' in description


@pytest.mark.parametrize('tolerance,timeout', [(3, 1200), (5, 750)])
def test_qualified_hold_description_uses_actual_tolerance_and_total_timeout(tolerance, timeout):
    step = ExperimentStep('hold', ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_MONITORED_HOLD, seconds=600, target_temperature=60,
        tolerance=tolerance, timeout=timeout))
    description = progress.guided_activity(step, dict(qualified_seconds=0))['description']
    assert f'±{tolerance}℃' in description
    assert f'总等待上限 {timeout} 秒' in description
    assert '额外等待10分钟' not in description


def test_hold_description_without_target_does_not_invent_temperature_band():
    step = ExperimentStep('hold', ActionType.WAIT,
        wait=WaitCondition(type=WaitType.MICROWAVE_MONITORED_HOLD, seconds=60))
    description = progress.guided_activity(step, dict(hold_mode='timed'))['description']
    assert '稳定到温' not in description and '±' not in description
    assert '按设定时长' in description


def test_progress_description_does_not_issue_device_calls():
    dm = Mock()
    executor = execution.StepExecutor(dm)
    step = ExperimentStep('prime_temperature', ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_BELOW, device_id='microwave1', target_temperature=55))
    executor.activity.reset(step)
    snapshot = executor.activity.snapshot()
    progress.guided_activity(step, snapshot)
    assert dm.mock_calls == []
    assert executor.activity.snapshot() == snapshot


@pytest.mark.parametrize('step_id', ['prime_temperature', 'prime_recheck_temperature',
                                    'cool_before_collection', 'recheck_temperature'])
@pytest.mark.parametrize('target', [45, 55, None])
def test_batch_step_label_uses_active_step_parameters(step_id, target, tmp_path):
    from src.experiment.guided import GuidedBatch
    from test_guided import FakeManager, spec

    dm = FakeManager()
    batch = GuidedBatch(dm, spec(), directory=tmp_path)
    step = ExperimentStep(step_id, ActionType.WAIT, wait=WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_BELOW, target_temperature=target))
    batch.engine = ExperimentEngine(batch.executor)
    batch.engine.load_steps([step])
    batch.executor._activity_step = step
    before = copy.deepcopy((step, dm.calls, batch.record))
    label = batch.snapshot()['progress']['step_label']
    if target is None:
        assert '45' not in label and '55' not in label
    else:
        assert f'≤{target}℃' in label
    assert (step, dm.calls, batch.record) == before


@pytest.mark.parametrize('step_id,tolerance,seconds', [
    ('heat_both_stable', 5, 30), ('prime_heat_both_stable', 3, 15),
    ('prime_heat_duration', 1, 90)])
def test_batch_wait_label_uses_step_and_handles_missing_activity(step_id, tolerance, seconds, tmp_path):
    from src.experiment.guided import GuidedBatch
    from test_guided import FakeManager, spec

    batch = GuidedBatch(FakeManager(), spec(), directory=tmp_path)
    step = ExperimentStep(step_id, ActionType.WAIT, wait=WaitCondition(
        type=WaitType.DURATION if step_id == 'prime_heat_duration' else WaitType.HEATER_PAIR_STABLE,
        tolerance=tolerance, seconds=seconds))
    batch.engine = ExperimentEngine(batch.executor)
    batch.engine.load_steps([step])
    assert not any(c.isdigit() for c in batch.snapshot()['progress']['step_label'])
    batch.executor._activity_step = step
    label = batch.snapshot()['progress']['step_label']
    assert f'{seconds} 秒' in label
    if step_id != 'prime_heat_duration':
        assert f'±{tolerance}℃' in label
