import json
import math
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.protocols.modbus_rtu import ModbusRTUProtocol
from src.protocols.pump_params import FlowUnit, PumpDirection, PumpRunMode
from src.utils.config import ConfigManager
from src.web.api.devices import StartPumpRequest, router as devices_router
from src.web.device_manager import DeviceManager


def _crc_frame(protocol: ModbusRTUProtocol, payload: bytes) -> bytes:
    crc = protocol.calculate_crc(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def _protocol_with_response(payload: bytes) -> ModbusRTUProtocol:
    protocol = ModbusRTUProtocol("TEST")
    protocol._send_frame = Mock(return_value=True)
    protocol._receive_frame = Mock(return_value=_crc_frame(protocol, payload))
    return protocol


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (bytes((1, 3, 2, 0, 7)), [7]),
        (bytes((2, 3, 2, 0, 7)), None),
        (bytes((1, 4, 2, 0, 7)), None),
        (bytes((1, 3, 4, 0, 7)), None),
        (bytes((1, 0x83, 0x7F)), None),
    ],
)
def test_modbus_read_rejects_mismatched_or_malformed_responses(payload, expected):
    protocol = _protocol_with_response(payload)

    assert protocol.read_holding_registers(1, 0, 1) == expected


@pytest.mark.parametrize(
    "payload",
    [
        bytes((2, 6, 0, 10, 0, 5)),
        bytes((1, 3, 0, 10, 0, 5)),
        bytes((1, 6, 0, 11, 0, 5)),
        bytes((1, 6, 0, 10, 0, 6)),
        bytes((1, 0x86, 0x7F)),
    ],
)
def test_modbus_single_write_requires_exact_echo(payload):
    protocol = _protocol_with_response(payload)

    assert protocol.write_single_register(1, 10, 5) is False


def test_modbus_single_and_multiple_write_accept_exact_echo_only():
    single = _protocol_with_response(bytes((1, 6, 0, 10, 0, 5)))
    assert single.write_single_register(1, 10, 5) is True

    multiple = _protocol_with_response(bytes((1, 16, 0, 10, 0, 2)))
    assert multiple.write_multiple_registers(1, 10, [5, 6]) is True

    wrong_count = _protocol_with_response(bytes((1, 16, 0, 10, 0, 1)))
    assert wrong_count.write_multiple_registers(1, 10, [5, 6]) is False


def test_invalid_pump_api_requests_return_422_without_calling_device_manager():
    app = FastAPI()
    app.include_router(devices_router, prefix="/api")
    app.state.device_manager = Mock()
    client = TestClient(app)
    url = "/api/pump/pump1/start"

    invalid_payloads = [
        {"direction": "clockwise"},
        {"mode": "TYPO"},
        {"channel": 5},
        {"tube_model": 14},
        {"flow_rate": 0.001},
        {"flow_rate": 151, "flow_unit": 3},
        {"mode": "TIME_SPEED"},
        {"mode": "QUANTITY_SPEED"},
        {
            "mode": "TIME_QUANTITY",
            "flow_rate": 1,
            "run_time": 1,
            "time_unit": 0,
            "dispense_volume": 1,
            "volume_unit": 2,
        },
        {"repeat_count": 2, "interval_time": 0},
        {"interval_time": 0.01},
    ]

    for payload in invalid_payloads:
        response = client.post(url, json={"flow_rate": 1.0, **payload})
        assert response.status_code == 422, (payload, response.text)

    app.state.device_manager.start_pump_channel.assert_not_called()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_pump_request_rejects_non_finite_values(value):
    with pytest.raises(ValidationError):
        StartPumpRequest(flow_rate=value)


def _fake_pump(*, max_flow_rate=5.0, tube_model=1, enabled=True):
    pump = Mock()
    pump.is_connected.return_value = True
    pump.get_channel_config.return_value = SimpleNamespace(
        channel=1,
        enabled=enabled,
        tube_model=tube_model,
        max_flow_rate=max_flow_rate,
    )
    pump.stop_channel.return_value = True
    pump.enable_channel.return_value = True
    pump.set_tube_model.return_value = True
    pump.get_tube_model.return_value = tube_model
    pump.set_direction.return_value = True
    pump.set_run_mode.return_value = True
    pump.set_flow_rate.return_value = True
    pump.set_repeat_count.return_value = True
    pump.start_channel.return_value = True
    return pump


def _manager_with_pump(pump):
    manager = DeviceManager()
    manager._pumps["pump1"] = pump
    manager._pump_locks["pump1"] = threading.Lock()
    manager._pump_abort_events["pump1"] = threading.Event()
    manager._pump_stop_generations["pump1"] = 0
    return manager


def test_pump_status_preserves_zero_valued_direction_and_flow_unit():
    pump = Mock()
    pump.is_connected.return_value = True
    pump.config.connection_params = {"port": "TEST"}
    pump.read_channel_status.return_value = SimpleNamespace(
        running=True,
        flow_rate=12.5,
        dispensed_volume=3.0,
        direction=PumpDirection.CLOCKWISE,
        flow_unit=FlowUnit.UL_MIN,
    )
    manager = _manager_with_pump(pump)

    channel = manager.read_pump_status("pump1")["channels"]["1"]

    assert channel["direction"] == "CLOCKWISE"
    assert channel["flow_unit"] == "UL_MIN"


def test_device_list_exposes_configured_pump_channel_limits():
    pump = Mock()
    pump.is_connected.return_value = False
    pump.status.name = "DISCONNECTED"
    pump.config = SimpleNamespace(
        connection_params={"port": "TEST"},
        channels=[SimpleNamespace(
            channel=1,
            enabled=True,
            tube_model=11,
            max_flow_rate=18.75,
        )],
    )
    manager = _manager_with_pump(pump)

    pump_status = manager.get_all_status()["pumps"]["pump1"]

    assert pump_status["channels"] == {
        "1": {
            "enabled": True,
            "tube_model": 11,
            "max_flow_rate": 18.75,
        }
    }


def test_pump_flow_limit_is_checked_before_any_hardware_write():
    pump = _fake_pump(max_flow_rate=5.0)
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, 6000.0, PumpDirection.CLOCKWISE,
        PumpRunMode.FLOW_MODE, flow_unit=FlowUnit.UL_MIN,
    ) is False
    pump.stop_channel.assert_not_called()
    pump.set_flow_rate.assert_not_called()
    pump.start_channel.assert_not_called()


@pytest.mark.parametrize(
    "pump",
    [_fake_pump(enabled=False), _fake_pump(max_flow_rate=math.nan)],
)
def test_disabled_or_invalidly_configured_channel_never_writes(pump):
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE, PumpRunMode.FLOW_MODE
    ) is False
    pump.stop_channel.assert_not_called()


@pytest.mark.parametrize(
    ("flow_rate", "flow_unit"),
    [(0.001, FlowUnit.ML_MIN), (151.0, FlowUnit.RPM), (10000.0, FlowUnit.UL_MIN)],
)
def test_pump_protocol_flow_range_is_checked_before_writes(flow_rate, flow_unit):
    pump = _fake_pump(max_flow_rate=100.0)
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, flow_rate, PumpDirection.CLOCKWISE,
        PumpRunMode.FLOW_MODE, flow_unit=flow_unit,
    ) is False
    pump.stop_channel.assert_not_called()


def test_pump_start_stops_first_writes_tube_zero_and_checks_readback():
    pump = _fake_pump(max_flow_rate=5.0, tube_model=1)
    pump.get_tube_model.return_value = 0
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE,
        PumpRunMode.FLOW_MODE, tube_model=0,
    ) is True
    pump.stop_channel.assert_called_once_with(1)
    pump.set_tube_model.assert_called_once_with(1, 0)
    pump.start_channel.assert_called_once_with(1)


def test_pump_start_aborts_on_stop_failure_or_tube_mismatch():
    stop_failure = _fake_pump()
    stop_failure.stop_channel.return_value = False
    manager = _manager_with_pump(stop_failure)
    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE, PumpRunMode.FLOW_MODE
    ) is False
    stop_failure.enable_channel.assert_not_called()
    stop_failure.start_channel.assert_not_called()

    mismatch = _fake_pump(tube_model=1)
    mismatch.get_tube_model.return_value = 2
    manager = _manager_with_pump(mismatch)
    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE, PumpRunMode.FLOW_MODE
    ) is False
    mismatch.start_channel.assert_not_called()


def test_concurrent_stop_cancels_in_progress_pump_start_before_start_command():
    pump = _fake_pump()
    pre_stop_entered = threading.Event()
    stop_call_count = 0

    def stop_channel(_channel):
        nonlocal stop_call_count
        stop_call_count += 1
        if stop_call_count == 1:
            pre_stop_entered.set()
        return True

    pump.stop_channel.side_effect = stop_channel
    manager = _manager_with_pump(pump)
    start_result = []

    start_thread = threading.Thread(
        target=lambda: start_result.append(manager.start_pump_channel(
            "pump1", 1, 1.0, PumpDirection.CLOCKWISE, PumpRunMode.FLOW_MODE
        ))
    )
    start_thread.start()
    assert pre_stop_entered.wait(timeout=1.0)

    assert manager.stop_pump_channel("pump1", 1) is True
    start_thread.join(timeout=1.0)

    assert start_thread.is_alive() is False
    assert start_result == [False]
    assert stop_call_count == 2
    pump.enable_channel.assert_not_called()
    pump.start_channel.assert_not_called()


def test_stop_that_finishes_during_validation_supersedes_older_start():
    pump = _fake_pump()
    validation_entered = threading.Event()
    release_validation = threading.Event()
    channel_config = pump.get_channel_config.return_value

    def delayed_channel_config(_channel):
        validation_entered.set()
        assert release_validation.wait(timeout=1.0)
        return channel_config

    pump.get_channel_config.side_effect = delayed_channel_config
    manager = _manager_with_pump(pump)
    start_result = []
    start_thread = threading.Thread(
        target=lambda: start_result.append(manager.start_pump_channel(
            "pump1", 1, 1.0, PumpDirection.CLOCKWISE, PumpRunMode.FLOW_MODE
        ))
    )
    start_thread.start()
    assert validation_entered.wait(timeout=1.0)

    assert manager.stop_pump_channel("pump1", 1) is True
    release_validation.set()
    start_thread.join(timeout=1.0)

    assert start_result == [False]
    pump.start_channel.assert_not_called()


def test_time_quantity_uses_volume_time_flow_for_limit_and_consistency():
    pump = _fake_pump(max_flow_rate=5.0)
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE,
        PumpRunMode.TIME_QUANTITY,
        run_time=1.0,
        dispense_volume=1.0,
        time_unit=0,
        volume_unit=2,
        flow_unit=FlowUnit.ML_MIN,
    ) is False
    pump.stop_channel.assert_not_called()

    consistent = _fake_pump(max_flow_rate=5.0)
    manager = _manager_with_pump(consistent)
    assert manager.start_pump_channel(
        "pump1", 1, 0.6, PumpDirection.CLOCKWISE,
        PumpRunMode.TIME_QUANTITY,
        run_time=5.0,
        dispense_volume=0.05,
        time_unit=0,
        volume_unit=1,
        flow_unit=FlowUnit.ML_MIN,
    ) is True
    consistent.set_repeat_count.assert_called_once_with(1, 1)


def test_cleanup_retains_connections_when_stop_is_not_confirmed():
    manager = DeviceManager()
    heater = Mock()
    heater.is_connected.return_value = True
    heater.stop.side_effect = RuntimeError("heater stop failed")
    heater.disconnect.return_value = True
    heater.config.device_id = "heater1"
    pump = _fake_pump()
    pump.stop_all.return_value = False
    pump.disconnect.return_value = True
    microwave = Mock()
    microwave.is_connected.return_value = True
    microwave.stop.return_value = True
    microwave.disconnect.return_value = True
    microwave.config.device_id = "microwave1"
    manager._heaters["heater1"] = heater
    manager._pumps["pump1"] = pump
    manager._pump_locks["pump1"] = threading.Lock()
    manager._pump_abort_events["pump1"] = threading.Event()
    manager._pump_stop_generations["pump1"] = 0
    manager._microwaves["microwave1"] = microwave

    assert manager.cleanup() is False
    heater.stop.assert_called_once_with()
    heater.disconnect.assert_not_called()
    pump.stop_all.assert_called_once_with()
    pump.disconnect.assert_not_called()
    microwave.stop.assert_called_once_with()
    microwave.disconnect.assert_called_once_with()


@pytest.mark.parametrize(
    ("mode", "run_time", "dispense_volume"),
    [
        (PumpRunMode.TIME_SPEED, None, None),
        (PumpRunMode.TIME_QUANTITY, 1.0, None),
        (PumpRunMode.QUANTITY_SPEED, None, None),
    ],
)
def test_pump_mode_required_values_are_checked_before_writes(
    mode, run_time, dispense_volume
):
    pump = _fake_pump()
    manager = _manager_with_pump(pump)

    assert manager.start_pump_channel(
        "pump1", 1, 1.0, PumpDirection.CLOCKWISE, mode,
        run_time=run_time, dispense_volume=dispense_volume,
    ) is False
    pump.stop_channel.assert_not_called()


def test_config_load_fails_fast_and_preserves_nested_serial_settings(tmp_path):
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps({
        "name": "test",
        "version": "1",
        "heaters": [{
            "device_id": "heater1",
            "min_temperature": 100,
            "max_temperature": 50,
            "safety_limit": 40,
            "connection": {"port": "COM1"},
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="配置验证失败"):
        ConfigManager(str(invalid_path)).load()

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps({
        "name": "test",
        "version": "1",
        "pumps": [{
            "device_id": "pump1",
            "connection": {
                "port": "COM9",
                "baudrate": 19200,
                "parity": "N",
                "stopbits": 2,
                "bytesize": 7,
                "timeout": 0.8,
            },
            "timeout": 1.5,
            "channels": [{
                "channel": 1,
                "tube_model": 13,
                "max_flow_rate": 5.0,
            }],
        }],
    }), encoding="utf-8")

    pump = ConfigManager(str(valid_path)).load().pumps[0]
    assert pump.connection.stopbits == 2
    assert pump.connection.bytesize == 7
    assert pump.stopbits == 2
    assert pump.bytesize == 7
    assert pump.channels[0].max_flow_rate == 5.0


def test_web_and_cli_propagate_pump_serial_timeout_and_flow_limit(tmp_path, monkeypatch):
    config_path = tmp_path / "system.json"
    config_path.write_text(json.dumps({
        "name": "test",
        "version": "1",
        "pumps": [{
            "device_id": "pump1",
            "connection": {
                "port": "COM9",
                "baudrate": 19200,
                "parity": "N",
                "stopbits": 2,
                "bytesize": 7,
                "timeout": 0.8,
            },
            "timeout": 1.5,
            "channels": [{
                "channel": 1,
                "tube_model": 13,
                "max_flow_rate": 5.0,
            }],
        }],
    }), encoding="utf-8")
    system_config = ConfigManager(str(config_path)).load()

    monkeypatch.setattr(ConfigManager, "load", lambda self: system_config)
    from src.web.app import create_device_manager

    web_manager = create_device_manager()
    web_config = web_manager._pumps["pump1"].config
    assert web_config.stopbits == 2
    assert web_config.bytesize == 7
    assert web_config.timeout == 1.5
    assert web_config.channels[0].max_flow_rate == 5.0

    from src.main import AutomationController

    cli_controller = AutomationController.__new__(AutomationController)
    cli_controller.config = system_config
    cli_controller._pumps = {}
    cli_controller._logger = Mock()
    cli_controller._init_pumps()
    cli_config = cli_controller._pumps["pump1"].config
    assert cli_config.connection_params["stopbits"] == 2
    assert cli_config.connection_params["bytesize"] == 7
    assert cli_config.timeout == 1.5
    assert cli_config.channels[0].max_flow_rate == 5.0
