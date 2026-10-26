"""Shared identity and per-user storage for the desktop host."""
import ctypes
import hashlib
import os
from pathlib import Path
import secrets
import sys


VERSION = "0.1.4"
URL = "http://127.0.0.1:8000"
SHELL_MUTEX = "HeatDesktopShell"
BACKEND_MUTEX = "HeatDesktopBackend"


def desktop_home():
    return Path(os.environ["LOCALAPPDATA"]) / "Heat"


def resource_path(relative):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / relative


def pipe_address(home, role):
    identity = hashlib.sha256(str(Path(home).resolve()).casefold().encode()).hexdigest()[:24]
    return rf"\\.\pipe\Heat-{identity}-{role}"


def ipc_token(home):
    """Keep the local authentication secret in the user's private profile."""
    directory = Path(home) / "desktop"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ipc.key"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = path.read_bytes()
        if len(token) != 32:
            raise RuntimeError("桌面身份文件损坏，请检查 Heat 数据目录。")
        return token.hex()
    with os.fdopen(descriptor, "wb") as stream:
        token = secrets.token_bytes(32)
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())
    return token.hex()


class InstanceLock:
    """Installer-visible mutex plus a data-directory lock across login sessions."""
    def __init__(self, home, role):
        self.home = Path(home)
        self.role = role
        self.handle = None
        self.file = None

    def acquire(self):
        import msvcrt

        self.home.joinpath("desktop").mkdir(parents=True, exist_ok=True)
        stream = (self.home / "desktop" / (self.role + ".lock")).open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            return False
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = SHELL_MUTEX if self.role == "shell" else BACKEND_MUTEX
        handle = kernel.CreateMutexW(None, False, mutex)
        if not handle:
            stream.close()
            raise ctypes.WinError(ctypes.get_last_error())
        self.file, self.handle = stream, handle
        return True

    def close(self):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.handle)
            self.handle = None
        if self.file:
            self.file.close()
            self.file = None


class ProcessHandle:
    """Hold the exact backend process, even if its PID is subsequently reused."""
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.OpenProcess(0x100000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, timeout):
        return self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000)) == 0

    def close(self):
        self.kernel.CloseHandle(self.handle)
