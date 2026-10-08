"""Synchronous valve control through a Zhongsheng relay (Modbus RTU)."""

from datetime import datetime

from src.devices.base_device import BaseDevice, DeviceData, DeviceInfo, DeviceStatus, DeviceType
from src.protocols.modbus_rtu import ModbusRTUProtocol


class RelayValveDevice(BaseDevice):
    def __init__(self, config):
        super().__init__(config, DeviceInfo(name=config.device_id, device_type=DeviceType.VALVE))
        self._protocol = None
        self.relay_energized = None
        self.read_ok = False

    def is_connected(self):
        return self._protocol is not None and self._protocol.is_connected

    def connect(self):
        with self._lock:
            if self.is_connected():
                return True
            self.status = DeviceStatus.CONNECTING
            self._protocol = ModbusRTUProtocol(**self.config.connection_params)
            try:
                if not self._protocol.connect():
                    raise IOError("阀门串口连接失败")
                self.read_data()
                return True
            except Exception:
                self._protocol.disconnect()
                self.status = DeviceStatus.ERROR
                self.read_ok = False
                self.relay_energized = None
                raise

    def disconnect(self):
        """Release communications without changing the fluid route."""
        with self._lock:
            if self._protocol is not None:
                self._protocol.disconnect()
            self.status = DeviceStatus.DISCONNECTED
            self.relay_energized = None
            self.read_ok = False
            return True

    def read_data(self):
        with self._lock:
            self.relay_energized = None
            self.read_ok = False
            if not self.is_connected():
                raise IOError("阀门未连接")
            values = self._protocol.read_holding_registers(1, 0, 1)
            if values not in ([0], [1]):
                self.status = DeviceStatus.ERROR
                raise IOError("继电器状态读取失败，阀位未知")
            self.relay_energized = bool(values[0])
            self.read_ok = True
            self.status = DeviceStatus.CONNECTED
            self._last_data = DeviceData(self.config.device_id, datetime.now(), {
                "relay_energized": self.relay_energized,
                "read_ok": True,
                "physical_route_confirmed": False,
            })
            return self._last_data

    def set_energized(self, energized):
        if type(energized) is not bool:
            raise ValueError("energized 必须为布尔值")
        with self._lock:
            if not self.is_connected():
                raise IOError("阀门未连接")
            self.read_ok = False
            self.relay_energized = None
            # Never retry a write after a timeout; the relay may already have switched.
            if not self._protocol.write_single_register(1, 0, int(energized)):
                self.status = DeviceStatus.ERROR
                raise IOError("切换回复未确认，阀位未知；请刷新状态")
            actual = self.read_data().data["relay_energized"]
            if actual != energized:
                self.status = DeviceStatus.ERROR
                raise IOError("继电器读回与目标不一致")
            return True

    def write_command(self, command, value):
        if command != "set_energized":
            raise ValueError("不支持的阀门命令")
        return self.set_energized(value)

    def get_available_commands(self):
        return ["set_energized"]

    def emergency_stop(self):
        # Neither position closes both outlets; no safe route has been accepted.
        return False
