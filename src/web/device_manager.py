import threading
from typing import Dict, Optional

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.peristaltic_pump import (
    LabSmartPumpDevice,
    PeristalticPumpConfig,
    PumpChannelConfig,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class DeviceManager:
    """设备管理器 - Web层与设备驱动层的桥梁"""

    def __init__(self):
        self._heaters: Dict[str, AIHeaterDevice] = {}
        self._pumps: Dict[str, LabSmartPumpDevice] = {}
        self._lock = threading.Lock()

    def add_heater(
        self,
        device_id: str,
        port: str,
        baudrate: int = 9600,
        address: int = 1,
        decimal_places: int = 1,
    ) -> str:
        """添加加热器配置

        Args:
            device_id: 设备ID
            port: 串口
            baudrate: 波特率
            address: 从站地址
            decimal_places: 小数位数

        Returns:
            str: 设备ID
        """
        config = HeaterConfig(
            device_id=device_id,
            connection_params={"port": port, "baudrate": baudrate, "address": address},
            decimal_places=decimal_places,
        )
        self._heaters[device_id] = AIHeaterDevice(config)
        logger.info(f"Registered heater: {device_id} on {port}")
        return device_id

    def add_pump(
        self,
        device_id: str,
        port: str,
        baudrate: int = 9600,
        slave_address: int = 1,
    ) -> str:
        """添加蠕动泵配置

        Args:
            device_id: 设备ID
            port: 串口
            baudrate: 波特率
            slave_address: 从站地址

        Returns:
            str: 设备ID
        """
        config = PeristalticPumpConfig(
            device_id=device_id,
            connection_params={
                "port": port,
                "baudrate": baudrate,
                "parity": "N",
                "stopbits": 1,
                "bytesize": 8,
            },
            slave_address=slave_address,
            channels=[
                PumpChannelConfig(channel=1, enabled=True),
                PumpChannelConfig(channel=2, enabled=True),
                PumpChannelConfig(channel=3, enabled=True),
                PumpChannelConfig(channel=4, enabled=True),
            ],
        )
        self._pumps[device_id] = LabSmartPumpDevice(config)
        logger.info(f"Registered pump: {device_id} on {port}")
        return device_id

    def connect_heater(self, device_id: str) -> bool:
        """连接加热器

        Args:
            device_id: 设备ID

        Returns:
            bool: 连接成功返回True

        Raises:
            ValueError: 设备不存在
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        return heater.connect()

    def disconnect_heater(self, device_id: str) -> bool:
        """断开加热器

        Args:
            device_id: 设备ID

        Returns:
            bool: 断开成功返回True

        Raises:
            ValueError: 设备不存在
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        return heater.disconnect()

    def connect_pump(self, device_id: str) -> bool:
        """连接蠕动泵

        Args:
            device_id: 设备ID

        Returns:
            bool: 连接成功返回True

        Raises:
            ValueError: 设备不存在
        """
        pump = self._pumps.get(device_id)
        if pump is None:
            raise ValueError(f"Pump not found: {device_id}")
        return pump.connect()

    def disconnect_pump(self, device_id: str) -> bool:
        """断开蠕动泵

        Args:
            device_id: 设备ID

        Returns:
            bool: 断开成功返回True

        Raises:
            ValueError: 设备不存在
        """
        pump = self._pumps.get(device_id)
        if pump is None:
            raise ValueError(f"Pump not found: {device_id}")
        return pump.disconnect()

    def read_heater_data(self, device_id: str) -> dict:
        """读取加热器数据

        Args:
            device_id: 设备ID

        Returns:
            dict: 加热器数据

        Raises:
            ValueError: 设备不存在
            IOError: 设备未连接
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        if not heater.is_connected():
            raise IOError("Device not connected")
        data = heater.read_data()
        return {
            "device_id": data.device_id,
            "pv": data.pv,
            "sv": data.sv,
            "mv": data.mv,
            "alarms": data.alarms,
            "run_status": data.run_status.name,
            "is_manual": data.is_manual,
            "is_auto_tuning": data.is_auto_tuning,
        }

    def read_pump_status(self, device_id: str) -> dict:
        """读取蠕动泵状态

        Args:
            device_id: 设备ID

        Returns:
            dict: 泵状态数据

        Raises:
            ValueError: 设备不存在
            IOError: 设备未连接
        """
        pump = self._pumps.get(device_id)
        if pump is None:
            raise ValueError(f"Pump not found: {device_id}")
        if not pump.is_connected():
            raise IOError("Device not connected")
        channels = {}
        for ch in range(1, 5):
            try:
                ch_data = pump.read_channel_status(ch)
                channels[str(ch)] = {
                    "running": ch_data.running,
                    "flow_rate": ch_data.flow_rate,
                    "volume": ch_data.volume,
                    "direction": ch_data.direction.name
                    if ch_data.direction
                    else None,
                }
            except Exception:
                channels[str(ch)] = {
                    "running": False,
                    "flow_rate": 0.0,
                    "volume": 0.0,
                    "direction": None,
                }
        return {"device_id": device_id, "channels": channels}

    def emergency_stop_all(self):
        """紧急停止所有设备"""
        logger.warning("EMERGENCY STOP ALL DEVICES")
        for heater in self._heaters.values():
            try:
                heater.emergency_stop()
            except Exception as e:
                logger.error(f"Emergency stop heater failed: {e}")
        for pump in self._pumps.values():
            try:
                pump.emergency_stop()
            except Exception as e:
                logger.error(f"Emergency stop pump failed: {e}")

    def get_all_status(self) -> dict:
        """获取所有设备状态摘要

        Returns:
            dict: 设备状态摘要
        """
        heaters = {}
        for did, h in self._heaters.items():
            heaters[did] = {
                "connected": h.is_connected(),
                "status": h.status.name,
            }
        pumps = {}
        for did, p in self._pumps.items():
            pumps[did] = {
                "connected": p.is_connected(),
                "status": p.status.name,
            }
        return {"heaters": heaters, "pumps": pumps}

    def cleanup(self):
        """清理所有设备资源"""
        for heater in self._heaters.values():
            try:
                if heater.is_connected():
                    heater.disconnect()
            except Exception:
                pass
        for pump in self._pumps.values():
            try:
                if pump.is_connected():
                    pump.disconnect()
            except Exception:
                pass
