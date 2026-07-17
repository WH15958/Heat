import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class _FakeControlDevice:
    def __init__(self, device_id: str):
        self.config = SimpleNamespace(
            device_id=device_id,
            connection_params={"port": "FAKE"},
        )
        self.pending_start_checked = threading.Event()
        self.release_pending_start = threading.Event()
        self.start_calls = 0
        self.stop_calls = 0
        self.emergency_stop_calls = 0
        self.disconnect_calls = 0

    def is_connected(self):
        if threading.current_thread().name == "pending-device-start":
            self.pending_start_checked.set()
            if not self.release_pending_start.wait(timeout=2):
                raise TimeoutError("test did not release pending start")
        return True

    def start(self, *_args):
        self.start_calls += 1
        return True

    def stop(self):
        self.stop_calls += 1
        return True

    def emergency_stop(self):
        self.emergency_stop_calls += 1
        return True

    def disconnect(self):
        self.disconnect_calls += 1
        return True


@pytest.mark.parametrize(
    ("device_type", "use_emergency_stop"),
    [
        ("heater", False),
        ("heater", True),
        ("microwave", False),
        ("microwave", True),
    ],
)
def test_stop_cancels_a_pending_start_before_returning(
    device_type, use_emergency_stop
):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    device_id = f"{device_type}1"
    device = _FakeControlDevice(device_id)
    if device_type == "heater":
        dm._heaters[device_id] = device
        start = lambda: dm.start_heater(device_id)
        stop = lambda: dm.stop_heater(device_id)
    else:
        dm._microwaves[device_id] = device
        start = lambda: dm.start_microwave(device_id, "manual_power")
        stop = lambda: dm.stop_microwave(device_id)

    start_results = []
    start_thread = threading.Thread(
        target=lambda: start_results.append(start()),
        name="pending-device-start",
    )
    start_thread.start()
    assert device.pending_start_checked.wait(timeout=1)

    if use_emergency_stop:
        assert dm.emergency_stop_all() is True
        assert device.emergency_stop_calls == 1
    else:
        assert stop() is True
        assert device.stop_calls == 1

    device.release_pending_start.set()
    start_thread.join(timeout=1)

    assert not start_thread.is_alive()
    assert start_results == [False]
    assert device.start_calls == 0


class _ObservedLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.waiter_blocked = threading.Event()

    def acquire(self):
        if self._lock.locked():
            self.waiter_blocked.set()
        return self._lock.acquire()

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


@pytest.mark.parametrize(
    ("device_type", "disconnect_name", "stop_name", "store_name", "generation_name"),
    [
        (
            "heater",
            "disconnect_heater",
            "stop",
            "_heaters",
            "_heater_stop_generations",
        ),
        (
            "pump",
            "disconnect_pump",
            "stop_all",
            "_pumps",
            "_pump_stop_generations",
        ),
        (
            "microwave",
            "disconnect_microwave",
            "stop",
            "_microwaves",
            "_microwave_stop_generations",
        ),
    ],
)
@pytest.mark.parametrize("stop_outcome", ["success", "false", "exception"])
def test_disconnect_requires_confirmed_stop_before_releasing_connection(
    device_type,
    disconnect_name,
    stop_name,
    store_name,
    generation_name,
    stop_outcome,
):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    device_id = f"{device_type}1"
    device = Mock()
    device.is_connected.return_value = True
    events = []
    stop = getattr(device, stop_name)
    if stop_outcome == "success":
        stop.side_effect = lambda: events.append("stop") or True
    elif stop_outcome == "false":
        stop.side_effect = lambda: events.append("stop") or False
    else:
        stop.side_effect = RuntimeError("stop failed")
    device.disconnect.side_effect = lambda: events.append("disconnect") or True
    getattr(dm, store_name)[device_id] = device
    getattr(dm, generation_name)[device_id] = 0
    if device_type == "pump":
        dm._pump_abort_events[device_id] = threading.Event()

    result = getattr(dm, disconnect_name)(device_id)

    assert getattr(dm, generation_name)[device_id] == 1
    if device_type == "pump":
        assert dm._pump_abort_events[device_id].is_set()
    if stop_outcome == "success":
        assert result is True
        assert events == ["stop", "disconnect"]
    else:
        assert result is False
        device.disconnect.assert_not_called()


class _BlockingMicrowave(_FakeControlDevice):
    def __init__(self, device_id: str):
        super().__init__(device_id)
        self.operation_entered = threading.Event()
        self.release_operation = threading.Event()
        self.calls = []

    def configure_manual(self, _segments):
        self.calls.append("configure.begin")
        self.operation_entered.set()
        if not self.release_operation.wait(timeout=2):
            raise TimeoutError("test did not release microwave configuration")
        self.calls.append("configure.end")
        return True

    def start(self, *_args):
        self.calls.append("start")
        return True

    def stop(self):
        self.calls.append("stop")
        return True


@pytest.mark.parametrize("competing_operation", ["start", "stop"])
def test_microwave_configuration_cannot_interleave_with_control(
    competing_operation,
):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    device_id = "microwave1"
    microwave = _BlockingMicrowave(device_id)
    control_lock = _ObservedLock()
    dm._microwaves[device_id] = microwave
    dm._microwave_locks[device_id] = control_lock

    configure_results = []
    configure_thread = threading.Thread(
        target=lambda: configure_results.append(
            dm.configure_microwave_manual(device_id, [object()])
        )
    )
    configure_thread.start()
    assert microwave.operation_entered.wait(timeout=1)

    control_results = []
    if competing_operation == "start":
        control = lambda: dm.start_microwave(device_id, "manual_power")
    else:
        control = lambda: dm.stop_microwave(device_id)
    control_thread = threading.Thread(
        target=lambda: control_results.append(control())
    )
    control_thread.start()

    assert control_lock.waiter_blocked.wait(timeout=1)
    assert microwave.calls == ["configure.begin"]

    microwave.release_operation.set()
    configure_thread.join(timeout=1)
    control_thread.join(timeout=1)

    assert not configure_thread.is_alive()
    assert not control_thread.is_alive()
    assert configure_results == [True]
    assert control_results == [True]
    assert microwave.calls == [
        "configure.begin",
        "configure.end",
        competing_operation,
    ]


@pytest.mark.parametrize("device_type", ["heater", "microwave"])
def test_start_requested_during_global_emergency_stop_is_rejected(device_type):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    device_id = f"{device_type}1"
    device = _FakeControlDevice(device_id)
    if device_type == "heater":
        dm._heaters[device_id] = device
        start = lambda: dm.start_heater(device_id)
    else:
        dm._microwaves[device_id] = device
        start = lambda: dm.start_microwave(device_id, "manual_power")

    emergency_entered = threading.Event()
    release_emergency = threading.Event()

    def blocked_emergency_stop():
        emergency_entered.set()
        assert release_emergency.wait(timeout=2)
        return True

    dm._emergency_stop_all_devices = blocked_emergency_stop
    emergency_results = []
    emergency_thread = threading.Thread(
        target=lambda: emergency_results.append(dm.emergency_stop_all())
    )
    emergency_thread.start()
    assert emergency_entered.wait(timeout=1)

    assert start() is False
    assert device.start_calls == 0

    release_emergency.set()
    emergency_thread.join(timeout=1)
    assert not emergency_thread.is_alive()
    assert emergency_results == [True]


@pytest.mark.parametrize("device_type", ["heater", "microwave"])
def test_cleanup_cancels_pending_start_before_disconnect(device_type):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    device_id = f"{device_type}1"
    device = _FakeControlDevice(device_id)
    if device_type == "heater":
        dm._heaters[device_id] = device
        start = lambda: dm.start_heater(device_id)
    else:
        dm._microwaves[device_id] = device
        start = lambda: dm.start_microwave(device_id, "manual_power")

    start_results = []
    start_thread = threading.Thread(
        target=lambda: start_results.append(start()),
        name="pending-device-start",
    )
    start_thread.start()
    assert device.pending_start_checked.wait(timeout=1)

    assert dm.cleanup() is True
    assert device.stop_calls == 1
    assert device.disconnect_calls == 1

    device.release_pending_start.set()
    start_thread.join(timeout=1)
    assert not start_thread.is_alive()
    assert start_results == [False]
    assert device.start_calls == 0
