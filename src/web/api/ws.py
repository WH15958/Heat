import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

DEVICE_READ_TIMEOUT = 5.0
PUMP_READ_TIMEOUT = 10.0


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active: list[WebSocket] = []
        self.last_payload: dict = {}

    async def connect(self, ws: WebSocket):
        """接受WebSocket连接

        Args:
            ws: WebSocket连接
        """
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WebSocket client connected, total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        """移除WebSocket连接

        Args:
            ws: WebSocket连接
        """
        if ws in self.active:
            self.active.remove(ws)
        logger.info(f"WebSocket client disconnected, total: {len(self.active)}")

    async def broadcast(self, data: dict):
        """向所有客户端广播数据

        Args:
            data: 要广播的数据
        """
        self.last_payload = data
        disconnected = []
        for ws in self.active:
            try:
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
    return {
        "ws_clients": len(manager.active),
        "heaters_registered": list(heaters.keys()),
        "heaters_connected": [did for did, h in heaters.items() if h.is_connected()],
        "pumps_registered": list(pumps.keys()),
        "pumps_connected": [did for did, p in pumps.items() if p.is_connected()],
        "last_payload_keys": {
            "heaters": list(manager.last_payload.get("heaters", {}).keys()),
            "pumps": list(manager.last_payload.get("pumps", {}).keys()),
        },
    }


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket端点 - 客户端连接后接收实时数据

    Args:
        ws: WebSocket连接
    """
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    finally:
        dm = ws.app.state.device_manager
        for did, pump in dm.get_all_pumps().items():
            if pump.is_connected():
                try:
                    pump.stop_all()
                    logger.info(f"WebSocket断开，自动停止泵 {did}")
                except Exception as e:
                    logger.warning(f"WebSocket断开时停止泵 {did} 失败: {e}")


async def data_push_loop(app):
    """后台任务：每秒读取设备数据并推送到所有WebSocket客户端

    Args:
        app: FastAPI应用实例
    """
    dm = app.state.device_manager
    logger.info("WebSocket data push loop started")

    from src.utils.serial_manager import get_serial_manager
    serial_mgr = get_serial_manager()

    while True:
        try:
            serial_mgr.feed_watchdog()

            payload = {"type": "realtime", "heaters": {}, "pumps": {}}
            loop = asyncio.get_running_loop()

            heaters = dm.get_all_heaters()
            for did, heater in heaters.items():
                if heater.is_connected():
                    try:
                        data = await asyncio.wait_for(
                            loop.run_in_executor(None, heater.read_data),
                            timeout=DEVICE_READ_TIMEOUT,
                        )
                        payload["heaters"][did] = {
                            "pv": data.pv,
                            "sv": data.sv,
                            "mv": data.mv,
                            "alarms": data.alarms,
                            "run_status": data.run_status.name,
                        }
                    except asyncio.TimeoutError:
                        logger.warning(f"Heater {did} read timeout")
                        payload["heaters"][did] = {"error": "read_timeout"}
                    except Exception as e:
                        logger.warning(f"Heater {did} read failed: {e}")
                        payload["heaters"][did] = {"error": "read_failed"}

            pumps = dm.get_all_pumps()
            for did, pump in pumps.items():
                if pump.is_connected():
                    try:
                        status = await asyncio.wait_for(
                            loop.run_in_executor(None, dm.read_pump_status, did),
                            timeout=PUMP_READ_TIMEOUT,
                        )
                        payload["pumps"][did] = status
                    except asyncio.TimeoutError:
                        logger.warning(f"Pump {did} read timeout")
                        payload["pumps"][did] = {"error": "read_timeout"}
                    except Exception as e:
                        logger.warning(f"Pump {did} read failed: {e}")
                        payload["pumps"][did] = {"error": "read_failed"}

            if manager.active:
                await manager.broadcast(payload)

        except Exception as e:
            logger.error(f"Push loop error: {e}")

        await asyncio.sleep(1.0)
