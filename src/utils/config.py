"""
配置管理模块

提供系统配置的加载、保存和管理功能。
支持YAML和JSON格式的配置文件。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T', bound='BaseConfig')


@dataclass
class BaseConfig:
    """配置基类，提供序列化/反序列化方法"""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """从字典创建实例，忽略多余键"""
        import dataclasses
        valid_keys = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
    
    def validate(self) -> List[str]:
        """
        验证配置
        
        Returns:
            List[str]: 错误信息列表，如果为空则验证通过
        """
        return []


@dataclass
class DeviceConnectionConfig(BaseConfig):
    """设备连接配置"""
    port: str = "COM1"
    baudrate: int = 9600
    address: int = 0
    parity: str = "N"
    timeout: float = 1.0
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not self.port:
            errors.append("端口不能为空")
        
        if self.baudrate not in [1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200]:
            errors.append(f"波特率无效: {self.baudrate}，支持: 1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200")
        
        if not (0 <= self.address <= 255):
            errors.append(f"地址无效: {self.address}，范围: 0-255")
        
        if self.parity not in ["N", "E", "O", "M", "S"]:
            errors.append(f"校验位无效: {self.parity}，支持: N, E, O, M, S")
        
        if self.timeout <= 0:
            errors.append(f"超时时间无效: {self.timeout}，必须大于0")
        
        return errors


@dataclass
class HeaterDeviceConfig(BaseConfig):
    """加热器设备配置"""
    device_id: str = "heater1"
    name: str = "主加热器"
    connection: DeviceConnectionConfig = field(default_factory=DeviceConnectionConfig)
    decimal_places: int = 1
    temperature_unit: str = "C"
    max_temperature: float = 400.0
    min_temperature: float = 0.0
    safety_limit: float = 450.0
    poll_interval: float = 1.0
    retry_count: int = 3
    retry_delay: float = 0.5
    enabled: bool = True
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not self.device_id:
            errors.append("设备ID不能为空")
        
        if not self.name:
            errors.append("设备名称不能为空")
        
        if self.decimal_places not in [0, 1, 2]:
            errors.append(f"小数位数无效: {self.decimal_places}，支持: 0, 1, 2")
        
        if self.temperature_unit not in ["C", "F"]:
            errors.append(f"温度单位无效: {self.temperature_unit}，支持: C, F")
        
        if self.min_temperature >= self.max_temperature:
            errors.append(f"最低温度必须小于最高温度: {self.min_temperature} >= {self.max_temperature}")
        
        if self.safety_limit <= self.max_temperature:
            errors.append(f"安全限制必须大于最高温度: {self.safety_limit} <= {self.max_temperature}")
        
        if self.poll_interval <= 0:
            errors.append(f"轮询间隔无效: {self.poll_interval}，必须大于0")
        
        if self.retry_count < 0:
            errors.append(f"重试次数无效: {self.retry_count}，必须大于等于0")
        
        if self.retry_delay < 0:
            errors.append(f"重试延迟无效: {self.retry_delay}，必须大于等于0")
        
        errors.extend(self.connection.validate())
        return errors


@dataclass
class PumpChannelConfigYaml(BaseConfig):
    """蠕动泵通道配置（YAML解析用）"""
    channel: int = 1
    enabled: bool = True
    pump_head: int = 5
    tube_model: int = 0
    suck_back_angle: int = 0
    max_flow_rate: float = 100.0
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not (1 <= self.channel <= 4):
            errors.append(f"通道号无效: {self.channel}，范围: 1-4")
        
        if not (0 <= self.pump_head <= 20):
            errors.append(f"泵头型号无效: {self.pump_head}，范围: 0-20")
        
        if not (0 <= self.tube_model <= 20):
            errors.append(f"管型号无效: {self.tube_model}，范围: 0-20")
        
        if not (0 <= self.suck_back_angle <= 360):
            errors.append(f"回吸角度无效: {self.suck_back_angle}，范围: 0-360")
        
        if self.max_flow_rate <= 0:
            errors.append(f"最大流速无效: {self.max_flow_rate}，必须大于0")
        
        return errors


@dataclass
class PumpDeviceConfig(BaseConfig):
    """蠕动泵设备配置"""
    device_id: str = "pump1"
    name: str = "蠕动泵"
    connection: DeviceConnectionConfig = field(default_factory=DeviceConnectionConfig)
    slave_address: int = 1
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 2.0
    poll_interval: float = 1.0
    retry_count: int = 3
    retry_delay: float = 0.5
    enabled: bool = True
    channels: List[PumpChannelConfigYaml] = field(default_factory=list)
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not self.device_id:
            errors.append("设备ID不能为空")
        
        if not self.name:
            errors.append("设备名称不能为空")
        
        if not (1 <= self.slave_address <= 247):
            errors.append(f"从站地址无效: {self.slave_address}，范围: 1-247")
        
        if self.parity not in ["N", "E", "O", "M", "S"]:
            errors.append(f"校验位无效: {self.parity}，支持: N, E, O, M, S")
        
        if self.stopbits not in [1, 2]:
            errors.append(f"停止位无效: {self.stopbits}，支持: 1, 2")
        
        if self.bytesize not in [5, 6, 7, 8]:
            errors.append(f"数据位无效: {self.bytesize}，支持: 5, 6, 7, 8")
        
        if self.timeout <= 0:
            errors.append(f"超时时间无效: {self.timeout}，必须大于0")
        
        if self.poll_interval <= 0:
            errors.append(f"轮询间隔无效: {self.poll_interval}，必须大于0")
        
        if self.retry_count < 0:
            errors.append(f"重试次数无效: {self.retry_count}，必须大于等于0")
        
        if self.retry_delay < 0:
            errors.append(f"重试延迟无效: {self.retry_delay}，必须大于等于0")
        
        seen_channels = set()
        for i, channel in enumerate(self.channels):
            channel_errors = channel.validate()
            for err in channel_errors:
                errors.append(f"通道{channel.channel}: {err}")
            
            if channel.channel in seen_channels:
                errors.append(f"通道{channel.channel}: 重复的通道号")
            seen_channels.add(channel.channel)
        
        errors.extend(self.connection.validate())
        return errors


@dataclass
class MonitorConfig(BaseConfig):
    """监控配置"""
    enabled: bool = True
    log_interval: float = 1.0
    data_retention_hours: int = 24
    alarm_check_interval: float = 0.5
    enable_csv_logging: bool = True
    enable_database: bool = False
    database_path: str = "data/monitor.db"
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if self.log_interval <= 0:
            errors.append(f"日志间隔无效: {self.log_interval}，必须大于0")
        
        if self.data_retention_hours < 0:
            errors.append(f"数据保留时间无效: {self.data_retention_hours}，必须大于等于0")
        
        if self.alarm_check_interval <= 0:
            errors.append(f"报警检查间隔无效: {self.alarm_check_interval}，必须大于0")
        
        return errors


@dataclass
class ReportConfig(BaseConfig):
    """报告配置"""
    output_dir: str = "reports"
    default_format: str = "html"
    include_charts: bool = True
    include_statistics: bool = True
    auto_generate: bool = False
    template_dir: str = "templates"
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not self.output_dir:
            errors.append("输出目录不能为空")
        
        if self.default_format not in ["html", "pdf"]:
            errors.append(f"默认格式无效: {self.default_format}，支持: html, pdf")
        
        return errors


@dataclass
class LoggingConfig(BaseConfig):
    """日志配置"""
    level: str = "INFO"
    log_dir: str = "logs"
    max_file_size_mb: int = 10
    backup_count: int = 5
    console_output: bool = True
    file_output: bool = True
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if self.level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            errors.append(f"日志级别无效: {self.level}，支持: DEBUG, INFO, WARNING, ERROR, CRITICAL")
        
        if not self.log_dir:
            errors.append("日志目录不能为空")
        
        if self.max_file_size_mb <= 0:
            errors.append(f"最大文件大小无效: {self.max_file_size_mb}，必须大于0")
        
        if self.backup_count < 0:
            errors.append(f"备份数量无效: {self.backup_count}，必须大于等于0")
        
        return errors


@dataclass
class SystemConfig(BaseConfig):
    """系统主配置"""
    name: str = "自动化控制系统"
    version: str = "1.0.0"
    heaters: List[HeaterDeviceConfig] = field(default_factory=list)
    pumps: List[PumpDeviceConfig] = field(default_factory=list)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        
        if not self.name:
            errors.append("系统名称不能为空")
        
        if not self.version:
            errors.append("版本号不能为空")
        
        seen_heater_ids = set()
        for i, heater in enumerate(self.heaters):
            heater_errors = heater.validate()
            for err in heater_errors:
                errors.append(f"加热器{heater.device_id}: {err}")
            
            if heater.device_id in seen_heater_ids:
                errors.append(f"加热器{heater.device_id}: 重复的设备ID")
            seen_heater_ids.add(heater.device_id)
        
        seen_pump_ids = set()
        for i, pump in enumerate(self.pumps):
            pump_errors = pump.validate()
            for err in pump_errors:
                errors.append(f"蠕动泵{pump.device_id}: {err}")
            
            if pump.device_id in seen_pump_ids:
                errors.append(f"蠕动泵{pump.device_id}: 重复的设备ID")
            seen_pump_ids.add(pump.device_id)
        
        errors.extend(self.monitor.validate())
        errors.extend(self.report.validate())
        errors.extend(self.logging.validate())
        
        return errors
    
    def get_heater_config(self, device_id: str) -> Optional[HeaterDeviceConfig]:
        """根据ID获取加热器配置"""
        for heater in self.heaters:
            if heater.device_id == device_id:
                return heater
        return None
    
    def get_pump_config(self, device_id: str) -> Optional[PumpDeviceConfig]:
        """根据ID获取蠕动泵配置"""
        for pump in self.pumps:
            if pump.device_id == device_id:
                return pump
        return None


class ConfigManager:
    """
    配置管理器
    
    负责加载、保存和管理系统配置。
    
    Example:
        >>> manager = ConfigManager("config/system.yaml")
        >>> config = manager.load()
        >>> print(config.name)
        >>> manager.save(config)
    """
    
    DEFAULT_CONFIG_FILENAME = "system_config.yaml"
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，如果为None则使用默认路径
        """
        if config_path is None:
            config_path = self._get_default_config_path()
        
        self.config_path = Path(config_path)
        self._config: Optional[SystemConfig] = None
        self._logger = logging.getLogger(__name__)
    
    def _get_default_config_path(self) -> str:
        """获取默认配置文件路径"""
        base_dir = Path(__file__).parent.parent.parent
        config_dir = base_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return str(config_dir / self.DEFAULT_CONFIG_FILENAME)
    
    def _convert_dict_to_config(self, data: Dict[str, Any]) -> SystemConfig:
        """将字典转换为配置对象"""
        heaters = []
        for heater_data in data.get("heaters", []):
            conn_data = heater_data.get("connection", {})
            connection = DeviceConnectionConfig(**conn_data)
            heater = HeaterDeviceConfig(
                **{k: v for k, v in heater_data.items() if k != "connection"},
                connection=connection
            )
            heaters.append(heater)
        
        pumps = []
        for pump_data in data.get("pumps", []):
            conn_data = pump_data.get("connection", {})
            connection = DeviceConnectionConfig(**conn_data)
            
            channels = []
            for ch_data in pump_data.get("channels", []):
                channels.append(PumpChannelConfigYaml(**ch_data))
            
            pump = PumpDeviceConfig(
                **{k: v for k, v in pump_data.items() if k not in ["connection", "channels"]},
                connection=connection,
                channels=channels
            )
            pumps.append(pump)
        
        return SystemConfig(
            name=data.get("name", "自动化控制系统"),
            version=data.get("version", "1.0.0"),
            heaters=heaters,
            pumps=pumps,
            monitor=MonitorConfig(**data.get("monitor", {})),
            report=ReportConfig(**data.get("report", {})),
            logging=LoggingConfig(**data.get("logging", {})),
        )
    
    def load(self) -> SystemConfig:
        """
        加载配置文件
        
        Returns:
            SystemConfig: 系统配置对象
        
        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件格式错误
        """
        if not self.config_path.exists():
            self._logger.warning(
                f"Config file not found: {self.config_path}, creating default"
            )
            return self.create_default()
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if self.config_path.suffix.lower() in ('.yaml', '.yml'):
                try:
                    import yaml
                    data = yaml.safe_load(content)
                except ImportError:
                    self._logger.warning("PyYAML not installed, trying JSON format")
                    data = json.loads(content)
            else:
                data = json.loads(content)
            
            self._config = self._convert_dict_to_config(data)
            
            errors = self._config.validate()
            if errors:
                error_msg = "\n".join([f"  - {e}" for e in errors])
                self._logger.warning(f"配置验证警告:\n{error_msg}")
            
            self._logger.info(f"Config loaded from: {self.config_path}")
            return self._config
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load config: {e}")
    
    def save(self, config: Optional[SystemConfig] = None) -> bool:
        """
        保存配置到文件
        
        Args:
            config: 要保存的配置对象，如果为None则保存当前配置
        
        Returns:
            bool: 保存成功返回True
        """
        if config is not None:
            self._config = config
        elif self._config is None:
            raise ValueError("No config to save")
        
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = self._config.to_dict()
            
            if self.config_path.suffix.lower() in ('.yaml', '.yml'):
                try:
                    import yaml
                    content = yaml.dump(data, allow_unicode=True, default_flow_style=False)
                except ImportError:
                    self._logger.warning("PyYAML not installed, saving as JSON")
                    content = json.dumps(data, indent=2, ensure_ascii=False)
            else:
                content = json.dumps(data, indent=2, ensure_ascii=False)
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self._logger.info(f"Config saved to: {self.config_path}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to save config: {e}")
            return False
    
    def create_default(self) -> SystemConfig:
        """
        创建默认配置
        
        Returns:
            SystemConfig: 默认配置对象
        """
        default_heater = HeaterDeviceConfig(
            device_id="heater1",
            name="主加热器",
            connection=DeviceConnectionConfig(
                port="COM3",
                baudrate=9600,
                address=0
            )
        )
        
        self._config = SystemConfig(
            name="自动化控制系统",
            version="1.0.0",
            heaters=[default_heater],
            monitor=MonitorConfig(),
            report=ReportConfig(),
            logging=LoggingConfig()
        )
        
        self.save()
        return self._config
    
    @property
    def config(self) -> Optional[SystemConfig]:
        """获取当前配置"""
        return self._config
    
    def reload(self) -> SystemConfig:
        """重新加载配置"""
        return self.load()
    
    def update_heater_config(self, device_id: str, 
                            updates: Dict[str, Any]) -> bool:
        """
        更新指定加热器的配置
        
        Args:
            device_id: 设备ID
            updates: 要更新的配置项
        
        Returns:
            bool: 更新成功返回True
        """
        if self._config is None:
            self.load()
        
        heater_config = self._config.get_heater_config(device_id)
        if heater_config is None:
            self._logger.error(f"Heater not found: {device_id}")
            return False
        
        for key, value in updates.items():
            if hasattr(heater_config, key):
                setattr(heater_config, key, value)
            elif key.startswith("connection."):
                conn_key = key.split(".", 1)[1]
                if hasattr(heater_config.connection, conn_key):
                    setattr(heater_config.connection, conn_key, value)
        
        return self.save()
