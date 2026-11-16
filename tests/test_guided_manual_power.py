"""Guided native manual-power compilation; fake protocol only."""
import pytest

from src.experiment import guided
from src.experiment.parser import parse_experiment_data
from src.protocols.microwave_params import manual_segment_start, manual_hold_time_start
from test_guided import spec
from test_microwave_atomic_config import make_device


def request(**changes):
    return spec(**{**dict(microwave_mode='manual_power',
        axes=[[30], [30], [.1], [.2], [70], [1], [70]]), **changes})


@pytest.mark.parametrize('power', [0, 1, 70, 100])
def test_manual_power_compiles_five_slots_and_preserves_temperature_gate(power):
    r = request(axes=[[30], [30], [.1], [.2], [70], [1], [power]])
    data = guided.compile_plan(r)[0]
    steps = {s.id: s for s in parse_experiment_data(data)['steps']}
    config, start = steps['microwave_config'], steps['microwave_start']
    assert config.type.value == 'microwave.configure_manual'
    assert start.params['mode'] == 'manual_power'
    assert start.wait.minimum_seconds == 0
    assert start.wait.seconds == 15
    assert start.wait.timeout == 600
    assert steps['hold'].wait.seconds == 60
    assert steps['hold'].wait.hold_mode == 'timed'
    assert steps['microwave_stop'].type.value == 'microwave.stop'
    assert data['metadata']['microwave_power_percent'] == power
    assert data['metadata']['microwave_ramp_seconds'] is None
    device, protocol = make_device()
    assert device.configure_manual(config.params['segments'])
    assert len(protocol.multi_writes) == 10
    for i in range(5):
        _, address, values = protocol.multi_writes[2*i]
        assert address == manual_segment_start(i+1)
        assert values == [70, power, 70, power, 0]
        _, address, values = protocol.multi_writes[2*i+1]
        assert address == manual_hold_time_start(i+1)
        assert values == [0, 12, 0]  # 600 + 60 + 60, no ramp delay.
    assert not protocol.single_writes


@pytest.mark.parametrize('power', [-1, 101, .5, True, '70', None, float('inf'), float('nan')])
def test_invalid_power_rejected(power):
    with pytest.raises(ValueError):
        request(axes=[[30], [30], [.1], [.2], [70], [1], [power]])


def test_mode_specific_axis_count_and_empty_power_rejected():
    for axes in [spec().axes, spec().axes + [[]], spec().axes + [[70], [80]]]:
        with pytest.raises(ValueError):
            request(axes=axes)
    with pytest.raises(ValueError):
        request(microwave_mode='auto_power')


def test_power_combinations_repeats_capacity_and_priming_signature():
    r = request(axes=[[30], [30], [.1], [.2], [60, 70], [1], [40, 70]], repeats=2)
    assert [(row[4], row[6]) for row in r.rows()] == [
        (60, 40), (60, 40), (60, 70), (60, 70), (70, 40), (70, 40), (70, 70), (70, 70)]
    assert len(guided.compile_plan(r)) == 8
    assert guided.priming_signature(r) != guided.priming_signature(request())
    assert guided.priming_signature(r) != guided.priming_signature(request(axes=r.axes, repeats=2, microwave_mode='constant_rate'))
    with pytest.raises(ValueError, match='用量|可用量'):
        request(axes=r.axes, repeats=2, source_available_a_ml=4.5)
    with pytest.raises(ValueError, match='瓶'):
        guided.compile_plan(request(repeats=guided.describe_collection(1)['capacity'] + 1))


def test_new_request_drains_all_use_ccw_and_explicit_old_direction_is_preserved():
    for direction in ['CCW', 'CW']:
        r = request(**({} if direction == 'CCW' else dict(drain_direction='CW')))
        data = guided.compile_plan(r)[0]
        steps = {s['id']: s for s in data['steps']}
        prime = next(s for s in guided.priming_recipe(r, 'test')['steps'] if s['id'] == 'prime_drain')
        assert prime['params']['direction'] == direction
        assert steps['collect_product']['params']['direction'] == direction
        assert steps['clean_0_out']['params']['direction'] == direction
        assert steps['clean_0_in']['params']['direction'] == 'CW'
