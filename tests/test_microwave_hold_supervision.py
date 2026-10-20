"""Temperature-qualified microwave holding with a simulated monotonic clock."""
import asyncio
from types import SimpleNamespace

import pytest

from src.experiment import executor as execution
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.parser import parse_experiment_data
from test_automation_safety_fixes import fake_clock


def state(temperature=60, **changes):
    return dict(material_temperature=temperature, fault_code=0, status_confirmed=True,
                control_active=True, control_word=0x5000, **changes)


def hold(seconds=3, **changes):
    return WaitCondition(type=WaitType.MICROWAVE_MONITORED_HOLD, device_id='microwave1',
                         seconds=seconds, target_temperature=60, tolerance=3,
                         timeout=seconds+600, **changes)


def execute(monkeypatch, temperatures, seconds=3, timeout=None):
    clock = fake_clock(monkeypatch)
    readings = iter(temperatures)
    last = temperatures[-1]
    executor = execution.StepExecutor(SimpleNamespace(
        read_microwave_data=lambda did: state(next(readings, last))))
    condition = hold(seconds)
    if timeout is not None:
        condition.timeout = timeout
    result = asyncio.run(executor.execute(ExperimentStep('hold', ActionType.WAIT, wait=condition)))
    return result, executor, clock


@pytest.mark.parametrize('temperature', [57, 60, 63])
def test_inclusive_temperature_boundaries(monkeypatch, temperature):
    success, executor, clock = execute(monkeypatch, [temperature])
    assert success and clock.now == pytest.approx(3)
    assert executor.activity_snapshot['qualified_seconds'] == pytest.approx(3)
    assert executor.activity_snapshot['remaining_seconds'] == 0


def test_cold_temperature_never_qualifies(monkeypatch):
    success, executor, clock = execute(monkeypatch, [20], timeout=5)
    assert not success and clock.now == pytest.approx(5)
    assert executor.activity_snapshot['qualified_seconds'] == 0
    assert '保温超时' in executor.last_error


def test_default_policy_has_a_finite_extra_600_seconds(monkeypatch):
    success, executor, clock = execute(monkeypatch, [20], seconds=1)
    assert not success and clock.now == pytest.approx(601)
    assert executor.activity_snapshot['hold_timeout_seconds'] == 601


@pytest.mark.parametrize('zero', [True, False])
def test_stop_received_during_read_wins_over_completion(monkeypatch, zero):
    fake_clock(monkeypatch)
    stopped = False
    def read(did):
        nonlocal stopped
        stopped = True
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    executor.set_stop_checker(lambda: stopped)
    assert not asyncio.run(executor._wait_condition(hold(0 if zero else 1)))


def test_legacy_wait_can_succeed_without_claiming_qualified_temperature(monkeypatch):
    fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state(20)))
    condition = hold(1)
    condition.target_temperature = None
    assert asyncio.run(executor._wait_condition(condition))
    assert executor.activity.qualified_seconds is None


def test_excursion_preserves_qualified_time_but_does_not_bridge_bad_samples(monkeypatch):
    success, executor, clock = execute(monkeypatch, [60, 60, 64, 60, 60, 60])
    assert success and clock.now == pytest.approx(5)
    assert executor.activity_snapshot['qualified_seconds'] == pytest.approx(3)
    frozen = executor.activity_snapshot
    clock.now += 100
    assert executor.activity_snapshot == frozen


@pytest.mark.parametrize('supervised', [True, False])
def test_stopped_sample_returning_past_deadline_cannot_succeed(monkeypatch, supervised):
    clock = fake_clock(monkeypatch)
    def read(did):
        if clock.now >= 59:
            clock.now += 2.1
            return dict(state(), control_active=False, control_word=0x4000)
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    condition = hold(60)
    if not supervised:
        condition.target_temperature = None
    assert not asyncio.run(executor._wait_condition(condition))
    assert '退出控制' in executor.last_error
    assert clock.now == pytest.approx(61.1)


@pytest.mark.parametrize('slow_kind', ['read', 'gap'])
def test_slow_read_or_sampling_gap_does_not_credit_elapsed_time(monkeypatch, slow_kind):
    clock = fake_clock(monkeypatch, stall=8 if slow_kind == 'gap' else 0)
    def read(did):
        if slow_kind == 'read':
            clock.now += 8
        return state()
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not asyncio.run(executor._wait_condition(hold()))
    assert '通讯预算' in executor.last_error


def test_actual_pause_preserves_time_without_bridging_pause(monkeypatch):
    clock = fake_clock(monkeypatch)
    paused = False
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state()))
    executor.set_pause_checker(lambda: paused)
    async def sleep(seconds):
        nonlocal paused
        clock.now += seconds
        clock.sleeps += 1
        if clock.sleeps == 2:
            paused = True
            executor.notify_pause(True)
        elif paused:
            clock.now += 100
            paused = False
            executor.notify_pause(False)
    monkeypatch.setattr(execution.asyncio, 'sleep', sleep)
    assert asyncio.run(executor._wait_condition(hold()))
    assert clock.now >= 103
    assert executor.activity.qualified_seconds == pytest.approx(3)


@pytest.mark.parametrize('payload', [IOError('lost'), dict(state(), status_confirmed=False),
    dict(state(), status_confirmed=None), {k: v for k, v in state().items() if k != 'status_confirmed'},
    dict(state(), read_ok=False), dict(state(), read_ok=None), state(float('nan')), dict(state(), fault_code=1)])
def test_unknown_or_failed_read_never_finishes(monkeypatch, payload):
    fake_clock(monkeypatch)
    def read(did):
        if isinstance(payload, Exception):
            raise payload
        return payload
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    assert not asyncio.run(executor._wait_condition(hold(0)))


@pytest.mark.parametrize('missing', ['target_temperature', 'tolerance', 'timeout'])
def test_yaml_supervised_hold_requires_explicit_policy(missing):
    wait = dict(type='microwave_monitored_hold', device_id='microwave1', seconds=3,
                target_temperature=60, tolerance=3, timeout=603)
    del wait[missing]
    if missing == 'target_temperature':
        # A legacy wait with no target remains a control-supervised timer.
        assert parse_experiment_data(dict(steps=[dict(id='hold', type='wait', wait=wait)]))
    else:
        with pytest.raises(ValueError):
            parse_experiment_data(dict(steps=[dict(id='hold', type='wait', wait=wait)]))


@pytest.mark.parametrize('changes', [dict(target_temperature=None), dict(tolerance=True),
    dict(timeout=0), dict(timeout=2), dict(target_temperature=float('nan'))])
def test_yaml_invalid_temperature_policy_does_not_degrade_to_legacy(changes):
    wait = dict(type='microwave_monitored_hold', device_id='microwave1', seconds=3,
                target_temperature=60, tolerance=3, timeout=603)
    wait.update(changes)
    with pytest.raises(ValueError):
        parse_experiment_data(dict(steps=[dict(id='hold', type='wait', wait=wait)]))
