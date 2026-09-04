import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock

from src.devices.base_device import DeviceStatus
from src.devices.heater import AIHeaterDevice, HeaterConfig
from src.protocols.parameters import ParameterCode, RunStatus
from src.experiment.executor import StepExecutor
from src.experiment.actions import ActionType, ExperimentStep, WaitCondition


def _heater():
    device = AIHeaterDevice(HeaterConfig(
        device_id="heater1",
        connection_params={"port": "FAKE"},
        retry_count=1,
    ))
    device._protocol = Mock()
    device.status = DeviceStatus.CONNECTED
    device.READBACK_ATTEMPTS = 1
    return device


def _heater_data(*, status, sv=60.0, mv=0, alarms=None):
    return SimpleNamespace(
        run_status=status,
        sv=sv,
        mv=mv,
        alarms=list(alarms or []),
    )


def test_heater_readback_registers_match_vendor_aibus_table():
    assert ParameterCode.SV_READ == 75
    assert ParameterCode.MV_ALARM == 76
    assert ParameterCode.OUTPUT_STATUS == 77
    assert ParameterCode.ROOM_TEMP == 78


def test_heater_set_temperature_requires_matching_sv(monkeypatch):
    heater = _heater()
    monkeypatch.setattr(
        heater, "read_data", lambda: _heater_data(status=RunStatus.STOP, sv=59.0)
    )

    assert heater.set_temperature(60.0) is False


def test_heater_start_rejects_unknown_status(monkeypatch):
    heater = _heater()
    monkeypatch.setattr(
        heater, "read_data", lambda: _heater_data(status=RunStatus.UNKNOWN)
    )

    assert heater.start() is False


def test_heater_emergency_stop_requires_zero_output(monkeypatch):
    heater = _heater()
    monkeypatch.setattr(
        heater, "read_data", lambda: _heater_data(status=RunStatus.STOP, mv=10)
    )

    assert heater.emergency_stop() is False


def test_pause_aware_sleep_uses_elapsed_monotonic_time(monkeypatch):
    executor = StepExecutor(Mock())
    original_sleep = asyncio.sleep

    async def delayed_sleep(seconds):
        await original_sleep(seconds + 0.03)

    monkeypatch.setattr("src.experiment.executor.asyncio.sleep", delayed_sleep)
    started = time.monotonic()
    assert asyncio.run(executor._pause_aware_sleep(0.1)) == 0.0
    elapsed = time.monotonic() - started

    assert 0.1 <= elapsed < 0.16


def test_pause_aware_sleep_zero_and_stop():
    executor = StepExecutor(Mock())
    assert asyncio.run(executor._pause_aware_sleep(0)) == 0.0
    executor.set_stop_checker(lambda: True)
    assert asyncio.run(executor._pause_aware_sleep(1)) is None


def test_executor_exposes_driver_readback_failure_detail():
    dm = Mock()
    dm.start_pump_channel.return_value = False
    dm.get_last_command_error.return_value = (
        "Pump pump1 CH4 flow_rate readback mismatch: expected=2.0 readback=None"
    )
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="start_inlet",
        type=ActionType.PUMP_START,
        params={
            "device_id": "pump1",
            "channel": 4,
            "flow_rate": 2.0,
            "direction": "CW",
            "mode": "FLOW_MODE",
        },
        wait=WaitCondition(),
    )

    assert asyncio.run(executor.execute(step)) is False
    assert "CH4 flow_rate readback mismatch" in executor.last_error
