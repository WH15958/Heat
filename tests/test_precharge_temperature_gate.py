"""Precharge starts its existing dwell at dual-heater target arrival, without hardware."""
import asyncio
import copy
from unittest.mock import Mock

import pytest
import yaml

from src.experiment import executor as execution, guided, parser
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.editor import validate_source
from test_automation_safety_fixes import fake_clock
from test_guided import spec


def reached_wait(**changes):
    return WaitCondition(**{**dict(type=WaitType.HEATER_PAIR_REACHED, timeout=60,
        targets=[dict(device_id='heater1', target_temperature=50),
                 dict(device_id='heater2', target_temperature=50)]), **changes})


@pytest.mark.parametrize('values', [(50, 50), (50.8, 56.1)])
def test_target_arrival_including_overshoot_passes_without_stability_delay(monkeypatch, values):
    clock = fake_clock(monkeypatch)
    calls = []
    def read(did):
        calls.append(did)
        return dict(pv=values[int(did[-1])-1], read_ok=True, fault_code=0)
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    step = ExperimentStep('prime_heat_both_reached', ActionType.WAIT, wait=reached_wait())
    assert asyncio.run(executor.execute(step))
    assert clock.now == 0
    assert calls == ['heater1', 'heater2']
    snapshot = executor.activity_snapshot
    assert snapshot['state'] == 'completed'
    assert snapshot['stable_required_seconds'] is None
    assert [r['value'] for r in snapshot['readings']] == list(values)
    clock.now += 100
    assert executor.activity_snapshot == snapshot


def test_both_explicit_targets_must_pass_in_same_sampling_cycle(monkeypatch):
    clock = fake_clock(monkeypatch)
    calls = []
    def read(did):
        cycle = len(calls) // 2
        calls.append(did)
        values = [(60, 34.9), (49.9, 40), (50, 35)]
        return dict(pv=values[min(cycle, 2)][int(did[-1])-1])
    wait = reached_wait(targets=[dict(device_id='heater1', target_temperature=50),
                                dict(device_id='heater2', target_temperature=35)])
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert asyncio.run(executor._wait_condition(wait))
    assert calls == ['heater1', 'heater2'] * 3
    assert 2 <= clock.now < 2.1


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), True, '50', -1])
def test_unknown_temperature_cannot_start_dwell(monkeypatch, bad):
    fake_clock(monkeypatch)
    read = Mock(side_effect=[dict(pv=50.8), dict(pv=bad)])
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert not asyncio.run(executor._wait_condition(reached_wait()))
    assert '读取失败' in executor.last_error


@pytest.mark.parametrize('failure', [IOError('sensor offline'),
    dict(pv=60, read_ok=False), dict(pv=60, fault_code=1)])
def test_read_failure_or_device_fault_cannot_start_dwell(monkeypatch, failure):
    fake_clock(monkeypatch)
    read = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert not asyncio.run(executor._wait_condition(reached_wait()))
    assert '读取失败' in executor.last_error


@pytest.mark.parametrize('stop_when', ['before_read', 'during_read'])
def test_stop_takes_priority_over_reached_temperature(monkeypatch, stop_when):
    fake_clock(monkeypatch)
    stopped = stop_when == 'before_read'
    def read(_):
        nonlocal stopped
        stopped = True
        return dict(pv=60)
    reader = Mock(side_effect=read)
    executor = execution.StepExecutor(Mock(read_heater_data=reader))
    executor.set_stop_checker(lambda: stopped)
    assert not asyncio.run(executor._wait_condition(reached_wait()))
    assert reader.call_count == (0 if stop_when == 'before_read' else 1)


@pytest.mark.parametrize('late_read', [False, True])
def test_timeout_cannot_be_overridden_by_late_target_read(monkeypatch, late_read):
    clock = fake_clock(monkeypatch)
    def read(_):
        if late_read:
            clock.now += 2
        return dict(pv=60 if late_read else 49.9)
    executor = execution.StepExecutor(Mock(read_heater_data=read))
    assert not asyncio.run(executor._wait_condition(reached_wait(timeout=1)))
    assert '超时' in executor.last_error


def test_pause_during_read_discards_observation_and_rechecks_after_resume(monkeypatch):
    clock = fake_clock(monkeypatch)
    calls = []
    executor = execution.StepExecutor(Mock())
    def read(did):
        calls.append(did)
        if len(calls) == 1:
            executor.notify_pause(True)
            clock.now += 100
            executor.notify_pause(False)
        return dict(pv=60)
    executor._dm.read_heater_data = read
    assert asyncio.run(executor._wait_condition(reached_wait(timeout=1)))
    assert calls == ['heater1', 'heater2'] * 2
    assert executor._wait_clock() == 0


def test_generated_threshold_wait_retains_validation_and_legacy_stability():
    data = guided.priming_recipe(spec(), 'arrival')
    step = next(s for s in data['steps'] if s['id'] == 'prime_heat_both_reached')
    parsed = parser.parse_experiment_data(dict(steps=[step]))['steps'][0]
    assert parsed.wait.type == WaitType.HEATER_PAIR_REACHED
    assert parsed.wait.seconds == 0
    assert validate_source(yaml.safe_dump(data))['valid']
    for changes in (dict(seconds=1), dict(timeout=0), dict(targets=[]),
                    dict(targets=[dict(device_id='heater1', target_temperature=50)] * 2),
                    dict(targets=[dict(device_id='heater1', target_temperature=True),
                                  dict(device_id='heater2', target_temperature=50)]),
                    dict(targets=[dict(device_id='heater1', target_temperature=50),
                                  dict(device_id='pump1', target_temperature=50)])):
        bad = copy.deepcopy(step)
        bad['wait'].update(changes)
        with pytest.raises(ValueError):
            parser.parse_experiment_data(dict(steps=[bad]))
    for changes in (dict(enabled=False), dict(on_error='skip')):
        with pytest.raises(ValueError):
            parser.parse_experiment_data(dict(steps=[{**step, **changes}]))
    legacy = copy.deepcopy(step)
    legacy['id'] = 'prime_heat_both_stable'
    legacy['wait'].update(type='heater_pair_stable', tolerance=3, seconds=30)
    old = parser.parse_experiment_data(dict(steps=[legacy]))['steps'][0]
    assert old.wait.type == WaitType.HEATER_PAIR_STABLE
    assert (old.wait.tolerance, old.wait.seconds) == (3, 30)
    unknown = copy.deepcopy(step)
    unknown['wait']['targets'][0]['device_id'] = 'missing_heater'
    checked = validate_source(yaml.safe_dump(dict(steps=[unknown])))
    assert checked['valid']
    assert any('missing_heater' in warning['message'] for warning in checked['warnings'])
