"""Explicit, retryable desktop shutdown; window and WebSocket events never call it."""
import asyncio
import json
import re

from starlette.responses import JSONResponse

from src.utils.logger import get_logger
from src.web.api import experiments

logger = get_logger(__name__)

_STOP_PATH = re.compile(
    r"/api/(?:heater|pump|microwave|experiments|guided|microwave-program)/[^/]+/stop"
)
_RECOVERY_PATH = re.compile(
    r"/api/(?:guided|microwave-program)/[^/]+/acknowledge-interrupted"
    r"|/api/experiments/recovery/[^/]+/acknowledge"
)
_STOP_COMMAND = re.compile(r"/api/(?:syringe_pump|turntable)/[^/]+/command")


class DesktopShutdownMiddleware:
    """Keep reads and explicit safety actions available after an exit request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        app = scope.get("app")
        coordinator = getattr(app.state, "desktop_shutdown", None) if app is not None else None
        if (scope["type"] != "http" or coordinator is None or not coordinator.exiting
                or scope["method"] in {"GET", "HEAD", "OPTIONS"}):
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        allowed = scope["method"] == "POST" and (
            path == "/api/emergency_stop" or _STOP_PATH.fullmatch(path)
            or _RECOVERY_PATH.fullmatch(path)
        )
        if scope["method"] == "POST" and _STOP_COMMAND.fullmatch(path):
            messages, body = [], bytearray()
            while True:
                message = await receive()
                messages.append(message)
                if message["type"] != "http.request":
                    break
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            try:
                command = json.loads(body)
                allowed = isinstance(command, dict) and command.get("action") == "stop"
            except (ValueError, UnicodeError):
                allowed = False
            original_receive = receive

            async def replay():
                return messages.pop(0) if messages else await original_receive()

            receive = replay
        if not allowed:
            response = JSONResponse(
                {"detail": "Heat 正在退出或等待停机确认；仅可读取、停止、急停和确认恢复"},
                status_code=409,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class DesktopShutdown:
    def __init__(self, app, timeout=30.0):
        self.app = app
        self.timeout = timeout
        self.exiting = False
        self.succeeded = False
        self.errors = []
        self._task = None
        experiments._desktop_exiting = False

    async def shutdown(self):
        """Await an attempt without cancelling in-flight synchronous device work."""
        if self.succeeded:
            return {"success": True, "errors": []}
        if not self.exiting:
            self.exiting = True
            experiments._desktop_exiting = True
            experiments._stop_generation += 1
            # Cancel manual writes that already passed HTTP validation. Keep this
            # manager fence raised after failure; STOP commands remain permitted.
            self.app.state.device_manager._begin_global_stop()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._attempt())
        done, _ = await asyncio.wait({self._task}, timeout=self.timeout)
        if not done:
            return {"success": False, "errors": [
                "停机或保存仍在进行，后台已保留；请检查设备状态后重试退出（不会强制结束）"
            ]}
        return self._task.result()

    async def _attempt(self):
        errors = []
        # Publish stop intent before waiting for a pending registration/manual
        # write. The generation fence cancels starts queued on this same lock.
        for name, engine in list(experiments._engines.items()):
            try:
                engine.request_stop()
            except Exception as exc:
                errors.append(f"{name}: 停止请求失败: {exc}")
        async with experiments._source_lock:
            engines = list(experiments._engines.items())
            for name, engine in engines:
                try:
                    engine.request_stop()
                except Exception as exc:
                    errors.append(f"{name}: 停止请求失败: {exc}")
        # Do not hold _source_lock or _stopping during device waits: explicit
        # STOP and recovery acknowledgement must remain usable after failure.
        results = await asyncio.gather(
            *(self._stop_engine(name, engine) for name, engine in engines)
        )
        for result in results:
            errors.extend(result)
        try:
            cleanup = self.app.state.device_manager.cleanup
            # A runner still owns its failed cleanup. Stop other devices too,
            # but retain connections until an explicit retry clears that owner.
            if errors:
                cleaned = await asyncio.to_thread(cleanup, disconnect=False)
            else:
                cleaned = await asyncio.to_thread(cleanup)
            if cleaned is not True:
                errors.append("设备停机或断开未确认，连接已保留供重试")
        except Exception as exc:
            errors.append(f"设备清理失败: {exc}")
        self.errors = errors
        self.succeeded = not errors
        if errors:
            logger.error("Desktop shutdown incomplete: %s", "; ".join(errors))
        return {"success": self.succeeded, "errors": list(errors)}

    @staticmethod
    async def _stop_engine(name, engine):
        errors = []
        try:
            if await engine.stop() is not True:
                errors.append(f"{name}: 实验、批次或托管程序停止未确认")
        except Exception as exc:
            errors.append(f"{name}: 停止失败: {exc}")
        exp_logger = getattr(engine, "exp_logger", None)
        run = getattr(exp_logger, "active_run", None)
        if run is not None and getattr(run, "persistence_status", None) in {"error", "pending"}:
            retry = getattr(engine, "retry_persistence", None)
            if not callable(retry):
                retry = getattr(exp_logger, "retry_persistence", None)
            if callable(retry):
                try:
                    await asyncio.to_thread(retry)
                except Exception as exc:
                    errors.append(f"{name}: 运行记录保存重试失败: {exc}")
        record = getattr(engine, "record", None)
        if isinstance(record, dict) and record.get("persistence_status") == "error":
            errors.append(f"{name}: 运行恢复记录保存失败，请检查存储并确认恢复")
        if run is not None and getattr(run, "persistence_status", None) in {"error", "pending"}:
            errors.append(f"{name}: 运行日志或样品记录保存未确认，请检查存储")
        return errors
