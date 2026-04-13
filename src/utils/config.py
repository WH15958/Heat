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
        """从字典创建实例"""
        return cls(**data)


@dataclass
class DeviceConnectionConfig(BaseConfig):
    """设备连接配置"""
    port: str = "COM1"
    baudrate: int = 9600
    address: int = 0
    parity: str = "N"
    timeout: float = 1.0


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


@dataclass
class ReportConfig(BaseConfig):
    """报告配置"""
    output_dir: str = "reports"
    default_format: str = "html"
    include_charts: bool = True
    include_statistics: bool = True
    auto_generate: bool = False
    template_dir: str = "templates"


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


@dataclass
class SystemConfig(BaseConfig):
    """系统主配置"""
    name: str = "自动化控制系统"
    version: str = "1.0.0"
    heaters: List[HeaterDeviceConfig] = field(default_factory=list)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    def get_heater_config(self, device_id: str) -> Optional[HeaterDeviceConfig]:
        """根据ID获取加热器配置"""
        for heater in self.heaters:
            if heater.device_id == device_id:
                return heater
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
        
        return SystemConfig(
            name=data.get("name", "自动化控制系统"),
            version=data.get("version", "1.0.0"),
            heaters=heaters,
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
