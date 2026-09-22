"""Windows launcher: validate locally, then run the normal server in foreground."""

import contextlib
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser


PROJECT_DIR = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000"
STARTUP_TIMEOUT = 30.0
DEPENDENCIES = ("serial", "fastapi", "uvicorn", "websockets", "matplotlib", "yaml", "pydantic")


class Tee(io.TextIOBase):
    """Retain early import errors as well as the normal console output."""

    def __init__(self, console, logfile):
        self.console = console
        self.logfile = logfile

    def write(self, text):
        self.console.write(text)
        if not self.logfile.closed:
            self.logfile.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        if not self.logfile.closed:
            self.logfile.flush()


def check_environment(project_dir):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required.")
    if not (project_dir / "run_server.py").is_file():
        raise RuntimeError("run_server.py is missing. Restore the complete project.")
    if not (project_dir / "src/web/static/index.html").is_file():
        raise RuntimeError(
            "Frontend build is missing. Run: npm --prefix frontend ci, then "
            "npm --prefix frontend run build"
        )
    for module in DEPENDENCIES:
        try:
            importlib.import_module(module)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot import {module}: {exc}. Install dependencies using "
                f'"{sys.executable}" -m pip install -r requirements.txt'
            ) from exc


def heat_is_ready(url=URL, timeout=1.0):
    # Probe only read-only web resources; bypass proxies for the local server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/openapi.json", timeout=timeout) as response:
            schema = json.load(response)
        if not isinstance(schema, dict) or not isinstance(schema.get("info"), dict):
            return False
        if schema["info"].get("title") != "Heat - 温控与流体输送控制系统":
            return False
        if "/api/devices" not in schema.get("paths", {}):
            return False
        with opener.open(url + "/", timeout=timeout) as response:
            return response.status == 200 and b'id="app"' in response.read(1024 * 1024)
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return False


def open_browser():
    try:
        if not webbrowser.open(URL):
            print(f"[INFO] Open {URL} in your browser.")
    except Exception as exc:
        print(f"[INFO] Browser could not open: {exc}. Open {URL} manually.")


def wait_for_ready(stopped, timeout=STARTUP_TIMEOUT):
    deadline = time.monotonic() + timeout
    while not stopped.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("[WARNING] Startup check timed out. Browser was not opened.")
            print("The server remains in this window. Inspect its logs; use Ctrl+C to exit.")
            return
        # Two HTTP requests per probe, each with a bounded timeout.
        if heat_is_ready(timeout=min(1.0, remaining / 2)):
            if not stopped.is_set():
                print(f"[Heat] Ready: {URL}")
                open_browser()
            return
        stopped.wait(min(0.25, max(0, deadline - time.monotonic())))


def acquire_lock(project_dir):
    import msvcrt

    lock_dir = project_dir / "output"
    lock_dir.mkdir(exist_ok=True)
    lock = (lock_dir / "heat-launcher.lock").open("a+b")
    if lock.seek(0, os.SEEK_END) == 0:
        lock.write(b"\0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return None
    return lock  # Closing the handle releases the lock, including on process exit.


def launch(project_dir):
    lock = acquire_lock(project_dir)
    if lock is None:
        if heat_is_ready():
            open_browser()
        else:
            print("[INFO] Heat launcher is already running or starting. Check its window.")
        return 0
    with lock:
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                occupied = True
        except OSError:
            occupied = False
        if occupied:
            if not heat_is_ready():
                raise RuntimeError("Port 8000 is occupied, but a ready Heat web UI was not found.")
            open_browser()
            return 0
        check_environment(project_dir)
        print("[Heat] Starting. Keep this window open; press Ctrl+C for normal shutdown.")
        print("Closing the browser does not stop Heat or its devices.")
        stopped = threading.Event()
        watcher = threading.Thread(target=wait_for_ready, args=(stopped,), daemon=True)
        watcher.start()
        try:
            runpy.run_path(str(project_dir / "run_server.py"), run_name="__main__")
        finally:
            stopped.set()
            watcher.join()
    return 0


def main():
    os.chdir(PROJECT_DIR)
    sys.path.insert(0, str(PROJECT_DIR))
    log_dir = PROJECT_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "launcher.log"
    with log_path.open("a", encoding="utf-8", buffering=1) as logfile:
        with contextlib.redirect_stdout(Tee(sys.stdout, logfile)), contextlib.redirect_stderr(Tee(sys.stderr, logfile)):
            print(f"\n[Heat] {time.strftime('%Y-%m-%d %H:%M:%S')} Python: {sys.executable}")
            print(f"[Heat] Launcher log: {log_path}")
            try:
                return launch(PROJECT_DIR)
            except KeyboardInterrupt:
                return 0
            except Exception:
                traceback.print_exc()
                return 1


if __name__ == "__main__":
    sys.exit(main())
