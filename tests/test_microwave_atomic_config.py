"""Regression tests for microwave configuration prevalidation."""

import threading

import pytest

from src.devices.microwave import MicrowaveConfig, MicrowaveDevice


class RecordingProtocol:
    def __init__(self):
        self.multi_writes = []
        self.single_writes = []
        self.calls = []

    @property
    def is_connected(self):
        return True

    def write_multiple_registers(self, slave_address, start_address, values):
        self.multi_writes.append((slave_address, start_address, list(values)))
        self.calls.append(("config", start_address))
        return True

    def write_single_register(self, slave_address, address, value):
        self.single_writes.append((slave_address, address, value))
        self.calls.append(("start", address))
        return True


class PauseAfterFirstConfigWriteDevice(MicrowaveDevice):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.first_config_write_complete = threading.Event()
        self.resume_config = threading.Event()
        self._config_write_count = 0

    def _write_registers(self, start_address, values):
        result = super()._write_registers(start_address, values)
        self._config_write_count += 1
        if self._config_write_count == 1:
            self.first_config_write_complete.set()
            if not self.resume_config.wait(timeout=5):
                raise TimeoutError("Timed out waiting to resume microwave configuration")
        return result


def make_device(device_class=MicrowaveDevice):
    protocol = RecordingProtocol()
    config = MicrowaveConfig(
        device_id="mw1",
        connection_params={"port": "FAKE"},
    )
    return device_class(config, protocol=protocol), protocol


@pytest.mark.parametrize(
    "method_name",
    [
        "configure_manual",
        "configure_auto_power",
        "configure_constant_rate",
    ],
)
@pytest.mark.parametrize(
    "segments",
    [
        pytest.param([], id="empty"),
        pytest.param([{"segment": 1}] * 6, id="more-than-five"),
    ],
)
def test_invalid_segment_count_is_rejected_before_any_write(method_name, segments):
    device, protocol = make_device()

    assert getattr(device, method_name)(segments) is False
    assert protocol.multi_writes == []


@pytest.mark.parametrize(
    ("method_name", "segments"),
    [
        (
            "configure_manual",
            [
                {"segment": 1, "heating_temperature": 50},
                {"segment": 2, "heating_power_percent": "invalid"},
            ],
        ),
        (
            "configure_auto_power",
            [
                {"segment": 1, "target_temperature": 50},
                {"segment": 2, "target_temperature": 301},
            ],
        ),
        (
            "configure_constant_rate",
            [
                {"segment": 1, "target_temperature": 50},
                {"segment": 2, "target_temperature": 60, "ramp_seconds": 65536},
            ],
        ),
    ],
)
def test_invalid_later_segment_is_rejected_before_any_write(method_name, segments):
    device, protocol = make_device()

    assert getattr(device, method_name)(segments) is False
    assert protocol.multi_writes == []


@pytest.mark.parametrize(
    ("method_name", "segments"),
    [
        ("configure_manual", [{"segment": 1, "heating_temperature": 50}]),
        (
            "configure_auto_power",
            [
                {"segment": 1, "target_temperature": 50},
                {"segment": 2, "target_temperature": 60},
            ],
        ),
        (
            "configure_constant_rate",
            [
                {"segment": 1, "target_temperature": 50},
                {"segment": 2, "target_temperature": 60},
            ],
        ),
    ],
)
def test_start_cannot_interleave_with_configuration_writes(method_name, segments):
    device, protocol = make_device(PauseAfterFirstConfigWriteDevice)
    original_write_register = device._write_register
    lock_probe_complete = threading.Event()
    lock_available_to_start = []
    results = {}
    errors = []

    def observed_write_register(address, value):
        acquired = device._lock.acquire(blocking=False)
        lock_available_to_start.append(acquired)
        if acquired:
            device._lock.release()
        lock_probe_complete.set()
        return original_write_register(address, value)

    def run_config():
        try:
            results["config"] = getattr(device, method_name)(segments)
        except Exception as exc:
            errors.append(exc)

    def run_start():
        try:
            results["start"] = device.start("manual_power")
        except Exception as exc:
            errors.append(exc)

    device._write_register = observed_write_register
    config_thread = threading.Thread(target=run_config, daemon=True)
    start_thread = threading.Thread(target=run_start, daemon=True)

    config_thread.start()
    first_write_completed = device.first_config_write_complete.wait(timeout=2)
    start_thread.start()
    probe_completed = lock_probe_complete.wait(timeout=2)
    device.resume_config.set()
    config_thread.join(timeout=2)
    start_thread.join(timeout=2)

    assert first_write_completed is True
    assert probe_completed is True
    assert lock_available_to_start == [False]
    assert config_thread.is_alive() is False
    assert start_thread.is_alive() is False
    assert errors == []
    assert results == {"config": True, "start": True}
    assert [call_type for call_type, _ in protocol.calls] == [
        "config",
        "config",
        "start",
    ]
