import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.utils.logger import get_logger, setup_logging
from src.utils.serial_binding import resolve_connection
from src.web.api.campaigns import router as campaigns_router
from src.web.api.devices import router as devices_router
from src.web.api.experiments import router as experiments_router
from src.web.api.ws import router as ws_router, data_push_loop
from src.web.device_manager import DeviceManager

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def _resolve_registered_port(device_id: str, connection) -> dict:
    resolution = resolve_connection(connection)
    binding_info = {
        "device_id": device_id,
        "_connection_config": connection,
        "resolved_port": resolution.resolved_port,
        "connection_binding_mode": resolution.connection_binding_mode,
        "binding_label": resolution.binding_label,
        "binding_resolved": resolution.binding_resolved,
        "binding_match_count": resolution.binding_match_count,
        "binding_error": resolution.binding_error,
        "binding_candidates": resolution.binding_candidates,
    }
    if resolution.binding_error == "fallback_to_port":
        logger.warning(
            "Device %s fingerprint binding fallback to configured port %s",
            device_id,
            resolution.resolved_port,
        )
    elif not resolution.binding_resolved:
        logger.warning(
            "Device %s binding unresolved: %s (%s)",
            device_id,
            resolution.binding_label,
            resolution.binding_error,
        )
    return binding_info


def create_device_manager() -> DeviceManager:
    """从配置文件创建设备管理器（使用 ConfigManager 做配置验证）

    Returns:
        DeviceManager: 已注册设备的设备管理器
    """
    from src.utils.config import ConfigManager

    dm = DeviceManager()
    config_mgr = ConfigManager()
    config = config_mgr.load()

    for h_cfg in config.heaters:
        if not h_cfg.enabled:
            continue
        binding_info = _resolve_registered_port(h_cfg.device_id, h_cfg.connection)
        dm.add_heater(
            device_id=h_cfg.device_id,
            port=binding_info["resolved_port"],
            baudrate=h_cfg.connection.baudrate,
            address=h_cfg.connection.address,
            parity=h_cfg.connection.parity,
            timeout=h_cfg.connection.timeout,
            decimal_places=h_cfg.decimal_places,
            temperature_unit=h_cfg.temperature_unit,
            max_temperature=h_cfg.max_temperature,
            min_temperature=h_cfg.min_temperature,
            safety_limit=h_cfg.safety_limit,
            poll_interval=h_cfg.poll_interval,
            retry_count=h_cfg.retry_count,
            retry_delay=h_cfg.retry_delay,
            binding_info=binding_info,
        )
        logger.info(f"Registered heater: {h_cfg.device_id}")

    for p_cfg in config.pumps:
        if not p_cfg.enabled:
            continue
        binding_info = _resolve_registered_port(p_cfg.device_id, p_cfg.connection)
        channels = None
        if p_cfg.channels:
            channels = [
                {
                    "channel": ch.channel,
                    "enabled": ch.enabled,
                    "pump_head": ch.pump_head,
                    "tube_model": ch.tube_model,
                    "suck_back_angle": ch.suck_back_angle,
                    "max_flow_rate": ch.max_flow_rate,
                }
                for ch in p_cfg.channels
            ]
        dm.add_pump(
            device_id=p_cfg.device_id,
            port=binding_info["resolved_port"],
            baudrate=p_cfg.connection.baudrate,
            slave_address=p_cfg.slave_address,
            parity=p_cfg.connection.parity,
            timeout=p_cfg.timeout,
            poll_interval=p_cfg.poll_interval,
            retry_count=p_cfg.retry_count,
            retry_delay=p_cfg.retry_delay,
            stopbits=p_cfg.connection.stopbits,
            bytesize=p_cfg.connection.bytesize,
            channels=channels,
            binding_info=binding_info,
        )
        logger.info(f"Registered pump: {p_cfg.device_id}")

    for m_cfg in config.microwaves:
        if not m_cfg.enabled:
            continue
        binding_info = _resolve_registered_port(m_cfg.device_id, m_cfg.connection)
        dm.add_microwave(
            device_id=m_cfg.device_id,
            port=binding_info["resolved_port"],
            baudrate=m_cfg.connection.baudrate,
            slave_address=m_cfg.slave_address,
            parity=m_cfg.connection.parity,
            timeout=m_cfg.connection.timeout,
            max_temperature=m_cfg.max_temperature,
            max_power_percent=m_cfg.max_power_percent,
            poll_interval=m_cfg.poll_interval,
            retry_count=m_cfg.retry_count,
            retry_delay=m_cfg.retry_delay,
            allow_experiment_control=m_cfg.allow_experiment_control,
            allow_real_hardware_writes=m_cfg.allow_real_hardware_writes,
            enable_control_writes=m_cfg.enable_control_writes,
            binding_info=binding_info,
        )
        logger.info(f"Registered microwave: {m_cfg.device_id}")
    return dm


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    Args:
        app: FastAPI应用实例
    """
    logger.info("Starting Heat Web Server...")
    setup_logging(level="INFO", console_output=True, file_output=True)
    app.state.device_manager = create_device_manager()
    push_task = asyncio.create_task(data_push_loop(app))
    yield
    logger.info("Shutting down...")
    push_task.cancel()
    try:
        await push_task
    except asyncio.CancelledError:
        pass
    if not app.state.device_manager.cleanup():
        logger.error("One or more devices failed to stop or disconnect during shutdown")


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
app.include_router(campaigns_router, prefix="/api")
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
        if path == "api" or path.startswith("api/") or path == "ws" or path.startswith("ws/"):
            raise HTTPException(status_code=404, detail="Not Found")

        static_root = STATIC_DIR.resolve()
        file_path = (static_root / path).resolve()
        try:
            file_path.relative_to(static_root)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not Found")

        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(static_root / "index.html"))

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))
