import asyncio
import time
from collections import deque
from typing import Any, Callable, Hashable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

DEVICE_READ_TIMEOUT = 5.0
PUMP_READ_TIMEOUT = 10.0
MICROWAVE_READ_TIMEOUT = 5.0
MONITOR_HISTORY_LIMIT = 1800


def _with_binding(payload: dict, binding_status: dict) -> dict:
    payload.update(binding_status)
    return payload


def _monitor_frame(payload: dict) -> dict:
    """Copy only the readings required to replay monitor charts."""
    frame = {
        "type": "realtime",
        "sampled_at_ms": payload["sampled_at_ms"],
        "heaters": {},
        "pumps": {},
        "microwaves": {},
    }
    for did, reading in payload.get("heaters", {}).items():
        frame["heaters"][did] = {
            key: reading[key] for key in ("pv", "sv", "error") if key in reading
        }
    for did, reading in payload.get("microwaves", {}).items():
        frame["microwaves"][did] = {
            key: reading[key]
            for key in ("material_temperature", "error") if key in reading
        }
    for did, reading in payload.get("pumps", {}).items():
        frame["pumps"][did] = {
            key: reading[key] for key in ("error",) if key in reading
        }
        frame["pumps"][did]["channels"] = {
            channel: {
                key: value[key]
                for key in ("flow_rate", "flow_unit", "running", "read_ok", "error")
                if key in value
            }
            for channel, value in reading.get("channels", {}).items()
        }
    return frame


class DeviceReadCoordinator:
    """Keep at most one blocking status read in flight for each device."""

    def __init__(self):
        self._tasks: dict[Hashable, asyncio.Task] = {}

    @staticmethod
    def _observe_completion(task: asyncio.Task):
        if task.cancelled():
            return
        try:
            task.exception()
        except asyncio.CancelledError:
            pass

    async def read(
        self,
        key: Hashable,
        reader: Callable[[], Any],
        timeout: float,
    ) -> Any:
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(reader))
            task.add_done_callback(self._observe_completion)
            self._tasks[key] = task

        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            raise
        except Exception:
            if self._tasks.get(key) is task:
                del self._tasks[key]
            raise
        else:
            if self._tasks.get(key) is task:
                del self._tasks[key]
            return result


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active: list[WebSocket] = []
        self._send_locks: dict[WebSocket, asyncio.Lock] = {}
        self.last_payload: dict = {}
        self.monitor_history: deque[dict] = deque(maxlen=MONITOR_HISTORY_LIMIT)

    async def connect(self, ws: WebSocket):
        """接受WebSocket连接

        Args:
            ws: WebSocket连接
        """
        await ws.accept()
        send_lock = asyncio.Lock()
        self._send_locks[ws] = send_lock
        try:
            async with send_lock:
                # Register before yielding so broadcasts wait behind this replay.
                self.active.append(ws)
                history = list(self.monitor_history)
                snapshot = self.last_payload
                await ws.send_json({"type": "monitor_history", "frames": history})
                if snapshot:
                    await ws.send_json({**snapshot, "snapshot": True})
        except asyncio.CancelledError:
            self.disconnect(ws)
            raise
        except Exception:
            logger.warning("WebSocket initial monitor replay failed")
            self.disconnect(ws)
            return False
        logger.info(f"WebSocket client connected, total: {len(self.active)}")
        return True

    def disconnect(self, ws: WebSocket):
        """移除WebSocket连接

        Args:
            ws: WebSocket连接
        """
        if ws in self.active:
            self.active.remove(ws)
        self._send_locks.pop(ws, None)
        logger.info(f"WebSocket client disconnected, total: {len(self.active)}")

    async def broadcast(self, data: dict):
        """向所有客户端广播数据

        Args:
            data: 要广播的数据
        """
        if data.get("type") == "realtime":
            self.last_payload = data
            self.monitor_history.append(_monitor_frame(data))
        disconnected = []
        for ws in list(self.active):
            if ws not in self.active:
                continue
            send_lock = self._send_locks.setdefault(ws, asyncio.Lock())
            try:
                async with send_lock:
                    if ws in self.active:
                        await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()


@router.get("/ws/status")
async def ws_status(request: Request):
    """WebSocket推送状态检查

    Returns:
        dict: 推送状态信息
    """
    dm = request.app.state.device_manager
    heaters = dm.get_all_heaters()
    pumps = dm.get_all_pumps()
    microwaves = dm.get_all_microwaves()
    return {
        "ws_clients": len(manager.active),
        "heaters_registered": list(heaters.keys()),
        "heaters_connected": [did for did, h in heaters.items() if h.is_connected()],
        "pumps_registered": list(pumps.keys()),
        "pumps_connected": [did for did, p in pumps.items() if p.is_connected()],
        "microwaves_registered": list(microwaves.keys()),
        "microwaves_connected": [
            did for did, m in microwaves.items() if m.is_connected()
        ],
        "last_payload_keys": {
            "heaters": list(manager.last_payload.get("heaters", {}).keys()),
            "pumps": list(manager.last_payload.get("pumps", {}).keys()),
            "microwaves": list(manager.last_payload.get("microwaves", {}).keys()),
        },
    }


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket端点 - 客户端连接后接收实时数据

    Args:
        ws: WebSocket连接
    """
    if not await manager.connect(ws):
        return
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


async def build_realtime_payload(
    dm,
    read_coordinator: DeviceReadCoordinator | None = None,
) -> dict:
    """Read connected devices once and build the WebSocket payload."""
    payload = {"type": "realtime", "heaters": {}, "pumps": {}, "microwaves": {}}
    read_coordinator = read_coordinator or DeviceReadCoordinator()

    # Independent device families own separate serial resources. Keep reads
    # within each family ordered, and retain the coordinator and driver locks.
    async def read_heaters():
        heaters = dm.get_all_heaters()
        for did, heater in heaters.items():
            if heater.is_connected():
                try:
                    data = await read_coordinator.read(
                        ("heater", did),
                        heater.read_data,
                        DEVICE_READ_TIMEOUT,
                    )
                    payload["heaters"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": heater.config.connection_params.get("port"),
                        "pv": data.pv,
                        "sv": data.sv,
                        "mv": data.mv,
                        "alarms": data.alarms,
                        "run_status": data.run_status.name,
                    }, dm.get_heater_binding(did))
                except (asyncio.TimeoutError, TimeoutError):
                    logger.warning(f"Heater {did} read timeout")
                    payload["heaters"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": heater.config.connection_params.get("port"),
                        "error": "read_timeout",
                    }, dm.get_heater_binding(did))
                except Exception as e:
                    logger.warning(f"Heater {did} read failed: {e}")
                    payload["heaters"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": heater.config.connection_params.get("port"),
                        "error": "read_failed",
                    }, dm.get_heater_binding(did))

    async def read_pumps():
        pumps = dm.get_all_pumps()
        for did, pump in pumps.items():
            if pump.is_connected():
                try:
                    status = await read_coordinator.read(
                        ("pump", did),
                        lambda did=did: dm.read_pump_status(did),
                        PUMP_READ_TIMEOUT,
                    )
                    payload["pumps"][did] = status
                except (asyncio.TimeoutError, TimeoutError):
                    logger.warning(f"Pump {did} read timeout")
                    payload["pumps"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": pump.config.connection_params.get("port"),
                        "error": "read_timeout",
                    }, dm.get_pump_binding(did))
                except Exception as e:
                    logger.warning(f"Pump {did} read failed: {e}")
                    payload["pumps"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": pump.config.connection_params.get("port"),
                        "error": "read_failed",
                    }, dm.get_pump_binding(did))

    async def read_microwaves():
        microwaves = dm.get_all_microwaves()
        for did, microwave in microwaves.items():
            if microwave.is_connected():
                try:
                    status = await read_coordinator.read(
                        ("microwave", did),
                        lambda did=did: dm.read_microwave_data(did),
                        MICROWAVE_READ_TIMEOUT,
                    )
                    payload["microwaves"][did] = status
                except (asyncio.TimeoutError, TimeoutError):
                    logger.warning(f"Microwave {did} read timeout")
                    payload["microwaves"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": microwave.config.connection_params.get("port"),
                        "error": "read_timeout",
                    }, dm.get_microwave_binding(did))
                except Exception as e:
                    logger.warning(f"Microwave {did} read failed: {e}")
                    payload["microwaves"][did] = _with_binding({
                        "device_id": did,
                        "connection_port": microwave.config.connection_params.get("port"),
                        "error": "read_failed",
                    }, dm.get_microwave_binding(did))

    async def read_valves():
        payload["valves"] = {}
        for did, valve in getattr(dm, "valves", {}).items():
            if not valve.is_connected():
                continue
            try:
                payload["valves"][did] = await read_coordinator.read(
                    ("valve", did), lambda did=did: dm.valve_operation(did, "status"), 5.0)
            except Exception as exc:
                # Do not synchronously wait for a reader that timed out holding a lock.
                payload["valves"][did] = {
                    "connected": valve.is_connected(), "read_ok": False,
                    "relay_energized": None, "physical_route_confirmed": False,
                    "connection_port": valve.config.connection_params.get("port"),
                    "error": str(exc),
                }

    async def read_syringe_pumps():
        payload["syringe_pumps"] = {}
        for did, controller in getattr(dm, "syringe_pumps", {}).items():
            try:
                payload["syringe_pumps"][did] = await read_coordinator.read(
                    ("syringe_pump", did), controller.read, 10.0)
            except Exception as exc:
                # A timed-out reader can still hold the controller lock. Do not
                # synchronously wait for that lock on the event loop.
                payload["syringe_pumps"][did] = {
                    "device_id": did, "name": controller.config.name,
                    "connected": controller.device.is_connected(),
                    "configured": bool(controller.config.connection.port or controller.config.connection.binding.serial_number),
                    "capacity_ml": controller.config.capacity_ml,
                    **controller.device.unknown(str(exc)),
                }

    async def read_turntables():
        payload["turntables"] = {}
        for did, controller in getattr(dm, "turntables", {}).items():
            try:
                payload["turntables"][did] = await read_coordinator.read(
                    ("turntable", did), controller.read, 5.0)
            except Exception as exc:
                # A timed-out reader may still own the I/O lock; do not wait on it.
                payload["turntables"][did] = {
                    "device_id": did, "name": controller.config.name,
                    "connected": controller.device.is_connected(),
                    **controller.device.unknown(str(exc)),
                    "stop_confirmed": False, "homed": False,
                    **controller.snapshot_version(),
                }

    await asyncio.gather(
        read_heaters(), read_pumps(), read_microwaves(),
        read_valves(), read_syringe_pumps(),
    )
    # Turntable controls expire from their own read_at, not the frame timestamp.
    # Keep this read last so unrelated slow readers do not age it before delivery.
    await read_turntables()
    payload["sampled_at_ms"] = int(time.time() * 1000)
    return payload


async def data_push_loop(app):
    """后台任务：每秒读取设备数据并推送到所有WebSocket客户端

    Args:
        app: FastAPI应用实例
    """
    dm = app.state.device_manager
    logger.info("WebSocket data push loop started")

    from src.utils.serial_manager import get_serial_manager
    serial_mgr = get_serial_manager()
    read_coordinator = getattr(app.state, "device_read_coordinator", None)
    if read_coordinator is None:
        read_coordinator = DeviceReadCoordinator()

    while True:
        try:
            serial_mgr.feed_watchdog()
            payload = await build_realtime_payload(dm, read_coordinator)

            await manager.broadcast(payload)

            try:
                from src.web.api.experiments import _engines
                for filename, engine in list(_engines.items()):
                    if engine.state.value in ("running", "paused") and engine.exp_logger and engine.exp_logger.active_run:
                        engine.exp_logger.record_sensor_data(payload)
            except Exception as e:
                logger.warning(f"Sensor data recording failed: {e}")

        except Exception as e:
            logger.error(f"Push loop error: {e}")

        await asyncio.sleep(1.0)
