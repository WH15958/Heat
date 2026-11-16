"""Constant-rate compilation and real executor timing with fake devices/clocks."""
from types import SimpleNamespace

import pytest

from src.experiment import guided, microwave_program, executor as execution
from src.experiment.parser import parse_experiment_data
from src.protocols.microwave_params import constant_rate_segment_start
from test_guided import spec
from test_microwave_atomic_config import make_device
from test_microwave_timed_hold import state, stable, run_step, inject_pause
from test_automation_safety_fixes import fake_clock


def request(**changes):
    return spec(**{**dict(microwave_mode='constant_rate',
        axes=[[30], [30], [.1], [.2], [70], [1], [2]]), **changes})


def program(**changes):
    return microwave_program.ProgramRequest(**{**dict(request_id='a'*32, mode='constant_rate',
        stages=[dict(temperature=70, hold_seconds=60, ramp_seconds=120)]), **changes})


@pytest.mark.parametrize('source', ['guided', 'program'])
def test_compilation_writes_all_five_rate_slots_and_separate_guard(source):
    if source == 'guided':
        r = request()
        recipe = guided.recipe(r.rows()[0], r, 'test', 0)
        assert recipe['metadata']['microwave_mode'] == 'constant_rate'
        assert recipe['metadata']['microwave_ramp_seconds'] == 120
        steps = parse_experiment_data(recipe)['steps']
        config, start = [s for s in steps if s.id in ('microwave_config', 'microwave_start')]
    else:
        config, start = microwave_program.compile_steps('microwave1', program())[:2]
    assert config.type.value == 'microwave.configure_constant_rate'
    assert start.params['mode'] == 'constant_rate'
    assert start.wait.minimum_seconds == 120
    assert start.wait.timeout == 720
    assert start.wait.seconds == 15
    device, protocol = make_device()
    assert device.configure_constant_rate(config.params['segments'])
    assert len(protocol.multi_writes) == 5
    for n, (_, address, values) in enumerate(protocol.multi_writes, 1):
        assert address == constant_rate_segment_start(n)
        # Ramp 2 minutes; guard 120 + 600 + 60 + 60 = 840 seconds.
        assert values == [0, 2, 0, 70, 0, 14, 0, 70]


def test_seventh_axis_order_repeats_capacity_and_signature():
    r = request(axes=[[30], [30], [.1], [.2], [60, 70], [1], [2, 3]], repeats=2)
    assert [(row[4], row[6]) for row in r.rows()] == [(60, 2), (60, 2), (60, 3), (60, 3),
                                                                    (70, 2), (70, 2), (70, 3), (70, 3)]
    assert len(guided.compile_plan(r)) == 8
    assert guided.priming_signature(request()) != guided.priming_signature(request(axes=r.axes))
    with pytest.raises(ValueError, match='用量|可用量'):
        request(axes=r.axes, repeats=2, source_available_a_ml=4.5)
    with pytest.raises(ValueError):
        request(repeats=201)


@pytest.mark.parametrize('value', [0, -1, .001, float('nan'), float('inf'), 6000])
def test_invalid_ramp_axis_rejected(value):
    with pytest.raises(ValueError):
        request(axes=[[30], [30], [.1], [.2], [70], [1], [value]])


def test_mode_axis_mismatch_and_total_guard_overflow_rejected():
    with pytest.raises(ValueError):
        request(microwave_mode='auto_power')
    with pytest.raises(ValueError):
        request(axes=spec().axes)
    with pytest.raises(ValueError, match='保护计时'):
        guided.compile_plan(request(axes=[[30], [30], [.1], [.2], [70], [1], [5999]]))
    with pytest.raises(ValueError, match='保护计时'):
        microwave_program.compile_steps('microwave1', program(stages=[dict(temperature=70, hold_seconds=60, ramp_seconds=359999)]))


@pytest.mark.parametrize('value', [None, 0, -1, .5, True, '120', 360000])
def test_host_requires_valid_ramp_in_each_stage(value):
    with pytest.raises(ValueError):
        program(stages=[dict(temperature=70, hold_seconds=0, ramp_seconds=value)])


def test_legacy_six_axes_and_explicit_directions_keep_meaning():
    r = spec(drain_direction='CW')
    assert r.microwave_mode == 'auto_power'
    start = next(s for s in guided.recipe(r.rows()[0], r, 'old', 0)['steps'] if s['id'] == 'microwave_start')
    assert start['params']['mode'] == 'auto_power'
    assert start['wait']['minimum_seconds'] == 0
    for direction in ['CW', 'CCW']:
        r = request(drain_direction=direction)
        recipe = guided.recipe(r.rows()[0], r, 'test', 0)
        drains = [s for s in recipe['steps'] if s['id'] in ('collect_product', 'clean_0_out')]
        drains += [s for s in guided.priming_recipe(r, 'test')['steps'] if s['id'] == 'prime_drain']
        assert len(drains) == 3
        assert all(s['params']['direction'] == direction for s in drains)
    assert request().drain_direction == 'CCW'
    assert request().clean_direction == 'CW'


@pytest.mark.parametrize('pause_at', [None, 5, 25])
def test_ramp_then_fresh_stability_then_hold_clock(monkeypatch, pause_at):
    clock = fake_clock(monkeypatch)
    observations = []
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: read()))
    def read():
        observations.append((clock.now, executor.activity_snapshot))
        return state()
    if pause_at is not None:
        inject_pause(monkeypatch, executor, clock, after=pause_at, duration=100)
    assert run_step(executor, stable(minimum_seconds=20, seconds=15, timeout=60))
    assert clock.now >= (35 if pause_at is None else 135 if pause_at == 5 else 140)
    assert all(o['stable_seconds'] == 0 for t, o in observations if t < 20)
    assert executor.activity_snapshot['ramp_remaining_seconds'] == 0
    assert executor.activity_snapshot['stable_seconds'] == 15
    from test_microwave_timed_hold import timed_hold
    start = clock.now
    assert run_step(executor, timed_hold(3))
    assert clock.now - start == pytest.approx(3)
    assert executor.activity_snapshot['ramp_seconds'] is None


@pytest.mark.parametrize('failure', ['fault', 'unknown', 'temperature', 'exited', 'read', 'slow', 'stop'])
def test_ramp_is_supervised_before_stability_starts(monkeypatch, failure):
    clock = fake_clock(monkeypatch)
    stopped = False
    def read(did):
        nonlocal stopped
        if clock.now < 2:
            return state()
        if failure == 'read':
            raise IOError('offline')
        if failure == 'slow':
            clock.now += 8
        if failure == 'stop':
            stopped = True
        return state(**{'fault': dict(fault_code=1), 'unknown': dict(status_confirmed=False),
            'temperature': dict(material_temperature=float('nan')), 'exited': dict(control_active=False)}.get(failure, {}))
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=read))
    executor.set_stop_checker(lambda: stopped)
    assert not run_step(executor, stable(minimum_seconds=20, seconds=15, timeout=60))
    assert clock.now < 20


def test_cannot_reach_target_after_ramp_times_out(monkeypatch):
    clock = fake_clock(monkeypatch)
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: state(10)))
    assert not run_step(executor, stable(minimum_seconds=20, seconds=15, timeout=40))
    assert 40 <= clock.now < 41


@pytest.mark.parametrize('minimum', [-1, .5, True, float('nan'), 99])
def test_yaml_minimum_wait_validation(minimum):
    recipe = guided.recipe(request().rows()[0], request(), 'test', 0)
    wait = next(s['wait'] for s in recipe['steps'] if s['id'] == 'microwave_start')
    wait.update(minimum_seconds=minimum, timeout=40)
    with pytest.raises(ValueError):
        parse_experiment_data(recipe)
