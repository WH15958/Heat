"""Synchronous CL-01A transport; action supervision belongs to the Web layer."""
from datetime import datetime, timezone

import serial

from src.devices.turntable_commands import TurntableCommand
from src.protocols.turntable import INPUT_BITS, TurntableProtocol
from src.utils.logger import get_logger
from src.utils.serial_manager import get_serial_manager

logger = get_logger(__name__)


class TurntableDevice:
    def __init__(self, config, serial_factory=None):
        self.config = config
        self.serial_factory = serial_factory or serial.Serial
        self.handle = self.protocol = None
        self._port = None
        self._handle_registered = False
        self._connect_failed = False
        self.connection_error = None
        self.last_command_error = None
        self.snapshot = self.unknown()

    def is_connected(self):
        # A failed connection may retain an open handle solely for cleanup retry.
        return (not self._connect_failed and self.handle is not None
                and self.handle.is_open and self.protocol is not None)

    @staticmethod
    def unknown(error=None):
        return {"read_ok": False, "read_at": None, "position": None,
                "speed_raw": None, "input_raw": None,
                "inputs": {name: None for name in INPUT_BITS},
                "work_state": None, "state_name": "unknown", "busy": None,
                "read_error": error}

    def connect(self, port):
        if self._connect_failed or (not self.is_connected() and self._port is not None):
            if not self.disconnect():
                raise RuntimeError("串口清理未完成，不能重新连接")
        if self.is_connected():
            return True
        if not port:
            raise ValueError("串口待配置")
        manager = get_serial_manager()
        if not manager.acquire_port(port, force=False):
            self.connection_error = "串口被占用"
            self.snapshot = self.unknown(self.connection_error)
            raise RuntimeError("串口被占用")
        self._port = port
        phase = "prepare"
        try:
            connection = self.config.connection
            self.handle = self.serial_factory(
                port=None, baudrate=connection.baudrate, bytesize=8, parity="N", stopbits=1,
                timeout=min(0.05, connection.timeout), write_timeout=min(1.0, connection.timeout),
                xonxoff=False, rtscts=False, dsrdtr=False)
            self.handle.rts = self.handle.dtr = False
            self.handle.port = port
            manager.register_handle(port, self.handle)
            self._handle_registered = True
            phase = "open"
            self.handle.open()
            self.protocol = TurntableProtocol(self.handle, connection.timeout)
            phase = "status"
            self.read_status()
            self.connection_error = None
            return True
        except Exception as exc:
            logger.warning("Turntable connection failed on %s during %s: %s", port, phase, exc, exc_info=True)
            message = str(exc)
            if phase == "open" and isinstance(exc, serial.SerialException):
                if "cannot configure port" in message.lower():
                    message = ("Windows 无法配置 USB 串口，请检查 USB 连接及串口驱动状态。"
                               f"原始错误：{exc}")
                elif "could not open port" in message.lower():
                    message = ("无法打开串口，请检查是否被其他程序占用或 USB 设备是否可用。"
                               f"原始错误：{exc}")
            elif phase == "status" and isinstance(exc, TimeoutError):
                message = ("串口已打开，但控制器状态查询超时；请核对控制器供电、串口接线及115200/8N1。"
                           f"原始错误：{exc}")
            self._connect_failed = True
            try:
                if not self.disconnect():
                    message += "；串口资源清理未完成，连接资源已保留供重试"
            except Exception as cleanup_error:
                logger.warning("Turntable connection cleanup failed on %s: %s", port, cleanup_error, exc_info=True)
                message += f"；串口资源清理失败：{cleanup_error}"
            self.connection_error = self.last_command_error = message
            self.snapshot = self.unknown(message)
            if message != str(exc) and isinstance(exc, (serial.SerialException, TimeoutError)):
                raise type(exc)(message) from exc
            raise

    def disconnect(self):
        if self.handle is not None and self._port is not None and not self._handle_registered:
            try:
                if self.handle.is_open:
                    self.handle.close()
                if self.handle.is_open:
                    return False
            except Exception as exc:
                self.last_command_error = str(exc)
                return False
        port = self._port if self._port is not None else getattr(self.handle, "port", None)
        if port is not None and not get_serial_manager().release_port(port):
            return False
        self.handle = self.protocol = None
        self._port = None
        self._handle_registered = False
        self._connect_failed = False
        self.connection_error = None
        self.snapshot = self.unknown()
        return True

    def read_status(self):
        self.snapshot = self.unknown()
        if not self.is_connected():
            raise RuntimeError("转盘未连接")
        try:
            status = self.protocol.read_status()
            self.snapshot = {**status, "read_ok": True,
                             "read_at": datetime.now(timezone.utc).isoformat(), "read_error": None}
            return self.snapshot
        except Exception as exc:
            self.last_command_error = str(exc)
            self.snapshot = self.unknown(str(exc))
            raise

    def send_command(self, request):
        req = request if isinstance(request, TurntableCommand) else TurntableCommand.model_validate(request)
        if not self.is_connected():
            raise RuntimeError("转盘未连接")
        self.snapshot = self.unknown()
        try:
            self.protocol.send_command(req)
        except Exception as exc:
            self.last_command_error = str(exc)
            self.snapshot = self.unknown(str(exc))
            raise
