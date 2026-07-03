import threading
import time
from typing import Any, Dict, Optional

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.microwave import MicrowaveConfig, MicrowaveDevice
from devices.peristaltic_pump import (
    LabSmartPumpDevice,
    PeristalticPumpConfig,
    PumpChannelConfig,
)
from protocols.microwave_params import MODE_CONTROL_MASKS
from utils.logger import get_logger
from utils.serial_binding import resolve_connection

logger = get_logger(__name__)


class DeviceManager:
    """设备管理器 - Web层与设备驱动层的桥梁"""

    def __init__(self):
        self._heaters: Dict[str, AIHeaterDevice] = {}
        self._pumps: Dict[str, LabSmartPumpDevice] = {}
        self._microwaves: Dict[str, MicrowaveDevice] = {}
        self._heater_bindings: Dict[str, Dict[str, Any]] = {}
        self._pump_bindings: Dict[str, Dict[str, Any]] = {}
        self._microwave_bindings: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pump_locks: Dict[str, threading.Lock] = {}
        self._pump_channel_index: Dict[str, int] = {}
        self._pump_channel_cache: Dict[str, Dict[str, dict]] = {}

    def add_heater(
        self,
        device_id: str,
        port: str,
        baudrate: int = 9600,
        address: int = 1,
        decimal_places: int = 1,
        binding_info: Optional[Dict[str, Any]] = None,
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
        self._heater_bindings[device_id] = self._normalize_binding_info(binding_info, port)
        logger.info(f"Registered heater: {device_id} on {port}")
        return device_id

    def add_pump(
        self,
        device_id: str,
        port: str,
        baudrate: int = 19200,
        slave_address: int = 1,
        parity: str = "E",
        channels: Optional[list] = None,
        binding_info: Optional[Dict[str, Any]] = None,
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
                "parity": parity,
                "stopbits": 1,
                "bytesize": 8,
            },
            slave_address=slave_address,
            channels=channel_configs,
        )
        self._pumps[device_id] = LabSmartPumpDevice(config)
        self._pump_locks[device_id] = threading.Lock()
        self._pump_bindings[device_id] = self._normalize_binding_info(binding_info, port)
        logger.info(f"Registered pump: {device_id} on {port}")
        return device_id

    def add_microwave(
        self,
        device_id: str,
        port: str,
        baudrate: int = 9600,
        slave_address: int = 1,
        parity: str = "N",
        timeout: float = 2.0,
        max_temperature: float = 300.0,
        max_power_percent: int = 100,
        poll_interval: float = 1.0,
        retry_count: int = 3,
        retry_delay: float = 0.5,
        allow_experiment_control: bool = True,
        allow_real_hardware_writes: bool = True,
        enable_control_writes: bool = True,
        binding_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """添加微波仪配置"""
        config = MicrowaveConfig(
            device_id=device_id,
            connection_params={
                "port": port,
                "baudrate": baudrate,
                "parity": parity,
                "stopbits": 1,
                "bytesize": 8,
            },
            slave_address=slave_address,
            baudrate=baudrate,
            parity=parity,
            timeout=timeout,
            poll_interval=poll_interval,
            retry_count=retry_count,
            retry_delay=retry_delay,
            max_temperature=max_temperature,
            max_power_percent=max_power_percent,
            allow_experiment_control=allow_experiment_control,
            allow_real_hardware_writes=allow_real_hardware_writes,
            enable_control_writes=enable_control_writes,
        )
        self._microwaves[device_id] = MicrowaveDevice(config)
        self._microwave_bindings[device_id] = self._normalize_binding_info(binding_info, port)
        logger.info(f"Registered microwave: {device_id} on {port}")
        return device_id

    def _normalize_binding_info(
        self,
        binding_info: Optional[Dict[str, Any]],
        port: str,
    ) -> Dict[str, Any]:
        info = dict(binding_info or {})
        info.setdefault("resolved_port", port)
        info.setdefault("connection_binding_mode", "fixed_port")
        info.setdefault("binding_label", f"固定串口 {port or '--'}")
        info.setdefault("binding_resolved", bool(port))
        info.setdefault("binding_match_count", 1 if port else 0)
        info.setdefault("binding_error", None if port else "missing_fixed_port")
        info.setdefault("binding_candidates", [port] if port else [])
        return info

    @staticmethod
    def _binding_port(info: Optional[Dict[str, Any]]) -> str:
        return info.get("resolved_port", "") if info is not None else ""

    def _binding_status(self, info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = self._normalize_binding_info(info, self._binding_port(info))
        return {
            "connection_binding_mode": normalized.get("connection_binding_mode"),
            "binding_label": normalized.get("binding_label"),
            "binding_resolved": bool(normalized.get("binding_resolved", False)),
            "binding_match_count": int(normalized.get("binding_match_count", 0)),
            "binding_error": normalized.get("binding_error"),
            "binding_candidates": list(normalized.get("binding_candidates", [])),
        }

    def _update_binding_resolution(
        self,
        device_id: str,
        device_type: str,
        info: Optional[Dict[str, Any]],
        device,
    ) -> Dict[str, Any]:
        binding = info if info is not None else self._normalize_binding_info(None, "")
        connection = binding.get("_connection_config")
        if connection is None:
            return self._normalize_binding_info(binding, self._binding_port(binding))

        resolution = resolve_connection(connection)
        binding.update({
            "resolved_port": resolution.resolved_port,
            "connection_binding_mode": resolution.connection_binding_mode,
            "binding_label": resolution.binding_label,
            "binding_resolved": resolution.binding_resolved,
            "binding_match_count": resolution.binding_match_count,
            "binding_error": resolution.binding_error,
            "binding_candidates": resolution.binding_candidates,
        })
        if resolution.binding_resolved and resolution.resolved_port:
            device.config.connection_params["port"] = resolution.resolved_port
            logger.info(
                "%s %s binding refreshed: %s",
                device_type,
                device_id,
                resolution.resolved_port,
            )
        elif not resolution.binding_resolved:
            logger.warning(
                "%s %s binding still unresolved: %s",
                device_type,
                device_id,
                resolution.binding_error,
            )
        return binding

    def _refresh_binding_if_needed(
        self,
        device_id: str,
        device_type: str,
        info: Optional[Dict[str, Any]],
        device,
    ) -> Dict[str, Any]:
        binding = self._normalize_binding_info(info, self._binding_port(info))
        if binding.get("binding_resolved"):
            return binding
        return self._update_binding_resolution(device_id, device_type, info, device)

    def refresh_bindings(self) -> dict:
        for did, heater in self._heaters.items():
            self._update_binding_resolution(did, "Heater", self._heater_bindings.get(did), heater)
        for did, pump in self._pumps.items():
            self._update_binding_resolution(did, "Pump", self._pump_bindings.get(did), pump)
        for did, microwave in self._microwaves.items():
            self._update_binding_resolution(
                did,
                "Microwave",
                self._microwave_bindings.get(did),
                microwave,
            )
        return self.get_all_status()

    def _require_binding_resolved(self, device_id: str, device_type: str, info: Optional[Dict[str, Any]]):
        binding = self._normalize_binding_info(info, self._binding_port(info))
        if binding.get("binding_resolved"):
            return
        error = binding.get("binding_error") or "binding_unresolved"
        raise RuntimeError(f"{device_type} {device_id} binding unresolved: {error}")

    def _binding_enriched_payload(
        self,
        payload: Dict[str, Any],
        info: Optional[Dict[str, Any]],
        connection_port: str,
    ) -> Dict[str, Any]:
        payload["connection_port"] = connection_port
        payload.update(self._binding_status(info))
        return payload

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
        self._refresh_binding_if_needed(device_id, "Heater", self._heater_bindings.get(device_id), heater)
        self._require_binding_resolved(device_id, "Heater", self._heater_bindings.get(device_id))
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
        self._refresh_binding_if_needed(device_id, "Pump", self._pump_bindings.get(device_id), pump)
        self._require_binding_resolved(device_id, "Pump", self._pump_bindings.get(device_id))
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

    def connect_microwave(self, device_id: str) -> bool:
        """连接微波仪"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        self._refresh_binding_if_needed(
            device_id,
            "Microwave",
            self._microwave_bindings.get(device_id),
            microwave,
        )
        self._require_binding_resolved(
            device_id,
            "Microwave",
            self._microwave_bindings.get(device_id),
        )
        return microwave.connect()

    def disconnect_microwave(self, device_id: str) -> bool:
        """断开微波仪"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        return microwave.disconnect()

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
        return self._binding_enriched_payload({
            "device_id": data.device_id,
            "pv": data.pv,
            "sv": data.sv,
            "mv": data.mv,
            "alarms": data.alarms,
            "run_status": data.run_status.name,
            "is_manual": data.is_manual,
            "is_auto_tuning": data.is_auto_tuning,
        }, self._heater_bindings.get(device_id), heater.config.connection_params.get("port"))

    def read_pump_status(self, device_id: str) -> dict:
        """读取蠕动泵状态（读取所有4个通道）

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

        if device_id not in self._pump_channel_cache:
            self._pump_channel_cache[device_id] = {}
            for ch in range(1, 5):
                self._pump_channel_cache[device_id][str(ch)] = {
                    "running": False,
                    "flow_rate": 0.0,
                    "volume": 0.0,
                    "direction": None,
                }

        for ch in range(1, 5):
            try:
                ch_data = pump.read_channel_status(ch)
                if ch_data is not None:
                    self._pump_channel_cache[device_id][str(ch)] = {
                        "running": ch_data.running,
                        "flow_rate": ch_data.flow_rate,
                        "volume": ch_data.dispensed_volume,
                        "direction": ch_data.direction.name
                        if ch_data.direction
                        else None,
                        "flow_unit": ch_data.flow_unit.name
                        if ch_data.flow_unit
                        else "ML_MIN",
                    }
            except Exception as e:
                logger.warning(f"Pump {device_id} CH{ch} read error: {e}")

        return self._binding_enriched_payload({
            "device_id": device_id,
            "channels": dict(self._pump_channel_cache[device_id]),
        }, self._pump_bindings.get(device_id), pump.config.connection_params.get("port"))

    def read_microwave_data(self, device_id: str) -> dict:
        """读取微波仪数据"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            raise IOError("Device not connected")
        data = microwave.read_data()
        return self._microwave_payload(microwave, data.data)

    def configure_microwave_manual(self, device_id: str, segments) -> bool:
        """配置微波仪手动功率模式参数"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        return microwave.configure_manual(segments)

    def configure_microwave_auto_power(self, device_id: str, segments) -> bool:
        """配置微波仪自动功率模式参数"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        return microwave.configure_auto_power(segments)

    def configure_microwave_constant_rate(self, device_id: str, segments) -> bool:
        """配置微波仪恒速率模式参数"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        return microwave.configure_constant_rate(segments)

    def start_microwave(self, device_id: str, mode) -> bool:
        """启动微波仪输出"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        return microwave.start(mode)

    def stop_microwave(self, device_id: str) -> bool:
        """停止微波仪输出"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        return microwave.stop()

    def is_microwave_experiment_control_allowed(self, device_id: str) -> bool:
        """兼容旧调用：微波仪 YAML 自动控制当前始终允许。"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        return True

    def emergency_stop_all(self) -> bool:
        """紧急停止所有设备"""
        logger.warning("EMERGENCY STOP ALL DEVICES")
        success = True
        for heater in self._heaters.values():
            try:
                if not heater.is_connected():
                    logger.warning(f"Emergency stop heater skipped, not connected: {heater.config.device_id}")
                    continue
                result = heater.emergency_stop()
                if result is False:
                    success = False
                    logger.error(f"Emergency stop heater returned false: {heater.config.device_id}")
            except Exception as e:
                success = False
                logger.error(f"Emergency stop heater failed: {e}")
        for pump in self._pumps.values():
            try:
                if not pump.is_connected():
                    logger.warning(f"Emergency stop pump skipped, not connected: {pump.config.device_id}")
                    continue
                result = pump.emergency_stop()
                if result is False:
                    success = False
                    logger.error(f"Emergency stop pump returned false: {pump.config.device_id}")
            except Exception as e:
                success = False
                logger.error(f"Emergency stop pump failed: {e}")
        for microwave in self._microwaves.values():
            try:
                if not microwave.is_connected():
                    logger.warning(
                        f"Emergency stop microwave skipped, not connected: {microwave.config.device_id}"
                    )
                    continue
                result = microwave.emergency_stop()
                if result is False:
                    success = False
                    logger.error(
                        f"Emergency stop microwave returned false: {microwave.config.device_id}"
                    )
            except Exception as e:
                success = False
                logger.error(f"Emergency stop microwave failed: {e}")
        return success

    def get_all_status(self) -> dict:
        """获取所有设备状态摘要

        Returns:
            dict: 设备状态摘要
        """
        heaters = {}
        for did, h in self._heaters.items():
            heaters[did] = self._binding_enriched_payload({
                "connected": h.is_connected(),
                "status": h.status.name,
            }, self._heater_bindings.get(did), h.config.connection_params.get("port"))
        pumps = {}
        for did, p in self._pumps.items():
            pumps[did] = self._binding_enriched_payload({
                "connected": p.is_connected(),
                "status": p.status.name,
            }, self._pump_bindings.get(did), p.config.connection_params.get("port"))
        microwaves = {}
        for did, m in self._microwaves.items():
            microwaves[did] = self._binding_enriched_payload({
                "connected": m.is_connected(),
                "status": m.status.name,
                "allow_experiment_control": bool(
                    getattr(m.config, "allow_experiment_control", False)
                ),
                "allow_real_hardware_writes": bool(
                    getattr(m.config, "allow_real_hardware_writes", False)
                ),
                "enable_control_writes": bool(
                    getattr(m.config, "enable_control_writes", False)
                ),
            }, self._microwave_bindings.get(did), m.config.connection_params.get("port"))
        return {"heaters": heaters, "pumps": pumps, "microwaves": microwaves}

    def _microwave_payload(self, microwave: MicrowaveDevice, data: dict) -> dict:
        device_id = microwave.config.device_id
        power_percent = data.get("power_percent", 0)
        current = data.get("current", 0)
        current_mode_code = data.get("current_mode_code", 0)
        return self._binding_enriched_payload({
            "device_id": device_id,
            "running": self._microwave_is_running(power_percent, current),
            "mode": self._microwave_mode_from_code(current_mode_code),
            "current_segment": data.get("current_segment", 0),
            "material_temperature": data.get("material_temperature"),
            "temperature_source": data.get("material_temperature_source", "unknown"),
            "power_percent": power_percent,
            "current": current,
            "runtime_seconds": data.get("runtime_seconds", 0),
            "fault_code": data.get("fault_code", 0),
            "faults": [],
            "current_mode_code": current_mode_code,
            "allow_experiment_control": bool(
                getattr(microwave.config, "allow_experiment_control", False)
            ),
            "allow_real_hardware_writes": bool(
                getattr(microwave.config, "allow_real_hardware_writes", False)
            ),
            "enable_control_writes": bool(
                getattr(microwave.config, "enable_control_writes", False)
            ),
        }, self._microwave_bindings.get(device_id), microwave.config.connection_params.get("port"))

    @staticmethod
    def _microwave_is_running(power_percent, current) -> bool:
        try:
            return float(power_percent or 0) > 0 or float(current or 0) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _microwave_mode_from_code(current_mode_code) -> str:
        try:
            code = int(current_mode_code or 0)
        except (TypeError, ValueError):
            return "unknown"
        for mode, mask in MODE_CONTROL_MASKS.items():
            if code == int(mask):
                return mode.value
        return "unknown"

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

    def get_microwave(self, device_id: str) -> Optional[MicrowaveDevice]:
        """获取微波仪设备实例"""
        with self._lock:
            return self._microwaves.get(device_id)

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

    def get_all_microwaves(self) -> Dict[str, MicrowaveDevice]:
        """获取所有微波仪（快照）"""
        with self._lock:
            return dict(self._microwaves)

    def get_heater_binding(self, device_id: str) -> Dict[str, Any]:
        return self._binding_status(self._heater_bindings.get(device_id))

    def get_pump_binding(self, device_id: str) -> Dict[str, Any]:
        return self._binding_status(self._pump_bindings.get(device_id))

    def get_microwave_binding(self, device_id: str) -> Dict[str, Any]:
        return self._binding_status(self._microwave_bindings.get(device_id))

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
        tube_model: Optional[int] = None,
        flow_unit: Optional[int] = None,
        time_unit: Optional[int] = None,
        volume_unit: Optional[int] = None,
        repeat_count: Optional[int] = None,
        interval_time: Optional[float] = None,
        interval_time_unit: Optional[int] = None,
    ) -> bool:
        """启动蠕动泵通道

        Args:
            device_id: 设备ID
            channel: 通道号
            flow_rate: 流速
            direction: 方向
            mode: 运行模式
            run_time: 运行时间
            dispense_volume: 定量体积
            tube_model: 软管型号（覆盖配置）
            flow_unit: 流速单位 (0=uL/min, 1=mL/min, 2=L/min, 3=RPM)
            time_unit: 时间单位 (0=sec, 1=min, 2=hour)
            volume_unit: 液量单位 (0=uL, 1=mL, 2=L)
            repeat_count: 重复次数 (0=无限, 1-9999)
            interval_time: 间隔时间
            interval_time_unit: 间隔时间单位 (0=sec, 1=min, 2=hour)

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
        pump_lock = self._pump_locks.get(device_id)
        if pump_lock:
            pump_lock.acquire()
        try:
            return self._start_pump_channel_inner(pump, device_id, channel, flow_rate, direction, mode, run_time, dispense_volume, tube_model, flow_unit, time_unit, volume_unit, repeat_count, interval_time, interval_time_unit)
        finally:
            if pump_lock:
                pump_lock.release()

    def _start_pump_channel_inner(self, pump: LabSmartPumpDevice, device_id: str,
                                   channel: int, flow_rate: float, direction, mode,
                                   run_time, dispense_volume, tube_model=None, flow_unit=None,
                                   time_unit=None, volume_unit=None, repeat_count=None,
                                   interval_time=None, interval_time_unit=None) -> bool:
        from src.protocols.pump_params import FlowUnit, PumpRunMode, TimeUnit, VolumeUnit

        if not pump.enable_channel(channel, True):
            logger.warning(f"Pump {device_id} CH{channel} enable failed")
            return False
        logger.info(f"Pump {device_id} CH{channel}: enable OK")
        pump.stop_channel(channel)
        time.sleep(0.2)

        effective_tube_model = tube_model
        if effective_tube_model is None:
            current_tube = pump.get_tube_model(channel)
            if current_tube is None or current_tube == 0:
                ch_config = pump.get_channel_config(channel)
                if ch_config and ch_config.tube_model > 0:
                    effective_tube_model = ch_config.tube_model
        if effective_tube_model is not None and effective_tube_model > 0:
            if not pump.set_tube_model(channel, effective_tube_model):
                logger.warning(f"Pump {device_id} CH{channel} set_tube_model({effective_tube_model}) failed")
                return False
            time.sleep(0.3)
            readback = pump.get_tube_model(channel)
            logger.info(f"Pump {device_id} CH{channel}: tube_model={effective_tube_model} written, readback={readback}")
            if readback is not None and readback != effective_tube_model:
                logger.warning(f"Pump {device_id} CH{channel}: tube_model mismatch! written={effective_tube_model} readback={readback}")
        else:
            logger.warning(f"Pump {device_id} CH{channel} tube_model not set, flow rate range may be limited")

        if not pump.set_direction(channel, direction):
            logger.warning(f"Pump {device_id} CH{channel} set_direction failed")
            return False
        time.sleep(0.05)

        effective_flow_unit = FlowUnit(flow_unit) if flow_unit is not None else FlowUnit.ML_MIN

        if not self._validate_pump_units(device_id, channel, flow_unit, time_unit, volume_unit, interval_time_unit):
            return False

        if not self._validate_pump_repeat_params(device_id, channel, repeat_count, interval_time):
            return False
        if isinstance(repeat_count, float):
            repeat_count = int(repeat_count)

        effective_time_unit = TimeUnit(time_unit) if time_unit is not None else TimeUnit.SECOND
        effective_volume_unit = VolumeUnit(volume_unit) if volume_unit is not None else VolumeUnit.ML
        effective_interval_time_unit = TimeUnit(interval_time_unit) if interval_time_unit is not None else TimeUnit.SECOND

        if not self._set_pump_flow_and_mode(pump, device_id, channel, flow_rate, effective_flow_unit, mode):
            return False

        if not self._set_pump_mode_params(pump, device_id, channel, mode, run_time, dispense_volume,
                                          effective_time_unit, effective_volume_unit):
            return False

        if repeat_count is not None:
            if not pump.set_repeat_count(channel, repeat_count):
                logger.warning(f"Pump {device_id} CH{channel} set_repeat_count({repeat_count}) failed")
                return False
            time.sleep(0.05)

        if interval_time is not None:
            if not pump.set_interval_time(channel, interval_time, effective_interval_time_unit):
                logger.warning(f"Pump {device_id} CH{channel} set_interval_time({interval_time} {effective_interval_time_unit}) failed")
                return False
            time.sleep(0.05)

        result = pump.start_channel(channel)
        logger.info(f"Pump {device_id} CH{channel}: start result={result}")
        return result

    def _validate_pump_units(self, device_id: str, channel: int,
                              flow_unit, time_unit, volume_unit, interval_time_unit) -> bool:
        from src.protocols.pump_params import FlowUnit, TimeUnit, VolumeUnit

        if flow_unit is not None:
            try:
                FlowUnit(flow_unit)
            except ValueError:
                logger.error(f"Pump {device_id} CH{channel}: invalid flow_unit={flow_unit}")
                return False

        if time_unit is not None:
            try:
                TimeUnit(time_unit)
            except ValueError:
                logger.error(f"Pump {device_id} CH{channel}: invalid time_unit={time_unit}")
                return False

        if volume_unit is not None:
            try:
                VolumeUnit(volume_unit)
            except ValueError:
                logger.error(f"Pump {device_id} CH{channel}: invalid volume_unit={volume_unit}")
                return False

        if interval_time_unit is not None:
            try:
                TimeUnit(interval_time_unit)
            except ValueError:
                logger.error(f"Pump {device_id} CH{channel}: invalid interval_time_unit={interval_time_unit}")
                return False

        return True

    def _validate_pump_repeat_params(self, device_id: str, channel: int,
                                      repeat_count, interval_time) -> bool:
        if repeat_count is not None:
            if not isinstance(repeat_count, (int, float)):
                logger.error(f"Pump {device_id} CH{channel}: repeat_count must be numeric, got {type(repeat_count).__name__}")
                return False
            if isinstance(repeat_count, float):
                if repeat_count != int(repeat_count):
                    logger.error(f"Pump {device_id} CH{channel}: repeat_count={repeat_count} must be integer")
                    return False
                repeat_count = int(repeat_count)
            if not (0 <= repeat_count <= 9999):
                logger.error(f"Pump {device_id} CH{channel}: repeat_count={repeat_count} out of range [0, 9999]")
                return False

        if interval_time is not None:
            if interval_time < 0:
                logger.error(f"Pump {device_id} CH{channel}: interval_time={interval_time} must be >= 0")
                return False
            if interval_time > 0 and interval_time < 0.1:
                logger.error(f"Pump {device_id} CH{channel}: interval_time={interval_time} below minimum 0.1sec")
                return False

        if repeat_count is not None and repeat_count != 1 and (interval_time is None or interval_time == 0):
            logger.error(f"Pump {device_id} CH{channel}: repeat_count={repeat_count} (0=infinite) requires interval_time > 0")
            return False

        return True

    def _set_pump_flow_and_mode(self, pump: LabSmartPumpDevice, device_id: str, channel: int,
                                  flow_rate: float, flow_unit, mode) -> bool:
        from src.protocols.pump_params import PumpRunMode

        if not pump.set_run_mode(channel, PumpRunMode.FLOW_MODE):
            logger.warning(f"Pump {device_id} CH{channel} set_run_mode(FLOW_MODE) for flow_rate failed")
            return False
        time.sleep(0.1)

        if not pump.set_flow_rate(channel, flow_rate, flow_unit):
            logger.warning(f"Pump {device_id} CH{channel} set_flow_rate({flow_rate} {flow_unit}) failed")
            return False
        time.sleep(0.05)

        if mode != PumpRunMode.FLOW_MODE:
            if not pump.set_run_mode(channel, mode):
                logger.warning(f"Pump {device_id} CH{channel} set_run_mode({mode}) failed")
                return False
            time.sleep(0.1)

        return True

    def _set_pump_mode_params(self, pump: LabSmartPumpDevice, device_id: str, channel: int,
                               mode, run_time, dispense_volume, time_unit, volume_unit) -> bool:
        from src.protocols.pump_params import PumpRunMode

        if mode == PumpRunMode.FLOW_MODE:
            return True

        if mode in (PumpRunMode.TIME_QUANTITY, PumpRunMode.TIME_SPEED):
            if run_time is not None:
                if not pump.set_run_time(channel, run_time, time_unit):
                    logger.warning(f"Pump {device_id} CH{channel} set_run_time failed")
                    return False
                time.sleep(0.05)

        if mode in (PumpRunMode.TIME_QUANTITY, PumpRunMode.QUANTITY_SPEED):
            if dispense_volume is not None:
                if not pump.set_dispense_volume(channel, dispense_volume, volume_unit):
                    logger.warning(f"Pump {device_id} CH{channel} set_dispense_volume failed")
                    return False
                time.sleep(0.05)

        return True

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
        for microwave in self._microwaves.values():
            try:
                if microwave.is_connected():
                    microwave.disconnect()
            except Exception:
                pass
