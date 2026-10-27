"""Config, registration and read paths use fake ports and isolated serial locks."""
import asyncio
import copy
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi import FastAPI, WebSocketDisconnect

from src.devices.turntable import TurntableDevice
from src.protocols.turntable import STATUS_FRAME
from src.utils.config import ConfigManager
from src.utils.serial_binding import SerialPortInfo
from src.web.api import devices, turntables, ws
from src.web.app import create_device_manager
from src.web.device_manager import DeviceManager


def config_data(**overrides):
    item = dict(device_id="turntable1", name="转盘接样", enabled=True,
        action_timeout=60.0, home_enabled=False, position_encoding_verified=False,
        connection=dict(port="COM16", baudrate=115200, parity="N", bytesize=8,
            stopbits=1, timeout=.005,
            binding=dict(mode="fingerprint", vid=0x1A86, pid=0x7523,
                         location="1-3.2.3", fallback_to_port=False)))
    item.update(overrides)
    return dict(name="test", version="1.0", turntables=[item])


def parsed_config(data):
    return ConfigManager()._convert_dict_to_config(data)


def port(name, location):
    return SerialPortInfo(port=name, vid=0x1A86, pid=0x7523,
                          location=location, description="USB-SERIAL CH340")


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    from src.utils import serial_manager
    monkeypatch.setattr("serial.Serial.open", Mock(side_effect=AssertionError("No physical serial access")))
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "workspace"))
    monkeypatch.setattr(serial_manager.SerialPortLock, "LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(serial_manager.SerialPortManager, "_instance", None)
    monkeypatch.setattr(serial_manager.SerialPortManager, "_register_cleanup", lambda _: None)
    manager = serial_manager.SerialPortManager()
    monkeypatch.setattr(serial_manager, "_global_manager", manager)
    yield
    manager.cleanup()


def test_legacy_configuration_without_turntables_loads_and_registers(tmp_path, monkeypatch):
    path = tmp_path / "system_config.yaml"
    path.write_text("name: legacy\nversion: '1.0'\n", encoding="utf-8")
    config = ConfigManager(str(path)).load()
    assert config.turntables == []
    monkeypatch.setattr(ConfigManager, "load", lambda _: config)
    dm = create_device_manager()
    assert dm.turntables == {}
    dm.require_turntables_idle()
    assert dm.get_all_status()["turntables"] == {}


def test_turntable_configuration_round_trip_retains_binding_and_safe_defaults(tmp_path):
    path = tmp_path / "system_config.yaml"
    path.write_text(yaml.safe_dump(config_data()), encoding="utf-8")
    manager = ConfigManager(str(path))
    config = manager.load()
    assert config.validate() == []
    turntable = config.turntables[0]
    assert turntable.home_enabled is False and turntable.position_encoding_verified is False
    assert manager.save(config)
    restored = ConfigManager(str(path)).load().turntables[0]
    assert restored.to_dict() == turntable.to_dict()


@pytest.mark.parametrize("field,value", [
    ("enabled", "true"), ("home_enabled", 1), ("position_encoding_verified", "false"),
    ("action_timeout", True), ("action_timeout", "60"), ("action_timeout", float("nan")),
])
def test_invalid_turntable_configuration_is_rejected(field, value):
    assert parsed_config(config_data(**{field: value})).validate()


def test_application_registration_resolves_location_without_connecting(monkeypatch):
    config = parsed_config(config_data())
    monkeypatch.setattr(ConfigManager, "load", lambda _: config)
    monkeypatch.setattr("src.utils.serial_binding.enumerate_serial_ports", lambda: [
        port("COM14", "1-3.4.2"), port("COM15", "1-3.3.4"), port("COM19", "1-3.2.3")])
    connect = Mock(side_effect=AssertionError("Registration must not connect"))
    monkeypatch.setattr(TurntableDevice, "connect", connect)
    dm = create_device_manager()
    state = dm.get_all_status()["turntables"]["turntable1"]
    assert state["binding_resolved"] is True and state["connection_port"] == "COM19"
    assert state["connected"] is False and state["read_ok"] is False
    connect.assert_not_called()


def test_disabled_turntable_is_not_registered(monkeypatch):
    config = parsed_config(config_data(enabled=False))
    monkeypatch.setattr(ConfigManager, "load", lambda _: config)
    enumerate_ports = Mock(side_effect=AssertionError("Disabled devices need no binding resolution"))
    monkeypatch.setattr("src.utils.serial_binding.enumerate_serial_ports", enumerate_ports)
    assert create_device_manager().turntables == {}
    enumerate_ports.assert_not_called()


@pytest.mark.parametrize("available", [
    [port("COM16", "1-3.4.2"), port("COM15", "1-3.3.4")],
    [port("COM19", "1-3.2.3"), port("COM20", "1-3.2.3")],
])
def test_missing_or_ambiguous_location_never_falls_back_to_other_ch340(monkeypatch, available):
    monkeypatch.setattr("src.utils.serial_binding.enumerate_serial_ports", lambda: available)
    dm = DeviceManager()
    dm.add_turntable(parsed_config(config_data()).turntables[0])
    controller = dm.turntable("turntable1")
    connect = Mock(side_effect=AssertionError("Unresolved binding must not connect"))
    monkeypatch.setattr(controller.device, "connect", connect)
    state = controller.summary()
    assert state["binding_resolved"] is False and not state["connection_port"]
    with pytest.raises(ValueError, match="唯一匹配"):
        controller.connect()
    connect.assert_not_called()


class Wire:
    def flush(self):
        pass

    def __init__(self, **kwargs):
        self.port = None
        self.is_open = False
        self.buffer = bytearray()
        self.writes = []

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, frame):
        self.writes.append(frame)
        if frame == STATUS_FRAME:
            self.buffer.extend(bytes.fromhex("00 00 00 00 00 00 3c 20"))
        return len(frame)

    def read(self, count):
        response = bytes(self.buffer[:count])
        del self.buffer[:count]
        return response


def connected_manager(monkeypatch):
    monkeypatch.setattr("src.utils.serial_binding.enumerate_serial_ports", lambda: [port("COM19", "1-3.2.3")])
    dm = DeviceManager()
    dm.add_turntable(parsed_config(config_data()).turntables[0])
    control = dm.turntable("turntable1")
    control.device.serial_factory = Wire
    control.connect()
    control.device.handle.writes.clear()
    return dm, control


def test_list_status_and_ws_only_query_even_when_action_deadline_has_expired(monkeypatch):
    dm, control = connected_manager(monkeypatch)
    control.command(dict(action="run", direction="positive", speed=400))
    control.action["deadline"] = 0
    wire = control.device.handle
    wire.writes.clear()
    app = FastAPI()
    app.include_router(devices.router, prefix="/api")
    app.include_router(turntables.router, prefix="/api")
    app.state.device_manager = dm
    app.state.device_read_coordinator = ws.DeviceReadCoordinator()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://heat.test") as client:
            response = await client.get("/api/devices")
            assert response.status_code == 200 and "turntable1" in response.json()["turntables"]
            listed = response.json()["turntables"]["turntable1"]
            assert wire.writes == []
            response = await client.get("/api/turntable/turntable1/status")
            assert response.status_code == 200 and response.json()["read_ok"] is True
            fetched = response.json()
            payload = await ws.build_realtime_payload(dm, app.state.device_read_coordinator)
            pushed = payload["turntables"]["turntable1"]
            assert pushed["position"] == 0
            assert listed["state_session"] == fetched["state_session"] == pushed["state_session"]
            assert listed["state_revision"] < fetched["state_revision"] < pushed["state_revision"]
            assert wire.writes == [STATUS_FRAME, STATUS_FRAME]
    asyncio.run(scenario())


def test_disconnected_get_and_ws_do_not_connect(monkeypatch):
    dm = DeviceManager()
    monkeypatch.setattr("src.utils.serial_binding.enumerate_serial_ports", lambda: [port("COM19", "1-3.2.3")])
    dm.add_turntable(parsed_config(config_data()).turntables[0])
    control = dm.turntable("turntable1")
    factory = Mock(side_effect=AssertionError("Read paths must not connect"))
    control.device.serial_factory = factory
    app = FastAPI()
    app.include_router(turntables.router, prefix="/api")
    app.state.device_manager = dm

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://heat.test") as client:
            response = await client.get("/api/turntable/turntable1/status")
            assert response.status_code == 200 and response.json()["connected"] is False
            payload = await ws.build_realtime_payload(dm)
            assert payload["turntables"]["turntable1"]["read_ok"] is False
    asyncio.run(scenario())
    factory.assert_not_called()


def test_ws_connection_and_disconnection_only_replay_cached_status(monkeypatch):
    dm, control = connected_manager(monkeypatch)
    manager = ws.ConnectionManager()
    monkeypatch.setattr(ws, "manager", manager)

    class Socket:
        def __init__(self):
            self.sent = []
        async def accept(self):
            pass
        async def send_json(self, data):
            self.sent.append(copy.deepcopy(data))
        async def receive_text(self):
            raise WebSocketDisconnect()

    async def scenario():
        payload = await ws.build_realtime_payload(dm)
        await manager.broadcast(payload)
        control.device.handle.writes.clear()
        socket = Socket()
        await ws.websocket_endpoint(socket)
        assert socket.sent[1]["turntables"] == payload["turntables"]
        assert socket.sent[1]["snapshot"] is True
        assert control.device.handle.writes == []
        assert control.device.is_connected() and manager.active == []
    asyncio.run(scenario())


def test_ws_timeout_returns_unknown_without_waiting_for_controller_lock(monkeypatch):
    dm, control = connected_manager(monkeypatch)
    previous = control.summary()
    monkeypatch.setattr(control, "summary", Mock(side_effect=AssertionError("Do not wait for reader's lock")))
    class TimedOut:
        async def read(self, key, reader, timeout):
            assert key == ("turntable", "turntable1")
            raise asyncio.TimeoutError()
    state = asyncio.run(ws.build_realtime_payload(dm, TimedOut()))["turntables"]["turntable1"]
    assert state["read_ok"] is False and state["position"] is None
    assert state["busy"] is None and state["stop_confirmed"] is False
    assert state["state_session"] == previous["state_session"]
    assert state["state_revision"] > previous["state_revision"]
    assert control.device.handle.writes == []
