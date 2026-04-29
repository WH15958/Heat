"""
LabSmart系列蠕动泵设备驱动

实现蠕动泵的完整控制功能，包括：
- 四通道独立控制
- 四种运行模式（流量、定时定量、定时定速、定量定速）
- 启停、换向、速度控制
- 流量校准
- 状态监控
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
import logging
import time
import threading
import copy
import atexit
import weakref
import struct

from devices.base_device import (
    BaseDevice, DeviceConfig, DeviceData, DeviceInfo, 
    DeviceStatus, DeviceType
)
from protocols.modbus_rtu import ModbusRTUProtocol, ModbusException
from protocols.pump_params import (
    PumpRunMode, PumpRunStatus, PumpDirection, TimeUnit, FlowUnit,
    get_channel_address, get_register_info,
    CHANNEL_CONTROL_REGISTERS, PARAMETER_REGISTERS, STATUS_REGISTERS,
    CALIBRATION_REGISTERS, PUMP_HEAD_MODELS, PUMP_TUBE_MODELS,
)

logger = logging.getLogger(__name__)


@dataclass
class PumpChannelConfig:
    """蠕动泵通道配置"""
    channel: int
    enabled: bool = True
    pump_head: int = 5
    tube_model: int = 1
    suck_back_angle: int = 0
    default_direction: PumpDirection = PumpDirection.CLOCKWISE
    max_flow_rate: float = 100.0


@dataclass
class PumpChannelData:
    """蠕动泵通道数据"""
    channel: int
    enabled: bool = False
    running: bool = False
    paused: bool = False
    direction: PumpDirection = PumpDirection.CLOCKWISE
    run_mode: PumpRunMode = PumpRunMode.FLOW_MODE
    flow_rate: float = 0.0
    flow_unit: FlowUnit = FlowUnit.ML_MIN
    current_speed: float = 0.0
    dispensed_volume: float = 0.0
    remaining_volume: float = 0.0
    remaining_time: float = 0.0
    repeat_count: int = 0
    completed_repeats: int = 0


@dataclass
class PeristalticPumpConfig(DeviceConfig):
    """蠕动泵配置"""
    channels: List[PumpChannelConfig] = field(default_factory=list)
    slave_address: int = 1
    baudrate: int = 9600
    parity: str = 'N'
    stopbits: int = 1
    bytesize: int = 8
    default_run_mode: PumpRunMode = PumpRunMode.FLOW_MODE


@dataclass
class PeristalticPumpData(DeviceData):
    """蠕动泵数据"""
    channels: Dict[int, PumpChannelData] = field(default_factory=dict)
    total_dispensed_volume: float = 0.0


class LabSmartPumpDevice(BaseDevice):
    """
    LabSmart系列蠕动泵设备驱动
    
    支持LabSmart系列多通道独立控制蠕动泵，通过MODBUS-RTU协议实现完整控制功能。
    
    Features:
        - 四通道独立控制
        - 四种运行模式
        - 启停、暂停、换向控制
        - 流速和流量设置
        - 流量校准
        - 实时状态监控
    
    Example:
        >>> config = PeristalticPumpConfig(
        ...     device_id="pump1",
        ...     connection_params={"port": "COM4"},
        ...     slave_address=1,
        ...     channels=[PumpChannelConfig(channel=1)]
        ... )
        >>> pump = LabSmartPumpDevice(config)
        >>> pump.connect()
        >>> pump.start_channel(1)
        >>> pump.set_flow_rate(1, 50.0)
        >>> pump.stop_channel(1)
        >>> pump.disconnect()
    """
    
    SUPPORTED_COMMANDS = [
        "start_channel",
        "stop_channel",
        "pause_channel",
        "full_speed_channel",
        "start_all",
        "stop_all",
        "set_direction",
        "set_flow_rate",
        "set_run_mode",
        "set_dispense_volume",
        "set_run_time",
        "set_repeat_count",
        "calibrate_flow",
        "get_channel_status",
    ]
    
    MAX_CHANNELS = 4
    _atexit_refs: List[weakref.ref] = []
    _atexit_registered = False
    _atexit_lock = threading.Lock()

    def __init__(self, config: PeristalticPumpConfig, info: Optional[DeviceInfo] = None):
        """
        初始化蠕动泵设备
        
        Args:
            config: 蠕动泵配置对象
            info: 设备信息对象（可选）
        """
        self._closed = False
        self._protocol: Optional[ModbusRTUProtocol] = None
        self._channel_data: Dict[int, PumpChannelData] = {}
        self._consecutive_failures = 0
        self._max_failures_before_reconnect = 5
        
        if info is None:
            info = DeviceInfo(
                name=config.device_id,
                device_type=DeviceType.PUMP,
                model="LabSmart",
                manufacturer="申辰",
                description="多通道独立控制蠕动泵",
            )
        super().__init__(config, info)
        
        for ch_config in config.channels:
            self._channel_data[ch_config.channel] = PumpChannelData(channel=ch_config.channel)
        
        self._weak_self = weakref.ref(self)
        with LabSmartPumpDevice._atexit_lock:
            LabSmartPumpDevice._atexit_refs.append(self._weak_self)
            if not LabSmartPumpDevice._atexit_registered:
                atexit.register(LabSmartPumpDevice._atexit_cleanup)
                LabSmartPumpDevice._atexit_registered = True
    
    @classmethod
    def _atexit_cleanup(cls):
        with cls._atexit_lock:
            refs = list(cls._atexit_refs)
            cls._atexit_refs.clear()
        for ref in refs:
            obj = ref()
            if obj is not None:
                obj._force_disconnect()
    
    @property
    def protocol(self) -> Optional[ModbusRTUProtocol]:
        """获取协议实例"""
        return self._protocol
    
    @property
    def channel_data(self) -> Dict[int, PumpChannelData]:
        """获取通道数据（深拷贝）"""
        return copy.deepcopy(self._channel_data)
    
    def get_serial_handle(self):
        """获取串口句柄"""
        if self._protocol is not None:
            return self._protocol._serial
        return None
    
    def connect(self) -> bool:
        """
        连接设备
        
        Returns:
            bool: 连接成功返回True
        """
        with self._lock:
            if self.status == DeviceStatus.CONNECTED:
                return True
            if self._status == DeviceStatus.CONNECTING:
                self._logger.error("Connection already in progress")
                return False
            self.status = DeviceStatus.CONNECTING
        
        protocol = None
        try:
            port = self.config.connection_params.get("port", "COM4")
            baudrate = self.config.connection_params.get("baudrate", 9600)
            parity = self.config.connection_params.get("parity", "N")
            stopbits = self.config.connection_params.get("stopbits", 1)
            bytesize = self.config.connection_params.get("bytesize", 8)
            
            protocol = ModbusRTUProtocol(
                port=port,
                baudrate=baudrate,
                parity=parity,
                stopbits=stopbits,
                bytesize=bytesize,
                timeout=self.config.timeout,
            )
            
            if not protocol.connect():
                with self._lock:
                    self.status = DeviceStatus.ERROR
                return False
            
            if not protocol.is_connected:
                protocol.disconnect()
                with self._lock:
                    self.status = DeviceStatus.ERROR
                return False
            
            with self._lock:
                if self.status == DeviceStatus.CONNECTED:
                    protocol.disconnect()
                    return True
                self._protocol = protocol
                self.status = DeviceStatus.CONNECTED
                protocol = None
            
            self._logger.info(f"Pump {self.config.device_id} connected on {port} ({baudrate}, {parity})")
            
            try:
                self._initialize_channels()
            except Exception as e:
                self._logger.warning(f"Channel initialization failed (non-fatal): {e}")
            
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to connect pump: {e}")
            if protocol is not None:
                try:
                    protocol.disconnect()
                except Exception as close_err:
                    self._logger.warning(f"Failed to disconnect protocol during error cleanup: {close_err}")
            with self._lock:
                self.status = DeviceStatus.ERROR
            return False
    
    def disconnect(self) -> bool:
        """
        断开设备连接
        
        Returns:
            bool: 断开成功返回True
        """
        with self._lock:
            self._closed = True
            if self._protocol is not None:
                self._protocol.disconnect()
                self._protocol = None
            
            self.status = DeviceStatus.DISCONNECTED
            self._logger.info(f"Pump {self.config.device_id} disconnected")
            return True
    
    def _force_disconnect(self):
        """强制断开 - 用于atexit回调，非阻塞"""
        try:
            if self._lock.acquire(blocking=False):
                try:
                    if self._protocol is not None:
                        self._protocol.disconnect()
                        self._protocol = None
                    self._closed = True
                finally:
                    self._lock.release()
            else:
                self._closed = True
                self._logger.warning("Force disconnect: lock unavailable, marked closed")
        except Exception:
            pass
    
    def is_closed(self) -> bool:
        """检查是否已关闭"""
        return self._closed
    
    def _initialize_channels(self):
        """初始化所有通道"""
        for ch_config in self.config.channels:
            channel = ch_config.channel
            if ch_config.enabled:
                self.set_tube_model(channel, ch_config.tube_model)
                time.sleep(0.3)
                self.set_direction(channel, ch_config.default_direction)
                time.sleep(0.3)
                self.set_run_mode(channel, PumpRunMode.FLOW_MODE)
                time.sleep(0.3)
                if ch_config.suck_back_angle > 0:
                    self.set_suck_back_angle(channel, ch_config.suck_back_angle)
                    time.sleep(0.3)
    
    def _get_slave_address(self) -> int:
        """获取从站地址"""
        return getattr(self.config, 'slave_address', 1)
    
    def _write_register(self, address: int, value: int) -> bool:
        """
        写单个寄存器
        
        Args:
            address: 寄存器地址
            value: 写入值
        
        Returns:
            bool: 成功返回True
        """
        with self._lock:
            if self._closed or self._protocol is None:
                return False
            return self._protocol.write_single_register(
                self._get_slave_address(),
                address,
                value
            )
    
    def _write_float(self, address: int, value: float) -> bool:
        """
        写浮点数寄存器
        
        Args:
            address: 寄存器地址
            value: 浮点数值
        
        Returns:
            bool: 成功返回True
        """
        with self._lock:
            if self._closed or self._protocol is None:
                return False
            return self._protocol.write_float_register(
                self._get_slave_address(),
                address,
                value
            )

    def _write_float_with_unit(self, float_addr: int, float_val: float,
                                unit_addr: int, unit_val: int) -> bool:
        """原子操作：写浮点数和单位寄存器

        Args:
            float_addr: 浮点数寄存器地址
            float_val: 浮点数值
            unit_addr: 单位寄存器地址
            unit_val: 单位值

        Returns:
            bool: 全部成功返回True
        """
        with self._lock:
            if self._closed or self._protocol is None:
                return False
            ok1 = self._protocol.write_float_register(
                self._get_slave_address(), float_addr, float_val
            )
            ok2 = self._protocol.write_single_register(
                self._get_slave_address(), unit_addr, unit_val
            )
            return ok1 and ok2
    
    def _read_registers(self, start_address: int, count: int) -> Optional[List[int]]:
        """
        读多个寄存器

        Args:
            start_address: 起始地址
            count: 寄存器数量

        Returns:
            Optional[List[int]]: 寄存器值列表
        """
        with self._lock:
            if self._closed or self._protocol is None:
                return None
            result = self._protocol.read_holding_registers(
                self._get_slave_address(),
                start_address,
                count
            )
            if result is not None:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._max_failures_before_reconnect:
                    logger.warning(f"Pump {self.config.device_id}: reconnecting after {self._consecutive_failures} failures")
                    self._try_reconnect_locked()
            return result

    def _try_reconnect_locked(self):
        """尝试重新连接串口（在锁内调用）"""
        if self._protocol is not None:
            try:
                self._protocol.disconnect()
            except Exception:
                pass
            self._protocol = None

        try:
            port = self.config.connection_params.get("port", "COM4")
            baudrate = self.config.connection_params.get("baudrate", 9600)
            parity = self.config.connection_params.get("parity", "N")
            stopbits = self.config.connection_params.get("stopbits", 1)
            bytesize = self.config.connection_params.get("bytesize", 8)

            protocol = ModbusRTUProtocol(
                port=port,
                baudrate=baudrate,
                parity=parity,
                stopbits=stopbits,
                bytesize=bytesize,
                timeout=self.config.timeout,
            )

            if protocol.connect():
                self._protocol = protocol
                self._consecutive_failures = 0
                self.status = DeviceStatus.CONNECTED
                logger.info(f"Pump {self.config.device_id} reconnected successfully")
            else:
                self.status = DeviceStatus.ERROR
                logger.error(f"Pump {self.config.device_id} reconnect failed")
        except Exception as e:
            self.status = DeviceStatus.ERROR
            logger.error(f"Pump {self.config.device_id} reconnect error: {e}")

    def _read_float(self, address: int) -> Optional[float]:
        """
        读浮点数寄存器
        
        Args:
            address: 寄存器地址
        
        Returns:
            Optional[float]: 浮点数值
        """
        with self._lock:
            if self._closed or self._protocol is None:
                return None
            return self._protocol.read_float_register(
                self._get_slave_address(),
                address
            )
    
    def enable_channel(self, channel: int, enable: bool) -> bool:
        """
        使能/失能通道
        
        Args:
            channel: 通道号(1-4)
            enable: True使能，False失能
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(0, channel)
        value = 1 if enable else 0
        result = self._write_register(address, value)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].enabled = enable
        
        return result
    
    def start_channel(self, channel: int) -> bool:
        """
        启动通道

        Args:
            channel: 通道号(1-4)

        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False

        address = get_channel_address(1, channel)
        max_retries = 5
        for attempt in range(max_retries):
            result = self._write_register(address, PumpRunStatus.START)
            if result:
                break
            if attempt < max_retries - 1:
                time.sleep(1.0)

        if result and channel in self._channel_data:
            self._channel_data[channel].running = True
            self._channel_data[channel].paused = False

        return result

    def stop_channel(self, channel: int) -> bool:
        """
        停止通道

        Args:
            channel: 通道号(1-4)

        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False

        address = get_channel_address(1, channel)
        max_retries = 5
        for attempt in range(max_retries):
            result = self._write_register(address, PumpRunStatus.STOP)
            if result:
                break
            if attempt < max_retries - 1:
                time.sleep(1.0)

        if result and channel in self._channel_data:
            self._channel_data[channel].running = False
            self._channel_data[channel].paused = False

        return result
    
    def pause_channel(self, channel: int) -> bool:
        """
        暂停通道
        
        Args:
            channel: 通道号(1-4)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(1, channel)
        result = self._write_register(address, PumpRunStatus.PAUSE)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].paused = True
        
        return result
    
    def full_speed_channel(self, channel: int) -> bool:
        """
        全速运行通道
        
        Args:
            channel: 通道号(1-4)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(1, channel)
        result = self._write_register(address, PumpRunStatus.FULL_SPEED)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].running = True
            self._channel_data[channel].paused = False
        
        return result
    
    def start_all(self) -> bool:
        """
        启动所有有效通道
        
        Returns:
            bool: 成功返回True
        """
        return self._write_register(10, 1)
    
    def stop_all(self) -> bool:
        """
        停止所有有效通道
        
        Returns:
            bool: 成功返回True
        """
        return self._write_register(10, 0)
    
    def set_direction(self, channel: int, direction: PumpDirection) -> bool:
        """
        设置通道方向
        
        Args:
            channel: 通道号(1-4)
            direction: 方向
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(2, channel)
        result = self._write_register(address, direction)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].direction = direction
        
        return result
    
    def set_run_mode(self, channel: int, mode: PumpRunMode) -> bool:
        """
        设置运行模式
        
        Args:
            channel: 通道号(1-4)
            mode: 运行模式
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        self.stop_channel(channel)
        
        address = get_channel_address(6, channel)
        result = self._write_register(address, mode)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].run_mode = mode
        
        return result
    
    def set_flow_rate(self, channel: int, flow_rate: float, unit: FlowUnit = FlowUnit.ML_MIN) -> bool:
        """
        设置流速
        
        Args:
            channel: 通道号(1-4)
            flow_rate: 流速值
            unit: 流速单位
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        flow_addr = get_channel_address(110, channel)
        unit_addr = get_channel_address(112, channel)
        
        if not self._write_float_with_unit(flow_addr, flow_rate, unit_addr, unit):
            return False
        
        if channel in self._channel_data:
            self._channel_data[channel].flow_rate = flow_rate
            self._channel_data[channel].flow_unit = unit
        
        return True
    
    def set_dispense_volume(self, channel: int, volume: float) -> bool:
        """
        设置分装液量
        
        Args:
            channel: 通道号(1-4)
            volume: 液量(mL)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(104, channel)
        result = self._write_float(address, volume)
        
        if result and channel in self._channel_data:
            self._channel_data[channel].remaining_volume = volume
        
        return result
    
    def set_total_volume(self, channel: int, volume: float) -> bool:
        """
        设置总液量
        
        Args:
            channel: 通道号(1-4)
            volume: 总液量(mL)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(113, channel)
        return self._write_float(address, volume)
    
    def set_run_time(self, channel: int, time_value: float, unit: TimeUnit = TimeUnit.SECOND) -> bool:
        """
        设置运行时间
        
        Args:
            channel: 通道号(1-4)
            time_value: 时间值
            unit: 时间单位
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        time_addr = get_channel_address(107, channel)
        unit_addr = get_channel_address(109, channel)
        
        if not self._write_float(time_addr, time_value):
            return False
        
        if not self._write_register(unit_addr, unit):
            return False
        
        return True
    
    def set_repeat_count(self, channel: int, count: int) -> bool:
        """
        设置重复次数
        
        Args:
            channel: 通道号(1-4)
            count: 重复次数
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(100, channel)
        return self._write_register(address, count)
    
    def set_interval_time(self, channel: int, time_value: float, unit: TimeUnit = TimeUnit.SECOND) -> bool:
        """
        设置间隔时间
        
        Args:
            channel: 通道号(1-4)
            time_value: 时间值
            unit: 时间单位
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        time_addr = get_channel_address(101, channel)
        unit_addr = get_channel_address(103, channel)
        
        if not self._write_float(time_addr, time_value):
            return False
        
        if not self._write_register(unit_addr, unit):
            return False
        
        return True
    
    def set_pump_head(self, channel: int, pump_head: int) -> bool:
        """
        设置泵头型号
        
        Args:
            channel: 通道号(1-4)
            pump_head: 泵头型号编号
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(3, channel)
        return self._write_register(address, pump_head)
    
    def set_tube_model(self, channel: int, tube_model: int) -> bool:
        """
        设置软管型号
        
        Args:
            channel: 通道号(1-4)
            tube_model: 软管型号编号
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(4, channel)
        return self._write_register(address, tube_model)
    
    def set_suck_back_angle(self, channel: int, angle: int) -> bool:
        """
        设置回吸角度
        
        Args:
            channel: 通道号(1-4)
            angle: 回吸角度(0-360度)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(5, channel)
        return self._write_register(address, angle)
    
    def calibrate_start(self, channel: int, test_time: float) -> bool:
        """
        开始校准测试
        
        Args:
            channel: 通道号(1-4)
            test_time: 测试时间(秒)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        time_addr = get_channel_address(200, channel)
        start_addr = get_channel_address(202, channel)
        
        if not self._write_float(time_addr, test_time):
            return False
        
        return self._write_register(start_addr, 1)
    
    def calibrate_set_actual_volume(self, channel: int, actual_volume: float) -> bool:
        """
        设置实际灌装量完成校准
        
        Args:
            channel: 通道号(1-4)
            actual_volume: 实际灌装量(mL)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(203, channel)
        return self._write_float(address, actual_volume)
    
    def calibrate_reset(self, channel: int) -> bool:
        """
        恢复校准系数
        
        Args:
            channel: 通道号(1-4)
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(205, channel)
        return self._write_register(address, 1)
    
    def calibrate_fine_tune(self, channel: int, increase: bool) -> bool:
        """
        微调液量
        
        Args:
            channel: 通道号(1-4)
            increase: True增加，False减小
        
        Returns:
            bool: 成功返回True
        """
        if not self._validate_channel(channel):
            return False
        
        address = get_channel_address(206, channel)
        return self._write_register(address, 1 if increase else 0)
    
    def read_channel_status(self, channel: int) -> Optional[PumpChannelData]:
        """
        读取通道状态

        Args:
            channel: 通道号(1-4)

        Returns:
            Optional[PumpChannelData]: 通道数据的深拷贝
        """
        if not self._validate_channel(channel):
            return None

        data = copy.deepcopy(self._channel_data.get(channel, PumpChannelData(channel=channel)))

        enable_addr = get_channel_address(300, channel)
        float_addr = get_channel_address(304, channel)

        int_values = self._read_registers(enable_addr, 4)
        if int_values is not None and len(int_values) >= 4:
            data.enabled = bool(int_values[0])
            run_status = int_values[1]
            data.running = run_status in (PumpRunStatus.START, PumpRunStatus.FULL_SPEED)
            data.paused = run_status == PumpRunStatus.PAUSE
            data.direction = self._safe_enum(PumpDirection, int_values[2], PumpDirection.CLOCKWISE)
            data.run_mode = self._safe_enum(PumpRunMode, int_values[3], PumpRunMode.FLOW_MODE)
        else:
            logger.debug(f"CH{channel} status read failed")
            self._channel_data[channel] = data
            return data

        float_values = self._read_registers(float_addr, 11)
        if float_values is not None and len(float_values) >= 10:
            data.remaining_time = self._parse_float_from_registers(float_values[0], float_values[1])
            data.remaining_volume = self._parse_float_from_registers(float_values[2], float_values[3])
            data.flow_rate = self._parse_float_from_registers(float_values[4], float_values[5])
            data.current_speed = self._parse_float_from_registers(float_values[6], float_values[7])
            data.dispensed_volume = self._parse_float_from_registers(float_values[8], float_values[9])
            if len(float_values) >= 11:
                data.completed_repeats = float_values[10]
        else:
            logger.debug(f"CH{channel} float read failed, trying key fields only")
            current_flow_addr = get_channel_address(308, channel)
            dispensed_vol_addr = get_channel_address(312, channel)
            _flow_rate = self._read_float(current_flow_addr)
            _dispensed_volume = self._read_float(dispensed_vol_addr)
            if _flow_rate is not None:
                data.flow_rate = _flow_rate
            if _dispensed_volume is not None:
                data.dispensed_volume = _dispensed_volume

        self._channel_data[channel] = data
        return data

    @staticmethod
    def _parse_float_from_registers(reg_high: int, reg_low: int) -> float:
        """从两个MODBUS寄存器解析IEEE754浮点数

        Args:
            reg_high: 高位寄存器值
            reg_low: 低位寄存器值

        Returns:
            float: 解析后的浮点数
        """
        try:
            float_bytes = bytes([
                (reg_high >> 8) & 0xFF,
                reg_high & 0xFF,
                (reg_low >> 8) & 0xFF,
                reg_low & 0xFF,
            ])
            return struct.unpack('>f', float_bytes)[0]
        except Exception:
            return 0.0
    
    def is_connected(self) -> bool:
        """
        检查设备是否已连接
        
        Returns:
            bool: 已连接返回True
        """
        return self.status == DeviceStatus.CONNECTED and self._protocol is not None
    
    def write_command(self, command: str, value: Any) -> bool:
        """
        向设备发送命令
        
        Args:
            command: 命令名称
            value: 命令值
        
        Returns:
            bool: 命令发送成功返回True
        """
        return self.execute_command(command, **value) if isinstance(value, dict) else False
    
    def get_available_commands(self) -> List[str]:
        """
        获取设备支持的命令列表
        
        Returns:
            List[str]: 命令名称列表
        """
        return self.SUPPORTED_COMMANDS.copy()
    
    def emergency_stop(self) -> bool:
        """
        紧急停止设备
        
        立即停止所有通道
        
        Returns:
            bool: 停止成功返回True
        """
        self._logger.warning("Emergency stop triggered!")
        return self.stop_all()
    
    def read_data(self) -> DeviceData:
        """
        读取设备数据
        
        Returns:
            DeviceData: 设备数据
        """
        pump_data = PeristalticPumpData(
            device_id=self.config.device_id,
            timestamp=datetime.now(),
            data={},
            status=self._status,
        )
        
        for channel in self._channel_data.keys():
            channel_data = self.read_channel_status(channel)
            if channel_data is not None:
                pump_data.channels[channel] = channel_data
                pump_data.total_dispensed_volume += channel_data.dispensed_volume
        
        return pump_data
    
    @staticmethod
    def _safe_enum(enum_cls, value, default):
        """安全枚举转换，越界时返回默认值

        Args:
            enum_cls: 枚举类
            value: 原始值
            default: 默认值

        Returns:
            枚举值
        """
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            return default

    def _validate_channel(self, channel: int) -> bool:
        """
        验证通道号
        
        Args:
            channel: 通道号
        
        Returns:
            bool: 有效返回True
        """
        if channel < 1 or channel > self.MAX_CHANNELS:
            self._logger.error(f"Invalid channel: {channel}, must be 1-{self.MAX_CHANNELS}")
            return False
        return True
    
    def execute_command(self, command: str, **kwargs) -> Any:
        """
        执行命令
        
        Args:
            command: 命令名称
            **kwargs: 命令参数
        
        Returns:
            Any: 命令结果
        """
        if command == "start_channel":
            return self.start_channel(kwargs.get("channel", 1))
        elif command == "stop_channel":
            return self.stop_channel(kwargs.get("channel", 1))
        elif command == "pause_channel":
            return self.pause_channel(kwargs.get("channel", 1))
        elif command == "full_speed_channel":
            return self.full_speed_channel(kwargs.get("channel", 1))
        elif command == "start_all":
            return self.start_all()
        elif command == "stop_all":
            return self.stop_all()
        elif command == "set_direction":
            return self.set_direction(
                kwargs.get("channel", 1),
                kwargs.get("direction", PumpDirection.CLOCKWISE)
            )
        elif command == "set_flow_rate":
            return self.set_flow_rate(
                kwargs.get("channel", 1),
                kwargs.get("flow_rate", 0.0),
                kwargs.get("unit", FlowUnit.ML_MIN)
            )
        elif command == "set_run_mode":
            return self.set_run_mode(
                kwargs.get("channel", 1),
                kwargs.get("mode", PumpRunMode.FLOW_MODE)
            )
        elif command == "set_dispense_volume":
            return self.set_dispense_volume(
                kwargs.get("channel", 1),
                kwargs.get("volume", 0.0)
            )
        elif command == "set_run_time":
            return self.set_run_time(
                kwargs.get("channel", 1),
                kwargs.get("time_value", 0.0),
                kwargs.get("unit", TimeUnit.SECOND)
            )
        elif command == "set_repeat_count":
            return self.set_repeat_count(
                kwargs.get("channel", 1),
                kwargs.get("count", 1)
            )
        elif command == "calibrate_flow":
            return self.calibrate_start(
                kwargs.get("channel", 1),
                kwargs.get("test_time", 10.0)
            )
        elif command == "get_channel_status":
            return self.read_channel_status(kwargs.get("channel", 1))
        else:
            self._logger.warning(f"Unknown command: {command}")
            return None
