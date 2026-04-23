"""
宇电AI系列加热器设备驱动

实现加热器的完整控制功能，包括：
- 温度设定与读取
- 运行/停止控制
- 报警监控
- 自整定功能
- 程序控制（程序型仪表）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
import logging
import threading
import time

from devices.base_device import (
    BaseDevice, DeviceConfig, DeviceData, DeviceInfo, 
    DeviceStatus, DeviceType
)
from protocols.aibus import AIBUSProtocol, AIBUSResponse
from protocols.parameters import (
    ParameterCode, ControlMode, RunStatus, 
    AutoTuneMode, ManualAutoMode,
    get_model_name, get_parameter_info
)

logger = logging.getLogger(__name__)


@dataclass
class HeaterConfig(DeviceConfig):
    """加热器配置"""
    decimal_places: int = 1
    temperature_unit: str = "C"
    max_temperature: float = 400.0
    min_temperature: float = 0.0
    safety_limit: float = 450.0
    auto_tune_on_start: bool = False
    default_ramp_rate: float = 5.0


@dataclass
class HeaterData(DeviceData):
    """加热器数据"""
    pv: float = 0.0
    sv: float = 0.0
    mv: int = 0
    alarm_status: int = 0
    run_status: RunStatus = RunStatus.STOP
    control_mode: ControlMode = ControlMode.APID
    is_manual: bool = False
    is_auto_tuning: bool = False
    alarms: List[str] = field(default_factory=list)


class AIHeaterDevice(BaseDevice):
    """
    宇电AI系列加热器设备驱动
    
    支持AI-516/518/716/719/8X8等系列温控仪表。
    通过AIBUS协议实现完整的温度控制功能。
    
    Features:
        - 温度设定与读取
        - 运行/停止/保持控制
        - 手动/自动切换
        - 自整定功能
        - 报警监控
        - 程序段控制（程序型仪表）
        - 安全限温保护
    
    Example:
        >>> config = HeaterConfig(device_id="heater1", connection_params={"port": "COM3"})
        >>> heater = AIHeaterDevice(config)
        >>> heater.connect()
        >>> heater.set_temperature(100.0)
        >>> heater.start()
        >>> data = heater.read_data()
        >>> print(f"PV: {data.pv}, SV: {data.sv}")
        >>> heater.stop()
        >>> heater.disconnect()
    """
    
    SUPPORTED_COMMANDS = [
        "set_temperature",
        "get_temperature",
        "start",
        "stop", 
        "hold",
        "set_manual_output",
        "start_auto_tune",
        "stop_auto_tune",
        "set_control_mode",
        "set_alarm",
        "get_alarm_status",
        "read_parameter",
        "write_parameter",
    ]
    
    def __init__(self, config: HeaterConfig, info: Optional[DeviceInfo] = None):
        """
        初始化加热器设备
        
        Args:
            config: 加热器配置对象
            info: 设备信息对象（可选）
        """
        if info is None:
            info = DeviceInfo(
                name=config.device_id,
                device_type=DeviceType.HEATER,
                manufacturer="宇电(Yudian)",
                model="AI系列温控仪表"
            )
        super().__init__(config, info)
        
        self._heater_config: HeaterConfig = config
        self._protocol: Optional[AIBUSProtocol] = None
        self._model_code: Optional[int] = None
        self._decimal_places: int = config.decimal_places
        self._lock = threading.RLock()
        
    @property
    def protocol(self) -> Optional[AIBUSProtocol]:
        """获取协议对象"""
        return self._protocol
    
    @property
    def model_name(self) -> str:
        """获取仪表型号名称"""
        if self._model_code is None:
            return "未知型号"
        return get_model_name(self._model_code)
    
    def connect(self) -> bool:
        """
        连接加热器设备
        
        Returns:
            bool: 连接成功返回True
        
        Raises:
            ConnectionError: 连接失败
        """
        if self.is_connected():
            return True
        
        self.status = DeviceStatus.CONNECTING
        
        try:
            port = self.config.connection_params.get("port", "COM1")
            baudrate = self.config.connection_params.get("baudrate", 9600)
            address = self.config.connection_params.get("address", 0)
            parity = self.config.connection_params.get("parity", "N")
            
            self._protocol = AIBUSProtocol(
                port=port,
                address=address,
                baudrate=baudrate,
                timeout=self.config.timeout,
                parity=parity
            )
            
            self._protocol.open()
            
            self._model_code = self._read_model_code()
            self._decimal_places = self._detect_decimal_places()
            
            self.status = DeviceStatus.CONNECTED
            self._logger.info(
                f"Connected to heater: {self.config.device_id}, "
                f"model: {self.model_name}"
            )
            return True
            
        except Exception as e:
            self.status = DeviceStatus.ERROR
            self._logger.error(f"Failed to connect: {e}")
            raise ConnectionError(f"Failed to connect to heater: {e}")
    
    def disconnect(self) -> bool:
        """
        断开加热器连接
        
        Returns:
            bool: 断开成功返回True
        """
        if self._protocol is not None:
            try:
                self._protocol.close()
            except Exception as e:
                self._logger.error(f"Error during disconnect: {e}")
            finally:
                self._protocol = None
        
        self.status = DeviceStatus.DISCONNECTED
        return True
    
    def is_connected(self) -> bool:
        """
        检查设备是否已连接
        
        Returns:
            bool: 已连接返回True
        """
        return self._protocol is not None and self._protocol.is_open
    
    def _read_model_code(self) -> int:
        """读取仪表型号特征字"""
        try:
            model_value, _ = self._protocol.read_parameter(ParameterCode.MODEL_CODE)
            return int(model_value)
        except Exception as e:
            self._logger.warning(f"Failed to read model code: {e}")
            return None
    
    def _detect_decimal_places(self) -> int:
        """检测小数位数设置"""
        try:
            dpt, _ = self._protocol.read_parameter(ParameterCode.D_P)
            dpt_int = int(dpt)
            if 0 <= dpt_int <= 3:
                return dpt_int
            else:
                self._logger.warning(f"Invalid D_P value: {dpt}, using config value")
                return self._heater_config.decimal_places
        except Exception as e:
            self._logger.warning(f"Failed to detect decimal places: {e}")
            return self._heater_config.decimal_places
    
    def read_data(self) -> HeaterData:
        """
        读取加热器全部数据（PV、SV、MV、报警状态等）
        
        Returns:
            HeaterData: 加热器数据对象
        
        Raises:
            IOError: 设备未连接
        """
        if not self.is_connected():
            raise IOError("Device not connected")
        
        def _read():
            with self._lock:
                pv, sv, mv, alarm_status = self._protocol.read_pv_sv()
                
                run_status_val = 0
                is_manual = False
                is_auto_tuning = False
                
                try:
                    status_val, _ = self._protocol.read_parameter(
                        ParameterCode.OUTPUT_STATUS
                    )
                    run_status_val = status_val & 0x03
                    is_auto_tuning = bool(status_val & 0x04)
                    is_manual = bool(status_val & 0x08)
                except Exception as e:
                    self._logger.debug(f"Could not read output status: {e}")
            
            alarms = self._parse_alarms(alarm_status)
            
            return HeaterData(
                device_id=self.config.device_id,
                timestamp=datetime.now(),
                data={
                    "pv": pv / (10 ** self._decimal_places),
                    "sv": sv / (10 ** self._decimal_places),
                    "mv": mv,
                    "alarm_status": alarm_status,
                },
                status=self.status,
                pv=pv / (10 ** self._decimal_places),
                sv=sv / (10 ** self._decimal_places),
                mv=mv,
                alarm_status=alarm_status,
                run_status=RunStatus(run_status_val),
                is_manual=is_manual,
                is_auto_tuning=is_auto_tuning,
                alarms=alarms
            )
        
        data = self.execute_with_retry(_read, "read_data")
        self._last_data = data
        return data
    
    def _parse_alarms(self, alarm_status: int) -> List[str]:
        """解析报警状态"""
        alarms = []
        if alarm_status & 0x01:
            alarms.append("上限报警(HIAL)")
        if alarm_status & 0x02:
            alarms.append("下限报警(LoAL)")
        if alarm_status & 0x04:
            alarms.append("正偏差报警(dHAL)")
        if alarm_status & 0x08:
            alarms.append("负偏差报警(dLAL)")
        if alarm_status & 0x10:
            alarms.append("输入超量程报警(orAL)")
        return alarms
    
    def write_command(self, command: str, value: Any) -> bool:
        """
        执行设备命令
        
        Args:
            command: 命令名称
            value: 命令参数
        
        Returns:
            bool: 执行成功返回True
        
        Raises:
            ValueError: 命令不支持
            IOError: 执行失败
        """
        if command not in self.SUPPORTED_COMMANDS:
            raise ValueError(f"Unsupported command: {command}")
        
        if command == "set_temperature":
            return self.set_temperature(float(value))
        elif command == "start":
            return self.start()
        elif command == "stop":
            return self.stop()
        elif command == "hold":
            return self.hold()
        elif command == "set_manual_output":
            return self.set_manual_output(int(value))
        elif command == "start_auto_tune":
            return self.start_auto_tune()
        elif command == "stop_auto_tune":
            return self.stop_auto_tune()
        elif command == "read_parameter":
            if isinstance(value, dict):
                return self.read_parameter(value.get("code", 0))
            return self.read_parameter(int(value))
        elif command == "write_parameter":
            if isinstance(value, dict):
                return self.write_parameter(
                    value.get("code", 0), 
                    value.get("value", 0)
                )
            return False
        else:
            raise ValueError(f"Command not implemented: {command}")
    
    def get_available_commands(self) -> List[str]:
        """
        获取支持的命令列表
        
        Returns:
            List[str]: 命令名称列表
        """
        return self.SUPPORTED_COMMANDS.copy()
    
    def emergency_stop(self) -> bool:
        """
        紧急停止加热器
        
        Returns:
            bool: 成功返回True
        """
        self._logger.warning("Emergency stop triggered!")
        
        with self._lock:
            try:
                self._protocol.write_parameter(
                    ParameterCode.SRUN, 
                    RunStatus.STOP,
                    decimal_places=0
                )
                
                self._protocol.write_parameter(
                    ParameterCode.MV,
                    0,
                    decimal_places=0
                )
                
                self._logger.info("Emergency stop completed")
                return True
            except Exception as e:
                self._logger.error(f"Emergency stop failed: {e}")
                return False
    
    def set_temperature(self, temperature: float) -> bool:
        if temperature > self._heater_config.safety_limit:
            raise ValueError(
                f"Temperature {temperature} exceeds safety limit "
                f"{self._heater_config.safety_limit}"
            )
        
        if temperature < self._heater_config.min_temperature:
            raise ValueError(
                f"Temperature {temperature} below minimum "
                f"{self._heater_config.min_temperature}"
            )
        
        with self._lock:
            def _set():
                self._protocol.write_parameter(
                    ParameterCode.SV,
                    temperature,
                    decimal_places=self._decimal_places
                )
                self._logger.info(f"Temperature set to {temperature}°{self._heater_config.temperature_unit}")
                return True
            
            return self.execute_with_retry(_set, "set_temperature")
    
    def get_temperature(self) -> tuple:
        """
        获取当前温度和设定温度
        
        Returns:
            tuple: (当前温度PV, 设定温度SV)
        """
        data = self.read_data()
        return data.pv, data.sv
    
    def start(self) -> bool:
        """启动加热器（运行状态设为RUN）"""
        with self._lock:
            def _start():
                self._protocol.write_parameter(
                    ParameterCode.SRUN,
                    RunStatus.RUN,
                    decimal_places=0
                )
                self._logger.info("Heater started")
                return True
            
            return self.execute_with_retry(_start, "start")
    
    def stop(self) -> bool:
        """停止加热器（运行状态设为STOP）"""
        with self._lock:
            def _stop():
                self._protocol.write_parameter(
                    ParameterCode.SRUN,
                    RunStatus.STOP,
                    decimal_places=0
                )
                self._logger.info("Heater stopped")
                return True
            
            return self.execute_with_retry(_stop, "stop")
    
    def hold(self) -> bool:
        """保持加热器当前输出（运行状态设为HOLD）"""
        with self._lock:
            def _hold():
                self._protocol.write_parameter(
                    ParameterCode.SRUN,
                    RunStatus.HOLD,
                    decimal_places=0
                )
                self._logger.info("Heater on hold")
                return True
            
            return self.execute_with_retry(_hold, "hold")
    
    def set_manual_output(self, output_percent: int) -> bool:
        if not 0 <= output_percent <= 100:
            raise ValueError(f"Output must be 0-100, got {output_percent}")
        
        with self._lock:
            def _set():
                self._protocol.write_parameter(
                    ParameterCode.AMAN,
                    ManualAutoMode.MAN,
                    decimal_places=0
                )
                self._protocol.write_parameter(
                    ParameterCode.MV,
                    output_percent,
                    decimal_places=0
                )
                self._logger.info(f"Manual output set to {output_percent}%")
                return True
            
            return self.execute_with_retry(_set, "set_manual_output")
    
    def set_auto_mode(self) -> bool:
        with self._lock:
            def _set():
                self._protocol.write_parameter(
                    ParameterCode.AMAN,
                    ManualAutoMode.AUTO,
                    decimal_places=0
                )
                self._logger.info("Switched to auto mode")
                return True
            
            return self.execute_with_retry(_set, "set_auto_mode")
    
    def start_auto_tune(self) -> bool:
        with self._lock:
            def _start():
                self._protocol.write_parameter(
                    ParameterCode.AT,
                    AutoTuneMode.ON,
                    decimal_places=0
                )
                self._logger.info("Auto-tune started")
                return True
            
            return self.execute_with_retry(_start, "start_auto_tune")
    
    def stop_auto_tune(self) -> bool:
        with self._lock:
            def _stop():
                self._protocol.write_parameter(
                    ParameterCode.AT,
                    AutoTuneMode.OFF,
                    decimal_places=0
                )
                self._logger.info("Auto-tune stopped")
                return True
            
            return self.execute_with_retry(_stop, "stop_auto_tune")
    
    def set_control_mode(self, mode: ControlMode) -> bool:
        with self._lock:
            def _set():
                self._protocol.write_parameter(
                    ParameterCode.CTR_L,
                    mode,
                    decimal_places=0
                )
                self._logger.info(f"Control mode set to {ControlMode.get_description(mode)}")
                return True
            
            return self.execute_with_retry(_set, "set_control_mode")
    
    def set_alarm(self, alarm_type: str, value: float) -> bool:
        param_map = {
            'high': ParameterCode.HIAL,
            'low': ParameterCode.LOAL,
            'deviation_high': ParameterCode.DHAL,
            'deviation_low': ParameterCode.DLAL,
        }
        
        if alarm_type not in param_map:
            raise ValueError(f"Unknown alarm type: {alarm_type}")
        
        with self._lock:
            def _set():
                self._protocol.write_parameter(
                    param_map[alarm_type],
                    value,
                    decimal_places=self._decimal_places
                )
                self._logger.info(f"Alarm '{alarm_type}' set to {value}")
                return True
            
            return self.execute_with_retry(_set, "set_alarm")
    
    def get_alarm_status(self) -> List[str]:
        """
        获取当前报警状态
        
        Returns:
            List[str]: 报警描述列表
        """
        data = self.read_data()
        return data.alarms
    
    def read_parameter(self, param_code: int) -> float:
        param_info = get_parameter_info(param_code)
        decimal_places = param_info.decimal_places if param_info else 0
        
        with self._lock:
            def _read():
                value, _ = self._protocol.read_parameter(
                    param_code, 
                    decimal_places=decimal_places
                )
                return value
            
            return self.execute_with_retry(_read, f"read_parameter({param_code})")
    
    def write_parameter(self, param_code: int, value: float) -> bool:
        param_info = get_parameter_info(param_code)
        decimal_places = param_info.decimal_places if param_info else 0
        
        with self._lock:
            def _write():
                self._protocol.write_parameter(
                    param_code,
                    value,
                    decimal_places=decimal_places
                )
                self._logger.info(f"Parameter {param_code} set to {value}")
                return True
            
            return self.execute_with_retry(_write, f"write_parameter({param_code})")
    
    def wait_for_temperature(self, target: float, tolerance: float = 1.0, 
                            timeout: float = 3600.0,
                            callback: Optional[Callable[[float, float], None]] = None) -> bool:
        """
        等待温度达到目标值
        
        Args:
            target: 目标温度
            tolerance: 允许误差
            timeout: 超时时间(秒)
            callback: 进度回调函数，接收(pv, sv)参数
        
        Returns:
            bool: 在超时前达到目标返回True
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            pv, sv = self.get_temperature()
            
            if callback:
                callback(pv, sv)
            
            if abs(pv - target) <= tolerance:
                self._logger.info(f"Temperature reached target: {pv}° (target: {target}°)")
                return True
            
            time.sleep(self.config.poll_interval)
        
        self._logger.warning(f"Wait for temperature timed out after {timeout}s")
        return False
