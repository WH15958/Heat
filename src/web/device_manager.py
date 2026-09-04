import math
import threading
import time
from typing import Any, Dict, Optional

from src.devices.heater import AIHeaterDevice, HeaterConfig
from src.devices.microwave import MicrowaveConfig, MicrowaveDevice
from src.devices.peristaltic_pump import (
    LabSmartPumpDevice,
    PeristalticPumpConfig,
    PumpChannelConfig,
)
from src.protocols.microwave_params import MODE_CONTROL_MASKS
from src.protocols.pump_params import get_channel_address
from src.utils.logger import get_logger
from src.utils.serial_binding import resolve_connection

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
        self._heater_locks: Dict[str, threading.Lock] = {}
        self._heater_stop_generations: Dict[str, int] = {}
        self._pump_locks: Dict[str, threading.Lock] = {}
        self._pump_abort_events: Dict[str, threading.Event] = {}
        self._pump_stop_generations: Dict[str, int] = {}
        self._microwave_locks: Dict[str, threading.Lock] = {}
        self._microwave_stop_generations: Dict[str, int] = {}
        self._pump_channel_index: Dict[str, int] = {}
        self._pump_channel_cache: Dict[str, Dict[str, dict]] = {}
        self._global_stop_depth = 0
        self._last_emergency_stop_report: list[dict] = []

    def add_heater(
        self,
        device_id: str,
        port: str,
        baudrate: int = 9600,
        address: int = 1,
        parity: str = "N",
        timeout: float = 2.0,
        decimal_places: int = 1,
        temperature_unit: str = "C",
        max_temperature: float = 400.0,
        min_temperature: float = 0.0,
        safety_limit: float = 450.0,
        poll_interval: float = 1.0,
        retry_count: int = 3,
        retry_delay: float = 0.5,
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
            connection_params={
                "port": port,
                "baudrate": baudrate,
                "address": address,
                "parity": parity,
            },
            timeout=timeout,
            poll_interval=poll_interval,
            retry_count=retry_count,
            retry_delay=retry_delay,
            decimal_places=decimal_places,
            temperature_unit=temperature_unit,
            max_temperature=max_temperature,
            min_temperature=min_temperature,
            safety_limit=safety_limit,
        )
        self._heaters[device_id] = AIHeaterDevice(config)
        self._heater_locks[device_id] = threading.Lock()
        self._heater_stop_generations[device_id] = 0
        self._heater_bindings[device_id] = self._normalize_binding_info(binding_info, port)
        logger.info(f"Registered heater: {device_id} on {port}")
        if safety_limit > max_temperature:
            logger.warning(
                f"Heater {device_id}: safety_limit={safety_limit} C is above "
                f"max_temperature={max_temperature} C and does not further "
                "reduce the software command ceiling"
            )
        return device_id

    def add_pump(
        self,
        device_id: str,
        port: str,
        baudrate: int = 19200,
        slave_address: int = 1,
        parity: str = "E",
        timeout: float = 2.0,
        poll_interval: float = 1.0,
        retry_count: int = 3,
        retry_delay: float = 0.5,
        stopbits: int = 1,
        bytesize: int = 8,
        channels: Optional[list] = None,
        tube_model_readback_overrides: Optional[Dict[int, int]] = None,
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
                        max_flow_rate=ch.get("max_flow_rate", 100.0),
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
                "stopbits": stopbits,
                "bytesize": bytesize,
            },
            slave_address=slave_address,
            timeout=timeout,
            poll_interval=poll_interval,
            retry_count=retry_count,
            retry_delay=retry_delay,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            channels=channel_configs,
            tube_model_readback_overrides=dict(
                tube_model_readback_overrides or {}
            ),
        )
        self._pumps[device_id] = LabSmartPumpDevice(config)
        self._pump_locks[device_id] = threading.Lock()
        self._pump_abort_events[device_id] = threading.Event()
        self._pump_stop_generations[device_id] = 0
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
        self._microwave_locks[device_id] = threading.Lock()
        self._microwave_stop_generations[device_id] = 0
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
        self._request_heater_stop(device_id)
        with self._heater_control_lock(device_id):
            return self._stop_and_disconnect(
                "heater", device_id, heater, heater.stop, "Disconnect"
            )

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
        self._request_pump_abort(device_id)
        with self._pump_control_lock(device_id):
            return self._stop_and_disconnect(
                "pump", device_id, pump, pump.stop_all, "Disconnect"
            )

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
        self._request_microwave_stop(device_id)
        with self._microwave_control_lock(device_id):
            return self._stop_and_disconnect(
                "microwave", device_id, microwave, microwave.stop, "Disconnect"
            )

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
            read_ok = False
            try:
                ch_data = pump.read_channel_status(ch)
                if ch_data is not None:
                    self._pump_channel_cache[device_id][str(ch)] = {
                        "running": ch_data.running,
                        "run_status": getattr(
                            getattr(ch_data, "run_status", None), "name",
                            "START" if ch_data.running else "STOP",
                        ),
                        "flow_rate": ch_data.flow_rate,
                        "volume": ch_data.dispensed_volume,
                        "direction": ch_data.direction.name
                        if ch_data.direction is not None
                        else None,
                        "flow_unit": ch_data.flow_unit.name
                        if ch_data.flow_unit is not None
                        else "ML_MIN",
                    }
                    read_ok = True
            except Exception as e:
                logger.warning(f"Pump {device_id} CH{ch} read error: {e}")

            self._pump_channel_cache[device_id][str(ch)]["read_ok"] = read_ok

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
        with self._microwave_control_lock(device_id):
            if not microwave.is_connected():
                logger.warning(f"Microwave {device_id} not connected")
                return False
            return microwave.configure_manual(segments)

    def configure_microwave_auto_power(self, device_id: str, segments) -> bool:
        """配置微波仪自动功率模式参数"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        with self._microwave_control_lock(device_id):
            if not microwave.is_connected():
                logger.warning(f"Microwave {device_id} not connected")
                return False
            return microwave.configure_auto_power(segments)

    def configure_microwave_constant_rate(self, device_id: str, segments) -> bool:
        """配置微波仪恒速率模式参数"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        with self._microwave_control_lock(device_id):
            if not microwave.is_connected():
                logger.warning(f"Microwave {device_id} not connected")
                return False
            return microwave.configure_constant_rate(segments)

    def start_microwave(self, device_id: str, mode) -> bool:
        """启动微波仪输出"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        start_generation = self._microwave_start_generation(device_id)
        if start_generation is None:
            logger.warning(f"Microwave {device_id} start rejected during global stop")
            return False
        if not microwave.is_connected():
            logger.warning(f"Microwave {device_id} not connected")
            return False
        with self._microwave_control_lock(device_id):
            if self._microwave_generation(device_id) != start_generation:
                logger.warning(f"Microwave {device_id} start superseded by stop request")
                return False
            if not microwave.is_connected():
                logger.warning(f"Microwave {device_id} not connected")
                return False
            return microwave.start(mode)

    def stop_microwave(self, device_id: str) -> bool:
        """停止微波仪输出"""
        microwave = self._microwaves.get(device_id)
        if microwave is None:
            raise ValueError(f"Microwave not found: {device_id}")
        self._request_microwave_stop(device_id)
        with self._microwave_control_lock(device_id):
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
        self._begin_global_stop()
        try:
            return self._emergency_stop_all_devices()
        finally:
            self._end_global_stop()

    def _emergency_stop_all_devices(self) -> bool:
        """Issue the device-specific emergency stop commands."""
        logger.warning("EMERGENCY STOP ALL DEVICES")
        success = True
        attempted = False
        report = []
        registered = bool(self._heaters or self._pumps or self._microwaves)
        for device_id, heater in self._heaters.items():
            self._request_heater_stop(device_id)
            with self._heater_control_lock(device_id):
                device_attempted = False
                try:
                    if not heater.is_connected():
                        success = False
                        logger.warning(f"Emergency stop heater skipped, not connected: {heater.config.device_id}")
                        report.append(self._stop_report("heater", device_id, False, None, "not_connected"))
                        continue
                    attempted = True
                    device_attempted = True
                    result = heater.emergency_stop()
                    report.append(self._stop_report("heater", device_id, True, result))
                    if result is False:
                        success = False
                        logger.error(f"Emergency stop heater returned false: {heater.config.device_id}")
                except Exception as e:
                    success = False
                    report.append(self._stop_report(
                        "heater", device_id, device_attempted,
                        False if device_attempted else None, str(e),
                    ))
                    logger.error(f"Emergency stop heater failed: {e}")
        for device_id, pump in self._pumps.items():
            self._request_pump_abort(device_id)
            pump_lock = self._pump_locks.get(device_id)
            if pump_lock:
                pump_lock.acquire()
            device_attempted = False
            try:
                if not pump.is_connected():
                    success = False
                    logger.warning(f"Emergency stop pump skipped, not connected: {pump.config.device_id}")
                    report.append(self._stop_report("pump", device_id, False, None, "not_connected"))
                    continue
                attempted = True
                device_attempted = True
                result = pump.emergency_stop()
                report.append(self._stop_report("pump", device_id, True, result))
                if result is False:
                    success = False
                    logger.error(f"Emergency stop pump returned false: {pump.config.device_id}")
            except Exception as e:
                success = False
                report.append(self._stop_report(
                    "pump", device_id, device_attempted,
                    False if device_attempted else None, str(e),
                ))
                logger.error(f"Emergency stop pump failed: {e}")
            finally:
                if pump_lock:
                    pump_lock.release()
        for device_id, microwave in self._microwaves.items():
            self._request_microwave_stop(device_id)
            with self._microwave_control_lock(device_id):
                device_attempted = False
                try:
                    if not microwave.is_connected():
                        success = False
                        logger.warning(
                            f"Emergency stop microwave skipped, not connected: {microwave.config.device_id}"
                        )
                        report.append(self._stop_report("microwave", device_id, False, None, "not_connected"))
                        continue
                    attempted = True
                    device_attempted = True
                    result = microwave.emergency_stop()
                    report.append(self._stop_report("microwave", device_id, True, result))
                    if result is False:
                        success = False
                        logger.error(
                            f"Emergency stop microwave returned false: {microwave.config.device_id}"
                        )
                except Exception as e:
                    success = False
                    report.append(self._stop_report(
                        "microwave", device_id, device_attempted,
                        False if device_attempted else None, str(e),
                    ))
                    logger.error(f"Emergency stop microwave failed: {e}")
        if not registered:
            logger.error("Emergency stop requested with no registered devices")
        self._last_emergency_stop_report = report
        return success and attempted

    @staticmethod
    def _stop_report(
        kind: str,
        device_id: str,
        attempted: bool,
        result: Optional[bool],
        reason: Optional[str] = None,
    ) -> dict:
        confirmed = result is True
        return {
            "device_type": kind,
            "device_id": device_id,
            "connected": attempted,
            "attempted": attempted,
            "command_result": result,
            "final_state": "confirmed_stopped" if confirmed else "unconfirmed",
            "success": confirmed,
            "reason": reason or (None if confirmed else "stop_not_confirmed"),
        }

    def get_last_emergency_stop_report(self) -> list[dict]:
        """Return a copy of the latest global-stop device results."""
        return [dict(item) for item in self._last_emergency_stop_report]

    def get_last_command_error(self, device_id: str) -> Optional[str]:
        """Return the latest driver verification detail for one device."""
        device = (
            self._heaters.get(device_id)
            or self._pumps.get(device_id)
            or self._microwaves.get(device_id)
        )
        detail = getattr(device, "last_command_error", None)
        return detail if isinstance(detail, str) and detail else None

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
                "channels": {
                    str(channel.channel): {
                        "enabled": channel.enabled,
                        "tube_model": channel.tube_model,
                        "max_flow_rate": channel.max_flow_rate,
                    }
                    for channel in p.config.channels
                },
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
            "control_word": data.get("control_word"),
            "control_active": data.get("control_active"),
            "output_active": bool(data.get("output_active", False)),
            "stop_confirmed": bool(data.get("stop_confirmed", False)),
            "status_confirmed": data.get("control_active") is not None,
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
        with self._heater_control_lock(device_id):
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
        start_generation = self._heater_start_generation(device_id)
        if start_generation is None:
            logger.warning(f"Heater {device_id} start rejected during global stop")
            return False
        if not heater.is_connected():
            logger.warning(f"Heater {device_id} not connected")
            return False
        with self._heater_control_lock(device_id):
            if self._heater_generation(device_id) != start_generation:
                logger.warning(f"Heater {device_id} start superseded by stop request")
                return False
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
        self._request_heater_stop(device_id)
        with self._heater_control_lock(device_id):
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
        start_generation = self._pump_start_generation(device_id)
        if start_generation is None:
            logger.warning(f"Pump {device_id} CH{channel}: start rejected during global stop")
            return False
        if not pump.is_connected():
            logger.warning(f"Pump {device_id} not connected")
            return False
        try:
            from src.protocols.pump_params import PumpDirection, PumpRunMode

            direction = PumpDirection(direction)
            mode = PumpRunMode(mode)
        except (TypeError, ValueError):
            logger.error(
                "Pump %s CH%s: invalid direction=%r or mode=%r",
                device_id,
                channel,
                direction,
                mode,
            )
            return False
        if mode != PumpRunMode.FLOW_MODE and repeat_count is None:
            repeat_count = 1
        if not self._validate_pump_start_params(
            pump,
            device_id,
            channel,
            flow_rate,
            mode,
            run_time,
            dispense_volume,
            tube_model,
            flow_unit,
            time_unit,
            volume_unit,
            repeat_count,
            interval_time,
            interval_time_unit,
        ):
            return False
        abort_event = self._pump_abort_events.get(device_id)
        pump_lock = self._pump_locks.get(device_id)
        if pump_lock:
            pump_lock.acquire()
        try:
            if self._pump_generation(device_id) != start_generation:
                logger.warning(f"Pump {device_id} CH{channel}: start superseded by stop request")
                return False
            if abort_event:
                abort_event.clear()
            if self._pump_generation(device_id) != start_generation:
                logger.warning(f"Pump {device_id} CH{channel}: start cancelled by concurrent stop request")
                return False
            return self._start_pump_channel_inner(
                pump, device_id, channel, flow_rate, direction, mode,
                run_time, dispense_volume, tube_model, flow_unit, time_unit,
                volume_unit, repeat_count, interval_time, interval_time_unit,
                abort_event,
            )
        finally:
            if pump_lock:
                pump_lock.release()

    def _start_pump_channel_inner(self, pump: LabSmartPumpDevice, device_id: str,
                                   channel: int, flow_rate: float, direction, mode,
                                   run_time, dispense_volume, tube_model=None, flow_unit=None,
                                   time_unit=None, volume_unit=None, repeat_count=None,
                                   interval_time=None, interval_time_unit=None,
                                   abort_event=None) -> bool:
        from src.protocols.pump_params import FlowUnit, PumpRunMode, TimeUnit, VolumeUnit

        if not pump.stop_channel(channel):
            logger.warning(f"Pump {device_id} CH{channel} pre-configuration stop failed")
            return False
        time.sleep(0.2)
        if abort_event and abort_event.is_set():
            logger.warning(f"Pump {device_id} CH{channel}: start cancelled after stop")
            return False

        if not pump.enable_channel(channel, True):
            logger.warning(f"Pump {device_id} CH{channel} enable failed")
            return False
        if not pump.wait_for_register_value(
            get_channel_address(0, channel), 1,
            label=f"Pump {device_id} CH{channel} enable",
        ):
            return False
        logger.info(f"Pump {device_id} CH{channel}: enable OK")

        effective_tube_model = tube_model
        if effective_tube_model is None:
            ch_config = pump.get_channel_config(channel)
            configured_tube_model = getattr(ch_config, "tube_model", None)
            if (
                isinstance(configured_tube_model, int)
                and not isinstance(configured_tube_model, bool)
                and 0 <= configured_tube_model <= 13
            ):
                effective_tube_model = configured_tube_model
            else:
                effective_tube_model = pump.get_tube_model(channel)
        if effective_tube_model is not None:
            if not pump.set_tube_model(channel, effective_tube_model):
                logger.warning(f"Pump {device_id} CH{channel} set_tube_model({effective_tube_model}) failed")
                return False
            if not pump.wait_for_tube_model(channel, effective_tube_model):
                return False
        else:
            logger.warning(f"Pump {device_id} CH{channel} tube_model not set, flow rate range may be limited")

        if abort_event and abort_event.is_set():
            logger.warning(f"Pump {device_id} CH{channel}: start cancelled after tube setup")
            return False

        if not pump.set_direction(channel, direction):
            logger.warning(f"Pump {device_id} CH{channel} set_direction failed")
            return False
        if not pump.wait_for_register_value(
            get_channel_address(2, channel), int(direction),
            label=f"Pump {device_id} CH{channel} direction",
        ):
            return False

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
            if not pump.wait_for_register_value(
                get_channel_address(100, channel), int(repeat_count),
                label=f"Pump {device_id} CH{channel} repeat_count",
            ):
                return False

        if interval_time is not None:
            if not pump.set_interval_time(channel, interval_time, effective_interval_time_unit):
                logger.warning(f"Pump {device_id} CH{channel} set_interval_time({interval_time} {effective_interval_time_unit}) failed")
                return False
            if not pump.wait_for_float_value(
                get_channel_address(101, channel), interval_time,
                label=f"Pump {device_id} CH{channel} interval_time",
            ):
                return False
            if not pump.wait_for_register_value(
                get_channel_address(103, channel), int(effective_interval_time_unit),
                label=f"Pump {device_id} CH{channel} interval_time_unit",
            ):
                return False

        if abort_event and abort_event.is_set():
            logger.warning(f"Pump {device_id} CH{channel}: start cancelled before start command")
            return False
        result = pump.start_channel(channel)
        logger.info(f"Pump {device_id} CH{channel}: start result={result}")
        return result

    def _validate_pump_start_params(
        self,
        pump: LabSmartPumpDevice,
        device_id: str,
        channel: int,
        flow_rate,
        mode,
        run_time,
        dispense_volume,
        tube_model,
        flow_unit,
        time_unit,
        volume_unit,
        repeat_count,
        interval_time,
        interval_time_unit,
    ) -> bool:
        from src.protocols.pump_params import FlowUnit, PumpRunMode, TimeUnit, VolumeUnit

        if not self._validate_pump_units(
            device_id, channel, flow_unit, time_unit, volume_unit, interval_time_unit
        ):
            return False

        numeric_values = {
            "flow_rate": flow_rate,
            "run_time": run_time,
            "dispense_volume": dispense_volume,
            "interval_time": interval_time,
        }
        for name, value in numeric_values.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                logger.error(f"Pump {device_id} CH{channel}: {name} must be finite numeric")
                return False
        if isinstance(repeat_count, bool):
            logger.error(f"Pump {device_id} CH{channel}: repeat_count must be integer")
            return False
        if not self._validate_pump_repeat_params(
            device_id, channel, repeat_count, interval_time
        ):
            return False
        if not (0.01 <= flow_rate <= 9999):
            logger.error(
                f"Pump {device_id} CH{channel}: flow_rate must be in protocol range [0.01, 9999]"
            )
            return False
        if mode in (PumpRunMode.TIME_QUANTITY, PumpRunMode.TIME_SPEED):
            if run_time is None or not (0.1 <= run_time <= 9999):
                logger.error(
                    f"Pump {device_id} CH{channel}: {mode.name} requires run_time in [0.1, 9999]"
                )
                return False
        if mode in (PumpRunMode.TIME_QUANTITY, PumpRunMode.QUANTITY_SPEED):
            if dispense_volume is None or not (0.01 <= dispense_volume <= 9999):
                logger.error(
                    f"Pump {device_id} CH{channel}: {mode.name} requires dispense_volume in [0.01, 9999]"
                )
                return False
        if interval_time is not None and interval_time > 999:
            logger.error(f"Pump {device_id} CH{channel}: interval_time must be <= 999")
            return False
        if tube_model is not None:
            if isinstance(tube_model, bool) or not isinstance(tube_model, int) or not (0 <= tube_model <= 13):
                logger.error(f"Pump {device_id} CH{channel}: invalid tube_model={tube_model}")
                return False

        channel_config = pump.get_channel_config(channel)
        if channel_config is None:
            logger.error(f"Pump {device_id} CH{channel}: channel is not configured")
            return False
        if not channel_config.enabled:
            logger.error(f"Pump {device_id} CH{channel}: channel is disabled in configuration")
            return False
        max_flow_rate = channel_config.max_flow_rate
        if (
            isinstance(max_flow_rate, bool)
            or not isinstance(max_flow_rate, (int, float))
            or not math.isfinite(max_flow_rate)
            or max_flow_rate <= 0
        ):
            logger.error(
                f"Pump {device_id} CH{channel}: invalid configured max_flow_rate={max_flow_rate!r}"
            )
            return False
        effective_unit = FlowUnit(flow_unit) if flow_unit is not None else FlowUnit.ML_MIN
        if effective_unit == FlowUnit.RPM and flow_rate > 150:
            logger.error(f"Pump {device_id} CH{channel}: RPM flow_rate must be <= 150")
            return False
        flow_ml_min = None
        if effective_unit == FlowUnit.UL_MIN:
            flow_ml_min = flow_rate / 1000.0
        elif effective_unit == FlowUnit.ML_MIN:
            flow_ml_min = flow_rate
        elif effective_unit == FlowUnit.L_MIN:
            flow_ml_min = flow_rate * 1000.0

        if mode == PumpRunMode.TIME_QUANTITY:
            if effective_unit == FlowUnit.RPM:
                logger.error(
                    f"Pump {device_id} CH{channel}: TIME_QUANTITY requires a volumetric flow unit"
                )
                return False
            effective_time_unit = TimeUnit(time_unit) if time_unit is not None else TimeUnit.SECOND
            effective_volume_unit = (
                VolumeUnit(volume_unit) if volume_unit is not None else VolumeUnit.ML
            )
            time_minutes = run_time / 60.0
            if effective_time_unit == TimeUnit.MINUTE:
                time_minutes = run_time
            elif effective_time_unit == TimeUnit.HOUR:
                time_minutes = run_time * 60.0
            volume_ml = dispense_volume
            if effective_volume_unit == VolumeUnit.UL:
                volume_ml = dispense_volume / 1000.0
            elif effective_volume_unit == VolumeUnit.L:
                volume_ml = dispense_volume * 1000.0
            implied_flow_ml_min = volume_ml / time_minutes
            if not math.isfinite(implied_flow_ml_min) or implied_flow_ml_min > max_flow_rate:
                logger.error(
                    "Pump %s CH%s: TIME_QUANTITY implied flow %.6g mL/min exceeds configured max %.6g mL/min",
                    device_id,
                    channel,
                    implied_flow_ml_min,
                    max_flow_rate,
                )
                return False
            if flow_ml_min is not None and not math.isclose(
                flow_ml_min, implied_flow_ml_min, rel_tol=1e-6, abs_tol=1e-9
            ):
                logger.error(
                    "Pump %s CH%s: TIME_QUANTITY flow %.6g mL/min does not match volume/time %.6g mL/min",
                    device_id,
                    channel,
                    flow_ml_min,
                    implied_flow_ml_min,
                )
                return False
        if (
            flow_ml_min is not None
            and flow_ml_min > max_flow_rate
        ):
            logger.error(
                "Pump %s CH%s: flow %.6g mL/min exceeds configured max %.6g mL/min",
                device_id,
                channel,
                flow_ml_min,
                max_flow_rate,
            )
            return False
        return True

    def _validate_pump_units(self, device_id: str, channel: int,
                              flow_unit, time_unit, volume_unit, interval_time_unit) -> bool:
        from src.protocols.pump_params import FlowUnit, TimeUnit, VolumeUnit

        if flow_unit is not None:
            try:
                FlowUnit(flow_unit)
            except (TypeError, ValueError):
                logger.error(f"Pump {device_id} CH{channel}: invalid flow_unit={flow_unit}")
                return False

        if time_unit is not None:
            try:
                TimeUnit(time_unit)
            except (TypeError, ValueError):
                logger.error(f"Pump {device_id} CH{channel}: invalid time_unit={time_unit}")
                return False

        if volume_unit is not None:
            try:
                VolumeUnit(volume_unit)
            except (TypeError, ValueError):
                logger.error(f"Pump {device_id} CH{channel}: invalid volume_unit={volume_unit}")
                return False

        if interval_time_unit is not None:
            try:
                TimeUnit(interval_time_unit)
            except (TypeError, ValueError):
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
        if not pump.wait_for_register_value(
            get_channel_address(6, channel), int(PumpRunMode.FLOW_MODE),
            label=f"Pump {device_id} CH{channel} flow setup mode",
        ):
            return False

        if not pump.set_flow_rate(channel, flow_rate, flow_unit):
            logger.warning(f"Pump {device_id} CH{channel} set_flow_rate({flow_rate} {flow_unit}) failed")
            return False
        if not pump.wait_for_float_value(
            get_channel_address(110, channel), flow_rate,
            label=f"Pump {device_id} CH{channel} flow_rate",
        ):
            return False
        if not pump.wait_for_register_value(
            get_channel_address(112, channel), int(flow_unit),
            label=f"Pump {device_id} CH{channel} flow_unit",
        ):
            return False

        if mode != PumpRunMode.FLOW_MODE:
            if not pump.set_run_mode(channel, mode):
                logger.warning(f"Pump {device_id} CH{channel} set_run_mode({mode}) failed")
                return False
            if not pump.wait_for_register_value(
                get_channel_address(6, channel), int(mode),
                label=f"Pump {device_id} CH{channel} run_mode",
            ):
                return False

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
                if not pump.wait_for_float_value(
                    get_channel_address(107, channel), run_time,
                    label=f"Pump {device_id} CH{channel} run_time",
                ):
                    return False
                if not pump.wait_for_register_value(
                    get_channel_address(109, channel), int(time_unit),
                    label=f"Pump {device_id} CH{channel} run_time_unit",
                ):
                    return False

        if mode in (PumpRunMode.TIME_QUANTITY, PumpRunMode.QUANTITY_SPEED):
            if dispense_volume is not None:
                if not pump.set_dispense_volume(channel, dispense_volume, volume_unit):
                    logger.warning(f"Pump {device_id} CH{channel} set_dispense_volume failed")
                    return False
                if not pump.wait_for_float_value(
                    get_channel_address(104, channel), dispense_volume,
                    label=f"Pump {device_id} CH{channel} dispense_volume",
                ):
                    return False
                if not pump.wait_for_register_value(
                    get_channel_address(106, channel), int(volume_unit),
                    label=f"Pump {device_id} CH{channel} volume_unit",
                ):
                    return False

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
        if channel is not None and not (1 <= channel <= 4):
            raise ValueError(f"Invalid channel: {channel}, must be 1-4")
        self._request_pump_abort(device_id)
        if not pump.is_connected():
            logger.warning(f"Pump {device_id} not connected")
            return False
        pump_lock = self._pump_locks.get(device_id)
        if pump_lock:
            pump_lock.acquire()
        try:
            if channel is None:
                return pump.stop_all()
            return pump.stop_channel(channel)
        finally:
            if pump_lock:
                pump_lock.release()

    def cleanup(self) -> bool:
        """Stop connected devices before releasing their resources."""
        self._begin_global_stop()
        try:
            return self._cleanup_devices()
        finally:
            self._end_global_stop()

    def _cleanup_devices(self) -> bool:
        """Stop and disconnect every registered device."""
        success = True
        for device_id, heater in self._heaters.items():
            self._request_heater_stop(device_id)
            with self._heater_control_lock(device_id):
                device_success = self._cleanup_device(
                    "heater", device_id, heater, heater.stop
                )
            success = device_success and success
        for device_id, pump in self._pumps.items():
            self._request_pump_abort(device_id)
            with self._pump_control_lock(device_id):
                device_success = self._cleanup_device(
                    "pump", device_id, pump, pump.stop_all
                )
                success = device_success and success
        for device_id, microwave in self._microwaves.items():
            self._request_microwave_stop(device_id)
            with self._microwave_control_lock(device_id):
                device_success = self._cleanup_device(
                    "microwave", device_id, microwave, microwave.stop
                )
            success = device_success and success
        return success

    @staticmethod
    def _cleanup_device(kind: str, device_id: str, device, stop) -> bool:
        return DeviceManager._stop_and_disconnect(
            kind, device_id, device, stop, "Cleanup"
        )

    @staticmethod
    def _stop_and_disconnect(
        kind: str, device_id: str, device, stop, operation: str
    ) -> bool:
        connection_check_failed = False
        try:
            connected = device.is_connected()
        except Exception as e:
            connected = True
            connection_check_failed = True
            logger.error(
                f"{operation} {kind} connection check failed: {device_id}: {e}"
            )

        if not connected:
            return not connection_check_failed

        try:
            if not stop():
                logger.critical(
                    f"{operation} {kind} stop returned false; "
                    f"connection retained for retry: {device_id}"
                )
                return False
        except Exception as e:
            logger.critical(
                f"{operation} {kind} stop failed; connection retained for retry: "
                f"{device_id}: {e}"
            )
            return False

        try:
            if not device.disconnect():
                logger.error(
                    f"{operation} {kind} disconnect returned false: {device_id}"
                )
                return False
        except Exception as e:
            logger.error(f"{operation} {kind} disconnect failed: {device_id}: {e}")
            return False
        return not connection_check_failed

    def _begin_global_stop(self) -> None:
        with self._lock:
            self._global_stop_depth += 1
            for device_id in self._heaters:
                self._heater_stop_generations[device_id] = (
                    self._heater_stop_generations.get(device_id, 0) + 1
                )
            for device_id in self._pumps:
                self._pump_stop_generations[device_id] = (
                    self._pump_stop_generations.get(device_id, 0) + 1
                )
            for device_id in self._microwaves:
                self._microwave_stop_generations[device_id] = (
                    self._microwave_stop_generations.get(device_id, 0) + 1
                )
            for abort_event in self._pump_abort_events.values():
                abort_event.set()

    def _end_global_stop(self) -> None:
        with self._lock:
            self._global_stop_depth = max(self._global_stop_depth - 1, 0)

    def _start_generation(self, generations: Dict[str, int], device_id: str):
        with self._lock:
            if self._global_stop_depth > 0:
                return None
            return generations.get(device_id, 0)

    def _heater_start_generation(self, device_id: str):
        return self._start_generation(self._heater_stop_generations, device_id)

    def _pump_start_generation(self, device_id: str):
        return self._start_generation(self._pump_stop_generations, device_id)

    def _microwave_start_generation(self, device_id: str):
        return self._start_generation(self._microwave_stop_generations, device_id)

    def _heater_control_lock(self, device_id: str) -> threading.Lock:
        with self._lock:
            return self._heater_locks.setdefault(device_id, threading.Lock())

    def _pump_control_lock(self, device_id: str) -> threading.Lock:
        with self._lock:
            return self._pump_locks.setdefault(device_id, threading.Lock())

    def _heater_generation(self, device_id: str) -> int:
        with self._lock:
            return self._heater_stop_generations.get(device_id, 0)

    def _request_heater_stop(self, device_id: str) -> None:
        with self._lock:
            self._heater_stop_generations[device_id] = (
                self._heater_stop_generations.get(device_id, 0) + 1
            )

    def _microwave_control_lock(self, device_id: str) -> threading.Lock:
        with self._lock:
            return self._microwave_locks.setdefault(device_id, threading.Lock())

    def _microwave_generation(self, device_id: str) -> int:
        with self._lock:
            return self._microwave_stop_generations.get(device_id, 0)

    def _request_microwave_stop(self, device_id: str) -> None:
        with self._lock:
            self._microwave_stop_generations[device_id] = (
                self._microwave_stop_generations.get(device_id, 0) + 1
            )

    def _pump_generation(self, device_id: str) -> int:
        with self._lock:
            return self._pump_stop_generations.get(device_id, 0)

    def _request_pump_abort(self, device_id: str) -> None:
        with self._lock:
            self._pump_stop_generations[device_id] = (
                self._pump_stop_generations.get(device_id, 0) + 1
            )
        abort_event = self._pump_abort_events.get(device_id)
        if abort_event:
            abort_event.set()
