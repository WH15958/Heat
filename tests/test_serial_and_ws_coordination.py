import asyncio
import threading

import pytest
import serial


def test_realtime_reads_independent_families_without_serial_delay():
    """A slow pump must not prevent the syringe reader from starting."""
    from types import SimpleNamespace
    from src.web.api.ws import build_realtime_payload

    both_started = threading.Barrier(2, timeout=2)
    calls = []

    def read_pump(did):
        both_started.wait()
        calls.append(did)
        return {"read_ok": True}

    def read_syringe():
        both_started.wait()
        calls.append("syringe1")
        return {"read_ok": True, "busy": False}

    def read_turntable():
        # Its own timestamp must not age while the slower families finish.
        assert sorted(calls) == ["pump1", "syringe1"]
        return {"read_ok": True}

    dm = SimpleNamespace(
        get_all_heaters=lambda: {}, get_all_microwaves=lambda: {},
        get_all_pumps=lambda: {"pump1": SimpleNamespace(is_connected=lambda: True)},
        read_pump_status=read_pump, valves={},
        turntables={"turntable1": SimpleNamespace(read=read_turntable)},
        syringe_pumps={"syringe1": SimpleNamespace(read=read_syringe)},
    )
    result = asyncio.run(build_realtime_payload(dm))
    assert sorted(calls) == ["pump1", "syringe1"]
    assert result["pumps"]["pump1"]["read_ok"]
    assert result["syringe_pumps"]["syringe1"]["read_ok"]
    assert result["turntables"]["turntable1"]["read_ok"]


def test_realtime_syringe_failure_stays_unknown_while_other_family_succeeds():
    from types import SimpleNamespace
    from src.web.api.ws import build_realtime_payload

    def failed():
        raise TimeoutError("simulated communication timeout")

    controller = SimpleNamespace(
        read=failed,
        config=SimpleNamespace(name="A", capacity_ml=10,
            connection=SimpleNamespace(port="FAKE", binding=SimpleNamespace(serial_number=""))),
        device=SimpleNamespace(is_connected=lambda: True,
            unknown=lambda error: {"read_ok": False, "error": error}),
    )
    dm = SimpleNamespace(
        get_all_heaters=lambda: {}, get_all_microwaves=lambda: {},
        get_all_pumps=lambda: {"pump1": SimpleNamespace(is_connected=lambda: True)},
        read_pump_status=lambda did: {"read_ok": True}, valves={}, turntables={},
        syringe_pumps={"syringe1": controller},
    )
    result = asyncio.run(build_realtime_payload(dm))
    assert result["pumps"]["pump1"]["read_ok"]
    assert result["syringe_pumps"]["syringe1"]["read_ok"] is False
    assert "timeout" in result["syringe_pumps"]["syringe1"]["error"]


def test_device_read_coordinator_reuses_timed_out_read():
    from src.web.api.ws import DeviceReadCoordinator

    started = threading.Event()
    release = threading.Event()
    call_count = 0

    def blocking_read():
        nonlocal call_count
        call_count += 1
        started.set()
        assert release.wait(timeout=2.0)
        return {"value": 42}

    async def scenario():
        coordinator = DeviceReadCoordinator()

        with pytest.raises(asyncio.TimeoutError):
            await coordinator.read(("pump", "pump1"), blocking_read, timeout=0.01)
        assert started.wait(timeout=1.0)

        with pytest.raises(asyncio.TimeoutError):
            await coordinator.read(("pump", "pump1"), blocking_read, timeout=0.01)

        assert call_count == 1
        release.set()
        result = await coordinator.read(
            ("pump", "pump1"), blocking_read, timeout=1.0
        )

        assert result == {"value": 42}
        assert call_count == 1

    asyncio.run(scenario())


def _isolated_serial_manager(monkeypatch, tmp_path):
    from src.utils import serial_manager as serial_mod

    monkeypatch.setattr(serial_mod.SerialPortLock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(serial_mod.SerialPortManager, "_instance", None)
    return serial_mod.SerialPortManager()


class FakeSerial:
    instances = []

    def __init__(self, **_kwargs):
        self.is_open = True
        self.__class__.instances.append(self)

    def close(self):
        self.is_open = False


def test_protocols_share_serial_port_manager(monkeypatch, tmp_path):
    from src.protocols import aibus as aibus_mod
    from src.protocols import modbus_rtu as modbus_mod

    manager = _isolated_serial_manager(monkeypatch, tmp_path)
    FakeSerial.instances = []
    monkeypatch.setattr(aibus_mod, "get_serial_manager", lambda: manager)
    monkeypatch.setattr(modbus_mod, "get_serial_manager", lambda: manager)
    monkeypatch.setattr(aibus_mod.serial, "Serial", FakeSerial)

    aibus = aibus_mod.AIBUSProtocol("COM_TEST")
    modbus = modbus_mod.ModbusRTUProtocol("COM_TEST")

    try:
        assert aibus.open() is True
        assert manager.is_port_acquired("COM_TEST") is True
        assert manager._port_handles["COM_TEST"] is aibus._serial
        assert manager._watchdog is None

        assert modbus.connect() is False
        assert len(FakeSerial.instances) == 1
        assert aibus.is_open is True

        assert aibus.close() is True
        assert manager.is_port_acquired("COM_TEST") is False

        assert modbus.connect() is True
        assert manager._port_handles["COM_TEST"] is modbus._serial
        assert len(FakeSerial.instances) == 2

        modbus.disconnect()
        assert manager.is_port_acquired("COM_TEST") is False
        assert FakeSerial.instances[-1].is_open is False
    finally:
        aibus.close()
        modbus.disconnect()
        manager.cleanup()


@pytest.mark.parametrize("protocol_name", ["aibus", "modbus"])
def test_protocol_releases_reserved_port_when_serial_open_fails(
    monkeypatch,
    tmp_path,
    protocol_name,
):
    from src.protocols import aibus as aibus_mod
    from src.protocols import modbus_rtu as modbus_mod

    manager = _isolated_serial_manager(monkeypatch, tmp_path)
    monkeypatch.setattr(aibus_mod, "get_serial_manager", lambda: manager)
    monkeypatch.setattr(modbus_mod, "get_serial_manager", lambda: manager)

    class FailingSerial:
        def __init__(self, **_kwargs):
            raise serial.SerialException("simulated open failure")

    monkeypatch.setattr(aibus_mod.serial, "Serial", FailingSerial)

    try:
        if protocol_name == "aibus":
            protocol = aibus_mod.AIBUSProtocol("COM_FAIL")
            with pytest.raises(serial.SerialException):
                protocol.open()
        else:
            protocol = modbus_mod.ModbusRTUProtocol("COM_FAIL")
            assert protocol.connect() is False

        assert manager.is_port_acquired("COM_FAIL") is False
        assert manager._port_handles == {}
        assert list(tmp_path.glob("*.lock")) == []
        # The unlocked OS guard keeps a stable file identity between owners.
        assert [path.suffix for path in tmp_path.iterdir()] == [".guard"]
    finally:
        manager.cleanup()


def test_pump_connection_state_requires_open_protocol():
    from src.devices.base_device import DeviceStatus
    from src.devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig

    pump = LabSmartPumpDevice(
        PeristalticPumpConfig(
            device_id="pump_connection_state",
            connection_params={"port": "COM_TEST"},
        )
    )
    pump.status = DeviceStatus.CONNECTED
    pump._protocol = type("ClosedProtocol", (), {"is_connected": False})()

    assert pump.is_connected() is False
