"""
串口资源管理器

功能：
1. 进程锁文件 - 防止多进程同时访问同一串口
2. 强制释放 - 启动时清理残留串口占用
3. 看门狗线程 - 监控进程状态，异常时自动释放
4. 幂等操作 - 防止重复连接/断开
"""

import os
import sys
import time
import json
import atexit
import signal
import threading
import tempfile
from pathlib import Path
from typing import Optional, Dict, Set
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

_platform = sys.platform
if _platform == 'win32':
    try:
        import win32file
        import win32con
        import win32api
        import psutil
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
        logger.warning("win32file not available, force release disabled")
else:
    HAS_WIN32 = False


class SerialPortLock:
    """串口锁文件管理"""
    
    LOCK_DIR = Path(tempfile.gettempdir()) / "heat_serial_locks"
    
    def __init__(self):
        self._locks: Dict[str, Path] = {}
        self._ensure_lock_dir()
    
    def _ensure_lock_dir(self):
        """确保锁文件目录存在"""
        self.LOCK_DIR.mkdir(parents=True, exist_ok=True)
    
    def _get_lock_file(self, port: str) -> Path:
        """获取锁文件路径"""
        safe_name = port.replace(":", "_").replace("\\", "_")
        return self.LOCK_DIR / f"{safe_name}.lock"
    
    def acquire(self, port: str, pid: Optional[int] = None) -> bool:
        """
        获取串口锁（原子操作，避免竞态条件）
        
        Args:
            port: 串口名称
            pid: 进程ID，默认当前进程
        
        Returns:
            bool: 成功获取返回True
        """
        if pid is None:
            pid = os.getpid()
        
        lock_file = self._get_lock_file(port)
        temp_lock_file = self._get_lock_file(f"{port}_temp_{pid}")
        
        try:
            data = {
                'pid': pid,
                'port': port,
                'time': time.time(),
                'datetime': datetime.now().isoformat(),
            }
            
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            
            self._locks[port] = lock_file
            logger.info(f"Lock acquired for {port} by PID {pid}")
            return True
            
        except FileExistsError:
            try:
                with open(lock_file, 'r') as f:
                    existing_data = json.load(f)
                
                old_pid = existing_data.get('pid')
                
                if old_pid and self._is_process_alive(old_pid):
                    logger.warning(f"Port {port} is locked by process {old_pid}")
                    return False
                
                logger.info(f"Removing stale lock file for {port} (dead process {old_pid})")
                
                try:
                    fd = os.open(str(temp_lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, 'w', encoding='utf-8') as f:
                        json.dump(data, f)
                    
                    try:
                        os.replace(str(temp_lock_file), str(lock_file))
                        self._locks[port] = lock_file
                        logger.info(f"Lock acquired for {port} by PID {pid} (replaced stale)")
                        return True
                    except OSError as e:
                        try:
                            temp_lock_file.unlink()
                        except (OSError, FileNotFoundError):
                            pass
                        logger.warning(f"Race condition detected for {port}, please retry")
                        return False
                        
                except FileExistsError:
                    logger.warning(f"Race condition detected for {port}, please retry")
                    return False
                    
            except Exception as e:
                logger.warning(f"Failed to read existing lock file: {e}")
                try:
                    lock_file.unlink()
                except (OSError, FileNotFoundError):
                    pass
                logger.warning(f"Removed corrupted lock file for {port}, please retry")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create lock file: {e}")
            return False
    
    def release(self, port: str) -> bool:
        """
        释放串口锁
        
        Args:
            port: 串口名称
        
        Returns:
            bool: 成功释放返回True
        """
        lock_file = self._get_lock_file(port)
        
        try:
            if lock_file.exists():
                lock_file.unlink()
            if port in self._locks:
                del self._locks[port]
            logger.info(f"Lock released for {port}")
            return True
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
            return False
    
    def release_all(self):
        """释放所有锁"""
        for port in list(self._locks.keys()):
            self.release(port)
    
    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活"""
        try:
            if _platform == 'win32':
                import psutil
                return psutil.pid_exists(pid)
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ImportError):
            return False
    
    def get_lock_info(self, port: str) -> Optional[Dict]:
        """获取锁信息"""
        lock_file = self._get_lock_file(port)
        if lock_file.exists():
            try:
                with open(lock_file, 'r') as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return None


class SerialPortForceRelease:
    """串口强制释放"""
    
    @staticmethod
    def force_release(port: str) -> bool:
        """
        强制释放串口
        
        Args:
            port: 串口名称
        
        Returns:
            bool: 成功释放返回True
        """
        if not HAS_WIN32:
            logger.warning("Force release not available on this platform")
            return False
        
        try:
            port_path = f"\\\\.\\{port}"
            
            handle = win32file.CreateFile(
                port_path,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            
            if handle != win32file.INVALID_HANDLE_VALUE:
                win32file.CloseHandle(handle)
                logger.info(f"Force released {port}")
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Force release attempt for {port}: {e}")
            return False
    
    @staticmethod
    def find_processes_using_port(port: str) -> list:
        """
        查找占用串口的进程
        
        Args:
            port: 串口名称
        
        Returns:
            list: 进程信息列表
        """
        if not HAS_WIN32:
            return []
        
        processes = []
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    for item in proc.open_files():
                        if port.lower() in item.path.lower():
                            processes.append({
                                'pid': proc.pid,
                                'name': proc.name(),
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass
        
        return processes


class WatchdogThread(threading.Thread):
    """看门狗线程 - 监控主进程状态"""
    
    def __init__(self, callback=None, interval=1.0, parent_pid=None, check_parent: bool = False):
        super().__init__(daemon=False, name="WatchdogThread")
        self._stop_event = threading.Event()
        self._callback = callback
        self._interval = interval
        self._check_parent = check_parent
        self._parent_pid = parent_pid if check_parent else None
        self._last_heartbeat = time.time()
        self._heartbeat_timeout = 30.0
    
    def run(self):
        while not self._stop_event.is_set():
            try:
                if self._check_parent and self._parent_pid:
                    if not self._is_parent_alive():
                        logger.warning("Parent process died, triggering cleanup")
                        if self._callback:
                            self._callback()
                        break
                
                if time.time() - self._last_heartbeat > self._heartbeat_timeout:
                    logger.warning("Heartbeat timeout, triggering cleanup")
                    if self._callback:
                        self._callback()
                    break
                
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            
            self._stop_event.wait(self._interval)
    
    def stop(self):
        self._stop_event.set()
    
    def heartbeat(self):
        """更新心跳时间"""
        self._last_heartbeat = time.time()
    
    def _is_parent_alive(self) -> bool:
        """检查父进程是否存活"""
        if self._parent_pid is None:
            return True
        try:
            import psutil
            return psutil.pid_exists(self._parent_pid)
        except ImportError:
            try:
                os.kill(self._parent_pid, 0)
                return True
            except OSError:
                return False


class SerialPortManager:
    """串口资源管理器 - 统一管理所有串口资源"""
    
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
        self._port_lock = SerialPortLock()
        self._active_ports: Set[str] = set()
        self._port_handles: Dict[str, object] = {}
        self._watchdog: Optional[WatchdogThread] = None
        self._cleanup_registered = False
        
        self._register_cleanup()
    
    def _register_cleanup(self):
        """注册清理函数"""
        if not self._cleanup_registered:
            atexit.register(self.cleanup)
            try:
                signal.signal(signal.SIGTERM, self._signal_handler)
                signal.signal(signal.SIGINT, self._signal_handler)
            except (OSError, ValueError):
                pass
            self._cleanup_registered = True
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info(f"Received signal {signum}, cleaning up...")
        self.cleanup()
    
    def acquire_port(self, port: str, force: bool = False) -> bool:
        """
        获取串口资源
        
        Args:
            port: 串口名称
            force: 是否强制获取（尝试释放已有占用）
        
        Returns:
            bool: 成功获取返回True
        """
        if port in self._active_ports:
            logger.warning(f"Port {port} already acquired")
            return True
        
        if force:
            SerialPortForceRelease.force_release(port)
        
        if not self._port_lock.acquire(port):
            return False
        
        self._active_ports.add(port)
        
        if self._watchdog is None or not self._watchdog.is_alive():
            self._watchdog = WatchdogThread(callback=self.cleanup)
            self._watchdog.start()
        
        return True
    
    def release_port(self, port: str) -> bool:
        """
        释放串口资源
        
        Args:
            port: 串口名称
        
        Returns:
            bool: 成功释放返回True
        """
        if port not in self._active_ports:
            return True
        
        if port in self._port_handles:
            try:
                handle = self._port_handles[port]
                if hasattr(handle, 'close'):
                    handle.close()
            except Exception as e:
                logger.warning(f"Error closing port handle: {e}")
            del self._port_handles[port]
        
        self._port_lock.release(port)
        self._active_ports.discard(port)
        
        return True
    
    def register_handle(self, port: str, handle):
        """注册串口句柄"""
        self._port_handles[port] = handle
    
    def cleanup(self):
        """清理所有资源"""
        logger.info("SerialPortManager cleanup started")
        
        for port in list(self._active_ports):
            try:
                self.release_port(port)
            except Exception as e:
                logger.error(f"Error releasing {port}: {e}")
        
        self._port_lock.release_all()
        
        if self._watchdog:
            self._watchdog.stop()
            if self._watchdog.is_alive():
                self._watchdog.join(timeout=2.0)
            self._watchdog = None
        
        logger.info("SerialPortManager cleanup completed")
    
    def get_status(self) -> Dict:
        """获取状态信息"""
        return {
            'active_ports': list(self._active_ports),
            'lock_info': {
                port: self._port_lock.get_lock_info(port)
                for port in self._active_ports
            }
        }
    
    def is_port_acquired(self, port: str) -> bool:
        """检查端口是否已被获取"""
        return port in self._active_ports


_global_manager = None

def get_serial_manager() -> SerialPortManager:
    """获取全局串口管理器"""
    global _global_manager
    if _global_manager is None:
        _global_manager = SerialPortManager()
    return _global_manager


def acquire_serial_port(port: str, force: bool = False) -> bool:
    """便捷函数：获取串口"""
    return get_serial_manager().acquire_port(port, force)


def release_serial_port(port: str) -> bool:
    """便捷函数：释放串口"""
    return get_serial_manager().release_port(port)


def cleanup_all_serial_ports():
    """便捷函数：清理所有串口"""
    get_serial_manager().cleanup()
