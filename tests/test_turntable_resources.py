"""Fake serial handles and isolated resource locks; never open real COM ports."""
from types import SimpleNamespace

import pytest
import serial

from src.devices.turntable import TurntableDevice
from src.protocols.turntable import STATUS_FRAME


@pytest.fixture(autouse=True)
def no_real_serial(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Real serial access forbidden")
    monkeypatch.setattr(serial.Serial, "open", forbidden)


@pytest.fixture
def manager(monkeypatch, tmp_path):
    from src.utils import serial_manager
    monkeypatch.setattr(serial_manager.SerialPortLock, "LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(serial_manager.SerialPortManager, "_instance", None)
    monkeypatch.setattr(serial_manager.SerialPortManager, "_register_cleanup", lambda _: None)
    instance = serial_manager.SerialPortManager()
    yield instance
    instance.cleanup()


class FakeSerial:
    def flush(self):
        pass

    def __init__(self, **kwargs):
        self.options = kwargs
        self.port = None
        self.is_open = False
        self.close_failure = None
        self.close_calls = 0
        self.response = bytes.fromhex("00 00 00 0a 00 00 3c 00")
        self.buffer = bytearray()
        self.writes = []

    def open(self):
        assert self.rts is False and self.dtr is False
        self.is_open = True

    def close(self):
        self.close_calls += 1
        if self.close_failure == "still_open":
            return
        if self.close_failure:
            raise self.close_failure("injected close failure")
        self.is_open = False

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        self.writes.append(data)
        if data == STATUS_FRAME:
            self.buffer.extend(self.response)
        return len(data)

    def read(self, count):
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result


@pytest.fixture
def device(monkeypatch, manager):
    from src.devices import turntable
    monkeypatch.setattr(turntable, "get_serial_manager", lambda: manager)
    handles = []
    def factory(**kwargs):
        handle = FakeSerial(**kwargs)
        handles.append(handle)
        return handle
    config = SimpleNamespace(connection=SimpleNamespace(baudrate=115200, timeout=.005))
    return TurntableDevice(config, serial_factory=factory), handles


def test_connect_read_disconnect_only_query_status(device, manager):
    instance, handles = device
    assert instance.connect("TEST") is True
    handle = handles[0]
    assert handle.options["port"] is None
    assert handle.options["timeout"] <= .005
    assert handle.options["write_timeout"] <= .005
    assert instance.snapshot["read_ok"] and instance.snapshot["position"] == 10
    assert instance.snapshot["read_at"]
    instance.read_status()
    assert instance.disconnect() is True
    assert handle.writes == [STATUS_FRAME, STATUS_FRAME]
    assert instance.snapshot["read_ok"] is False and instance.snapshot["position"] is None
    assert not manager.is_port_acquired("TEST")


def test_read_failure_clears_stale_position_and_motion_send_is_unconfirmed(device):
    instance, handles = device
    instance.connect("TEST")
    assert instance.send_command({"action": "move_relative", "steps": 5, "speed": 400}) is None
    assert instance.snapshot["read_ok"] is False
    assert instance.snapshot["busy"] is None
    handles[0].response = bytes(7) + b"\x02"
    with pytest.raises(OSError, match="Undefined"):
        instance.read_status()
    assert instance.snapshot["position"] is None
    assert instance.snapshot["read_error"]


@pytest.mark.parametrize("failure", [False, OSError])
def test_failed_status_retains_resources_until_release_retry(monkeypatch, device, manager, failure):
    instance, handles = device
    def fail_status():
        raise TimeoutError("injected status failure")
    def fail_release(_port):
        if failure is False:
            return False
        raise failure("injected release failure")
    with monkeypatch.context() as patch:
        patch.setattr(instance, "read_status", fail_status)
        patch.setattr(manager, "release_port", fail_release)
        with pytest.raises(TimeoutError, match="status failure"):
            instance.connect("TEST")
        assert instance.handle is handles[0] and instance.protocol is not None
        assert manager.is_port_acquired("TEST")
        with pytest.raises((RuntimeError, OSError)):
            instance.connect("NEXT_TEST")
        assert len(handles) == 1 and not manager.is_port_acquired("NEXT_TEST")
    assert instance.disconnect() is True
    assert not handles[0].is_open and not manager.is_port_acquired("TEST")


@pytest.mark.parametrize("failure", [False, OSError])
def test_closed_handle_with_unreleased_lock_cannot_be_replaced(monkeypatch, device, manager, failure):
    instance, handles = device
    instance.connect("TEST")
    def fail_release(_port):
        if failure is False:
            return False
        raise failure("injected lock release failure")
    with monkeypatch.context() as patch:
        patch.setattr(manager._port_lock, "release", fail_release)
        if failure is False:
            assert instance.disconnect() is False
        else:
            with pytest.raises(OSError):
                instance.disconnect()
        assert not handles[0].is_open
        assert instance.handle is handles[0] and manager.is_port_acquired("TEST")
        with pytest.raises((RuntimeError, OSError)):
            instance.connect("NEXT_TEST")
        assert len(handles) == 1 and not manager.is_port_acquired("NEXT_TEST")
    assert instance.disconnect() is True
    assert handles[0].close_calls == 1


@pytest.mark.parametrize("failure", [OSError, "still_open"])
def test_failed_close_retains_registered_handle_and_lock(device, manager, failure):
    instance, handles = device
    instance.connect("TEST")
    handle = handles[0]
    handle.close_failure = failure
    assert instance.disconnect() is False
    assert instance.handle is handle and instance.protocol is not None
    assert manager.is_port_acquired("TEST")
    handle.close_failure = None
    assert instance.disconnect() is True


def test_factory_failure_keeps_failed_release_reservation(monkeypatch, device, manager):
    instance, _ = device
    factory_calls = []
    def factory(**_kwargs):
        factory_calls.append(True)
        raise ValueError("injected factory failure")
    with monkeypatch.context() as patch:
        patch.setattr(instance, "serial_factory", factory)
        patch.setattr(manager, "release_port", lambda _: False)
        with pytest.raises(ValueError, match="factory failure"):
            instance.connect("TEST")
        assert instance.handle is None and manager.is_port_acquired("TEST")
        with pytest.raises(RuntimeError):
            instance.connect("NEXT_TEST")
        assert factory_calls == [True]
    assert instance.disconnect() is True


def test_failed_open_releases_registered_handle_and_reservation(monkeypatch, device, manager):
    instance, handles = device
    def fail_open(_self):
        raise OSError("injected open failure")
    monkeypatch.setattr(FakeSerial, "open", fail_open)
    with pytest.raises(OSError, match="open failure"):
        instance.connect("TEST")
    assert len(handles) == 1 and not handles[0].is_open
    assert instance.handle is None and instance.protocol is None
    assert not manager.is_port_acquired("TEST")


@pytest.mark.parametrize("raw_error,expected,excluded", [
    ("Cannot configure port, something went wrong. Original message: PermissionError(13, 'device not functioning', None, 31)",
     "Windows 无法配置 USB 串口", "占用"),
    ("could not open port 'TEST': PermissionError(13, 'Access is denied', None, 5)",
     "检查是否被其他程序占用或 USB 设备是否可用", "Windows 无法配置"),
])
def test_open_error_is_distinct_persisted_after_cleanup_and_cleared_by_disconnect(
        monkeypatch, device, manager, caplog, raw_error, expected, excluded):
    from src.utils.config import TurntableConfig
    from src.web import turntable_control

    instance, handles = device
    instance.config = TurntableConfig()
    instance.config.connection.port = "TEST"
    instance.config.connection.timeout = .005
    control = turntable_control.TurntableController(instance.config, device=instance)
    monkeypatch.setattr(turntable_control, "resolve_connection", lambda _config: SimpleNamespace(
        binding_resolved=True, resolved_port="TEST"))

    def fail_open(_self):
        raise serial.SerialException(raw_error)
    monkeypatch.setattr(FakeSerial, "open", fail_open)
    with pytest.raises(serial.SerialException, match=expected) as raised:
        control.connect()
    assert raw_error in caplog.text
    assert isinstance(raised.value.__cause__, serial.SerialException)
    assert str(raised.value.__cause__) == raw_error
    assert len(handles) == 1 and not handles[0].writes
    assert not manager.is_port_acquired("TEST")
    assert instance.handle is None and instance.protocol is None
    for state in (control.summary(), control.read(), control.read()):
        assert expected in state["connection_error"]
        assert state["read_error"] == state["connection_error"]
        assert excluded not in state["connection_error"]
        assert "管理员" not in state["connection_error"]
        assert not state["read_ok"] and not state["connected"]
    cleared = control.disconnect()
    assert cleared["connection_error"] is None and cleared["read_error"] is None
    assert control.read()["connection_error"] is None
    control.require_idle()
    assert len(handles) == 1 and not handles[0].writes


def test_successful_explicit_reconnect_clears_previous_connection_error(monkeypatch, device, manager):
    instance, handles = device
    with monkeypatch.context() as patch:
        def fail_open(_self):
            raise serial.SerialException("Cannot configure port: injected WinError31")
        patch.setattr(FakeSerial, "open", fail_open)
        with pytest.raises(serial.SerialException):
            instance.connect("TEST")
    assert instance.connection_error
    assert instance.connect("TEST")
    assert instance.connection_error is None
    assert instance.snapshot["read_ok"] and instance.snapshot["read_error"] is None
    assert len(handles) == 2
    assert handles[0].writes == [] and handles[1].writes == [STATUS_FRAME]


def test_status_timeout_reports_controller_checks_not_windows_configuration(monkeypatch, device, manager, caplog):
    instance, handles = device
    original_open = FakeSerial.open
    def no_reply(handle):
        original_open(handle)
        handle.response = b""
    monkeypatch.setattr(FakeSerial, "open", no_reply)
    with pytest.raises(TimeoutError, match="控制器状态查询超时") as raised:
        instance.connect("TEST")
    assert "eight-byte CL-01A status response" in caplog.text
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert "控制器供电" in instance.connection_error and "115200/8N1" in instance.connection_error
    assert "驱动" not in instance.connection_error and "占用" not in instance.connection_error
    assert instance.snapshot["read_error"] == instance.connection_error
    assert len(handles) == 1 and handles[0].writes == [STATUS_FRAME]
    assert not manager.is_port_acquired("TEST")


def test_unregistered_handle_close_failure_retains_reservation(monkeypatch, device, manager):
    instance, _ = device
    handle = FakeSerial()
    handle.is_open = True
    handle.close_failure = OSError
    def fail_registration(*_args):
        raise ValueError("injected registration failure")
    monkeypatch.setattr(instance, "serial_factory", lambda **_kwargs: handle)
    monkeypatch.setattr(manager, "register_handle", fail_registration)
    with pytest.raises(ValueError, match="registration failure"):
        instance.connect("TEST")
    assert instance.handle is handle and manager.is_port_acquired("TEST")
    assert "TEST" not in manager._port_handles
    with pytest.raises(RuntimeError):
        instance.connect("NEXT_TEST")
    handle.close_failure = None
    assert instance.disconnect() is True


@pytest.mark.parametrize("close_failure", [OSError, "still_open"])
@pytest.mark.parametrize("unknown_motion", [False, True])
def test_controller_reconnect_cleans_failed_connection_before_reopening(
        monkeypatch, device, manager, close_failure, unknown_motion):
    from src.utils.config import TurntableConfig
    from src.web import turntable_control

    instance, handles = device
    instance.config = TurntableConfig()
    instance.config.connection.port = "TEST"
    instance.config.connection.timeout = .005
    control = turntable_control.TurntableController(instance.config, device=instance)
    monkeypatch.setattr(turntable_control, "resolve_connection", lambda _config: SimpleNamespace(
        binding_resolved=True, resolved_port="TEST"))
    if unknown_motion:
        control.action = {"action": "run", "result": "accepted"}
        control._fail("previous motion outcome unknown")

    original_open = FakeSerial.open
    def fail_first_status(handle):
        original_open(handle)
        if len(handles) == 1:
            handle.response = b""
            handle.close_failure = close_failure
    monkeypatch.setattr(FakeSerial, "open", fail_first_status)

    with pytest.raises(TimeoutError, match="控制器状态查询超时"):
        control.connect()
    failed = handles[0]
    assert failed.is_open and manager.is_port_acquired("TEST")
    assert not instance.is_connected() and not control.summary()["connected"]
    assert instance.connection_error and failed.close_calls == 1
    with pytest.raises(RuntimeError, match="未连接"):
        instance.send_command({"action": "stop"})
    with pytest.raises(RuntimeError, match="串口清理未完成"):
        control.connect()
    assert len(handles) == 1 and instance.handle is failed
    assert failed.close_calls == 2 and failed.writes == [STATUS_FRAME]

    failed.close_failure = None
    state = control.connect()
    assert len(handles) == 2 and instance.handle is handles[1]
    assert not failed.is_open and failed.close_calls == 3
    assert manager._port_handles["TEST"] is handles[1]
    assert state["connected"] and state["read_ok"]
    assert state["connection_error"] is None and state["read_error"] is None
    assert handles[1].writes == [STATUS_FRAME]
    if unknown_motion:
        assert state["action"]["result"] == "unknown" and state["motion_blocked"]
        with pytest.raises(RuntimeError, match="转盘"):
            control.require_idle()
        with pytest.raises(RuntimeError, match="未确认"):
            control.command({"action": "run", "direction": "positive", "speed": 400})
        assert handles[1].writes == [STATUS_FRAME]
    assert instance.disconnect() is True
    assert not manager.is_port_acquired("TEST")
