import math
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from src.devices.heater import AIHeaterDevice
from src.protocols.parameters import ParameterCode
from src.utils.config import (
    ConfigManager,
    DeviceConnectionConfig,
    HeaterDeviceConfig,
    LoggingConfig,
    MicrowaveDeviceConfig,
    MonitorConfig,
    PumpChannelConfigYaml,
    PumpDeviceConfig,
    ReportConfig,
    SerialBindingConfig,
)
from src.web.api.devices import SetTemperatureRequest


def _binding_config():
    return SerialBindingConfig(mode="fingerprint", serial_number="test-serial")


INTEGER_CONFIG_FIELDS = [
    pytest.param(_binding_config, "vid", 0x1234, id="binding-vid"),
    pytest.param(_binding_config, "pid", 0x5678, id="binding-pid"),
    pytest.param(DeviceConnectionConfig, "baudrate", 9600, id="connection-baudrate"),
    pytest.param(DeviceConnectionConfig, "address", 1, id="connection-address"),
    pytest.param(DeviceConnectionConfig, "stopbits", 1, id="connection-stopbits"),
    pytest.param(DeviceConnectionConfig, "bytesize", 8, id="connection-bytesize"),
    pytest.param(HeaterDeviceConfig, "decimal_places", 1, id="heater-decimals"),
    pytest.param(HeaterDeviceConfig, "retry_count", 3, id="heater-retries"),
    pytest.param(PumpChannelConfigYaml, "channel", 1, id="pump-channel"),
    pytest.param(PumpChannelConfigYaml, "pump_head", 5, id="pump-head"),
    pytest.param(PumpChannelConfigYaml, "tube_model", 11, id="pump-tube"),
    pytest.param(PumpChannelConfigYaml, "suck_back_angle", 0, id="pump-angle"),
    pytest.param(PumpDeviceConfig, "slave_address", 1, id="pump-address"),
    pytest.param(PumpDeviceConfig, "stopbits", 1, id="pump-stopbits"),
    pytest.param(PumpDeviceConfig, "bytesize", 8, id="pump-bytesize"),
    pytest.param(PumpDeviceConfig, "retry_count", 3, id="pump-retries"),
    pytest.param(MicrowaveDeviceConfig, "slave_address", 1, id="microwave-address"),
    pytest.param(MicrowaveDeviceConfig, "max_power_percent", 100, id="microwave-power"),
    pytest.param(MicrowaveDeviceConfig, "retry_count", 3, id="microwave-retries"),
    pytest.param(MonitorConfig, "data_retention_hours", 24, id="monitor-retention"),
    pytest.param(LoggingConfig, "max_file_size_mb", 10, id="logging-size"),
    pytest.param(LoggingConfig, "backup_count", 5, id="logging-backups"),
]


BOOLEAN_CONFIG_FIELDS = [
    pytest.param(_binding_config, "fallback_to_port", id="binding-fallback"),
    pytest.param(HeaterDeviceConfig, "enabled", id="heater-enabled"),
    pytest.param(PumpChannelConfigYaml, "enabled", id="pump-channel-enabled"),
    pytest.param(PumpDeviceConfig, "enabled", id="pump-enabled"),
    pytest.param(MicrowaveDeviceConfig, "enabled", id="microwave-enabled"),
    pytest.param(
        MicrowaveDeviceConfig,
        "allow_experiment_control",
        id="microwave-experiment-control",
    ),
    pytest.param(
        MicrowaveDeviceConfig,
        "allow_real_hardware_writes",
        id="microwave-hardware-writes",
    ),
    pytest.param(
        MicrowaveDeviceConfig,
        "enable_control_writes",
        id="microwave-control-writes",
    ),
    pytest.param(MonitorConfig, "enabled", id="monitor-enabled"),
    pytest.param(MonitorConfig, "enable_csv_logging", id="monitor-csv"),
    pytest.param(MonitorConfig, "enable_database", id="monitor-database"),
    pytest.param(ReportConfig, "include_charts", id="report-charts"),
    pytest.param(ReportConfig, "include_statistics", id="report-statistics"),
    pytest.param(ReportConfig, "auto_generate", id="report-auto-generate"),
    pytest.param(LoggingConfig, "console_output", id="logging-console"),
    pytest.param(LoggingConfig, "file_output", id="logging-file"),
]


@pytest.mark.parametrize("temperature", [math.nan, math.inf, -math.inf])
def test_heater_api_rejects_non_finite_temperature(temperature):
    with pytest.raises(ValidationError):
        SetTemperatureRequest.model_validate({"temperature": temperature})


def _fake_heater():
    return SimpleNamespace(
        _heater_config=SimpleNamespace(
            max_temperature=400.0,
            safety_limit=450.0,
            min_temperature=0.0,
            temperature_unit="C",
        ),
        _lock=threading.Lock(),
        _protocol=Mock(),
        _decimal_places=1,
        _logger=Mock(),
        execute_with_retry=lambda operation, _name: operation(),
    )


@pytest.mark.parametrize("temperature", [math.nan, math.inf, -math.inf])
def test_heater_driver_rejects_non_finite_temperature_before_protocol_write(
    temperature,
):
    heater = _fake_heater()

    with pytest.raises(ValueError, match="finite number"):
        AIHeaterDevice.set_temperature(heater, temperature)

    heater._protocol.write_parameter.assert_not_called()


def test_heater_driver_keeps_finite_temperature_compatible():
    heater = _fake_heater()

    assert AIHeaterDevice.set_temperature(heater, 25.0) is True
    heater._protocol.write_parameter.assert_called_once_with(
        ParameterCode.SV, 25.0, decimal_places=1
    )


@pytest.mark.parametrize("factory,field_name,valid_value", INTEGER_CONFIG_FIELDS)
@pytest.mark.parametrize("invalid_kind", ["bool", "float", "nan"])
def test_integer_config_fields_reject_non_integer_types(
    factory, field_name, valid_value, invalid_kind
):
    invalid_value = {
        "bool": True,
        "float": float(valid_value),
        "nan": math.nan,
    }[invalid_kind]
    config = factory()
    setattr(config, field_name, invalid_value)

    assert len(config.validate()) > 0


@pytest.mark.parametrize("factory,field_name,valid_value", INTEGER_CONFIG_FIELDS)
def test_integer_config_fields_keep_valid_integers_compatible(
    factory, field_name, valid_value
):
    config = factory()
    setattr(config, field_name, valid_value)

    assert config.validate() == []


@pytest.mark.parametrize("factory,field_name", BOOLEAN_CONFIG_FIELDS)
@pytest.mark.parametrize("invalid_value", ["false", 0, 1.0, None])
def test_boolean_config_fields_reject_truthy_or_falsey_non_booleans(
    factory, field_name, invalid_value
):
    config = factory()
    setattr(config, field_name, invalid_value)

    assert len(config.validate()) > 0


@pytest.mark.parametrize("factory,field_name", BOOLEAN_CONFIG_FIELDS)
@pytest.mark.parametrize("valid_value", [True, False])
def test_boolean_config_fields_keep_real_booleans_compatible(
    factory, field_name, valid_value
):
    config = factory()
    setattr(config, field_name, valid_value)

    assert config.validate() == []


@pytest.mark.parametrize(
    ("field_name", "yaml_value"),
    [
        ("retry_count", "true"),
        ("retry_count", "1.0"),
        ("retry_count", ".nan"),
        ("enabled", "'false'"),
    ],
)
def test_config_manager_rejects_invalid_yaml_scalar_types(
    tmp_path, field_name, yaml_value
):
    config_path = tmp_path / "system.yaml"
    config_path.write_text(
        (
            "name: strict scalar types\n"
            "version: '1'\n"
            "heaters:\n"
            "  - device_id: heater1\n"
            f"    {field_name}: {yaml_value}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        ConfigManager(str(config_path)).load()
