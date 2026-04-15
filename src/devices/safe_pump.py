"""
安全蠕动泵设备驱动

在原有蠕动泵驱动基础上增加：
1. 串口资源管理器集成
2. 通道隔离与异常捕获
3. 命令队列
4. 紧急停止保障
5. 心跳检测
"""

import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import logging
import time
import threading
import atexit
import queue
import traceback

from devices.peristaltic_pump import (
    LabSmartPumpDevice, 
    PeristalticPumpConfig, 
    PumpChannelConfig,
    PumpChannelData,
)
from devices.base_device import DeviceStatus
from protocols.pump_params import PumpRunMode, PumpDirection
from utils.serial_manager import get_serial_manager, SerialPortForceRelease
from utils.device_safety import (
    SafeDevice, DeviceState, DeviceError, 
    ChannelManager, ThreadSafeExecutor, get_safety_manager
)

logger = logging.getLogger(__name__)


class ChannelState(Enum):
    """通道状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass
class ChannelTask:
    """通道任务"""
    channel: int
    volume: float
    flow_rate: float
    direction: PumpDirection = PumpDirection.CLOCKWISE
    mode: PumpRunMode = PumpRunMode.QUANTITY_SPEED
    callback: Optional[Callable] = None
    error_callback: Optional[Callable] = None


class SafePumpDevice(SafeDevice):
    """
    安全蠕动泵设备驱动
    
    增强功能：
    1. 串口资源管理器集成 - 防止端口占用
    2. 通道隔离 - 单通道异常不影响其他通道
    3. 命令队列 - 串行化串口操作
    4. 紧急停止 - 确保设备可安全关停
    5. 心跳检测 - 监控设备在线状态
    """
    
    MAX_CHANNELS = 4
    
    def __init__(self, config: PeristalticPumpConfig, info=None):
        super().__init__(device_id=config.device_id)
        
        self._config = config
        self._base_pump: Optional[LabSmartPumpDevice] = None
        self._serial_manager = get_serial_manager()
        self._safety_manager = get_safety_manager()
        
        self._channel_manager = ChannelManager(self.MAX_CHANNELS, self)
        self._command_queue: queue.Queue = queue.Queue()
        self._command_thread: Optional[threading.Thread] = None
        self._channel_threads: Dict[int, threading.Thread] = {}
        
        self._port = config.connection_params.get('port', 'COM4')
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._last_heartbeat = time.time()
        self._heartbeat_interval = 5.0
        self._heartbeat_timeout = 15.0
        
        self._connecting = False
        self._disposed = False
        
        for ch_config in config.channels:
            channel = ch_config.channel
            self._channel_manager.set_channel_state(channel, DeviceState.UNINITIALIZED)
    
    def connect(self, force: bool = False) -> bool:
        """
        连接设备
        
        Args:
            force: 是否强制获取串口（尝试释放已有占用）
        
        Returns:
            bool: 连接成功返回True
        """
        if self._state == DeviceState.RUNNING:
            return True
        
        with self._lock:
            if self._connecting:
                logger.warning(f"Pump {self._device_id} is already connecting")
                return False
            self._connecting = True
        
        try:
            self._set_state(DeviceState.INITIALIZING)
            
            if not self._serial_manager.acquire_port(self._port, force=force):
                self._report_error(
                    code="PORT_LOCK_FAILED",
                    message=f"Failed to acquire port {self._port}"
                )
                self._set_state(DeviceState.ERROR)
                return False
            
            self._base_pump = LabSmartPumpDevice(self._config)
            
            if not self._base_pump.connect():
                self._serial_manager.release_port(self._port)
                self._report_error(
                    code="CONNECT_FAILED",
                    message="Failed to connect to pump"
                )
                self._set_state(DeviceState.ERROR)
                return False
            
            self._serial_manager.register_handle(
                self._port, 
                self._base_pump.get_serial_handle() if self._base_pump else None
            )
            
            self._start_command_thread()
            self._start_heartbeat_thread()
            
            for ch_config in self._config.channels:
                channel = ch_config.channel
                self._channel_manager.set_channel_state(channel, DeviceState.READY)
            
            self._set_state(DeviceState.RUNNING)
            logger.info(f"SafePump {self._device_id} connected on {self._port}")
            return True
            
        except Exception as e:
            self._report_error(
                code="CONNECT_EXCEPTION",
                message=str(e)
            )
            self._set_state(DeviceState.ERROR)
            return False
        finally:
            self._connecting = False
    
    def disconnect(self) -> bool:
        """断开设备连接"""
        with self._lock:
            if self._state == DeviceState.DISPOSED:
                return True
            
            self._set_state(DeviceState.STOPPING)
            
            self._stop_all_channels()
            self._stop_command_thread()
            self._stop_heartbeat_thread()
            
            if self._base_pump:
                try:
                    self._base_pump.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting base pump: {e}")
                self._base_pump = None
            
            self._serial_manager.release_port(self._port)
            
            self._set_state(DeviceState.DISPOSED)
            logger.info(f"SafePump {self._device_id} disconnected")
            return True
    
    def _start_command_thread(self):
        """启动命令处理线程"""
        if self._command_thread and self._command_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._command_thread = threading.Thread(
            target=self._command_loop,
            daemon=True,
            name=f"PumpCommand-{self._device_id}"
        )
        self._command_thread.start()
    
    def _stop_command_thread(self):
        """停止命令处理线程"""
        self._stop_event.set()
        self._command_queue.put(None)
        
        if self._command_thread and self._command_thread.is_alive():
            self._command_thread.join(timeout=3.0)
    
    def _command_loop(self):
        """命令处理循环"""
        while not self.should_stop():
            try:
                cmd = self._command_queue.get(timeout=1.0)
                if cmd is None:
                    break
                
                func, args, kwargs, result_event, result_container = cmd
                
                try:
                    result = func(*args, **kwargs)
                    if result_container is not None:
                        result_container['result'] = result
                except Exception as e:
                    if result_container is not None:
                        result_container['error'] = e
                    logger.error(f"Command execution error: {e}")
                finally:
                    if result_event:
                        result_event.set()
                        
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Command loop error: {e}")
    
    def _execute_command(self, func: Callable, *args, timeout: float = 5.0, **kwargs) -> Any:
        """通过命令队列执行命令"""
        if self.should_stop():
            return None
        
        result_event = threading.Event()
        result_container = {}
        
        self._command_queue.put((func, args, kwargs, result_event, result_container))
        
        if result_event.wait(timeout=timeout):
            if 'error' in result_container:
                raise result_container['error']
            return result_container.get('result')
        else:
            raise TimeoutError("Command execution timeout")
    
    def _start_heartbeat_thread(self):
        """启动心跳线程"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"PumpHeartbeat-{self._device_id}"
        )
        self._heartbeat_thread.start()
    
    def _stop_heartbeat_thread(self):
        """停止心跳线程"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
    
    def _heartbeat_loop(self):
        """心跳检测循环"""
        while not self.should_stop():
            try:
                if self._base_pump and self._base_pump.is_connected():
                    status = self._base_pump.read_channel_status(1)
                    if status is not None:
                        self._last_heartbeat = time.time()
                    else:
                        if time.time() - self._last_heartbeat > self._heartbeat_timeout:
                            self._report_error(
                                code="HEARTBEAT_TIMEOUT",
                                message="Pump heartbeat timeout"
                            )
            except Exception as e:
                logger.debug(f"Heartbeat check error: {e}")
            
            for _ in range(int(self._heartbeat_interval * 10)):
                if self.should_stop():
                    return
                time.sleep(0.1)
    
    def start_channel(self, channel: int) -> bool:
        """启动通道"""
        if self.should_stop():
            return False
        
        if not self._validate_channel(channel):
            return False
        
        try:
            result = self._execute_command(
                self._base_pump.start_channel,
                channel,
                timeout=3.0
            )
            
            if result:
                self._channel_manager.set_channel_state(channel, DeviceState.RUNNING)
            
            return result
        except Exception as e:
            self._report_error(
                code="START_CHANNEL_ERROR",
                message=str(e),
                channel=channel
            )
            return False
    
    def stop_channel(self, channel: int) -> bool:
        """停止通道"""
        if not self._validate_channel(channel):
            return False
        
        try:
            self._channel_manager.set_channel_state(channel, DeviceState.STOPPING)
            
            if channel in self._channel_threads:
                thread = self._channel_threads[channel]
                if thread.is_alive():
                    thread.join(timeout=2.0)
            
            result = self._execute_command(
                self._base_pump.stop_channel,
                channel,
                timeout=3.0
            )
            
            self._channel_manager.set_channel_state(channel, DeviceState.READY)
            return result
        except Exception as e:
            self._report_error(
                code="STOP_CHANNEL_ERROR",
                message=str(e),
                channel=channel
            )
            return False
    
    def stop_all_channels(self) -> bool:
        """停止所有通道"""
        self._stop_all_channels()
        return True
    
    def _stop_all_channels(self):
        """内部停止所有通道"""
        for channel in range(1, self.MAX_CHANNELS + 1):
            try:
                self.stop_channel(channel)
            except Exception as e:
                logger.warning(f"Error stopping channel {channel}: {e}")
    
    def run_channel_task(self, task: ChannelTask) -> bool:
        """
        运行通道任务
        
        Args:
            task: 通道任务
        
        Returns:
            bool: 成功启动返回True
        """
        if self.should_stop():
            return False
        
        if not self._validate_channel(task.channel):
            return False
        
        if self._channel_manager.is_channel_running(task.channel):
            logger.warning(f"Channel {task.channel} is already running")
            return False
        
        def task_thread():
            try:
                self._channel_manager.set_channel_state(task.channel, DeviceState.RUNNING)
                
                self._execute_command(
                    self._base_pump.set_run_mode,
                    task.channel, task.mode,
                    timeout=3.0
                )
                self._execute_command(
                    self._base_pump.set_direction,
                    task.channel, task.direction,
                    timeout=3.0
                )
                self._execute_command(
                    self._base_pump.set_flow_rate,
                    task.channel, task.flow_rate,
                    timeout=3.0
                )
                self._execute_command(
                    self._base_pump.set_dispense_volume,
                    task.channel, task.volume,
                    timeout=3.0
                )
                
                self._execute_command(
                    self._base_pump.start_channel,
                    task.channel,
                    timeout=3.0
                )
                
                estimated_time = task.volume / task.flow_rate * 60
                start_time = time.time()
                
                while not self.should_stop():
                    if time.time() - start_time > estimated_time * 2:
                        self._execute_command(
                            self._base_pump.stop_channel,
                            task.channel,
                            timeout=3.0
                        )
                        break
                    
                    status = self._execute_command(
                        self._base_pump.read_channel_status,
                        task.channel,
                        timeout=3.0
                    )
                    
                    if status and not status.running and status.dispensed_volume >= task.volume * 0.95:
                        if task.callback:
                            task.callback(status)
                        break
                    
                    for _ in range(10):
                        if self.should_stop():
                            break
                        time.sleep(0.1)
                
                if self.should_stop():
                    self._execute_command(
                        self._base_pump.stop_channel,
                        task.channel,
                        timeout=3.0
                    )
                
                self._channel_manager.set_channel_state(task.channel, DeviceState.READY)
                
            except Exception as e:
                self._channel_manager.report_channel_error(
                    task.channel,
                    DeviceError(
                        code="TASK_ERROR",
                        message=str(e),
                        device_id=self._device_id,
                        channel=task.channel
                    )
                )
                if task.error_callback:
                    task.error_callback(e)
                self._channel_manager.set_channel_state(task.channel, DeviceState.ERROR)
        
        thread = threading.Thread(
            target=task_thread,
            daemon=False,
            name=f"ChannelTask-{task.channel}"
        )
        self._channel_threads[task.channel] = thread
        thread.start()
        
        return True
    
    def read_channel_status(self, channel: int) -> Optional[PumpChannelData]:
        """读取通道状态"""
        if self.should_stop():
            return None
        
        if not self._validate_channel(channel):
            return None
        
        try:
            return self._execute_command(
                self._base_pump.read_channel_status,
                channel,
                timeout=3.0
            )
        except Exception as e:
            logger.debug(f"Read channel {channel} status error: {e}")
            return None
    
    def emergency_stop(self):
        """紧急停止"""
        logger.warning(f"EMERGENCY STOP: {self._device_id}")
        
        self._stop_event.set()
        
        if self._base_pump:
            try:
                self._base_pump.stop_all()
            except Exception as e:
                logger.error(f"Emergency stop error: {e}")
        
        self._stop_all_channels()
        self.disconnect()
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._state == DeviceState.RUNNING and self._base_pump is not None
    
    def is_closed(self) -> bool:
        """检查是否已关闭"""
        return self._state == DeviceState.DISPOSED or self.should_stop()
    
    def get_channel_state(self, channel: int) -> DeviceState:
        """获取通道状态"""
        return self._channel_manager.get_channel_state(channel)
    
    def get_channel_error(self, channel: int) -> Optional[DeviceError]:
        """获取通道错误"""
        return self._channel_manager.get_channel_error(channel)
    
    def _validate_channel(self, channel: int) -> bool:
        """验证通道号"""
        if channel < 1 or channel > self.MAX_CHANNELS:
            self._report_error(
                code="INVALID_CHANNEL",
                message=f"Invalid channel: {channel}, must be 1-{self.MAX_CHANNELS}"
            )
            return False
        return True
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
