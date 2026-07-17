import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from src.utils.config import ConfigManager, DeviceConnectionConfig, PumpDeviceConfig, SerialBindingConfig
from src.utils.serial_binding import SerialBindingResolution, SerialPortInfo, resolve_connection
from src.web.device_manager import DeviceManager


def _make_connection(**kwargs) -> DeviceConnectionConfig:
    binding = kwargs.pop("binding", SerialBindingConfig())
    return DeviceConnectionConfig(binding=binding, **kwargs)


def test_old_config_defaults_to_fixed_port():
    conn = DeviceConnectionConfig.from_dict({"port": "COM7", "baudrate": 9600})
    assert conn.binding.mode == "fixed_port"
    assert conn.port == "COM7"


def test_config_manager_parses_binding_block():
    mgr = ConfigManager()
    conn = mgr._parse_connection_config({
        "port": "COM7",
        "baudrate": 9600,
        "binding": {
            "mode": "fingerprint",
            "serial_number": "A6001234",
            "fallback_to_port": True,
        },
    })
    assert conn.binding.mode == "fingerprint"
    assert conn.binding.serial_number == "A6001234"
    assert conn.binding.fallback_to_port is True


def test_config_manager_ignores_legacy_connection_fields():
    mgr = ConfigManager()
    conn = mgr._parse_connection_config({
        "port": "COM10",
        "baudrate": 19200,
        "parity": "E",
        "stopbits": 1,
        "bytesize": 8,
    })
    assert conn.port == "COM10"
    assert conn.baudrate == 19200
    assert conn.parity == "E"


def test_connection_validate_includes_binding_rules():
    conn = _make_connection(
        port="",
        binding=SerialBindingConfig(mode="fingerprint", serial_number=""),
    )
    errors = conn.validate()
    assert any("fingerprint" in err or "serial_number" in err for err in errors)


def test_pump_validate_uses_connection_only():
    pump = PumpDeviceConfig(
        device_id="pump1",
        name="Pump 1",
        connection=DeviceConnectionConfig(port="COM10", baudrate=19200, parity="E"),
    )
    errors = pump.validate()
    assert isinstance(errors, list)


def test_resolve_serial_number_unique_match():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", serial_number="A6001234"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(port="COM9", serial_number="A6001234", description="USB Serial"),
        SerialPortInfo(port="COM10", serial_number="B0000001", description="Other"),
    ]):
        result = resolve_connection(conn)
    assert result.binding_resolved is True
    assert result.resolved_port == "COM9"
    assert result.binding_error is None


def test_resolve_fixed_port_unique_match():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fixed_port"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(port="COM7", description="USB-SERIAL CH340"),
        SerialPortInfo(port="COM10", description="Other"),
    ]):
        result = resolve_connection(conn)
    assert result.binding_resolved is True
    assert result.resolved_port == "COM7"
    assert result.binding_error is None


def test_resolve_fixed_port_missing_is_unresolved():
    conn = _make_connection(
        port="COM9",
        binding=SerialBindingConfig(mode="fixed_port"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(port="COM7", description="USB-SERIAL CH340"),
        SerialPortInfo(port="COM8", description="USB-SERIAL CH340"),
    ]):
        result = resolve_connection(conn)
    assert result.binding_resolved is False
    assert result.resolved_port == ""
    assert result.binding_error == "no_match"
    assert result.binding_match_count == 0


def test_resolve_vid_pid_location_unique_match():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", vid=0x1A86, pid=0x7523, location="1-3.2"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(port="COM11", vid=0x1A86, pid=0x7523, location="1-3.2", description="USB-SERIAL CH340"),
    ]):
        result = resolve_connection(conn)
    assert result.binding_resolved is True
    assert result.resolved_port == "COM11"


def test_current_microwave_config_resolves_new_usb_rs485_adapter():
    config = ConfigManager().load()
    microwave = config.get_microwave_config("microwave1")
    assert microwave is not None
    assert microwave.connection.port == "COM17"
    assert microwave.connection.binding.serial_number == "DU0ENS4UA"

    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(
            port="COM17",
            serial_number="DU0ENS4UA",
            vid=0x0403,
            pid=0x6015,
            description="USB Serial Port",
        ),
    ]):
        result = resolve_connection(microwave.connection)

    assert result.binding_resolved is True
    assert result.resolved_port == "COM17"
    assert result.binding_error is None


def test_resolve_no_match():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", serial_number="NOPE"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[]):
        result = resolve_connection(conn)
    assert result.binding_resolved is False
    assert result.binding_error == "no_match"
    assert result.binding_match_count == 0


def test_resolve_multiple_matches():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", description_regex="USB-SERIAL"),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[
        SerialPortInfo(port="COM4", description="USB-SERIAL CH340"),
        SerialPortInfo(port="COM5", description="USB-SERIAL CH340"),
    ]):
        result = resolve_connection(conn)
    assert result.binding_resolved is False
    assert result.binding_error == "multiple_matches"
    assert result.binding_match_count == 2


def test_resolve_fallback_to_port():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", serial_number="NOPE", fallback_to_port=True),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[]):
        result = resolve_connection(conn)
    assert result.binding_resolved is True
    assert result.binding_error == "fallback_to_port"
    assert result.resolved_port == "COM7"


def test_resolve_without_fallback_stays_unresolved():
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", serial_number="NOPE", fallback_to_port=False),
    )
    with patch("src.utils.serial_binding.enumerate_serial_ports", return_value=[]):
        result = resolve_connection(conn)
    assert result.binding_resolved is False
    assert result.resolved_port == ""


def test_device_manager_exposes_binding_fields_and_blocks_unresolved_connect():
    dm = DeviceManager()
    dm.add_heater(
        device_id="heater1",
        port="",
        baudrate=9600,
        address=1,
        decimal_places=1,
        binding_info={
            "resolved_port": "",
            "connection_binding_mode": "fingerprint",
            "binding_label": "SN=A6001234",
            "binding_resolved": False,
            "binding_match_count": 0,
            "binding_error": "no_match",
            "binding_candidates": [],
        },
    )
    status = dm.get_all_status()["heaters"]["heater1"]
    assert status["binding_label"] == "SN=A6001234"
    assert status["binding_resolved"] is False
    assert status["binding_error"] == "no_match"
    try:
        dm.connect_heater("heater1")
    except RuntimeError as exc:
        assert "binding unresolved" in str(exc)
    else:
        raise AssertionError("Expected unresolved binding to block connect")


def test_device_manager_binding_status_handles_none():
    dm = DeviceManager()
    status = dm.get_heater_binding("missing")
    assert status["binding_resolved"] is False
    assert status["binding_error"] == "missing_fixed_port"
    assert status["binding_candidates"] == []


def test_device_manager_refreshes_unresolved_binding_port():
    dm = DeviceManager()
    conn = _make_connection(
        port="COM7",
        binding=SerialBindingConfig(mode="fingerprint", vid=0x1A86, pid=0x7523, location="1-3.3"),
    )
    dm.add_heater(
        device_id="heater1",
        port="",
        baudrate=9600,
        address=1,
        decimal_places=1,
        binding_info={
            "_connection_config": conn,
            "resolved_port": "",
            "connection_binding_mode": "fingerprint",
            "binding_label": "VID:PID=1A86:7523 @ 1-3.3",
            "binding_resolved": False,
            "binding_match_count": 0,
            "binding_error": "no_match",
            "binding_candidates": [],
        },
    )
    with patch("src.web.device_manager.resolve_connection", return_value=SerialBindingResolution(
        resolved_port="COM7",
        connection_binding_mode="fingerprint",
        binding_label="VID:PID=1A86:7523 @ 1-3.3",
        binding_resolved=True,
        binding_match_count=1,
        binding_error=None,
        binding_candidates=["COM7 VID:PID=1A86:7523 LOC=1-3.3"],
    )):
        status = dm.refresh_bindings()["heaters"]["heater1"]

    assert status["binding_resolved"] is True
    assert status["connection_port"] == "COM7"
    assert dm.get_heater("heater1").config.connection_params["port"] == "COM7"


def run_all():
    tests = [
        test_old_config_defaults_to_fixed_port,
        test_config_manager_parses_binding_block,
        test_config_manager_ignores_legacy_connection_fields,
        test_connection_validate_includes_binding_rules,
        test_pump_validate_uses_connection_only,
        test_resolve_serial_number_unique_match,
        test_resolve_fixed_port_unique_match,
        test_resolve_fixed_port_missing_is_unresolved,
        test_resolve_vid_pid_location_unique_match,
        test_current_microwave_config_resolves_new_usb_rs485_adapter,
        test_resolve_no_match,
        test_resolve_multiple_matches,
        test_resolve_fallback_to_port,
        test_resolve_without_fallback_stays_unresolved,
        test_device_manager_exposes_binding_fields_and_blocks_unresolved_connect,
        test_device_manager_binding_status_handles_none,
        test_device_manager_refreshes_unresolved_binding_port,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {test.__name__}: {exc}")
            raise
    print(f"serial binding tests: {passed} passed, {failed} failed")


if __name__ == "__main__":
    run_all()
