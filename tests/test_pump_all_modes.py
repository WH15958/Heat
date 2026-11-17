"""Mode-specific inputs and final readbacks using a stateful fake, never serial I/O."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.executor import StepExecutor
from src.protocols.pump_params import PumpRunMode
from src.web.api.devices import router
from test_pump_time_speed import rig, start, writes


MODES = list(PumpRunMode)


def configure(dm, mode, **changes):
    return start(dm, **{**dict(mode=mode, flow_rate=10, run_time=36, time_unit=0,
                              dispense_volume=6, volume_unit=1), **changes})


@pytest.mark.parametrize('mode', MODES)
def test_all_modes_keep_ten_after_mode_and_parameter_coupling(rig, mode):
    dm, pump, wire = rig
    assert configure(dm, mode)
    assert wire.get_float(4110) == 10
    assert writes(wire, 4006) == [(int(mode),)]
    assert writes(wire, 4001) == [(0,), (1,)]
    assert bool(writes(wire, 4104)) == (mode in (1, 3))
    assert bool(writes(wire, 4107)) == (mode in (1, 2))
    assert bool(writes(wire, 4100)) == (mode != 0)
    assert bool(writes(wire, 4110)) == (mode != 1)
    if mode == 1:
        assert not writes(wire, 4112)
    addresses = [c[1] for c in wire.calls if c[0] == 'write']
    if mode == 1:
        assert addresses.index(4104) < addresses.index(4107)
    elif mode == 3:
        assert addresses.index(4104) < addresses.index(4110)


@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('post_start', [False, True])
@pytest.mark.parametrize('fault', ['flow', 'unit', 'mode', 'unreadable'])
def test_drift_is_rejected_in_every_mode(rig, mode, post_start, fault):
    dm, pump, wire = rig
    final_write = 4100 if mode == 1 else 4110

    def corrupt(address):
        if post_start:
            if address != 4001 or wire.registers[4001] != 1:
                return
        elif address != final_write:
            return
        if fault == 'flow':
            wire.put_float(4110, 3)
        elif fault == 'unit':
            wire.registers[4112] = 3 if mode == 1 else 0
        elif fault == 'mode':
            wire.registers[4006] = (int(mode) + 1) % 4
        else:
            wire.fail_read = 4110

    wire.after_write = corrupt
    assert not configure(dm, mode)
    assert writes(wire, 4001) == ([(0,), (1,), (0,)] if post_start else [(0,)])
    assert '停止已确认' in pump.last_command_error if post_start else '未启动' in pump.last_command_error


@pytest.mark.parametrize('mode', MODES)
def test_stop_during_setup_never_starts_any_mode(rig, mode):
    dm, pump, wire = rig
    wire.after_write = lambda address: dm._request_pump_abort('pump1') if address == 4006 else None
    assert not configure(dm, mode)
    assert not wire.started


@pytest.mark.parametrize('mode', MODES)
def test_failed_post_start_stop_is_reported_without_restart(rig, mode):
    dm, pump, wire = rig
    wire.after_write = lambda address: wire.put_float(4110, 3) if wire.started else None
    wire.fail_stop = True
    assert not configure(dm, mode)
    assert '停止未确认' in pump.last_command_error
    assert 'readback=3' in pump.last_command_error
    assert writes(wire, 4001).count((1,)) == 1


@pytest.mark.parametrize('mode', [1, 2, 3])
def test_countdown_does_not_invalidate_success(rig, mode):
    dm, pump, wire = rig

    def countdown(address):
        if address == 4001 and wire.started:
            wire.put_float(4104, 5.9)
            wire.put_float(4107, 35.5)
            wire.registers[4100] = 0

    wire.after_write = countdown
    assert configure(dm, mode)


@pytest.mark.parametrize('volume,volume_unit', [(6000, 0), (6, 1), (.06, 2)])
@pytest.mark.parametrize('time_unit', [0, 1, 2])
@pytest.mark.parametrize('read_unit', [0, 1, 2])
def test_time_quantity_verifies_derived_flow_in_device_units(rig, volume, volume_unit, time_unit, read_unit):
    dm, pump, wire = rig
    wire.registers[4112] = read_unit
    ml = volume * (.001, 1, 1000)[volume_unit]
    # Keep the requested time in the device's legal range, at 1 mL/min.
    run_time = ml / (1 / 60, 1, 60)[time_unit]
    assert configure(dm, PumpRunMode.TIME_QUANTITY, dispense_volume=volume,
                     volume_unit=volume_unit, run_time=run_time, time_unit=time_unit, flow_rate=1)
    assert wire.get_float(4110) == pytest.approx(1 / (.001, 1, 1000)[read_unit])
    assert not writes(wire, 4110) and not writes(wire, 4112)


@pytest.mark.parametrize('offset', [4104, 4106, 4107, 4109, 4100, 4101, 4103])
def test_time_quantity_final_inputs_must_not_be_recomputed_or_lost(rig, offset):
    dm, pump, wire = rig

    def corrupt(address):
        if address == 4101:
            if offset in (4104, 4107, 4101):
                wire.put_float(offset, 2)
            else:
                wire.registers[offset] = 2

    wire.after_write = corrupt
    assert not configure(dm, PumpRunMode.TIME_QUANTITY, interval_time=1)
    assert not wire.started


@pytest.mark.parametrize('mode', [PumpRunMode.FLOW_MODE, PumpRunMode.TIME_SPEED, PumpRunMode.QUANTITY_SPEED])
@pytest.mark.parametrize('unit,flow', [(0, 1000), (1, 1), (2, .01), (3, 15)])
def test_speed_modes_preserve_requested_units(rig, mode, unit, flow):
    dm, pump, wire = rig
    assert configure(dm, mode, flow_unit=unit, flow_rate=flow)
    assert wire.registers[4112] == unit
    assert wire.get_float(4110) == pytest.approx(flow)


@pytest.mark.parametrize('mode', MODES)
def test_setup_write_failure_never_retries_start(rig, mode):
    dm, pump, wire = rig
    wire.fail_write = 4104 if mode in (1, 3) else 4110
    assert not configure(dm, mode)
    assert not wire.started
    assert len(writes(wire, wire.fail_write)) == 1


@pytest.mark.parametrize('previous', MODES)
@pytest.mark.parametrize('mode', MODES)
def test_each_mode_transition_replaces_previous_inputs(rig, previous, mode):
    dm, pump, wire = rig
    assert configure(dm, previous, flow_rate=3, dispense_volume=3, run_time=60)
    assert configure(dm, mode)
    assert wire.get_float(4110) == pytest.approx(10)
    assert wire.registers[4006] == int(mode)


@pytest.mark.parametrize('mode', MODES)
def test_api_and_yaml_cannot_report_success_after_flow_drift(rig, mode):
    dm, pump, wire = rig
    def drift(address):
        if address == 4001 and wire.registers[4001] == 1:
            wire.put_float(4110, 3)
    wire.after_write = drift
    params = dict(channel=4, flow_rate=10, mode=mode.name, run_time=36,
                  time_unit=0, dispense_volume=6, volume_unit=1, flow_unit=1)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.state.device_manager = dm
    with TestClient(app) as client:
        response = client.post('/api/pump/pump1/start', json=params)
    assert response.status_code == 200
    assert response.json()['success'] is False
    assert 'readback=3' in response.json()['error']
    executor = StepExecutor(dm)
    step = ExperimentStep('dose', ActionType.PUMP_START, dict(device_id='pump1', **params))
    assert not asyncio.run(executor.execute(step))
    assert ('pump1', 4) not in executor._pump_start_confirmed
    assert 'readback=3' in executor.last_error
