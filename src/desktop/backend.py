"""Independent local backend. UI loss never starts/stops devices."""
import asyncio
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading

from src.desktop.common import InstanceLock, URL, VERSION, desktop_home
from src.desktop.ipc import PipeServer
from src.desktop.migration import is_initialized


logger = logging.getLogger(__name__)


def require_port_available():
    # Windows may permit an exclusive loopback bind alongside an existing
    # wildcard listener. A successful bind alone does not prove port ownership.
    for address in ("127.0.0.1", "::1"):
        try:
            connection = socket.create_connection((address, 8000), timeout=0.25)
        except OSError:
            continue
        connection.close()
        raise RuntimeError("端口 8000 已占用。请先正常退出原 Web 后端或其他占用程序。")


async def serve(home):
    require_port_available()
    import uvicorn
    from src.web.app import app

    state = {"pid": os.getpid(), "version": VERSION, "url": URL,
             "workspace": str((home / "workspace").resolve()),
             "instance_id": secrets.token_hex(16), "state": "starting", "errors": []}
    guard = threading.Lock()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000,
                                          workers=1, log_config=None))
    shutdown_task = None
    loop = asyncio.get_running_loop()

    async def shutdown():
        with guard:
            state.update(state="stopping", errors=[])
        try:
            result = await app.state.desktop_shutdown.shutdown()
        except Exception as exc:
            logger.exception("Desktop shutdown failed")
            result = {"success": False, "errors": [str(exc)]}
        with guard:
            state.update(state="stopped" if result["success"] else "exit_failed",
                         errors=result["errors"])
    def handle(command, instance_id):
        nonlocal shutdown_task
        if command != "status" and instance_id != state["instance_id"]:
            raise RuntimeError("Heat 后台身份已变化，退出请求已拒绝。")
        if command == "shutdown":
            # Schedule once. Timeouts/repeated clicks cannot start concurrent cleanups.
            with guard:
                if state["state"] not in ("ready", "exit_failed"):
                    return dict(state)
                state["state"] = "stopping"
                shutdown_task = asyncio.run_coroutine_threadsafe(shutdown(), loop)
        elif command == "commit_exit":
            with guard:
                if state["state"] != "stopped":
                    raise RuntimeError("后台尚未完成停机与保存，不能退出。")
            loop.call_soon_threadsafe(lambda: loop.call_later(0.2, setattr, server, "should_exit", True))
        elif command != "status":
            raise ValueError("不支持的后台命令。")
        with guard:
            return dict(state)

    control = PipeServer(home, "backend", handle)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", 8000))
        require_port_available()
        sock.listen(2048)
        sock.setblocking(False)
        control.start()
        identity = home / "desktop" / "backend.json"
        identity.write_text(json.dumps(state), encoding="utf-8")

        async def ready():
            while not server.started:
                await asyncio.sleep(0.05)
            with guard:
                state["state"] = "ready"

        readiness = asyncio.create_task(ready())
        try:
            await server.serve(sockets=[sock])
        finally:
            readiness.cancel()
            await asyncio.gather(readiness, return_exceptions=True)
            identity.unlink(missing_ok=True)
    finally:
        sock.close()
        control.close()


def main():
    if sys.platform != "win32":
        raise RuntimeError("Heat 桌面后台仅支持 Windows。")
    home = desktop_home()
    workspace = home / "workspace"
    if not is_initialized(workspace):
        raise RuntimeError("请先通过 Heat 桌面导入向导初始化数据。")
    os.environ["HEAT_DATA_DIR"] = str(workspace.resolve())
    os.environ["HEAT_DESKTOP_MODE"] = "1"
    lock = InstanceLock(home, "backend")
    if not lock.acquire():
        return 2
    log = (home / "desktop" / "backend.log").open("a", encoding="utf-8", buffering=1)
    original_streams = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = log
    logging.basicConfig(level=logging.INFO, stream=log)
    try:
        asyncio.run(serve(home))
        return 0
    except Exception:
        logger.exception("Heat backend startup failed")
        return 1
    finally:
        lock.close()
        sys.stdout, sys.stderr = original_streams
        log.close()


if __name__ == "__main__":
    sys.exit(main())
