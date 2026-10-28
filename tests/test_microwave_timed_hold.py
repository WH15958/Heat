"""Fixed microwave holding after a continuously stable temperature entry gate."""
import asyncio
from types import SimpleNamespace

import pytest

from src.experiment import executor as execution
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.parser import parse_experiment_data
from test_automation_safety_fixes import fake_clock


def state(temperature=60, **changes):
    result = dict(material_temperature=temperature, fault_code=0,
                  status_confirmed=True, control_active=True, control_word=0x5000)
    result.update(changes)
    return result


def stable(**changes):
    params = dict(type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
                  device_id='microwave1', target_temperature=60,
                  tolerance=3, seconds=30, timeout=60)
    params.update(changes)
    return WaitCondition(**params)


def timed_hold(seconds=3, **changes):
    params = dict(type=WaitType.MICROWAVE_MONITORED_HOLD,
                  device_id='microwave1', target_temperature=60,
                  tolerance=3, seconds=seconds, timeout=max(1, seconds),
                  hold_mode='timed')
    params.update(changes)
    return WaitCondition(**params)


def run_step(executor, condition):
    return asyncio.run(executor.execute(ExperimentStep(
        'hold' if condition.type == WaitType.MICROWAVE_MONITORED_HOLD else 'microwave_start',
        ActionType.WAIT, wait=condition)))


@pytest.mark.parametrize('source', ['guided', 'program'])
@pytest.mark.parametrize('profile', ['lower', 'upper', 'outside', 'reset', 'late'])
def test_generated_microwave_gate_uses_five_degrees_and_fifteen_seconds(monkeypatch, source, profile):
    from src.experiment import guided, microwave_program
    from test_guided import spec

    if source == 'guided':
        request = spec(axes=[[30], [30], [0.1], [0.2], [80], [0]], heating_timeout=30)
        steps = parse_experiment_data(guided.recipe(request.rows()[0], request, 'test', 0))['steps']
        condition = next(s.wait for s in steps if s.id == 'microwave_start')
    else:
        request = microwave_program.ProgramRequest(request_id='a'*32, mode='auto_power',
            stages=[dict(temperature=80, hold_seconds=0)], heating_timeout=30)
        condition = microwave_program.compile_steps('microwave1', request)[1].wait
    clock = fake_clock(monkeypatch)
    def read(device_id):
        temperature = 75 if profile == 'lower' else 85
        if profile == 'outside' or (profile == 'reset' and 10 <= clock.now < 11):
            temperature = 85.01
        if profile == 'late' and clock.now < 20:
            temperature = 70
        return state(temperature)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert run_step(executor, condition) is (profile not in ('outside', 'late'))
    expected = 26 if profile == 'reset' else 30 if profile in ('outside', 'late') else 15
    assert expected <= clock.now < expected + 1
    assert executor.activity_snapshot['stable_required_seconds'] == 15


@pytest.mark.parametrize('temperature', [57, 60, 63])
def test_stable_entry_requires_full_30_seconds_at_inclusive_boundaries(monkeypatch, temperature):
    clock = fake_clock(monkeypatch)
    reads = []
    def read(device_id):
        reads.append(clock.now)
        return state(temperature)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert run_step(executor, stable())
    assert clock.now == pytest.approx(30, abs=.21)
    assert len(reads) > 1
    assert reads[-1] - reads[0] >= 30 - 1e-8
    assert executor.activity_snapshot['stable_seconds'] == pytest.approx(30)
    assert executor.activity_snapshot['stable_required_seconds'] == 30


def test_stable_entry_excursion_resets_instead_of_accumulating(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(64 if 20 <= clock.now < 21 else 60)))
    assert run_step(executor, stable())
    assert 51 <= clock.now < 52
    assert executor.activity_snapshot['stable_seconds'] == pytest.approx(30)


@pytest.mark.parametrize('temperature', [56.99, 63.01])
def test_stable_entry_never_succeeds_outside_band(monkeypatch, temperature):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(temperature)))
    assert not run_step(executor, stable(timeout=31))
    assert 31 <= clock.now < 32
    assert executor.activity_snapshot['stable_seconds'] == 0


def test_stability_is_part_of_original_heating_timeout(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(20 if clock.now < 35 else 60)))
    assert not run_step(executor, stable(timeout=60))
    assert 60 <= clock.now < 61
    assert executor.activity_snapshot['stable_seconds'] < 30


def inject_pause(monkeypatch, executor, clock, *, after, duration):
    paused = False
    injected = False
    executor.set_pause_checker(lambda: paused)
    async def sleep(seconds):
        nonlocal paused, injected
        # A real scheduler advances even when subtraction leaves a sub-ULP wait.
        clock.now += max(seconds, 1e-8)
        clock.sleeps += 1
        if not injected and clock.now >= after:
            injected = True
            paused = True
            executor.notify_pause(True)
        elif paused:
            clock.now += duration
            paused = False
            executor.notify_pause(False)
    monkeypatch.setattr(execution.asyncio, 'sleep', sleep)


def test_actual_pause_restarts_stability_and_does_not_consume_timeout(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state()))
    inject_pause(monkeypatch, executor, clock, after=15, duration=100)
    assert run_step(executor, stable())
    assert 145 <= clock.now < 146
    assert executor.activity_snapshot['stable_seconds'] == pytest.approx(30)
    assert executor.activity_snapshot['elapsed_seconds'] < 46


@pytest.mark.parametrize('changes', [dict(fault_code=1), dict(status_confirmed=False),
    dict(control_active=False), dict(control_active=None), dict(read_ok=False),
    dict(material_temperature=float('nan'))])
def test_stability_cannot_finish_on_invalid_deadline_sample(monkeypatch, changes):
    clock = fake_clock(monkeypatch)
    def read(device_id):
        return state(**changes) if clock.now >= 29.9 else state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not run_step(executor, stable())
    assert clock.now < 31


def test_stability_stop_during_deadline_read_has_priority(monkeypatch):
    clock = fake_clock(monkeypatch)
    stopped = False
    def read(device_id):
        nonlocal stopped
        if clock.now >= 29.9:
            stopped = True
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    executor.set_stop_checker(lambda: stopped)
    assert not run_step(executor, stable())
    assert clock.now < 31


@pytest.mark.parametrize('kind', ['read', 'gap'])
def test_stability_late_data_cannot_complete_the_gate(monkeypatch, kind):
    clock = fake_clock(monkeypatch, stall=8 if kind == 'gap' else 0)
    def read(device_id):
        if kind == 'read':
            clock.now += 8
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not run_step(executor, stable())
    assert clock.now < 30
    assert '通讯预算' in executor.last_error


def test_old_temperature_wait_retains_immediate_entry_default(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state()))
    condition = WaitCondition(type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
                              device_id='microwave1', target_temperature=60)
    assert run_step(executor, condition)
    assert clock.now == 0


@pytest.mark.parametrize('temperature', [20, 56.99, 57, 60, 63, 63.01, 73])
def test_fixed_hold_counts_time_even_when_temperature_is_outside_band(monkeypatch, temperature):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(temperature)))
    assert run_step(executor, timed_hold())
    assert clock.now == pytest.approx(3)
    snapshot = executor.activity_snapshot
    assert snapshot['elapsed_seconds'] == pytest.approx(3)
    assert snapshot['remaining_seconds'] == 0
    assert snapshot['qualified_seconds'] is None
    assert snapshot['hold_in_band'] is (57 <= temperature <= 63)


def test_temperature_excursions_do_not_restart_fixed_hold(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(73 if 1 <= clock.now < 2 else 60)))
    assert run_step(executor, timed_hold())
    assert clock.now == pytest.approx(3)
    assert executor.activity_snapshot['qualified_seconds'] is None


def test_fixed_hold_actual_pause_is_excluded_without_restarting_timer(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state(70)))
    inject_pause(monkeypatch, executor, clock, after=1, duration=100)
    assert run_step(executor, timed_hold())
    assert 103 <= clock.now < 104
    assert executor.activity_snapshot['elapsed_seconds'] == pytest.approx(3)
    assert executor.activity_snapshot['qualified_seconds'] is None


def test_pending_pause_request_does_not_freeze_fixed_hold(monkeypatch):
    clock = fake_clock(monkeypatch)
    orchestration = SimpleNamespace(pause_pending=True, paused=False)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state(70)))
    executor.set_pause_checker(lambda: orchestration.paused)
    assert run_step(executor, timed_hold())
    assert orchestration.pause_pending and clock.now == pytest.approx(3)


@pytest.mark.parametrize('seconds', [0, 3])
@pytest.mark.parametrize('failure', [IOError('lost'), dict(fault_code=1),
    dict(status_confirmed=False), dict(control_active=False), dict(read_ok=False),
    dict(material_temperature=float('nan'))])
def test_fixed_hold_checks_failure_before_deadline_success(monkeypatch, seconds, failure):
    clock = fake_clock(monkeypatch)
    reads = []
    def read(device_id):
        reads.append(clock.now)
        if clock.now >= seconds:
            if isinstance(failure, Exception):
                raise failure
            return state(**failure)
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not run_step(executor, timed_hold(seconds))
    assert reads
    assert executor.activity_snapshot['state'] == 'failed'


@pytest.mark.parametrize('seconds', [0, 3])
def test_fixed_hold_stop_received_in_last_read_has_priority(monkeypatch, seconds):
    clock = fake_clock(monkeypatch)
    stopped = False
    def read(device_id):
        nonlocal stopped
        stopped = clock.now >= seconds
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    executor.set_stop_checker(lambda: stopped)
    assert not run_step(executor, timed_hold(seconds))


def test_exit_before_deadline_returning_after_it_is_failure(monkeypatch):
    clock = fake_clock(monkeypatch)
    def read(device_id):
        if clock.now >= 59:
            clock.now += 2.1
            return state(control_active=False, control_word=0x4000)
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not run_step(executor, timed_hold(60))
    assert clock.now == pytest.approx(61.1)


@pytest.mark.parametrize('kind', ['read', 'gap'])
def test_fixed_hold_late_data_cannot_finish_timer(monkeypatch, kind):
    clock = fake_clock(monkeypatch, stall=8 if kind == 'gap' else 0)
    def read(device_id):
        if kind == 'read':
            clock.now += 8
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not run_step(executor, timed_hold(timeout=603))
    assert '通讯预算' in executor.last_error


def test_zero_second_fixed_hold_still_reads_and_validates_device(monkeypatch):
    clock = fake_clock(monkeypatch)
    reads = []
    def read(device_id):
        reads.append(device_id)
        return state(70)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert run_step(executor, timed_hold(0))
    assert reads == ['microwave1']
    assert clock.now == 0


@pytest.mark.parametrize('success', [True, False])
def test_terminal_fixed_hold_progress_is_frozen(monkeypatch, success):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(control_active=success)))
    assert run_step(executor, timed_hold()) is success
    snapshot = executor.activity_snapshot
    clock.now += 100
    assert executor.activity_snapshot == snapshot
    assert snapshot['qualified_seconds'] is None


@pytest.mark.parametrize('mode', ['timed', 'qualified'])
def test_yaml_explicit_hold_mode_roundtrips(mode):
    data = dict(steps=[dict(id='hold', type='wait', wait=dict(
        type='microwave_monitored_hold', device_id='microwave1',
        target_temperature=60, tolerance=3, timeout=603, seconds=3, hold_mode=mode))])
    experiment = parse_experiment_data(data)
    assert experiment['steps'][0].wait.hold_mode == mode


def test_yaml_old_supervised_hold_keeps_qualified_default():
    data = dict(steps=[dict(id='hold', type='wait', wait=dict(
        type='microwave_monitored_hold', device_id='microwave1',
        target_temperature=60, tolerance=3, timeout=603, seconds=3))])
    assert parse_experiment_data(data)['steps'][0].wait.hold_mode == 'qualified'
