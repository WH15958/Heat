"""Windows desktop window/tray; the backend alone owns all hardware."""
import base64
import ctypes
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from src.desktop.common import InstanceLock, ProcessHandle, URL, VERSION, desktop_home, resource_path
from src.desktop.ipc import PipeServer, request
from src.desktop.migration import import_workspace, is_initialized
from src.desktop.ui import page


logger = logging.getLogger(__name__)


def message_box(text, *, question=False):
    flags = 0x124 if question else 0x10  # Yes/No, question, default No; or error.
    return ctypes.windll.user32.MessageBoxW(None, text, "Heat", flags) == 6


def validate_backend(status, home):
    expected = str((Path(home) / "workspace").resolve())
    if (not isinstance(status, dict) or status.get("version") != VERSION
            or status.get("workspace") != expected or status.get("url") != URL
            or type(status.get("pid")) is not int or status["pid"] <= 0
            or not isinstance(status.get("instance_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", status["instance_id"]) is None
            or status.get("state") not in {"starting", "ready", "stopping", "exit_failed", "stopped"}):
        raise RuntimeError("现有 Heat 后台版本或数据目录不一致，请先正常退出已有程序。")
    return status


def backend_command():
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("HeatBackend.exe"))]
    return [sys.executable, "-m", "src.desktop.backend"]


class Bridge:
    """Expose only the three UI actions, never the host object or filesystem."""
    def __init__(self, desktop):
        self._desktop = desktop

    def choose_source(self):
        return self._desktop.choose_source()

    def start_backend(self):
        return self._desktop.start_backend(present=False)

    def request_exit(self):
        if not self._desktop._trusted_page():
            return {"error": "此操作只在 Heat 桌面页面中可用。"}
        return self._desktop.request_exit()


class Desktop:
    def __init__(self, home):
        self.home = Path(home)
        self.window = None
        self.icon = None
        self.pipe = None
        self.process = None
        self.allow_close = False
        self.setup_visible = not is_initialized(self.home / "workspace")
        self.operation = threading.Lock()
        self.finished = threading.Event()
        self.navigation_ready = threading.Event()
        self.tray_ready = threading.Event()
        self.backend_id = None
        self._offline_url = None

    def show(self, *_):
        self.window.show()
        self.window.restore()

    def show_from_tray(self, *_):
        # Keep the native tray message loop free while WinForms handles Invoke.
        threading.Thread(target=self.show, name="HeatShowWindow", daemon=True).start()

    def exit_from_tray(self, *_):
        threading.Thread(target=self.request_exit, name="HeatExit", daemon=True).start()

    def _show_page(self, title, message, **kwargs):
        self.window.load_html(self._page(title, message, **kwargs))
        self.show()

    def _page(self, title, message, **kwargs):
        content = page(title, message, **kwargs)
        # WebView2 can report NavigateToString as this data URI rather than
        # about:blank. Only the current host-generated document is trusted.
        self._offline_url = "data:text/html;charset=utf-8;base64," + base64.b64encode(
            content.encode("utf-8")).decode("ascii")
        return content

    def _navigation_allowed(self, uri):
        if uri == "about:blank" or uri == self._offline_url:
            return True
        candidate = uri[5:] if uri.startswith("blob:") else uri
        parsed = urlsplit(candidate)
        return (parsed.scheme, parsed.netloc) == ("http", "127.0.0.1:8000")

    def _loaded(self):
        """Restrict native-bridge pages to our offline UI and local backend."""
        if self.navigation_ready.is_set():
            return
        try:
            from System import Action

            def guard(sender, event):
                if not self._navigation_allowed(str(event.Uri)):
                    event.Cancel = True

            def attach():
                self.window.native.webview.CoreWebView2.NavigationStarting += guard

            self.window.native.Invoke(Action(attach))
            self.navigation_ready.set()
        except Exception:
            logger.exception("Unable to restrict desktop navigation")

    def _trusted_page(self):
        current = self.window.get_current_url()
        return current in (None, "about:blank", self._offline_url)

    def choose_source(self):
        import webview

        if not self.setup_visible or not self._trusted_page():
            return {"error": "导入只在首次初始化向导中可用。"}
        if not self.operation.acquire(blocking=False):
            return {"error": "已有操作正在进行，请稍候。"}
        try:
            selected = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:
                return {}
            source = Path(selected[0])
            if not message_box("请确认原 Heat 后端已正常退出。\n将复制所选目录中的配置和实验记录，原文件保持不变。", question=True):
                return {}
            import_workspace(source, self.home / "workspace")
            self.setup_visible = False
            return self._start_backend(present=False)
        except Exception as exc:
            logger.exception("Workspace import/startup failed")
            if is_initialized(self.home / "workspace"):
                self.setup_visible = False
                return {"error": str(exc), "page": self._error_page(str(exc))}
            return {"error": str(exc)}
        finally:
            self.operation.release()

    def start_backend(self, *, present=True):
        if self.setup_visible or not self._trusted_page():
            return {"error": "请先完成数据导入。"}
        if not self.operation.acquire(blocking=False):
            return {"error": "已有操作正在进行，请稍候。"}
        try:
            return self._start_backend(present=present)
        except Exception as exc:
            logger.exception("Backend startup failed")
            return {"error": str(exc)}
        finally:
            self.operation.release()

    def _show_error(self, detail):
        content = self._error_page(detail)
        self._show_page(**content)

    @staticmethod
    def _error_page(detail):
        return dict(title="Heat 后台未就绪", message=detail + "\n请查看桌面日志，确认设备现场状态后再重试。",
                    action="start_backend", label="重新连接／启动后台")

    def _start_backend(self, *, present=True):
        try:
            status = validate_backend(request(self.home, "backend", "status"), self.home)
        except (FileNotFoundError, ConnectionRefusedError):
            status = None
        if status is None:
            for address in ("127.0.0.1", "::1"):
                try:
                    with socket.create_connection((address, 8000), timeout=0.3):
                        raise RuntimeError("端口 8000 已占用。请先正常退出原 Web 后端或其他占用程序。")
                except OSError:
                    pass
            environment = os.environ.copy()
            environment["HEAT_DATA_DIR"] = str((self.home / "workspace").resolve())
            environment["HEAT_DESKTOP_MODE"] = "1"
            self.process = subprocess.Popen(
                backend_command(), env=environment, cwd=str(resource_path(".")),
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True,
            )
        if present:
            self._show_page("正在连接 Heat", "正在等待本机后台就绪。设备不会因打开界面而启动。")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                status = validate_backend(request(self.home, "backend", "status"), self.home)
                if status["state"] in {"ready", "exit_failed", "stopped"}:
                    self.backend_id = status["instance_id"]
                    if status["state"] == "stopped":
                        content = dict(title="Heat 已完成停机", message="后台正在等待退出确认。请退出后重新打开 Heat。",
                                       action="request_exit", label="退出 Heat")
                        if present:
                            self._show_page(**content)
                        return {"page": content}
                    if present:
                        self.window.load_url(URL)
                    if status["state"] == "exit_failed":
                        message_box("上次退出未完成，后台已保留。请确认停止与保存结果后，通过托盘重试退出。")
                    return {"url": URL}
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("Heat 后台启动失败，请查看桌面数据目录 desktop/backend.log。")
            self.finished.wait(0.2)
        raise TimeoutError("后台仍未就绪；不会自动结束它。请检查 desktop/backend.log 后明确重试。")

    def request_exit(self, *_):
        if not self.operation.acquire(blocking=False):
            logger.info("Desktop exit skipped: another operation is in progress")
            return {"error": "已有启动或退出操作正在进行，请稍候。"}
        handle = None
        try:
            logger.info("Desktop exit requested; waiting for confirmation")
            if not message_box("退出 Heat 将停止实验并确认设备清理和记录保存。\n仅收起窗口请点击右上角关闭。是否退出？", question=True):
                logger.info("Desktop exit cancelled")
                return {}
            logger.info("Desktop exit confirmed; checking backend status")
            try:
                status = validate_backend(request(self.home, "backend", "status"), self.home)
            except (FileNotFoundError, ConnectionRefusedError):
                probe = InstanceLock(self.home, "backend")
                if not probe.acquire():
                    raise RuntimeError("后台仍在运行但控制通道不可用，不能确认退出；请检查桌面日志。")
                probe.close()
                if self.process is not None and self.process.poll() is None:
                    raise RuntimeError("后台进程仍在启动或退出，窗口将保留。")
                self._finish()
                return {}
            instance_id = status["instance_id"]
            if self.backend_id is not None and self.backend_id != instance_id:
                raise RuntimeError("后台身份已变化，退出请求已拒绝；请明确重新连接。")
            handle = ProcessHandle(status["pid"])
            logger.info("Backend shutdown requested")
            status = validate_backend(request(self.home, "backend", "shutdown", instance_id=instance_id), self.home)
            logger.info("Restoring desktop window while shutdown proceeds")
            self.show()
            deadline = time.monotonic() + 40
            previous_state = None
            while time.monotonic() < deadline:
                status = validate_backend(request(self.home, "backend", "status"), self.home)
                if status["instance_id"] != instance_id:
                    raise RuntimeError("后台身份已变化，退出请求已拒绝。")
                if status["state"] != previous_state:
                    logger.info("Backend shutdown state: %s", status["state"])
                    previous_state = status["state"]
                if status["state"] == "stopped":
                    logger.info("Backend cleanup confirmed; committing exit")
                    request(self.home, "backend", "commit_exit", instance_id=instance_id)
                    if not handle.wait(8):
                        raise TimeoutError("停机已确认，但后台进程尚未结束。窗口将保留，请稍候重试退出。")
                    logger.info("Backend process exited")
                    self._finish()
                    return {}
                if status["state"] == "exit_failed":
                    raise RuntimeError("\n".join(status["errors"]) or "退出未完成，后台已保留。")
                self.finished.wait(0.2)
            raise TimeoutError("停机或保存仍未完成，后台已保留。请检查设备状态后通过托盘重试退出。")
        except Exception as exc:
            logger.exception("Explicit desktop exit incomplete")
            message_box(str(exc))
            return {"error": str(exc)}
        finally:
            if handle:
                handle.close()
            self.operation.release()

    def _finish(self):
        self.allow_close = True
        self.finished.set()
        if self.icon:
            logger.info("Stopping desktop tray")
            self.icon.stop()
        logger.info("Destroying desktop window")
        self.window.destroy()
        logger.info("Desktop exit complete")

    def closing(self):
        if self.allow_close:
            return True
        if not self.tray_ready.is_set():
            message_box("系统托盘尚未就绪，窗口将保留。请通过窗口中的退出操作处理。")
            return False
        self.window.hide()
        return False

    def _watch(self):
        # This watches only our local process/IPC, never reads a device.
        while not self.finished.wait(1):
            if not self.backend_id or self.operation.locked():
                continue
            try:
                status = validate_backend(request(self.home, "backend", "status"), self.home)
                if status["instance_id"] != self.backend_id:
                    raise RuntimeError("后台身份已变化，请明确重新连接。")
            except (OSError, RuntimeError, TimeoutError) as exc:
                self.backend_id = None
                self._show_error("后台连接已断开。不会自动重启或恢复实验。\n" + str(exc))

    def _boot(self):
        try:
            if not self.navigation_ready.wait(20):
                raise RuntimeError("WebView2 未能初始化，请检查运行时和桌面日志。")
            from PIL import Image
            import pystray

            icon_path = resource_path("desktop/heat.ico")
            if not icon_path.exists():
                icon_path = resource_path("output/desktop/assets/heat.ico")
            image = Image.open(icon_path)
            self.icon = pystray.Icon("Heat", image, "Heat", menu=pystray.Menu(
                pystray.MenuItem("显示窗口", self.show_from_tray, default=True),
                pystray.MenuItem("退出 Heat", self.exit_from_tray),
            ))

            def tray_setup(icon):
                icon.visible = True
                self.tray_ready.set()

            threading.Thread(target=lambda: self.icon.run(setup=tray_setup), daemon=True).start()
            if not self.tray_ready.wait(10):
                raise RuntimeError("无法创建系统托盘，Heat 未启动后台。")
            threading.Thread(target=self._watch, daemon=True).start()
            if not self.setup_visible:
                result = self.start_backend()
                if result.get("error"):
                    self._show_error(result["error"])
        except Exception as exc:
            logger.exception("Desktop initialization failed")
            message_box(str(exc))
            # No backend has been started when tray/runtime initialization fails.
            self._finish()

    def run(self):
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        content = self._page("导入现有 Heat 项目", "请先正常退出原 Heat 后端，再选择原项目目录。\n配置、实验文件和历史将复制到独立数据目录，原文件保留。",
                       action="choose_source", label="选择项目目录并导入")
        self.window = webview.create_window("Heat", html=content, js_api=Bridge(self),
                                            width=1400, height=900, min_size=(1000, 700))
        self.window.events.loaded += self._loaded
        self.window.events.closing += self.closing
        self.pipe = PipeServer(self.home, "shell", lambda cmd: self._activate(cmd))
        self.pipe.start()
        try:
            webview.start(self._boot, gui="edgechromium", private_mode=False,
                          storage_path=str(self.home / "webview"), debug=False)
        finally:
            self.finished.set()
            if self.icon:
                self.icon.stop()
            self.pipe.close()

    def _activate(self, command):
        if command != "show":
            raise ValueError("不支持的窗口命令。")
        self.show()
        return {"version": VERSION}


def main():
    if sys.platform != "win32":
        raise RuntimeError("Heat 桌面应用仅支持 Windows。")
    home = desktop_home()
    lock = InstanceLock(home, "shell")
    if not lock.acquire():
        try:
            request(home, "shell", "show")
        except Exception:
            message_box("Heat 窗口正在启动或位于其他登录会话，请检查已有窗口。")
        return 0
    logfile = (home / "desktop" / "desktop.log").open("a", encoding="utf-8", buffering=1)
    original_streams = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = logfile
    logging.basicConfig(level=logging.INFO, stream=logfile,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Starting Heat desktop %s", VERSION)
    try:
        Desktop(home).run()
        return 0
    except Exception as exc:
        logger.exception("Desktop host failed")
        message_box(str(exc))
        return 1
    finally:
        lock.close()
        sys.stdout, sys.stderr = original_streams
        logfile.close()


if __name__ == "__main__":
    sys.exit(main())
