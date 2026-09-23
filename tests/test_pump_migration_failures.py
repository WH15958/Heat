from pathlib import Path, PureWindowsPath
from unittest.mock import Mock

import pytest

from src.devices.base_device import DeviceStatus
from src.devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from src.utils.serial_manager import SerialPortLock
from src.web.device_manager import DeviceManager


def make_pump():
    return LabSmartPumpDevice(PeristalticPumpConfig(
        device_id="pump_test", connection_params={"port": "TEST"},
        channels=[PumpChannelConfig(channel=1, suck_back_angle=1)],
    ))


@pytest.mark.parametrize("failed", [
    "stop_channel", "enable_channel", "set_tube_model", "set_direction",
    "set_run_mode", "set_suck_back_angle",
])
@pytest.mark.parametrize("raises", [False, True])
def test_initialization_stops_at_first_failed_command(monkeypatch, failed, raises):
    pump = make_pump()
    commands = ["stop_channel", "enable_channel", "set_tube_model",
                "set_direction", "set_run_mode", "set_suck_back_angle"]
    monkeypatch.setattr("src.devices.peristaltic_pump.time.sleep", lambda _: None)
    for name in commands:
        setattr(pump, name, Mock(return_value=True))
    command = getattr(pump, failed)
    command.return_value = False
    if raises:
        command.side_effect = TimeoutError("no reply")
    assert pump._initialize_channels() is False
    for name in commands[commands.index(failed) + 1:]:
        getattr(pump, name).assert_not_called()


def test_failed_connect_retains_stop_path_and_blocks_start(monkeypatch):
    pump = make_pump()
    protocol = Mock(is_connected=True)
    monkeypatch.setattr("src.devices.peristaltic_pump.ModbusRTUProtocol", lambda **_: protocol)
    pump._initialize_channels = Mock(return_value=False)
    assert pump.connect() is False
    assert pump.status == DeviceStatus.ERROR
    assert pump.is_connected() is True
    protocol.disconnect.assert_not_called()
    assert pump.connect() is False
    assert pump._initialize_channels.call_count == 1
    manager = DeviceManager()
    manager._pumps["pump_test"] = pump
    assert manager.start_pump_channel("pump_test", 1, 1.0, 0, 0) is False
    assert manager.get_all_status()["pumps"]["pump_test"]["connection_error"]
    pump.stop_all = Mock(return_value=False)
    assert manager.disconnect_pump("pump_test") is False
    assert pump.is_connected() is True
    pump.stop_all.return_value = True
    assert manager.disconnect_pump("pump_test") is True
    assert pump.connection_error is None
    protocol.disconnect.assert_called_once()


def test_successful_initialization_returns_true(monkeypatch):
    pump = make_pump()
    monkeypatch.setattr("src.devices.peristaltic_pump.time.sleep", lambda _: None)
    for name in ["stop_channel", "enable_channel", "set_tube_model",
                 "set_direction", "set_run_mode", "set_suck_back_angle"]:
        setattr(pump, name, Mock(return_value=True))
    assert pump._initialize_channels() is True


@pytest.mark.parametrize("persistent", [False, True])
def test_lock_permission_failure_has_bounded_retry(monkeypatch, tmp_path, persistent):
    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr("src.utils.serial_manager.time.sleep", lambda _: None)
    lock = SerialPortLock()
    assert lock.acquire("TEST")
    original = Path.unlink
    calls = []

    def unlink(path, *args, **kwargs):
        calls.append(path)
        if persistent or len(calls) == 1:
            raise PermissionError("temporary sharing denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert lock.release("TEST") is (not persistent)
    assert len(calls) == (3 if persistent else 2)
    assert ("TEST" in lock._locks) is persistent


def test_failed_release_keeps_port_reserved(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortManager
    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(SerialPortManager, "_instance", None)
    manager = SerialPortManager()
    assert manager.acquire_port("TEST")
    release = manager._port_lock.release
    monkeypatch.setattr(manager._port_lock, "release", lambda _: False)
    assert manager.release_port("TEST") is False
    assert manager.is_port_acquired("TEST") is True
    assert manager.acquire_port("TEST") is False
    monkeypatch.setattr(manager._port_lock, "release", release)
    assert manager.release_port("TEST") is True


@pytest.mark.parametrize("port", [f"COM{i}" for i in range(1, 10)])
def test_windows_port_lock_is_a_real_file_not_device_alias(monkeypatch, tmp_path, port):
    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    lock = SerialPortLock()
    path = lock._get_lock_file(port)
    assert not PureWindowsPath(path.name).is_reserved()
    assert lock.acquire(port) is True
    assert path in list(tmp_path.iterdir())
    assert lock.get_lock_info(port)["port"] == port
    assert lock.release(port) is True
    assert not path.exists()
