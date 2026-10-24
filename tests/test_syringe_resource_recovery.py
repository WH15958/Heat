"""Serial resource failures use fake handles and isolated lock directories."""
import pytest
import serial


@pytest.fixture(autouse=True)
def no_real_serial(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No real serial port may be opened")

    monkeypatch.setattr(serial.Serial, "open", forbidden)
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "data"))


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
    def __init__(self, opened=False, close_failure=None):
        self.port = None
        self.is_open = opened
        self.close_failure = close_failure
        self.close_calls = 0

    def open(self):
        self.is_open = True

    def close(self):
        self.close_calls += 1
        if self.close_failure == "still_open":
            return
        if self.close_failure:
            raise self.close_failure("injected close failure")
        self.is_open = False


@pytest.fixture
def device(monkeypatch, manager):
    from src.devices import syringe_pump
    from src.utils.config import SyringePumpConfig

    monkeypatch.setattr(syringe_pump, "get_serial_manager", lambda: manager)
    handles = []

    def factory(**_kwargs):
        handle = FakeSerial()
        handles.append(handle)
        return handle

    instance = syringe_pump.SyringePumpDevice(SyringePumpConfig(), serial_factory=factory)
    return instance, handles


def fail_status():
    raise TimeoutError("injected status failure")


@pytest.mark.parametrize("failure", [False, OSError])
def test_connect_failure_retains_resources_until_release_can_be_retried(
    monkeypatch, manager, device, failure
):
    instance, handles = device
    release = manager.release_port

    def fail_release(_port):
        if failure is False:
            return False
        raise failure("injected release failure")

    with monkeypatch.context() as patch:
        patch.setattr(instance, "read_status", fail_status)
        patch.setattr(manager, "release_port", fail_release)
        with pytest.raises(TimeoutError, match="status failure"):
            instance.connect("TEST")
        handle, protocol = instance.handle, instance.protocol
        assert handle is handles[0] and protocol is not None
        assert manager._port_handles["TEST"] is handle
        assert manager.is_port_acquired("TEST")
        assert manager._port_lock.get_lock_info("TEST") is not None

        with pytest.raises((RuntimeError, OSError)):
            instance.connect("NEXT_TEST")
        assert instance.handle is handle and instance.protocol is protocol
        assert len(handles) == 1
        assert not manager.is_port_acquired("NEXT_TEST")

    assert manager.release_port == release
    assert instance.disconnect() is True
    assert not handle.is_open
    assert instance.handle is None and instance.protocol is None
    assert not manager.is_port_acquired("TEST")


@pytest.mark.parametrize("failure", [False, OSError])
def test_closed_handle_with_unreleased_reservation_cannot_be_replaced(
    monkeypatch, manager, device, failure
):
    instance, handles = device

    def fail_lock_release(_port):
        if failure is False:
            return False
        raise failure("injected lock release failure")

    with monkeypatch.context() as patch:
        patch.setattr(instance, "read_status", fail_status)
        patch.setattr(manager._port_lock, "release", fail_lock_release)
        with pytest.raises(TimeoutError, match="status failure"):
            instance.connect("TEST")
        handle, protocol = handles[0], instance.protocol
        assert not handle.is_open
        assert instance.handle is handle and protocol is not None
        assert manager.is_port_acquired("TEST")

        with pytest.raises((RuntimeError, OSError)):
            instance.connect("NEXT_TEST")
        assert instance.handle is handle and instance.protocol is protocol
        assert len(handles) == 1
        assert not manager.is_port_acquired("NEXT_TEST")

    assert instance.disconnect() is True
    assert handle.close_calls == 1
    assert instance.handle is None and instance.protocol is None
    assert not manager.is_port_acquired("TEST")


def test_unfinished_protocol_cannot_be_reported_as_connected(monkeypatch, manager, device):
    from src.devices import syringe_pump

    instance, handles = device

    def fail_protocol(*_args):
        raise ValueError("injected protocol failure")

    with monkeypatch.context() as patch:
        patch.setattr(syringe_pump, "SyringeProtocol", fail_protocol)
        patch.setattr(manager, "release_port", lambda _port: False)
        with pytest.raises(ValueError, match="protocol failure"):
            instance.connect("TEST")
        assert instance.handle is handles[0] and handles[0].is_open
        assert instance.protocol is None
        assert not instance.is_connected()
        with pytest.raises(RuntimeError):
            instance.connect("TEST")
        assert len(handles) == 1

    assert instance.disconnect() is True
    assert not handles[0].is_open


@pytest.mark.parametrize("failure", [False, OSError])
def test_factory_failure_keeps_reservation_available_for_cleanup_retry(
    monkeypatch, manager, device, failure
):
    instance, _handles = device
    factory_calls = []

    def fail_factory(**_kwargs):
        factory_calls.append(True)
        raise ValueError("injected factory failure")

    def fail_release(_port):
        if failure is False:
            return False
        raise failure("injected release failure")

    with monkeypatch.context() as patch:
        patch.setattr(instance, "serial_factory", fail_factory)
        patch.setattr(manager, "release_port", fail_release)
        with pytest.raises(ValueError, match="factory failure"):
            instance.connect("TEST")
        assert instance.handle is None
        assert manager.is_port_acquired("TEST")
        with pytest.raises((RuntimeError, OSError)):
            instance.connect("NEXT_TEST")
        assert factory_calls == [True]
        assert not manager.is_port_acquired("NEXT_TEST")

    assert instance.disconnect() is True
    assert not manager.is_port_acquired("TEST")


@pytest.mark.parametrize("failure", [OSError, TimeoutError, "still_open"])
def test_unregistered_open_handle_is_retained_until_it_can_close(
    monkeypatch, manager, device, failure
):
    instance, _handles = device
    handle = FakeSerial(opened=True, close_failure=failure)

    def fail_registration(_port, _handle):
        raise ValueError("injected registration failure")

    monkeypatch.setattr(instance, "serial_factory", lambda **_kwargs: handle)
    monkeypatch.setattr(manager, "register_handle", fail_registration)
    with pytest.raises(ValueError, match="registration failure"):
        instance.connect("TEST")
    assert handle.is_open and instance.handle is handle
    assert manager.is_port_acquired("TEST")
    assert "TEST" not in manager._port_handles
    with pytest.raises(RuntimeError):
        instance.connect("NEXT_TEST")
    assert instance.handle is handle
    assert not manager.is_port_acquired("NEXT_TEST")

    handle.close_failure = None
    assert instance.disconnect() is True
    assert not handle.is_open
    assert instance.handle is None
    assert not manager.is_port_acquired("TEST")
