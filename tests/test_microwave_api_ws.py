"""
Microwave REST API and WebSocket integration tests.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException, WebSocketDisconnect

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from src.web.api.devices import (
    MicrowaveConfigureRequest,
    MicrowaveSegmentRequest,
    MicrowaveStartRequest,
    configure_microwave_manual,
    connect_microwave,
    disconnect_microwave,
    emergency_stop,
    list_devices,
    start_microwave,
    stop_microwave,
)
from src.web.api.ws import build_realtime_payload, manager, websocket_endpoint
from src.web.app import create_device_manager
from src.web.device_manager import DeviceManager


def make_request(device_manager):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(device_manager=device_manager))
    )


def run(coro):
    return asyncio.run(coro)


class FakeApiDeviceManager:
    def __init__(self):
        self.calls = []
        self.should_succeed = True
        self.emergency_stop_result = True

    def get_all_status(self):
        return {
            "heaters": {
                "heater1": {
                    "connected": False,
                    "status": "DISCONNECTED",
                    "connection_port": "COM7",
                }
            },
            "pumps": {
                "pump1": {
                    "connected": False,
                    "status": "DISCONNECTED",
                    "connection_port": "COM10",
                }
            },
            "microwaves": {
                "mw1": {
                    "connected": False,
                    "status": "DISCONNECTED",
                    "connection_port": "COM12",
                    "allow_real_hardware_writes": True,
                    "enable_control_writes": True,
                }
            },
        }

    def connect_microwave(self, device_id):
        self.calls.append(("connect_microwave", device_id))
        return self.should_succeed

    def disconnect_microwave(self, device_id):
        self.calls.append(("disconnect_microwave", device_id))
        return self.should_succeed

    def configure_microwave_manual(self, device_id, segments):
        self.calls.append(("configure_microwave_manual", device_id, segments))
        return self.should_succeed

    def start_microwave(self, device_id, mode):
        self.calls.append(("start_microwave", device_id, mode.value))
        return self.should_succeed

    def stop_microwave(self, device_id):
        self.calls.append(("stop_microwave", device_id))
        return self.should_succeed

    def emergency_stop_all(self):
        self.calls.append(("emergency_stop_all",))
        return self.emergency_stop_result


class FakeConnectedMicrowave:
    def __init__(self):
        self.stop = Mock()

    def is_connected(self):
        return True


class FakeWebSocket:
    def __init__(self, device_manager=None):
        self.app = SimpleNamespace(state=SimpleNamespace(device_manager=device_manager))

    async def accept(self):
        return None

    async def receive_text(self):
        raise WebSocketDisconnect()


def test_list_devices_includes_microwaves():
    dm = FakeApiDeviceManager()
    response = run(list_devices(make_request(dm)))

    assert response["heaters"]["heater1"]["connection_port"] == "COM7"
    assert response["pumps"]["pump1"]["connection_port"] == "COM10"
    assert "microwaves" in response
    assert "mw1" in response["microwaves"]
    assert response["microwaves"]["mw1"]["connection_port"] == "COM12"


def test_microwave_connect_disconnect_call_manager():
    dm = FakeApiDeviceManager()
    request = make_request(dm)

    connect_response = run(connect_microwave("mw1", request))
    disconnect_response = run(disconnect_microwave("mw1", request))

    assert connect_response == {"success": True, "device_id": "mw1"}
    assert disconnect_response == {"success": True, "device_id": "mw1"}
    assert dm.calls == [
        ("connect_microwave", "mw1"),
        ("disconnect_microwave", "mw1"),
    ]


def test_configure_start_stop_false_results_are_http_failures():
    dm = FakeApiDeviceManager()
    dm.should_succeed = False
    request = make_request(dm)
    configure_body = MicrowaveConfigureRequest(
        segments=[MicrowaveSegmentRequest(segment=1, heating_temperature=80)],
        confirm_real_hardware_write=True,
    )
    start_body = MicrowaveStartRequest(mode="manual_power")

    for call in (
        lambda: configure_microwave_manual("mw1", configure_body, request),
        lambda: start_microwave("mw1", start_body, request),
        lambda: stop_microwave("mw1", request),
    ):
        try:
            run(call())
            raise AssertionError("Expected HTTPException")
        except HTTPException as e:
            assert e.status_code == 400


def test_microwave_configure_without_confirmation_calls_manager():
    dm = FakeApiDeviceManager()
    request = make_request(dm)
    configure_body = MicrowaveConfigureRequest(
        segments=[MicrowaveSegmentRequest(segment=1, heating_temperature=80)]
    )

    response = run(configure_microwave_manual("mw1", configure_body, request))

    assert response == {"success": True, "device_id": "mw1"}
    assert dm.calls[0][0] == "configure_microwave_manual"


def test_websocket_payload_includes_microwaves():
    microwave = FakeConnectedMicrowave()
    dm = Mock()
    dm.get_all_heaters.return_value = {}
    dm.get_all_pumps.return_value = {}
    dm.get_all_microwaves.return_value = {"mw1": microwave}
    dm.read_microwave_data.return_value = {
        "device_id": "mw1",
        "connection_port": "COM12",
        "running": False,
        "mode": "unknown",
        "current_segment": 1,
        "material_temperature": 25.0,
        "temperature_source": "float",
        "power_percent": 0,
        "current": 0,
        "runtime_seconds": 0,
        "fault_code": 0,
        "faults": [],
        "allow_real_hardware_writes": True,
        "enable_control_writes": True,
    }

    payload = run(build_realtime_payload(dm))

    assert "microwaves" in payload
    assert payload["microwaves"]["mw1"]["device_id"] == "mw1"
    assert payload["microwaves"]["mw1"]["connection_port"] == "COM12"


def test_websocket_payload_includes_heater_and_pump_ports():
    heater = Mock()
    heater.is_connected.return_value = True
    heater.config = SimpleNamespace(connection_params={"port": "COM7"})
    heater.read_data.return_value = SimpleNamespace(
        pv=25.0,
        sv=30.0,
        mv=0,
        alarms=[],
        run_status=SimpleNamespace(name="STOP"),
    )
    pump = Mock()
    pump.is_connected.return_value = True
    pump.config = SimpleNamespace(connection_params={"port": "COM10"})

    dm = Mock()
    dm.get_all_heaters.return_value = {"heater1": heater}
    dm.get_all_pumps.return_value = {"pump1": pump}
    dm.get_all_microwaves.return_value = {}
    dm.get_heater_binding.return_value = {}
    dm.get_pump_binding.return_value = {}
    dm.read_pump_status.return_value = {
        "device_id": "pump1",
        "connection_port": "COM10",
        "channels": {},
    }

    payload = run(build_realtime_payload(dm))

    assert payload["heaters"]["heater1"]["connection_port"] == "COM7"
    assert payload["pumps"]["pump1"]["connection_port"] == "COM10"


def test_websocket_microwave_read_failure_is_error_payload():
    microwave = FakeConnectedMicrowave()
    microwave.config = SimpleNamespace(connection_params={"port": "COM12"})
    dm = Mock()
    dm.get_all_heaters.return_value = {}
    dm.get_all_pumps.return_value = {}
    dm.get_all_microwaves.return_value = {"mw1": microwave}
    dm.get_microwave_binding.return_value = {}
    dm.read_microwave_data.side_effect = TimeoutError("simulated timeout")

    payload = run(build_realtime_payload(dm))

    assert payload["microwaves"]["mw1"] == {
        "device_id": "mw1",
        "connection_port": "COM12",
        "error": "read_timeout",
    }


def test_create_device_manager_raises_on_config_load_failure():
    import src.utils.config as config_mod

    def fail_load(self):
        raise ValueError("broken config")

    original_load = config_mod.ConfigManager.load
    config_mod.ConfigManager.load = fail_load
    try:
        create_device_manager()
        raise AssertionError("Expected create_device_manager to raise")
    except ValueError as e:
        assert "broken config" in str(e)
    finally:
        config_mod.ConfigManager.load = original_load


def test_websocket_disconnect_does_not_stop_microwave():
    microwave = FakeConnectedMicrowave()
    dm = Mock()
    dm.get_all_microwaves.return_value = {"mw1": microwave}
    manager.active = []

    run(websocket_endpoint(FakeWebSocket(dm)))

    assert microwave.stop.call_count == 0
    assert manager.active == []


def test_emergency_stop_all_calls_microwave_stop_and_reports_failure():
    dm = DeviceManager()
    microwave = Mock()
    microwave.config = SimpleNamespace(device_id="mw1")
    microwave.emergency_stop.return_value = False
    dm._microwaves["mw1"] = microwave

    result = dm.emergency_stop_all()

    assert result is False
    assert microwave.emergency_stop.call_count == 1


def test_emergency_stop_endpoint_reports_device_failure():
    dm = FakeApiDeviceManager()
    dm.emergency_stop_result = False
    request = make_request(dm)

    response = run(emergency_stop(request))

    assert response == {"success": False}
    assert dm.calls == [("emergency_stop_all",)]


def run_all():
    tests = [
        test_list_devices_includes_microwaves,
        test_microwave_connect_disconnect_call_manager,
        test_configure_start_stop_false_results_are_http_failures,
        test_microwave_configure_without_confirmation_calls_manager,
        test_websocket_payload_includes_microwaves,
        test_websocket_payload_includes_heater_and_pump_ports,
        test_websocket_microwave_read_failure_is_error_payload,
        test_create_device_manager_raises_on_config_load_failure,
        test_websocket_disconnect_does_not_stop_microwave,
        test_emergency_stop_all_calls_microwave_stop_and_reports_failure,
        test_emergency_stop_endpoint_reports_device_failure,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
    passed = len(tests) - failed
    print(f"microwave API/WS tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
