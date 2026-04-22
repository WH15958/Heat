"""
CSV数据记录器

提供简单的CSV格式数据记录功能，完全在主线程运行，
避免多线程串口资源竞争问题。
"""

import csv
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

_logger = logging.getLogger(__name__)


class CSVDataLogger:
    """
    CSV数据记录器
    
    用于记录实验数据到CSV文件，支持多设备数据记录。
    """
    
    def __init__(self, output_dir: str, filename_prefix: str = "data"):
        """
        初始化CSV数据记录器
        
        Args:
            output_dir: 输出目录
            filename_prefix: 文件名前缀
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = f"{filename_prefix}_{timestamp}.csv"
        self.filepath = self.output_dir / self.filename
        
        self._file = None
        self._writer = None
        self._fieldnames = [
            "timestamp",
            "device_id",
            "pv",
            "sv",
            "mv",
            "alarm_status",
            "alarms"
        ]
        
        # 内存缓存的数据点，用于报告生成
        self._data_points: Dict[str, List[Dict]] = {}
    
    def start(self):
        """开始记录"""
        if self._file is None:
            self._file = open(self.filepath, 'w', newline='', encoding='utf-8')
            self._writer = csv.DictWriter(self._file, fieldnames=self._fieldnames)
            self._writer.writeheader()
            self._file.flush()
    
    def record(self, device_id: str, pv: float, sv: float, mv: float = 0.0, 
               alarm_status: int = 0, alarms: List[str] = None):
        if self._writer is None:
            self.start()
        
        try:
            timestamp = datetime.now().isoformat()
            
            row = {
                "timestamp": timestamp,
                "device_id": device_id,
                "pv": pv,
                "sv": sv,
                "mv": mv,
                "alarm_status": alarm_status,
                "alarms": ",".join(alarms) if alarms else ""
            }
            
            self._writer.writerow(row)
            self._file.flush()
            
            if device_id not in self._data_points:
                self._data_points[device_id] = []
            
            data_point = {
                "timestamp": datetime.fromisoformat(timestamp),
                "pv": pv,
                "sv": sv,
                "mv": mv,
                "alarm_status": alarm_status,
                "alarms": alarms or [],
                "device_id": device_id
            }
            self._data_points[device_id].append(data_point)
        except Exception as e:
            _logger.warning(f"Failed to write CSV record: {e}")
    
    def get_data_points(self, device_id: str) -> List[Dict]:
        """
        获取指定设备的所有数据点
        
        Args:
            device_id: 设备ID
        
        Returns:
            数据点列表
        """
        return self._data_points.get(device_id, [])
    
    def get_all_data(self) -> Dict[str, List[Dict]]:
        """
        获取所有设备的数据
        
        Returns:
            设备ID到数据点列表的映射
        """
        return self._data_points.copy()
    
    def stop(self):
        """停止记录"""
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None
    
    def close(self):
        """关闭记录器"""
        self.stop()
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SimpleDataPoint:
    """
    简单数据点类，用于模拟DataMonitor的DataPoint结构
    
    用于保持与现有报告生成系统的兼容性。
    """
    
    def __init__(self, timestamp: datetime, pv: float, sv: float, 
                 mv: float = 0.0, alarm_status: int = 0, alarms: List[str] = None):
        self.timestamp = timestamp
        self.pv = pv
        self.sv = sv
        self.mv = mv
        self.alarm_status = alarm_status
        self.alarms = alarms or []
        self.device_id = ""


def dict_to_data_point(data: Dict) -> SimpleDataPoint:
    """
    将字典转换为SimpleDataPoint对象
    
    Args:
        data: 数据字典
    
    Returns:
        SimpleDataPoint对象
    """
    point = SimpleDataPoint(
        timestamp=data["timestamp"],
        pv=data["pv"],
        sv=data["sv"],
        mv=data.get("mv", 0.0),
        alarm_status=data.get("alarm_status", 0),
        alarms=data.get("alarms", [])
    )
    point.device_id = data.get("device_id", "")
    return point


def data_points_to_simple(points: List[Dict]) -> List[SimpleDataPoint]:
    """
    将字典列表转换为SimpleDataPoint列表
    
    Args:
        points: 数据字典列表
    
    Returns:
        SimpleDataPoint列表
    """
    return [dict_to_data_point(p) for p in points]
