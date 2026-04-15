"""
设备安全基类

提供：
1. 线程安全的操作
2. 异常隔离
3. 状态监控
4. 紧急停止
"""

import threading
import time
import atexit
import signal
import logging
from typing import Optional, Callable, Dict, Any, List
from abc import abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


class DeviceState(Enum):
    """设备状态"""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    DISPOSED = "disposed"


@dataclass
class DeviceError:
    """设备错误"""
    code: str
    message: str
    device_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    channel: Optional[int] = None
    recoverable: bool = True


class DeviceSafetyManager:
    """设备安全管理器 - 全局单例"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._devices: Dict[str, 'SafeDevice'] = {}
        self._emergency_stop_callbacks: List[Callable] = []
        self._global_stop_event = threading.Event()
        self._errors: List[DeviceError] = []
        self._max_errors = 100
        
        self._register_cleanup()
    
    def _register_cleanup(self):
        """注册清理函数"""
        atexit.register(self.emergency_stop_all)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except:
            pass
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.warning(f"Received signal {signum}, emergency stop all devices")
        self.emergency_stop_all()
    
    def register_device(self, device: 'SafeDevice'):
        """注册设备"""
        self._devices[device.device_id] = device
    
    def unregister_device(self, device_id: str):
        """注销设备"""
        self._devices.pop(device_id, None)
    
    def register_emergency_stop(self, callback: Callable):
        """注册紧急停止回调"""
        self._emergency_stop_callbacks.append(callback)
    
    def emergency_stop_all(self, timeout: float = 3.0):
        """
        紧急停止所有设备（带超时保护）
        
        Args:
            timeout: 每个设备的超时时间（秒）
        """
        logger.warning("EMERGENCY STOP ALL DEVICES")
        
        self._global_stop_event.set()
        
        for callback in self._emergency_stop_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Emergency stop callback error: {e}")
        
        def stop_device_with_timeout(device, device_id):
            try:
                device.emergency_stop()
            except Exception as e:
                logger.error(f"Emergency stop device {device_id} error: {e}")
        
        threads = []
        for device_id, device in list(self._devices.items()):
            thread = threading.Thread(
                target=stop_device_with_timeout,
                args=(device, device_id),
                daemon=True,
                name=f"EmergencyStop-{device_id}"
            )
            thread.start()
            threads.append((device_id, thread))
        
        for device_id, thread in threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.error(f"Emergency stop timeout for device {device_id}")
    
    def report_error(self, error: DeviceError):
        """报告错误"""
        self._errors.append(error)
        if len(self._errors) > self._max_errors:
            self._errors.pop(0)
        
        logger.error(f"Device error: [{error.code}] {error.message}")
    
    def get_errors(self, device_id: Optional[str] = None) -> List[DeviceError]:
        """获取错误列表"""
        if device_id:
            return [e for e in self._errors if e.device_id == device_id]
        return self._errors.copy()
    
    def clear_errors(self):
        """清除错误"""
        self._errors.clear()
    
    @property
    def global_stop_event(self) -> threading.Event:
        return self._global_stop_event
    
    def is_stopped(self) -> bool:
        return self._global_stop_event.is_set()


def get_safety_manager() -> DeviceSafetyManager:
    """获取安全管理器"""
    return DeviceSafetyManager()


class SafeDevice:
    """安全设备基类"""
    
    def __init__(self, device_id: str):
        self._device_id = device_id
        self._state = DeviceState.UNINITIALIZED
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._errors: List[DeviceError] = []
        self._channels: Dict[int, Dict] = {}
        self._safety_manager = get_safety_manager()
        
        self._safety_manager.register_device(self)
    
    @property
    def device_id(self) -> str:
        return self._device_id
    
    @property
    def state(self) -> DeviceState:
        with self._lock:
            return self._state
    
    def _set_state(self, state: DeviceState):
        with self._lock:
            self._state = state
            logger.debug(f"Device {self._device_id} state: {state.value}")
    
    def is_running(self) -> bool:
        return self._state == DeviceState.RUNNING
    
    def is_stopped(self) -> bool:
        return self._stop_event.is_set() or self._safety_manager.is_stopped()
    
    def should_stop(self) -> bool:
        """检查是否应该停止"""
        return self._stop_event.is_set() or self._safety_manager.is_stopped()
    
    def _report_error(self, code: str, message: str, channel: Optional[int] = None, recoverable: bool = True):
        """报告错误"""
        error = DeviceError(
            code=code,
            message=message,
            device_id=self._device_id,
            channel=channel,
            recoverable=recoverable
        )
        self._errors.append(error)
        self._safety_manager.report_error(error)
    
    def _safe_execute(self, func: Callable, *args, **kwargs) -> Any:
        """安全执行函数"""
        if self.should_stop():
            return None
        
        with self._lock:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self._report_error(
                    code="EXECUTION_ERROR",
                    message=str(e),
                    recoverable=True
                )
                return None
    
    @abstractmethod
    def emergency_stop(self):
        """紧急停止 - 必须由子类实现"""
        pass
    
    def stop(self):
        """正常停止"""
        self._stop_event.set()
    
    def reset_stop(self):
        """重置停止标志"""
        self._stop_event.clear()
    
    def dispose(self):
        """释放资源"""
        with self._lock:
            self._set_state(DeviceState.DISPOSED)
            self._safety_manager.unregister_device(self._device_id)


class ChannelManager:
    """通道管理器 - 管理多通道独立运行"""
    
    def __init__(self, num_channels: int, device: SafeDevice):
        self._num_channels = num_channels
        self._device = device
        self._channel_states: Dict[int, DeviceState] = {}
        self._channel_threads: Dict[int, threading.Thread] = {}
        self._channel_errors: Dict[int, DeviceError] = {}
        self._channel_locks: Dict[int, threading.Lock] = {}
        self._command_queue: Dict[int, List] = {}
        self._queue_lock = threading.Lock()
        
        for i in range(1, num_channels + 1):
            self._channel_states[i] = DeviceState.UNINITIALIZED
            self._channel_locks[i] = threading.Lock()
            self._command_queue[i] = []
    
    def get_channel_state(self, channel: int) -> DeviceState:
        """获取通道状态"""
        return self._channel_states.get(channel, DeviceState.UNINITIALIZED)
    
    def set_channel_state(self, channel: int, state: DeviceState):
        """设置通道状态"""
        self._channel_states[channel] = state
    
    def report_channel_error(self, channel: int, error: DeviceError):
        """报告通道错误"""
        self._channel_errors[channel] = error
        self._device._report_error(
            code=error.code,
            message=error.message,
            channel=channel,
            recoverable=error.recoverable
        )
    
    def get_channel_error(self, channel: int) -> Optional[DeviceError]:
        """获取通道错误"""
        return self._channel_errors.get(channel)
    
    def clear_channel_error(self, channel: int):
        """清除通道错误"""
        self._channel_errors.pop(channel, None)
    
    def is_channel_running(self, channel: int) -> bool:
        """检查通道是否运行中"""
        return self._channel_states.get(channel) == DeviceState.RUNNING
    
    def queue_command(self, channel: int, command: Callable, *args, **kwargs):
        """将命令加入队列"""
        with self._queue_lock:
            self._command_queue[channel].append((command, args, kwargs))
    
    def get_next_command(self, channel: int) -> Optional[tuple]:
        """获取下一个命令"""
        with self._queue_lock:
            if self._command_queue[channel]:
                return self._command_queue[channel].pop(0)
        return None
    
    def stop_channel(self, channel: int):
        """停止通道"""
        with self._channel_locks[channel]:
            self._channel_states[channel] = DeviceState.STOPPING
            
            if channel in self._channel_threads:
                thread = self._channel_threads[channel]
                if thread.is_alive():
                    thread.join(timeout=2.0)
            
            self._channel_states[channel] = DeviceState.READY
    
    def stop_all_channels(self):
        """停止所有通道"""
        for channel in range(1, self._num_channels + 1):
            self.stop_channel(channel)


class ThreadSafeExecutor:
    """线程安全执行器"""
    
    def __init__(self, name: str = "Executor"):
        self._name = name
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._result_queue: List[Any] = []
        self._error_queue: List[Exception] = []
        self._active_threads: List[threading.Thread] = []
    
    def execute(self, func: Callable, *args, daemon: bool = False, **kwargs) -> threading.Thread:
        """在线程中执行函数"""
        if self._stop_event.is_set():
            raise RuntimeError("Executor is stopped")
        
        def wrapper():
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self._result_queue.append(result)
            except Exception as e:
                with self._lock:
                    self._error_queue.append(e)
                logger.error(f"Thread execution error: {e}")
        
        thread = threading.Thread(target=wrapper, daemon=daemon, name=f"{self._name}-{len(self._active_threads)}")
        with self._lock:
            self._active_threads.append(thread)
        thread.start()
        return thread
    
    def get_results(self) -> List[Any]:
        """获取所有结果"""
        with self._lock:
            return self._result_queue.copy()
    
    def get_errors(self) -> List[Exception]:
        """获取所有错误"""
        with self._lock:
            return self._error_queue.copy()
    
    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """等待所有线程完成"""
        deadline = time.time() + timeout if timeout else None
        
        for thread in self._active_threads:
            remaining = max(0, deadline - time.time()) if deadline else None
            thread.join(timeout=remaining)
            if thread.is_alive():
                return False
        
        return True
    
    def stop(self):
        """停止执行器"""
        self._stop_event.set()
        for thread in self._active_threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
    
    def reset(self):
        """重置执行器"""
        self._stop_event.clear()
        with self._lock:
            self._result_queue.clear()
            self._error_queue.clear()
            self._active_threads.clear()
