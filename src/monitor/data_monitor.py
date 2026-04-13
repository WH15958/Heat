"""
数据监控模块

提供实时数据采集、存储和报警监控功能。
"""

import csv
import json
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataPoint:
    """数据点"""
    timestamp: datetime
    device_id: str
    pv: float
    sv: float
    mv: int
    alarm_status: int
    alarms: List[str]
    extra: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = {
            "timestamp": self.timestamp.isoformat(),
            "device_id": self.device_id,
            "pv": self.pv,
            "sv": self.sv,
            "mv": self.mv,
            "alarm_status": self.alarm_status,
            "alarms": self.alarms,
        }
        if self.extra:
            data.update(self.extra)
        return data


@dataclass
class AlarmRule:
    """报警规则"""
    name: str
    device_id: str
    parameter: str
    operator: str
    threshold: float
    enabled: bool = True
    description: str = ""
    
    def check(self, value: float) -> bool:
        """检查是否触发报警"""
        if not self.enabled:
            return False
        
        if self.operator == ">":
            return value > self.threshold
        elif self.operator == ">=":
            return value >= self.threshold
        elif self.operator == "<":
            return value < self.threshold
        elif self.operator == "<=":
            return value <= self.threshold
        elif self.operator == "==":
            return value == self.threshold
        return False


class AlarmManager:
    """
    报警管理器
    
    管理报警规则和报警状态。
    """
    
    def __init__(self):
        self._rules: Dict[str, AlarmRule] = {}
        self._active_alarms: Dict[str, List[str]] = {}
        self._callbacks: List[Callable[[str, str, float], None]] = []
        self._logger = logging.getLogger(__name__)
    
    def add_rule(self, rule: AlarmRule):
        """添加报警规则"""
        self._rules[rule.name] = rule
        self._logger.info(f"Alarm rule added: {rule.name}")
    
    def remove_rule(self, name: str):
        """移除报警规则"""
        if name in self._rules:
            del self._rules[name]
            self._logger.info(f"Alarm rule removed: {name}")
    
    def add_callback(self, callback: Callable[[str, str, float], None]):
        """添加报警回调函数"""
        self._callbacks.append(callback)
    
    def check_data(self, device_id: str, data: Dict[str, Any]) -> List[str]:
        """
        检查数据是否触发报警
        
        Args:
            device_id: 设备ID
            data: 数据字典
        
        Returns:
            List[str]: 触发的报警名称列表
        """
        triggered = []
        
        for name, rule in self._rules.items():
            if rule.device_id != device_id:
                continue
            
            value = data.get(rule.parameter)
            if value is None:
                continue
            
            if rule.check(value):
                triggered.append(name)
                self._notify_alarm(name, device_id, value)
        
        self._active_alarms[device_id] = triggered
        return triggered
    
    def _notify_alarm(self, rule_name: str, device_id: str, value: float):
        """通知报警"""
        self._logger.warning(
            f"Alarm triggered: {rule_name} on {device_id}, value={value}"
        )
        for callback in self._callbacks:
            try:
                callback(rule_name, device_id, value)
            except Exception as e:
                self._logger.error(f"Alarm callback error: {e}")
    
    def get_active_alarms(self, device_id: str = None) -> Dict[str, List[str]]:
        """获取活动报警"""
        if device_id:
            return {device_id: self._active_alarms.get(device_id, [])}
        return self._active_alarms.copy()


class DataStorage:
    """
    数据存储
    
    支持CSV文件和SQLite数据库存储。
    """
    
    def __init__(self, storage_dir: str = "data", use_database: bool = False):
        """
        初始化数据存储
        
        Args:
            storage_dir: 存储目录
            use_database: 是否使用数据库
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.use_database = use_database
        self._db_conn: Optional[sqlite3.Connection] = None
        self._csv_files: Dict[str, csv.writer] = {}
        self._logger = logging.getLogger(__name__)
        
        if use_database:
            self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        db_path = self.storage_dir / "monitor.db"
        self._db_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        
        cursor = self._db_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_id TEXT NOT NULL,
                pv REAL,
                sv REAL,
                mv INTEGER,
                alarm_status INTEGER,
                alarms TEXT
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_device_timestamp 
            ON device_data(device_id, timestamp)
        ''')
        self._db_conn.commit()
        self._logger.info("Database initialized")
    
    def _get_csv_writer(self, device_id: str) -> csv.writer:
        """获取CSV写入器"""
        if device_id not in self._csv_files:
            date_str = datetime.now().strftime('%Y%m%d')
            csv_path = self.storage_dir / f"{device_id}_{date_str}.csv"
            
            file = open(csv_path, 'a', newline='', encoding='utf-8')
            writer = csv.writer(file)
            
            if file.tell() == 0:
                writer.writerow([
                    'timestamp', 'device_id', 'pv', 'sv', 'mv', 
                    'alarm_status', 'alarms'
                ])
            
            self._csv_files[device_id] = writer
        
        return self._csv_files[device_id]
    
    def save(self, data_point: DataPoint):
        """
        保存数据点
        
        Args:
            data_point: 数据点对象
        """
        if self.use_database and self._db_conn:
            self._save_to_database(data_point)
        else:
            self._save_to_csv(data_point)
    
    def _save_to_csv(self, data_point: DataPoint):
        """保存到CSV文件"""
        try:
            writer = self._get_csv_writer(data_point.device_id)
            writer.writerow([
                data_point.timestamp.isoformat(),
                data_point.device_id,
                data_point.pv,
                data_point.sv,
                data_point.mv,
                data_point.alarm_status,
                json.dumps(data_point.alarms)
            ])
        except Exception as e:
            self._logger.error(f"Failed to save to CSV: {e}")
    
    def _save_to_database(self, data_point: DataPoint):
        """保存到数据库"""
        try:
            cursor = self._db_conn.cursor()
            cursor.execute('''
                INSERT INTO device_data 
                (timestamp, device_id, pv, sv, mv, alarm_status, alarms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                data_point.timestamp.isoformat(),
                data_point.device_id,
                data_point.pv,
                data_point.sv,
                data_point.mv,
                data_point.alarm_status,
                json.dumps(data_point.alarms)
            ))
            self._db_conn.commit()
        except Exception as e:
            self._logger.error(f"Failed to save to database: {e}")
    
    def query(self, device_id: str, start_time: datetime, 
              end_time: datetime) -> List[DataPoint]:
        """
        查询历史数据
        
        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            List[DataPoint]: 数据点列表
        """
        if not self.use_database or not self._db_conn:
            return self._query_from_csv(device_id, start_time, end_time)
        
        cursor = self._db_conn.cursor()
        cursor.execute('''
            SELECT timestamp, device_id, pv, sv, mv, alarm_status, alarms
            FROM device_data
            WHERE device_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        ''', (device_id, start_time.isoformat(), end_time.isoformat()))
        
        results = []
        for row in cursor.fetchall():
            results.append(DataPoint(
                timestamp=datetime.fromisoformat(row[0]),
                device_id=row[1],
                pv=row[2],
                sv=row[3],
                mv=row[4],
                alarm_status=row[5],
                alarms=json.loads(row[6]) if row[6] else []
            ))
        
        return results
    
    def _query_from_csv(self, device_id: str, start_time: datetime,
                        end_time: datetime) -> List[DataPoint]:
        """从CSV文件查询数据"""
        results = []
        
        for csv_file in self.storage_dir.glob(f"{device_id}_*.csv"):
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ts = datetime.fromisoformat(row['timestamp'])
                        if start_time <= ts <= end_time:
                            results.append(DataPoint(
                                timestamp=ts,
                                device_id=row['device_id'],
                                pv=float(row['pv']),
                                sv=float(row['sv']),
                                mv=int(row['mv']),
                                alarm_status=int(row['alarm_status']),
                                alarms=json.loads(row['alarms']) if row['alarms'] else []
                            ))
            except Exception as e:
                self._logger.error(f"Error reading CSV {csv_file}: {e}")
        
        results.sort(key=lambda x: x.timestamp)
        return results
    
    def close(self):
        """关闭存储"""
        for writer in self._csv_files.values():
            if hasattr(writer, '_file'):
                writer._file.close()
        
        if self._db_conn:
            self._db_conn.close()
        
        self._logger.info("Data storage closed")


class DataMonitor:
    """
    数据监控器
    
    定期采集设备数据并存储，监控报警状态。
    
    Example:
        >>> monitor = DataMonitor()
        >>> monitor.add_device(heater_device)
        >>> monitor.start()
        >>> # ... 运行中 ...
        >>> monitor.stop()
    """
    
    def __init__(self, 
                 storage_dir: str = "data",
                 use_database: bool = False,
                 poll_interval: float = 1.0,
                 buffer_size: int = 1000):
        """
        初始化数据监控器
        
        Args:
            storage_dir: 数据存储目录
            use_database: 是否使用数据库
            poll_interval: 采集间隔(秒)
            buffer_size: 内存缓冲区大小
        """
        self.storage = DataStorage(storage_dir, use_database)
        self.alarm_manager = AlarmManager()
        self.poll_interval = poll_interval
        self.buffer_size = buffer_size
        
        self._devices: Dict[str, Any] = {}
        self._data_buffers: Dict[str, Deque[DataPoint]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[DataPoint], None]] = []
        self._logger = logging.getLogger(__name__)
    
    def add_device(self, device: Any):
        """
        添加监控设备
        
        Args:
            device: 设备对象，需要有read_data()方法
        """
        device_id = device.config.device_id
        self._devices[device_id] = device
        self._data_buffers[device_id] = deque(maxlen=self.buffer_size)
        self._logger.info(f"Device added to monitor: {device_id}")
    
    def remove_device(self, device_id: str):
        """移除监控设备"""
        if device_id in self._devices:
            del self._devices[device_id]
            if device_id in self._data_buffers:
                del self._data_buffers[device_id]
            self._logger.info(f"Device removed from monitor: {device_id}")
    
    def add_data_callback(self, callback: Callable[[DataPoint], None]):
        """添加数据回调函数"""
        self._callbacks.append(callback)
    
    def add_alarm_rule(self, rule: AlarmRule):
        """添加报警规则"""
        self.alarm_manager.add_rule(rule)
    
    def add_alarm_callback(self, callback: Callable[[str, str, float], None]):
        """添加报警回调函数"""
        self.alarm_manager.add_callback(callback)
    
    def _collect_data(self):
        """采集数据"""
        for device_id, device in self._devices.items():
            try:
                if not device.is_connected():
                    continue
                
                raw_data = device.read_data()
                
                data_point = DataPoint(
                    timestamp=datetime.now(),
                    device_id=device_id,
                    pv=raw_data.pv if hasattr(raw_data, 'pv') else raw_data.data.get('pv', 0),
                    sv=raw_data.sv if hasattr(raw_data, 'sv') else raw_data.data.get('sv', 0),
                    mv=raw_data.mv if hasattr(raw_data, 'mv') else raw_data.data.get('mv', 0),
                    alarm_status=raw_data.alarm_status if hasattr(raw_data, 'alarm_status') else 0,
                    alarms=raw_data.alarms if hasattr(raw_data, 'alarms') else []
                )
                
                self._data_buffers[device_id].append(data_point)
                self.storage.save(data_point)
                
                self.alarm_manager.check_data(device_id, data_point.to_dict())
                
                for callback in self._callbacks:
                    try:
                        callback(data_point)
                    except Exception as e:
                        self._logger.error(f"Data callback error: {e}")
                
            except Exception as e:
                self._logger.error(f"Error collecting data from {device_id}: {e}")
    
    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            self._collect_data()
            time.sleep(self.poll_interval)
    
    def start(self):
        """启动监控"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        self._logger.info("Data monitor started")
    
    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.storage.close()
        self._logger.info("Data monitor stopped")
    
    def get_latest_data(self, device_id: str) -> Optional[DataPoint]:
        """获取最新数据"""
        buffer = self._data_buffers.get(device_id)
        if buffer:
            return buffer[-1]
        return None
    
    def get_history_data(self, device_id: str, count: int = 100) -> List[DataPoint]:
        """获取历史数据"""
        buffer = self._data_buffers.get(device_id)
        if buffer:
            return list(buffer)[-count:]
        return []
    
    def query_data(self, device_id: str, start_time: datetime,
                   end_time: datetime) -> List[DataPoint]:
        """查询历史数据"""
        return self.storage.query(device_id, start_time, end_time)
    
    @property
    def is_running(self) -> bool:
        """监控器是否正在运行"""
        return self._running
