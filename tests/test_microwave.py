"""
Microwave backend driver tests using a fake Modbus protocol.
"""

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    class _RaisesContext:
        def __init__(self, expected_exception, match=None):
            self.expected_exception = expected_exception
            self.match = match

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            if exc_type is None:
                raise AssertionError(f"Did not raise {self.expected_exception.__name__}")
            if not issubclass(exc_type, self.expected_exception):
                return False
            if self.match is not None and self.match not in str(exc):
                raise AssertionError(f"Exception message does not contain {self.match!r}: {exc}")
            return True

    class _PytestFallback:
        @staticmethod
        def raises(expected_exception, match=None):
            return _RaisesContext(expected_exception, match)

    pytest = _PytestFallback()

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from devices.microwave import MicrowaveConfig, MicrowaveDevice, MicrowaveSegment
from protocols.microwave_params import (
    CONTROL_AUTO_POWER,
    CONTROL_CONSTANT_RATE,
    CONTROL_MANUAL_POWER,
    CONTROL_MICROWAVE_START,
    CONTROL_STOP,
    CONTROL_WORD,
    STATUS_CURRENT,
    STATUS_CURRENT_MODE_CODE,
    STATUS_CURRENT_SEGMENT,
    STATUS_FAULT_CODE,
    STATUS_FLOAT_TEMPERATURE,
    STATUS_MATERIAL_TEMPERATURE_RAW,
    STATUS_POWER_PERCENT,
    STATUS_RUNTIME_HOURS,
    STATUS_RUNTIME_MINUTES,
    STATUS_RUNTIME_SECONDS_PART,
    MicrowaveMode,
    holding_address,
    manual_hold_time_start,
)


class FakeModbusProtocol:
    def __init__(self):
        self.connected = False
        self.registers = {}
        self.float_registers = {}
        self.single_writes = []
        self.multi_writes = []
        self.fail_write_addresses = set()
        self.fail_float_addresses = set()

    @property
    def is_connected(self):
        return self.connected

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def write_single_register(self, slave_address, address, value):
        if address in self.fail_write_addresses:
            return False
        self.single_writes.append((slave_address, address, value))
        self.registers[address] = value
        return True

    def write_multiple_registers(self, slave_address, start_address, values):
        addresses = range(start_address, start_address + len(values))
        if any(address in self.fail_write_addresses for address in addresses):
            return False
        self.multi_writes.append((slave_address, start_address, list(values)))
        for offset, value in enumerate(values):
            self.registers[start_address + offset] = value
        return True

    def read_holding_registers(self, slave_address, start_address, count):
        return [self.registers.get(start_address + offset, 0) for offset in range(count)]

    def read_float_register(self, slave_address, start_address):
        if start_address in self.fail_float_addresses:
            return None
        return self.float_registers.get(start_address)


def make_device(enable_control_writes=True):
    protocol = FakeModbusProtocol()
    config = MicrowaveConfig(
        device_id="mw1",
        connection_params={"port": "FAKE"},
        enable_control_writes=enable_control_writes,
    )
    device = MicrowaveDevice(config, protocol=protocol)
    assert device.connect() is True
    return device, protocol


def test_holding_address_conversion():
    assert holding_address(40001) == 0
    assert holding_address(40151) == 150


def test_start_and_stop_control_words():
    device, protocol = make_device()

    cases = [
        (MicrowaveMode.MANUAL_POWER, CONTROL_MANUAL_POWER | CONTROL_MICROWAVE_START),
        ("auto_power", CONTROL_AUTO_POWER | CONTROL_MICROWAVE_START),
        (MicrowaveMode.CONSTANT_RATE, CONTROL_CONSTANT_RATE | CONTROL_MICROWAVE_START),
    ]
    for mode, expected in cases:
        assert device.start(mode) is True
        assert protocol.single_writes[-1] == (1, CONTROL_WORD, expected)

    assert device.stop() is True
    assert protocol.single_writes[-1] == (1, CONTROL_WORD, CONTROL_STOP)


def test_control_writes_are_disabled_by_default():
    device, protocol = make_device(enable_control_writes=False)

    assert device.start(MicrowaveMode.MANUAL_POWER) is False
    assert protocol.single_writes == []


def test_manual_configuration_validation():
    device, _ = make_device()

    assert device.configure_manual([
        MicrowaveSegment(segment=1, heating_temperature=301)
    ]) is False
    assert device.configure_manual([
        MicrowaveSegment(segment=1, seconds=-1)
    ]) is False
    assert device.configure_manual([
        MicrowaveSegment(segment=6)
    ]) is False


def test_configure_manual_returns_false_on_failed_write():
    device, protocol = make_device()
    protocol.fail_write_addresses.add(manual_hold_time_start(1))

    ok = device.configure_manual([
        MicrowaveSegment(
            segment=1,
            heating_temperature=80,
            heating_power_percent=50,
            holding_temperature=60,
            holding_power_percent=40,
            holding_deviation=2,
            minutes=5,
        )
    ])

    assert ok is False


def test_read_data_uses_float_temperature_and_runtime_seconds():
    device, protocol = make_device()
    protocol.registers.update({
        STATUS_CURRENT: 7,
        STATUS_MATERIAL_TEMPERATURE_RAW: 82,
        STATUS_POWER_PERCENT: 65,
        STATUS_RUNTIME_HOURS: 1,
        STATUS_RUNTIME_MINUTES: 2,
        STATUS_RUNTIME_SECONDS_PART: 3,
        STATUS_FAULT_CODE: 4,
        STATUS_CURRENT_SEGMENT: 5,
        STATUS_CURRENT_MODE_CODE: 6,
    })
    protocol.float_registers[STATUS_FLOAT_TEMPERATURE] = 82.5

    data = device.read_data()
    status = data.microwave_status

    assert status.material_temperature == 82.5
    assert status.material_temperature_source == "float"
    assert status.runtime_seconds == 3723
    assert data.data["fault_code"] == 4
    assert data.data["current_mode_code"] == 6


def test_read_data_falls_back_to_raw_temperature():
    device, protocol = make_device()
    protocol.registers[STATUS_MATERIAL_TEMPERATURE_RAW] = 79
    protocol.fail_float_addresses.add(STATUS_FLOAT_TEMPERATURE)

    data = device.read_data()

    assert data.microwave_status.material_temperature == 79.0
    assert data.microwave_status.material_temperature_source == "raw"


def test_read_data_not_connected_raises_ioerror():
    config = MicrowaveConfig(device_id="mw1", connection_params={"port": "FAKE"})
    device = MicrowaveDevice(config, protocol=FakeModbusProtocol())

    with pytest.raises(IOError, match="Device not connected"):
        device.read_data()


def test_config_manager_loads_disabled_microwave_config():
    from utils.config import ConfigManager

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "system_config.yaml"
        config_path.write_text(
            """name: test
version: "1.0.0"
microwaves:
  - device_id: microwave1
    name: test microwave
    connection:
      port: FAKE
      baudrate: 9600
      address: 1
      parity: N
      timeout: 2.0
    slave_address: 1
    max_temperature: 300.0
    max_power_percent: 100
    poll_interval: 1.0
    retry_count: 3
    retry_delay: 0.5
    enabled: false
    allow_experiment_control: false
    enable_control_writes: false
""",
            encoding="utf-8",
        )

        config = ConfigManager(str(config_path)).load()

    assert len(config.microwaves) == 1
    microwave = config.microwaves[0]
    assert microwave.enabled is False
    assert microwave.allow_experiment_control is False
    assert microwave.enable_control_writes is False
    assert microwave.max_temperature == 300.0


def test_device_manager_registers_microwave_status_bucket():
    from web.device_manager import DeviceManager

    manager = DeviceManager()
    manager.add_microwave("mw1", port="FAKE")

    assert "mw1" in manager.get_all_microwaves()
    assert manager.get_all_status()["microwaves"]["mw1"]["connected"] is False


def run_all():
    tests = [
        test_holding_address_conversion,
        test_start_and_stop_control_words,
        test_control_writes_are_disabled_by_default,
        test_manual_configuration_validation,
        test_configure_manual_returns_false_on_failed_write,
        test_read_data_uses_float_temperature_and_runtime_seconds,
        test_read_data_falls_back_to_raw_temperature,
        test_read_data_not_connected_raises_ioerror,
        test_config_manager_loads_disabled_microwave_config,
        test_device_manager_registers_microwave_status_bucket,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
    passed = len(tests) - failed
    print(f"microwave tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
