"""Microwave audit regressions using fake devices, clocks and isolated history."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.experiment import executor as execution
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.editor import validate_source
from src.experiment.engine import ExperimentEngine
from src.experiment.parameter_models import MicrowaveSegmentRequest
from src.experiment.parser import parse_experiment_data
from src.web.api import devices
from test_automation_safety_fixes import fake_clock
from test_guided import spec
from test_microwave_api_ws import FakeApiDeviceManager, make_request
from test_microwave_atomic_config import make_device
from test_microwave_experiment import FakeMicrowaveExperimentManager


@pytest.mark.parametrize('method', ['configure_manual', 'configure_auto_power', 'configure_constant_rate'])
@pytest.mark.parametrize('field', ['heating_temperature', 'target_temperature', 'holding_temperature'])
def test_fractional_later_temperature_never_writes_any_register(method, field):
    device, protocol = make_device()
    assert not getattr(device, method)([dict(segment=1, heating_temperature=50),
                                        dict(segment=2, **{field: 50.9})])
    assert protocol.multi_writes == protocol.single_writes == []
    assert 'integer' in device.last_command_error


@pytest.mark.parametrize('field', ['heating_temperature', 'target_temperature', 'holding_temperature', 'holding_deviation'])
def test_rest_temperature_contract_rejects_fractions_accepts_integral_float(field):
    with pytest.raises(ValidationError):
        MicrowaveSegmentRequest(segment=1, **{field: 50.9})
    assert getattr(MicrowaveSegmentRequest(segment=1, **{field: 50.0}), field) == 50


@pytest.mark.parametrize('method', ['configure_manual', 'configure_auto_power', 'configure_constant_rate'])
def test_integral_float_configuration_still_writes_exact_integer(method):
    device, protocol = make_device()
    assert getattr(device, method)([dict(segment=1, heating_temperature=50.0,
                                        target_temperature=50.0, holding_temperature=50.0)])
    assert protocol.multi_writes
    assert all(type(value) is int for _, _, values in protocol.multi_writes for value in values)


def test_fractional_manual_deviation_is_rejected_without_partial_writes():
    device, protocol = make_device()
    assert not device.configure_manual([dict(segment=1, heating_temperature=50),
                                        dict(segment=2, holding_deviation=.5)])
    assert protocol.multi_writes == protocol.single_writes == []


@pytest.mark.parametrize('field', ['heating_temperature', 'heat_temperature', 'target_temperature',
                                  'ramp_target_temperature', 'holding_temperature', 'hold_temperature',
                                  'hold_target_temperature', 'holding_deviation', 'hold_deviation'])
def test_yaml_canonical_and_alias_temperatures_are_checked_before_execution(field):
    step = dict(id='config', type='microwave.configure_manual',
                params=dict(device_id='microwave1', segments=[dict(segment=1, **{field: 50.9})]))
    with pytest.raises(ValueError, match='整数'):
        parse_experiment_data(dict(steps=[step]), validate_devices=False)
    source = ('steps:\n  - id: config\n    type: microwave.configure_manual\n'
              '    params:\n      device_id: microwave1\n      segments:\n'
              f'        - segment: 1\n          {field}: 50.9\n')
    assert not validate_source(source)['valid']


def test_guided_rejects_fractional_microwave_but_keeps_heater_precision():
    axes = [[30.5], [30.5], [.1], [.2], [50.9], [0]]
    with pytest.raises(ValidationError, match='微波目标温度必须为整数'):
        spec(axes=axes)
    axes[4] = [50.0]
    assert spec(axes=axes).axes[0] == [30.5]


@pytest.mark.parametrize('call_name', ['configure_microwave_manual', 'configure_microwave_auto_power',
                                     'configure_microwave_constant_rate', 'start_microwave', 'stop_microwave'])
def test_rest_returns_original_command_failure(call_name):
    dm = FakeApiDeviceManager()
    dm.should_succeed = False
    detail = 'control word readback did not confirm START'
    dm.get_last_command_error = lambda did: detail
    dm.configure_microwave_auto_power = dm.configure_microwave_manual
    dm.configure_microwave_constant_rate = dm.configure_microwave_manual
    body = (devices.MicrowaveConfigureRequest(segments=[dict(segment=1)]) if 'configure' in call_name
            else devices.MicrowaveStartRequest(mode='auto_power'))
    args = ('mw1', make_request(dm)) if call_name == 'stop_microwave' else ('mw1', body, make_request(dm))
    with pytest.raises(HTTPException) as error:
        asyncio.run(getattr(devices, call_name)(*args))
    assert error.value.status_code == 400 and error.value.detail == detail


@pytest.mark.parametrize('cleanup_ok', [True, False])
def test_engine_log_preserves_start_failure_when_cleanup_replaces_driver_error(cleanup_ok):
    class Manager(FakeMicrowaveExperimentManager):
        detail = None

        def get_last_command_error(self, did):
            return self.detail

        def start_microwave(self, *args, **kwargs):
            super().start_microwave(*args)
            self.detail = 'START readback mismatch 0x4000'
            return False

        def stop_microwave(self, did, **kwargs):
            self.detail = None if cleanup_ok else 'STOP not confirmed'
            super().stop_microwave(did)
            return cleanup_ok

    async def scenario():
        dm = Manager()
        executor = execution.StepExecutor(dm)
        engine = ExperimentEngine(executor)
        engine.load_steps([ExperimentStep('start', ActionType.MICROWAVE_START,
                          params=dict(device_id='microwave1', mode='auto_power'))])
        await engine.start()
        await engine.wait_finished()
        assert engine.state.value == 'failed'
        assert executor.last_error == 'START readback mismatch 0x4000'
        error = engine._exp_logger.active_run.steps[0]['error']
        assert 'START readback mismatch 0x4000' in error
        assert ('failed to stop' in error) is not cleanup_ok
        assert dm.calls == [('start_microwave', 'microwave1'), ('stop_microwave', 'microwave1')]
    asyncio.run(scenario())


@pytest.mark.parametrize('slow_read', [False, True])
def test_temperature_timeout_reports_wait_with_last_measurement_and_no_extra_commands(monkeypatch, slow_read):
    clock = fake_clock(monkeypatch)
    dm = FakeMicrowaveExperimentManager()
    state = dict(material_temperature=53.625, fault_code=0, status_confirmed=True,
                 control_active=True, output_active=True, control_word=0x5800)
    def read(did):
        dm.calls.append(('read_microwave_data', did))
        if slow_read:
            clock.now += 2
        return state
    dm.read_microwave_data = read
    executor = execution.StepExecutor(dm)
    # A stale driver error must not override an explicit wait diagnostic.
    dm.get_last_command_error = lambda did: 'old configure failure'
    step = ExperimentStep('heat', ActionType.MICROWAVE_START,
        params=dict(device_id='microwave1', mode='auto_power'), wait=WaitCondition(
            type=WaitType.MICROWAVE_TEMPERATURE_REACHED, device_id='microwave1',
            target_temperature=50, tolerance=1, timeout=1))
    assert not asyncio.run(executor.execute(step))
    error = executor.last_error
    for text in ['微波到温等待超时', '50±1℃', '53.625℃', '上限 1 秒', '控制状态=True', '22528']:
        assert text in error
    assert 'microwave.start failed' not in error
    assert all(call[0] == 'read_microwave_data' for call in dm.calls[1:])
    assert dm.calls[0] == ('start_microwave', 'microwave1')
    assert executor.activity_snapshot['devices']['microwave1']['control_word'] == 0x5800


def test_temperature_wait_timeout_excludes_pause(monkeypatch):
    clock = fake_clock(monkeypatch)
    paused = False
    executor = execution.StepExecutor(SimpleNamespace(read_microwave_data=lambda did: dict(
        material_temperature=54, fault_code=0, control_active=True, status_confirmed=True)))
    executor.set_pause_checker(lambda: paused)
    async def sleep(seconds):
        nonlocal paused
        clock.now += seconds
        clock.sleeps += 1
        if clock.sleeps == 1:
            paused = True
            executor.notify_pause(True)
        elif paused:
            clock.now += 100
            paused = False
            executor.notify_pause(False)
    monkeypatch.setattr(execution.asyncio, 'sleep', sleep)
    assert not asyncio.run(executor._wait_condition(WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_REACHED, device_id='microwave1',
        target_temperature=50, timeout=1)))
    assert clock.now > 101
    assert '已等待 1.' in executor.last_error


def test_cooling_rejection_prevents_subsequent_drain_command():
    class Manager(FakeMicrowaveExperimentManager):
        def start_pump_channel(self, *args):
            raise AssertionError('Cooling guard must prevent pump command')

    async def scenario():
        dm = Manager()
        dm.read_payloads = [dict(material_temperature=40, fault_code=0, status_confirmed=True,
                                 control_active=True, output_active=False, stop_confirmed=False)]
        engine = ExperimentEngine(execution.StepExecutor(dm))
        engine.load_steps([
            ExperimentStep('cool', ActionType.WAIT, wait=WaitCondition(
                type=WaitType.MICROWAVE_TEMPERATURE_BELOW, device_id='microwave1', target_temperature=45)),
            ExperimentStep('drain', ActionType.PUMP_START, params=dict(device_id='pump1', channel=4)),
        ])
        await engine.start()
        await engine.wait_finished()
        assert engine.state.value == 'failed'
        assert dm.calls == [('read_microwave_data', 'microwave1')]
        assert len(engine._exp_logger.active_run.steps) == 1
        assert '禁止排液' in engine._exp_logger.active_run.steps[0]['error']
    asyncio.run(scenario())
