"""Monitor replay uses existing samples and never issues device operations."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import WebSocketDisconnect

from src.web.api import ws as ws_api


def frame(at, **groups):
    return {
        "type": "realtime", "sampled_at_ms": at,
        "heaters": {}, "pumps": {}, "microwaves": {}, **groups,
    }


class Socket:
    def __init__(self, fail_send=False, receive_error=None):
        self.accepted = False
        self.sent = []
        self.fail_send = fail_send
        self.receive_error = receive_error or WebSocketDisconnect()

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self.fail_send:
            raise RuntimeError("closed socket")
        self.sent.append(copy.deepcopy(data))

    async def receive_text(self):
        raise self.receive_error


def empty_devices():
    return SimpleNamespace(
        get_all_heaters=Mock(return_value={}),
        get_all_pumps=Mock(return_value={}),
        get_all_microwaves=Mock(return_value={}),
        valves={}, syringe_pumps={},
    )


def test_empty_cache_sends_history_without_inventing_a_sample():
    async def scenario():
        manager = ws_api.ConnectionManager()
        socket = Socket()
        assert await manager.connect(socket) is True
        assert socket.accepted is True
        assert socket.sent == [{"type": "monitor_history", "frames": []}]
        assert manager.active == [socket]
        assert manager.last_payload == {}

    asyncio.run(scenario())


def test_samples_are_kept_without_clients_and_replay_keeps_original_time(monkeypatch):
    async def scenario():
        manager = ws_api.ConnectionManager()
        await manager.broadcast(frame(1000, heaters={"heater1": {"pv": 20, "sv": 50}}))
        await manager.broadcast(frame(2000, heaters={"heater1": {"pv": 21, "sv": 50}}))
        assert manager.active == []
        monkeypatch.setattr(ws_api.time, "time", lambda: 999999999)
        socket = Socket()
        await manager.connect(socket)
        assert [item["sampled_at_ms"] for item in socket.sent[0]["frames"]] == [1000, 2000]
        assert socket.sent[1] == {
            **frame(2000, heaters={"heater1": {"pv": 21, "sv": 50}}),
            "snapshot": True,
        }
        assert manager.last_payload["sampled_at_ms"] == 2000

    asyncio.run(scenario())


def test_history_is_bounded_and_does_not_cache_non_realtime_events():
    async def scenario():
        manager = ws_api.ConnectionManager()
        for at in range(ws_api.MONITOR_HISTORY_LIMIT + 5):
            await manager.broadcast(frame(at))
        event = {"type": "experiment_log", "data": {"message": "message"}}
        socket = Socket()
        manager.active.append(socket)
        await manager.broadcast(event)
        assert socket.sent == [event]
        assert len(manager.monitor_history) == ws_api.MONITOR_HISTORY_LIMIT
        assert manager.monitor_history[0]["sampled_at_ms"] == 5
        assert manager.last_payload["sampled_at_ms"] == ws_api.MONITOR_HISTORY_LIMIT + 4

    asyncio.run(scenario())


def test_trend_projection_keeps_errors_and_excludes_control_state():
    async def scenario():
        manager = ws_api.ConnectionManager()
        data = frame(1000,
            heaters={"h1": {"pv": 20, "sv": 50, "mv": 80, "run_status": "RUN"}},
            microwaves={"m1": {"material_temperature": 40, "control_active": True}},
            pumps={"p1": {"channels": {"1": {
                "flow_rate": 15, "flow_unit": "ML_MIN", "running": True,
                "read_ok": True, "volume": 200,
            }}}},
            valves={"v1": {"relay_energized": True}},
            syringe_pumps={"s1": {"position": 50}},
        )
        await manager.broadcast(data)
        data["pumps"]["p1"]["channels"]["1"]["flow_rate"] = 100
        assert manager.monitor_history[0] == frame(1000,
            heaters={"h1": {"pv": 20, "sv": 50}},
            microwaves={"m1": {"material_temperature": 40}},
            pumps={"p1": {"channels": {"1": {
                "flow_rate": 15, "flow_unit": "ML_MIN", "running": True,
                "read_ok": True,
            }}}},
        )
        await manager.broadcast(frame(2000,
            heaters={"h1": {"error": "read_timeout"}},
            microwaves={"m1": {"error": "read_failed"}},
            pumps={"p1": {"channels": {"1": {
                "running": None, "read_ok": False, "error": "read_failed",
            }}}},
        ))
        history = manager.monitor_history[-1]
        assert history["heaters"]["h1"] == {"error": "read_timeout"}
        assert history["microwaves"]["m1"] == {"error": "read_failed"}
        assert history["pumps"]["p1"]["channels"]["1"]["read_ok"] is False
        assert "pv" not in history["heaters"]["h1"]

    asyncio.run(scenario())


def test_completed_payload_has_collection_time_without_extra_reads(monkeypatch):
    async def scenario():
        clock = [1]
        heater = SimpleNamespace(
            is_connected=lambda: True,
            config=SimpleNamespace(connection_params={"port": "COM_FAKE"}),
            read_data=Mock(),
        )
        dm = empty_devices()
        dm.get_all_heaters.return_value = {"h1": heater}
        dm.get_heater_binding = Mock(return_value={})
        dm.get_all_microwaves.return_value = {"m1": SimpleNamespace(is_connected=lambda: True)}
        dm.read_microwave_data = Mock(return_value={"material_temperature": 40})
        reads = []

        class Coordinator:
            async def read(self, key, reader, timeout):
                reads.append(key)
                clock[0] += 10
                if key[0] == "heater":
                    return SimpleNamespace(pv=20, sv=50, mv=0, alarms=[], run_status=SimpleNamespace(name="STOP"))
                return reader()

        monkeypatch.setattr(ws_api.time, "time", lambda: clock[0])
        data = await ws_api.build_realtime_payload(dm, Coordinator())
        assert data["sampled_at_ms"] == 21000
        assert reads == [("heater", "h1"), ("microwave", "m1")]
        dm.read_microwave_data.assert_called_once_with("m1")
        manager = ws_api.ConnectionManager()
        await manager.broadcast(data)
        await manager.connect(Socket())
        assert reads == [("heater", "h1"), ("microwave", "m1")]
        dm.read_microwave_data.assert_called_once_with("m1")

    asyncio.run(scenario())


def test_push_loop_retains_completed_samples_with_no_clients(monkeypatch):
    from src.utils import serial_manager

    async def scenario():
        manager = ws_api.ConnectionManager()
        monkeypatch.setattr(ws_api, "manager", manager)
        dm = empty_devices()
        watchdog = Mock()
        monkeypatch.setattr(serial_manager, "get_serial_manager", lambda: watchdog)

        async def stop_after_iteration(_delay):
            raise asyncio.CancelledError()

        monkeypatch.setattr(ws_api.asyncio, "sleep", stop_after_iteration)
        with pytest.raises(asyncio.CancelledError):
            await ws_api.data_push_loop(SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        assert manager.active == []
        assert len(manager.monitor_history) == 1
        assert manager.last_payload["sampled_at_ms"] > 0
        dm.get_all_heaters.assert_called_once()
        dm.get_all_pumps.assert_called_once()
        dm.get_all_microwaves.assert_called_once()
        watchdog.feed_watchdog.assert_called_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_send", ["monitor_history", "snapshot"])
def test_broadcasts_during_replay_are_serialized_without_losing_samples(blocked_send):
    async def scenario():
        manager = ws_api.ConnectionManager()
        await manager.broadcast(frame(1000))
        replay_blocked = asyncio.Event()
        release_replay = asyncio.Event()

        class BlockingSocket(Socket):
            sending = False

            async def send_json(self, data):
                assert not self.sending, "WebSocket sends must not overlap"
                self.sending = True
                try:
                    await super().send_json(data)
                    kind = "snapshot" if data.get("snapshot") else data["type"]
                    if kind == blocked_send:
                        replay_blocked.set()
                        await release_replay.wait()
                finally:
                    self.sending = False

        socket = BlockingSocket()
        connecting = asyncio.create_task(manager.connect(socket))
        await asyncio.wait_for(replay_blocked.wait(), timeout=1)
        broadcasts = []
        for at in (2000, 3000):
            task = asyncio.create_task(manager.broadcast(frame(at)))
            broadcasts.append(task)
            await asyncio.sleep(0)
            assert manager.last_payload["sampled_at_ms"] == at
            assert not task.done()
        release_replay.set()
        assert await asyncio.wait_for(connecting, timeout=1) is True
        await asyncio.wait_for(asyncio.gather(*broadcasts), timeout=1)
        await manager.broadcast(frame(4000))
        assert [data["type"] for data in socket.sent] == ["monitor_history"] + ["realtime"] * 4
        assert [data["sampled_at_ms"] for data in socket.sent[0]["frames"]] == [1000]
        assert socket.sent[1]["snapshot"] is True
        assert [data["sampled_at_ms"] for data in socket.sent[1:]] == [1000, 2000, 3000, 4000]
        assert manager.active == [socket]

    asyncio.run(scenario())


def test_replay_failure_removes_connection_before_waiting_broadcast_can_send():
    async def scenario():
        manager = ws_api.ConnectionManager()
        await manager.broadcast(frame(1000))
        replay_blocked = asyncio.Event()
        release_replay = asyncio.Event()

        class FailingSocket(Socket):
            async def send_json(self, data):
                self.sent.append(copy.deepcopy(data))
                replay_blocked.set()
                await release_replay.wait()
                raise RuntimeError("closed during replay")

        socket = FailingSocket()
        connecting = asyncio.create_task(manager.connect(socket))
        await asyncio.wait_for(replay_blocked.wait(), timeout=1)
        broadcasting = asyncio.create_task(manager.broadcast(frame(2000)))
        await asyncio.sleep(0)
        assert not broadcasting.done()
        release_replay.set()
        assert await asyncio.wait_for(connecting, timeout=1) is False
        await asyncio.wait_for(broadcasting, timeout=1)
        assert manager.active == []
        assert manager._send_locks == {}
        assert [data["type"] for data in socket.sent] == ["monitor_history"]
        assert [data["sampled_at_ms"] for data in manager.monitor_history] == [1000, 2000]

    asyncio.run(scenario())


def test_cancelled_replay_removes_connection_and_releases_waiting_broadcast():
    async def scenario():
        manager = ws_api.ConnectionManager()
        replay_blocked = asyncio.Event()

        class BlockingSocket(Socket):
            async def send_json(self, data):
                await super().send_json(data)
                replay_blocked.set()
                await asyncio.Event().wait()

        socket = BlockingSocket()
        connecting = asyncio.create_task(manager.connect(socket))
        await asyncio.wait_for(replay_blocked.wait(), timeout=1)
        broadcasting = asyncio.create_task(manager.broadcast(frame(1000)))
        await asyncio.sleep(0)
        connecting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await connecting
        await asyncio.wait_for(broadcasting, timeout=1)
        assert manager.active == []
        assert manager._send_locks == {}
        assert [data["type"] for data in socket.sent] == ["monitor_history"]

    asyncio.run(scenario())


def test_disconnect_during_another_send_does_not_recreate_a_removed_lock():
    async def scenario():
        manager = ws_api.ConnectionManager()
        send_blocked = asyncio.Event()
        release_send = asyncio.Event()

        class BlockingSocket(Socket):
            async def send_json(self, data):
                await super().send_json(data)
                if data["type"] == "realtime":
                    send_blocked.set()
                    await release_send.wait()

        first, second = BlockingSocket(), Socket()
        await manager.connect(first)
        await manager.connect(second)
        broadcasting = asyncio.create_task(manager.broadcast(frame(1000)))
        await asyncio.wait_for(send_blocked.wait(), timeout=1)
        manager.disconnect(second)
        release_send.set()
        await asyncio.wait_for(broadcasting, timeout=1)
        assert manager.active == [first]
        assert second not in manager._send_locks
        assert [data["type"] for data in second.sent] == ["monitor_history"]

    asyncio.run(scenario())


def test_initial_send_failure_does_not_register_or_touch_devices(monkeypatch):
    async def scenario():
        manager = ws_api.ConnectionManager()
        monkeypatch.setattr(ws_api, "manager", manager)
        socket = Socket(fail_send=True)
        socket.app = SimpleNamespace(state=SimpleNamespace(device_manager=Mock()))
        await ws_api.websocket_endpoint(socket)
        assert manager.active == []
        assert socket.app.state.device_manager.mock_calls == []

    asyncio.run(scenario())


def test_failed_live_send_and_receive_remove_only_client(monkeypatch):
    async def scenario():
        manager = ws_api.ConnectionManager()
        failed, healthy = Socket(), Socket()
        await manager.connect(failed)
        await manager.connect(healthy)
        failed.fail_send = True
        await manager.broadcast(frame(1000))
        assert manager.active == [healthy]
        assert healthy.sent[-1] == frame(1000)
        monkeypatch.setattr(ws_api, "manager", manager)
        bad_receiver = Socket(receive_error=RuntimeError("receive failed"))
        with pytest.raises(RuntimeError, match="receive failed"):
            await ws_api.websocket_endpoint(bad_receiver)
        assert manager.active == [healthy]

    asyncio.run(scenario())
