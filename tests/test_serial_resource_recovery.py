import json
import multiprocessing
import os
from pathlib import Path
import queue
import time
from unittest.mock import Mock

import pytest
import serial


def _forbid_serial_open(*_args, **_kwargs):
    raise AssertionError("No real serial port may be opened in this test")


@pytest.fixture(autouse=True)
def no_real_serial(monkeypatch, tmp_path):
    monkeypatch.setattr(serial.Serial, "open", _forbid_serial_open)
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def manager(monkeypatch, tmp_path):
    from src.utils import serial_manager

    monkeypatch.setattr(serial_manager.SerialPortLock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(serial_manager.SerialPortManager, "_instance", None)
    monkeypatch.setattr(serial_manager.SerialPortManager, "_register_cleanup", lambda _: None)
    instance = serial_manager.SerialPortManager()
    yield instance
    instance.cleanup()


class FlakyCloseSerial:
    def __init__(self, failure):
        self.is_open = True
        self.close_calls = 0
        self.failure = failure

    def close(self):
        self.close_calls += 1
        if self.close_calls == 1 and self.failure is not None:
            if self.failure == "still_open":
                return
            raise self.failure("injected close failure")
        self.is_open = False


def _reserved_protocol(monkeypatch, manager, protocol_name, failure=OSError):
    from src.protocols import aibus, modbus_rtu

    port = "REVIEW_TEST"
    assert manager.acquire_port(port)
    handle = FlakyCloseSerial(failure)
    manager.register_handle(port, handle)
    if protocol_name == "aibus":
        monkeypatch.setattr(aibus, "get_serial_manager", lambda: manager)
        protocol = aibus.AIBUSProtocol(port)
    else:
        monkeypatch.setattr(modbus_rtu, "get_serial_manager", lambda: manager)
        protocol = modbus_rtu.ModbusRTUProtocol(port)
        protocol._connected = True
    protocol._serial = handle
    protocol._port_acquired = True
    protocol._serial_registered = True
    return protocol, handle, port


@pytest.mark.parametrize("protocol_name", ["aibus", "modbus"])
@pytest.mark.parametrize("failure", [OSError, TimeoutError, "still_open"])
def test_failed_close_preserves_protocol_handle_and_lock_for_retry(
    monkeypatch, manager, protocol_name, failure
):
    protocol, handle, port = _reserved_protocol(monkeypatch, manager, protocol_name, failure)
    disconnect = protocol.close if protocol_name == "aibus" else protocol.disconnect

    assert disconnect() is False
    assert protocol._serial is handle
    assert protocol._port_acquired is True
    assert manager._port_handles[port] is handle
    assert manager.is_port_acquired(port)
    assert manager._port_lock.get_lock_info(port) is not None
    assert handle.is_open

    assert disconnect() is True
    assert handle.close_calls == 2
    assert not handle.is_open
    assert protocol._serial is None
    assert not protocol._port_acquired
    assert not manager.is_port_acquired(port)
    assert manager._port_lock.get_lock_info(port) is None


def test_manager_cleanup_keeps_failed_close_ownership(manager):
    handle = FlakyCloseSerial(OSError)
    assert manager.acquire_port("TEST")
    manager.register_handle("TEST", handle)

    manager.cleanup()
    assert manager._port_handles["TEST"] is handle
    assert manager._port_lock.get_lock_info("TEST") is not None
    manager.cleanup()
    assert not manager.is_port_acquired("TEST")
    assert not handle.is_open


@pytest.mark.parametrize("kind", ["heater", "pump", "microwave", "valve"])
def test_device_disconnect_propagates_failure_and_keeps_protocol(monkeypatch, manager, kind):
    from src.devices.base_device import DeviceConfig, DeviceStatus
    from src.devices.heater import AIHeaterDevice, HeaterConfig
    from src.devices.microwave import MicrowaveConfig, MicrowaveDevice
    from src.devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig
    from src.devices.relay_valve import RelayValveDevice

    protocol, handle, _ = _reserved_protocol(
        monkeypatch, manager, "aibus" if kind == "heater" else "modbus"
    )
    device_type, config_type = {
        "heater": (AIHeaterDevice, HeaterConfig),
        "pump": (LabSmartPumpDevice, PeristalticPumpConfig),
        "microwave": (MicrowaveDevice, MicrowaveConfig),
        "valve": (RelayValveDevice, DeviceConfig),
    }[kind]
    device = device_type(config_type(device_id="test_device"))
    device._protocol = protocol
    device.status = DeviceStatus.CONNECTED

    assert device.disconnect() is False
    assert device._protocol is protocol
    assert device.status != DeviceStatus.DISCONNECTED
    assert handle.is_open
    assert device.connect() is False
    assert device._protocol is protocol
    assert device.disconnect() is True
    assert device.status == DeviceStatus.DISCONNECTED
    assert not handle.is_open


@pytest.mark.parametrize("protocol_name", ["aibus", "modbus"])
def test_reconnect_does_not_discard_failed_release(monkeypatch, manager, protocol_name):
    protocol, handle, _ = _reserved_protocol(monkeypatch, manager, protocol_name)
    handle.is_open = False
    monkeypatch.setattr(manager, "release_port", lambda _port: False)

    if protocol_name == "aibus":
        with pytest.raises(serial.SerialException):
            protocol.open()
    else:
        assert protocol.connect() is False
    assert protocol._port_acquired is True
    assert protocol._serial is handle


@pytest.mark.parametrize("protocol_name", ["aibus", "modbus"])
@pytest.mark.parametrize("failure", [None, OSError, TimeoutError, "still_open"])
def test_registration_failure_closes_unregistered_handle_or_retains_it_for_retry(
    monkeypatch, manager, protocol_name, failure
):
    from src.protocols import aibus, modbus_rtu

    module = aibus if protocol_name == "aibus" else modbus_rtu
    protocol_type = aibus.AIBUSProtocol if protocol_name == "aibus" else modbus_rtu.ModbusRTUProtocol
    protocol = protocol_type("REGISTER_FAIL")
    handle = FlakyCloseSerial(failure)
    monkeypatch.setattr(module, "get_serial_manager", lambda: manager)
    monkeypatch.setattr(module.serial, "Serial", lambda **_kwargs: handle)

    def fail_registration(_port, _handle):
        raise RuntimeError("injected registration failure")

    monkeypatch.setattr(manager, "register_handle", fail_registration)
    if protocol_name == "aibus":
        with pytest.raises(RuntimeError, match="registration failure"):
            protocol.open()
    else:
        assert protocol.connect() is False

    assert handle.close_calls == 1
    assert "REGISTER_FAIL" not in manager._port_handles
    if failure is not None:
        assert handle.is_open
        assert protocol._serial is handle
        assert protocol._port_acquired
        assert manager.is_port_acquired("REGISTER_FAIL")
        assert manager._port_lock.get_lock_info("REGISTER_FAIL") is not None
        disconnect = protocol.close if protocol_name == "aibus" else protocol.disconnect
        assert disconnect() is True
        assert handle.close_calls == 2

    assert not handle.is_open
    assert protocol._serial is None
    assert not protocol._port_acquired
    assert not manager.is_port_acquired("REGISTER_FAIL")
    assert manager._port_lock.get_lock_info("REGISTER_FAIL") is None


@pytest.mark.parametrize("kind", ["heater", "pump", "microwave", "valve"])
@pytest.mark.parametrize("physical_open", [False, True])
@pytest.mark.parametrize("cleanup_raises", [False, True])
def test_failed_device_connect_keeps_protocol_until_explicit_cleanup_succeeds(
    monkeypatch, kind, physical_open, cleanup_raises
):
    from src.devices import heater, microwave, peristaltic_pump, relay_valve
    from src.devices.base_device import DeviceConfig, DeviceStatus

    module, device_type, config_type, protocol_name = {
        "heater": (heater, heater.AIHeaterDevice, heater.HeaterConfig, "AIBUSProtocol"),
        "pump": (peristaltic_pump, peristaltic_pump.LabSmartPumpDevice,
                 peristaltic_pump.PeristalticPumpConfig, "ModbusRTUProtocol"),
        "microwave": (microwave, microwave.MicrowaveDevice,
                      microwave.MicrowaveConfig, "ModbusRTUProtocol"),
        "valve": (relay_valve, relay_valve.RelayValveDevice, DeviceConfig, "ModbusRTUProtocol"),
    }[kind]
    protocol = Mock(is_open=physical_open, is_connected=physical_open)
    protocol.open.side_effect = OSError("injected connection failure")
    protocol.connect.return_value = False
    cleanup = protocol.close if kind == "heater" else protocol.disconnect
    cleanup.return_value = False
    if cleanup_raises:
        cleanup.side_effect = OSError("injected cleanup failure")
    factory = Mock(return_value=protocol)
    monkeypatch.setattr(module, protocol_name, factory)
    device = device_type(config_type(device_id="CONNECT_FAIL"))

    if kind in ("heater", "valve"):
        with pytest.raises((ConnectionError, OSError)):
            device.connect()
    else:
        assert device.connect() is False

    assert device._protocol is protocol
    assert device.status == DeviceStatus.ERROR
    assert device.connect() is False
    assert factory.call_count == 1
    assert protocol.open.call_count == (1 if kind == "heater" else 0)
    assert protocol.connect.call_count == (0 if kind == "heater" else 1)

    cleanup.side_effect = None
    cleanup.return_value = True
    assert device.disconnect() is True
    assert device._protocol is None
    assert device.status == DeviceStatus.DISCONNECTED


@pytest.mark.parametrize("cleanup_raises", [False, True])
def test_pump_reconnect_cannot_discard_protocol_when_cleanup_fails(monkeypatch, cleanup_raises):
    from src.devices import peristaltic_pump
    from src.devices.base_device import DeviceStatus

    protocol = Mock(is_connected=False)
    protocol.disconnect.return_value = False
    if cleanup_raises:
        protocol.disconnect.side_effect = OSError("injected cleanup failure")
    factory = Mock()
    monkeypatch.setattr(peristaltic_pump, "ModbusRTUProtocol", factory)
    pump = peristaltic_pump.LabSmartPumpDevice(
        peristaltic_pump.PeristalticPumpConfig(device_id="RECONNECT_FAIL")
    )
    pump._protocol = protocol
    pump._try_reconnect_locked()
    assert pump._protocol is protocol
    assert pump.status == DeviceStatus.ERROR
    factory.assert_not_called()
    pump._try_reconnect_locked()
    assert protocol.disconnect.call_count == 1
    factory.assert_not_called()


@pytest.mark.parametrize("connect_raises", [False, True])
def test_failed_pump_reconnect_keeps_new_protocol_for_cleanup(monkeypatch, connect_raises):
    from src.devices import peristaltic_pump
    from src.devices.base_device import DeviceStatus

    protocol = Mock(is_connected=False)
    protocol.connect.return_value = False
    if connect_raises:
        protocol.connect.side_effect = OSError("injected connect failure")
    factory = Mock(return_value=protocol)
    monkeypatch.setattr(peristaltic_pump, "ModbusRTUProtocol", factory)
    pump = peristaltic_pump.LabSmartPumpDevice(
        peristaltic_pump.PeristalticPumpConfig(device_id="NEW_RECONNECT_FAIL")
    )
    pump._try_reconnect_locked()
    assert pump._protocol is protocol
    assert pump.status == DeviceStatus.ERROR
    pump._try_reconnect_locked()
    assert factory.call_count == 1
    assert protocol.connect.call_count == 1
    assert pump.disconnect() is True
    assert pump._protocol is None


class Clock:
    def __init__(self, adjustment):
        self.elapsed = 0.0
        self.offset = 0.0
        self.adjustment = adjustment
        self.adjusted = False

    def time(self):
        return 10000 + self.elapsed + self.offset

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


def test_modbus_public_read_timeout_ignores_wall_clock_adjustments(monkeypatch):
    from src.protocols import modbus_rtu

    elapsed = []
    for adjustment in (0, -60, 60):
        clock = Clock(adjustment)

        def read(_size):
            clock.elapsed += 0.25
            if not clock.adjusted:
                clock.offset += clock.adjustment
                clock.adjusted = True
            return b""

        handle = Mock(is_open=True, in_waiting=0)
        handle.read.side_effect = read
        protocol = modbus_rtu.ModbusRTUProtocol("TEST", timeout=1)
        protocol._serial = handle
        protocol._connected = True
        monkeypatch.setattr(modbus_rtu, "time", clock)
        assert protocol.read_holding_registers(1, 10, 1) is None
        elapsed.append(clock.elapsed)
    assert elapsed == pytest.approx([elapsed[0]] * 3)
    assert 1 <= elapsed[0] < 1.5


@pytest.mark.parametrize("count", [1, 2])
def test_vid_pid_only_binding_resolves_only_unique_match(monkeypatch, count):
    from src.utils.config import DeviceConnectionConfig, SerialBindingConfig
    from src.utils import serial_binding

    connection = DeviceConnectionConfig(port="", binding=SerialBindingConfig(
        mode="fingerprint", vid=0x1234, pid=0x5678
    ))
    assert connection.validate() == []
    ports = [serial_binding.SerialPortInfo(f"COM_TEST_{i}", vid=0x1234, pid=0x5678)
             for i in range(count)]
    ports.append(serial_binding.SerialPortInfo("OTHER", vid=0x1234, pid=0x9999))
    monkeypatch.setattr(serial_binding, "enumerate_serial_ports", lambda: ports)
    resolution = serial_binding.resolve_connection(connection)
    assert resolution.binding_match_count == count
    assert resolution.binding_resolved is (count == 1)
    assert resolution.binding_error == (None if count == 1 else "multiple_matches")


def test_only_owner_can_release_lock(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortLock

    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    owner, stranger = SerialPortLock(), SerialPortLock()
    assert owner.acquire("TEST")
    try:
        original = owner.get_lock_info("TEST")
        assert stranger.release("TEST") is False
        assert owner.get_lock_info("TEST") == original
    finally:
        owner.release("TEST")


def test_release_rejects_replaced_owner_token(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortLock

    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    lock = SerialPortLock()
    assert lock.acquire("TEST")
    path = lock._get_lock_file("TEST")
    original = path.read_bytes()
    try:
        replacement = json.loads(original)
        replacement["owner_token"] = "a-different-acquisition"
        path.write_text(json.dumps(replacement), encoding="utf-8")
        assert lock.release("TEST") is False
        assert path.exists()
    finally:
        path.write_bytes(original)
        lock.release("TEST")


def test_stale_cleanup_cannot_remove_active_owner(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortLock

    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    owner, cleaner = SerialPortLock(), SerialPortLock()
    assert owner.acquire("TEST")
    try:
        assert cleaner.cleanup_all_stale_locks(include_current_process=True) == 0
        assert owner.get_lock_info("TEST") is not None
    finally:
        owner.release("TEST")


def _competing_stale_claim(lock_root, start, allow_replace, release, messages):
    serial.Serial.open = _forbid_serial_open
    from src.utils.serial_manager import SerialPortLock

    SerialPortLock.LOCK_DIR = Path(lock_root)
    lock = SerialPortLock()
    check = lock._is_process_alive

    def stale_check(pid):
        alive = check(pid)
        if not alive:
            messages.put(("stale", os.getpid(), None))
            if not allow_replace.wait(10):
                raise TimeoutError("parent did not allow stale-lock replacement")
        return alive

    lock._is_process_alive = stale_check
    try:
        if not start.wait(10):
            raise TimeoutError("parent did not start the contenders")
        acquired = lock.acquire("TEST")
        messages.put(("result", os.getpid(), acquired))
        if acquired:
            if not release.wait(10):
                raise TimeoutError("parent did not release the winning contender")
            lock.release("TEST")
    except Exception as exc:
        messages.put(("error", os.getpid(), repr(exc)))


def _abandon_process_lock(lock_root, messages):
    serial.Serial.open = _forbid_serial_open
    from src.utils.serial_manager import SerialPortLock

    SerialPortLock.LOCK_DIR = Path(lock_root)
    lock = SerialPortLock()
    acquired = lock.acquire("TEST")
    messages.put((acquired, lock.get_lock_info("TEST")))
    messages.close()
    messages.join_thread()
    # Simulate process death without calling release or destructors.
    os._exit(0)


def test_process_death_releases_os_guard_for_stale_takeover(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortLock

    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    child = context.Process(target=_abandon_process_lock, args=(str(tmp_path), messages))
    try:
        child.start()
        acquired, previous = messages.get(timeout=10)
        child.join(timeout=5)
        assert child.exitcode == 0
        assert acquired
        lock = SerialPortLock()
        assert lock.acquire("TEST")
        try:
            current = lock.get_lock_info("TEST")
            assert current["pid"] == os.getpid()
            assert current["owner_token"] != previous["owner_token"]
        finally:
            assert lock.release("TEST")
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        messages.close()


def test_stale_lock_takeover_has_one_winner_across_processes(monkeypatch, tmp_path):
    from src.utils.serial_manager import SerialPortLock

    monkeypatch.setattr(SerialPortLock, "LOCK_DIR", tmp_path)
    stale = SerialPortLock()._get_lock_file("TEST")
    stale.write_text(json.dumps({"pid": 999999999, "port": "TEST"}), encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    start, allow_replace, release = (context.Event() for _ in range(3))
    messages = context.Queue()
    children = [context.Process(target=_competing_stale_claim,
                args=(str(tmp_path), start, allow_replace, release, messages)) for _ in range(2)]
    observations = []
    try:
        for child in children:
            child.start()
        start.set()
        deadline = time.monotonic() + 15
        while len([item for item in observations if item[0] == "result"]) < 2:
            remaining = deadline - time.monotonic()
            assert remaining > 0, observations
            try:
                item = messages.get(timeout=remaining)
            except queue.Empty:
                pytest.fail(f"Contenders did not finish: {observations}")
            observations.append(item)
            assert item[0] != "error", observations
            stale_checks = sum(item[0] == "stale" for item in observations)
            rejected = any(item[0] == "result" and item[2] is False for item in observations)
            if stale_checks == 2 or (stale_checks == 1 and rejected):
                allow_replace.set()
        results = [item for item in observations if item[0] == "result"]
        assert sorted(item[2] for item in results) == [False, True], observations
        winner = next(item[1] for item in results if item[2])
        assert json.loads(stale.read_text(encoding="utf-8"))["pid"] == winner
    finally:
        allow_replace.set()
        release.set()
        for child in children:
            child.join(timeout=5)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        messages.close()
    assert all(child.exitcode == 0 for child in children)
