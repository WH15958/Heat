import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.utils.logger import get_logger
from src.web.api.devices import router as devices_router
from src.web.api.experiments import router as experiments_router
from src.web.api.ws import router as ws_router, data_push_loop
from src.web.device_manager import DeviceManager

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_device_manager() -> DeviceManager:
    """从配置文件创建设备管理器

    Returns:
        DeviceManager: 已注册设备的设备管理器
    """
    dm = DeviceManager()
    try:
        import yaml

        config_path = Path("config/system_config.yaml")
        if not config_path.exists():
            logger.warning("Config file not found, starting with empty devices")
            return dm

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for h_cfg in data.get("heaters", []):
            if not h_cfg.get("enabled", True):
                continue
            conn = h_cfg.get("connection", {})
            dm.add_heater(
                device_id=h_cfg["device_id"],
                port=conn.get("port", "COM1"),
                baudrate=conn.get("baudrate", 9600),
                address=conn.get("address", 1),
                decimal_places=h_cfg.get("decimal_places", 1),
            )
            logger.info(f"Registered heater: {h_cfg['device_id']}")

        for p_cfg in data.get("pumps", []):
            if not p_cfg.get("enabled", True):
                continue
            conn = p_cfg.get("connection", {})
            dm.add_pump(
                device_id=p_cfg["device_id"],
                port=conn.get("port", "COM1"),
                baudrate=conn.get("baudrate", 9600),
                slave_address=p_cfg.get("slave_address", 1),
            )
            logger.info(f"Registered pump: {p_cfg['device_id']}")

    except Exception as e:
        logger.warning(f"Failed to load config, starting with empty devices: {e}")
    return dm


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    Args:
        app: FastAPI应用实例
    """
    logger.info("Starting Heat Web Server...")
    app.state.device_manager = create_device_manager()
    push_task = asyncio.create_task(data_push_loop(app))
    yield
    logger.info("Shutting down...")
    push_task.cancel()
    try:
        await push_task
    except asyncio.CancelledError:
        pass
    app.state.device_manager.cleanup()


app = FastAPI(
    title="Heat - 温控与流体输送控制系统",
    description="Web远程控制 + 实时数据可视化",
    version="2.2",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(devices_router, prefix="/api")
app.include_router(experiments_router, prefix="/api")
app.include_router(ws_router)

if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(str(STATIC_DIR / "favicon.svg"))

    @app.get("/icons.svg")
    async def icons():
        return FileResponse(str(STATIC_DIR / "icons.svg"))

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        """SPA fallback: 所有非API/非静态资源路径返回index.html

        Args:
            request: 请求对象
            path: 请求路径

        Returns:
            FileResponse: index.html文件
        """
        file_path = STATIC_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))
