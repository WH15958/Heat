"""
设备抽象基类模块

提供所有设备的统一接口定义，方便后续扩展其他设备类型。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, TypeVar
import logging

T = TypeVar('T')

logger = logging.getLogger(__name__)


class DeviceStatus(Enum):
    """设备状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    BUSY = "busy"


class DeviceType(Enum):
    """设备类型枚举"""
    HEATER = "heater"
    PUMP = "pump"
    SENSOR = "sensor"
    SPECTROMETER = "spectrometer"
    HPLC = "hplc"
    MICROWAVE = "microwave"
    OTHER = "other"


@dataclass
class DeviceInfo:
    """设备信息数据类"""
    name: str
    device_type: DeviceType
    model: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    description: str = ""


@dataclass
class DeviceConfig:
    """设备配置数据类"""
    device_id: str
    connection_params: Dict[str, Any] = field(default_factory=dict)
    poll_interval: float = 1.0
    timeout: float = 5.0
    retry_count: int = 3
    retry_delay: float = 0.5
    auto_reconnect: bool = True


@dataclass
class DeviceData:
    """设备数据记录"""
    device_id: str
    timestamp: datetime
    data: Dict[str, Any]
    status: DeviceStatus = DeviceStatus.CONNECTED


class BaseDevice(ABC):
    """
    设备抽象基类
    
    所有设备驱动都必须继承此类并实现所有抽象方法。
    提供统一的设备控制接口，便于主程序管理和扩展。
    
    Attributes:
        config: 设备配置对象
        info: 设备信息对象
        status: 当前设备状态
        _callbacks: 状态变化回调函数列表
    """
    
    def __init__(self, config: DeviceConfig, info: Optional[DeviceInfo] = None):
        """
        初始化设备基类
        
        Args:
            config: 设备配置对象
            info: 设备信息对象（可选）
        """
        self.config = config
        self.info = info or DeviceInfo(
            name=config.device_id,
            device_type=DeviceType.OTHER
        )
        self._status = DeviceStatus.DISCONNECTED
        self._callbacks: List[Callable[[DeviceStatus], None]] = []
        self._last_data: Optional[DeviceData] = None
        self._logger = logging.getLogger(f"{__name__}.{config.device_id}")
        
    @property
    def status(self) -> DeviceStatus:
        """获取当前设备状态"""
        return self._status
    
    @status.setter
    def status(self, value: DeviceStatus):
        """设置设备状态并触发回调"""
        old_status = self._status
        self._status = value
        if old_status != value:
            self._logger.info(f"Device status changed: {old_status.value} -> {value.value}")
            self._notify_status_change(value)
    
    @property
    def last_data(self) -> Optional[DeviceData]:
        """获取最后一次读取的数据"""
        return self._last_data
    
    def add_status_callback(self, callback: Callable[[DeviceStatus], None]):
        """
        添加状态变化回调函数
        
        Args:
            callback: 回调函数，接收DeviceStatus参数
        """
        self._callbacks.append(callback)
    
    def remove_status_callback(self, callback: Callable[[DeviceStatus], None]):
        """
        移除状态变化回调函数
        
        Args:
            callback: 要移除的回调函数
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _notify_status_change(self, status: DeviceStatus):
        """通知所有回调函数状态变化"""
        for callback in self._callbacks:
            try:
                callback(status)
            except Exception as e:
                self._logger.error(f"Callback error: {e}")
    
    @abstractmethod
    def connect(self) -> bool:
        """
        连接设备
        
        Returns:
            bool: 连接成功返回True，否则返回False
        
        Raises:
            ConnectionError: 连接失败时抛出
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        断开设备连接
        
        Returns:
            bool: 断开成功返回True，否则返回False
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        检查设备是否已连接
        
        Returns:
            bool: 已连接返回True，否则返回False
        """
        pass
    
    @abstractmethod
    def read_data(self) -> DeviceData:
        """
        读取设备数据
        
        Returns:
            DeviceData: 设备数据对象
        
        Raises:
            IOError: 读取失败时抛出
        """
        pass
    
    @abstractmethod
    def write_command(self, command: str, value: Any) -> bool:
        """
        向设备发送命令
        
        Args:
            command: 命令名称
            value: 命令值
        
        Returns:
            bool: 命令发送成功返回True，否则返回False
        
        Raises:
            IOError: 写入失败时抛出
        """
        pass
    
    @abstractmethod
    def get_available_commands(self) -> List[str]:
        """
        获取设备支持的命令列表
        
        Returns:
            List[str]: 命令名称列表
        """
        pass
    
    @abstractmethod
    def emergency_stop(self) -> bool:
        """
        紧急停止设备
        
        立即停止设备所有操作，确保安全。
        
        Returns:
            bool: 停止成功返回True，否则返回False
        """
        pass
    
    def execute_with_retry(self, operation: Callable[[], T], 
                          operation_name: str = "operation") -> T:
        """
        带重试机制执行操作
        
        Args:
            operation: 要执行的操作函数
            operation_name: 操作名称（用于日志）
        
        Returns:
            操作返回值
        
        Raises:
            Exception: 所有重试失败后抛出最后一次异常
        """
        last_error = None
        for attempt in range(self.config.retry_count):
            try:
                return operation()
            except Exception as e:
                last_error = e
                self._logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{self.config.retry_count}): {e}"
                )
                if attempt < self.config.retry_count - 1:
                    import time
                    time.sleep(self.config.retry_delay)
        
        raise last_error
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.disconnect()
        return False
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.config.device_id}, status={self.status.value})>"
