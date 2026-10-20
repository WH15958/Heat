"""Progress observes existing execution; fake time, no serial devices."""
import asyncio
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
