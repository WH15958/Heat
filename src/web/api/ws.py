import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active: list[WebSocket] = []

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
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()


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


async def data_push_loop(app):
    """后台任务：每秒读取设备数据并推送到所有WebSocket客户端

    Args:
        app: FastAPI应用实例
    """
    dm = app.state.device_manager
    logger.info("WebSocket data push loop started")

    while True:
        try:
            payload = {"type": "realtime", "heaters": {}, "pumps": {}}
            loop = asyncio.get_event_loop()

            for did, heater in dm._heaters.items():
                if heater.is_connected():
                    try:
                        data = await loop.run_in_executor(None, heater.read_data)
                        payload["heaters"][did] = {
                            "pv": data.pv,
                            "sv": data.sv,
                            "mv": data.mv,
                            "alarms": data.alarms,
                            "run_status": data.run_status.name,
                        }
                    except Exception:
                        payload["heaters"][did] = {"error": "read_failed"}

            for did, pump in dm._pumps.items():
                if pump.is_connected():
                    try:
                        status = await loop.run_in_executor(
                            None, dm.read_pump_status, did
                        )
                        payload["pumps"][did] = status
                    except Exception:
                        payload["pumps"][did] = {"error": "read_failed"}

            if manager.active:
                await manager.broadcast(payload)

        except Exception as e:
            logger.error(f"Push loop error: {e}")

        await asyncio.sleep(1.0)
