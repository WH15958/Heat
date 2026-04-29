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
        self._pump_channel_index: Dict[str, int] = {}
        self._pump_channel_cache: Dict[str, Dict[str, dict]] = {}

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
        channels: Optional[list] = None,
    ) -> str:
        """添加蠕动泵配置

        Args:
            device_id: 设备ID
            port: 串口
            baudrate: 波特率
            slave_address: 从站地址
            channels: 通道配置列表，每项为dict含channel/enabled/pump_head等，为None时默认4通道

        Returns:
            str: 设备ID
        """
        if channels is None:
            channel_configs = [
                PumpChannelConfig(channel=i, enabled=True)
                for i in range(1, 5)
            ]
        else:
            channel_configs = []
            for ch in channels:
                if isinstance(ch, dict):
                    channel_configs.append(PumpChannelConfig(
                        channel=ch.get("channel", 1),
                        enabled=ch.get("enabled", True),
                        pump_head=ch.get("pump_head", 5),
                        tube_model=ch.get("tube_model", 0),
                        suck_back_angle=ch.get("suck_back_angle", 0),
                    ))
                elif isinstance(ch, PumpChannelConfig):
                    channel_configs.append(ch)
                else:
                    channel_configs.append(PumpChannelConfig(channel=int(ch), enabled=True))

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
            channels=channel_configs,
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
        """读取蠕动泵状态（通道轮询，每次读2个通道）

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

        idx = self._pump_channel_index.get(device_id, 0)
        channels_to_read = [idx % 4 + 1, (idx + 1) % 4 + 1]
        self._pump_channel_index[device_id] = (idx + 2) % 4

        if device_id not in self._pump_channel_cache:
            self._pump_channel_cache[device_id] = {}
            for ch in range(1, 5):
                self._pump_channel_cache[device_id][str(ch)] = {
                    "running": False,
                    "flow_rate": 0.0,
                    "volume": 0.0,
                    "direction": None,
                }

        for ch in channels_to_read:
            try:
                ch_data = pump.read_channel_status(ch)
                self._pump_channel_cache[device_id][str(ch)] = {
                    "running": ch_data.running,
                    "flow_rate": ch_data.flow_rate,
                    "volume": ch_data.dispensed_volume,
                    "direction": ch_data.direction.name
                    if ch_data.direction
                    else None,
                }
            except Exception as e:
                logger.warning(f"Pump {device_id} CH{ch} read error: {e}")

        return {
            "device_id": device_id,
            "channels": dict(self._pump_channel_cache[device_id]),
        }

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

    def get_heater(self, device_id: str) -> Optional[AIHeaterDevice]:
        """获取加热器设备实例

        Args:
            device_id: 设备ID

        Returns:
            Optional[AIHeaterDevice]: 加热器实例，不存在返回None
        """
        with self._lock:
            return self._heaters.get(device_id)

    def get_pump(self, device_id: str) -> Optional[LabSmartPumpDevice]:
        """获取蠕动泵设备实例

        Args:
            device_id: 设备ID

        Returns:
            Optional[LabSmartPumpDevice]: 蠕动泵实例，不存在返回None
        """
        with self._lock:
            return self._pumps.get(device_id)

    def get_all_heaters(self) -> Dict[str, AIHeaterDevice]:
        """获取所有加热器（快照）

        Returns:
            Dict[str, AIHeaterDevice]: 设备ID到加热器实例的映射
        """
        with self._lock:
            return dict(self._heaters)

    def get_all_pumps(self) -> Dict[str, LabSmartPumpDevice]:
        """获取所有蠕动泵（快照）

        Returns:
            Dict[str, LabSmartPumpDevice]: 设备ID到蠕动泵实例的映射
        """
        with self._lock:
            return dict(self._pumps)

    def set_temperature(self, device_id: str, temperature: float) -> bool:
        """设置加热器目标温度

        Args:
            device_id: 设备ID
            temperature: 目标温度

        Returns:
            bool: 设置成功返回True

        Raises:
            ValueError: 设备不存在
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        if not heater.is_connected():
            logger.warning(f"Heater {device_id} not connected")
            return False
        return heater.set_temperature(temperature)

    def start_heater(self, device_id: str) -> bool:
        """启动加热器

        Args:
            device_id: 设备ID

        Returns:
            bool: 启动成功返回True

        Raises:
            ValueError: 设备不存在
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        if not heater.is_connected():
            logger.warning(f"Heater {device_id} not connected")
            return False
        return heater.start()

    def stop_heater(self, device_id: str) -> bool:
        """停止加热器

        Args:
            device_id: 设备ID

        Returns:
            bool: 停止成功返回True

        Raises:
            ValueError: 设备不存在
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            raise ValueError(f"Heater not found: {device_id}")
        if not heater.is_connected():
            logger.warning(f"Heater {device_id} not connected")
            return False
        return heater.stop()

    def start_pump_channel(
        self,
        device_id: str,
        channel: int,
        flow_rate: float,
        direction: "PumpDirection",
        mode: "PumpRunMode",
        run_time: Optional[float] = None,
        dispense_volume: Optional[float] = None,
    ) -> bool:
        """启动蠕动泵通道

        Args:
            device_id: 设备ID
            channel: 通道号
            flow_rate: 流速
            direction: 方向
            mode: 运行模式
            run_time: 运行时间（秒）
            dispense_volume: 定量体积（mL）

        Returns:
            bool: 启动成功返回True

        Raises:
            ValueError: 设备不存在
        """
        pump = self._pumps.get(device_id)
        if pump is None:
            raise ValueError(f"Pump not found: {device_id}")
        if not (1 <= channel <= 4):
            raise ValueError(f"Invalid channel: {channel}, must be 1-4")
        if not pump.is_connected():
            logger.warning(f"Pump {device_id} not connected")
            return False
        if not pump.set_direction(channel, direction):
            return False
        if not pump.set_run_mode(channel, mode):
            return False
        if not pump.set_flow_rate(channel, flow_rate):
            return False
        if run_time is not None:
            if not pump.set_run_time(channel, run_time):
                return False
        if dispense_volume is not None:
            if not pump.set_dispense_volume(channel, dispense_volume):
                return False
        return pump.start_channel(channel)

    def stop_pump_channel(self, device_id: str, channel: Optional[int] = None) -> bool:
        """停止蠕动泵

        Args:
            device_id: 设备ID
            channel: 通道号，为None时停止所有通道

        Returns:
            bool: 停止成功返回True

        Raises:
            ValueError: 设备不存在或通道号无效
        """
        pump = self._pumps.get(device_id)
        if pump is None:
            raise ValueError(f"Pump not found: {device_id}")
        if not pump.is_connected():
            logger.warning(f"Pump {device_id} not connected")
            return False
        if channel is None:
            return pump.stop_all()
        if not (1 <= channel <= 4):
            raise ValueError(f"Invalid channel: {channel}, must be 1-4")
        return pump.stop_channel(channel)

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
