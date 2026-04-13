"""
日志工具模块

提供统一的日志配置和管理功能。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from logging.handlers import RotatingFileHandler


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    max_file_size_mb: int = 10,
    backup_count: int = 5,
    console_output: bool = True,
    file_output: bool = True,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
) -> logging.Logger:
    """
    配置系统日志
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: 日志文件目录
        max_file_size_mb: 单个日志文件最大大小(MB)
        backup_count: 保留的日志文件数量
        console_output: 是否输出到控制台
        file_output: 是否输出到文件
        log_format: 日志格式
    
    Returns:
        logging.Logger: 根日志记录器
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    formatter = logging.Formatter(log_format)
    
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    if file_output:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        log_filename = f"system_{datetime.now().strftime('%Y%m%d')}.log"
        file_path = log_path / log_filename
        
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器
    
    Args:
        name: 日志记录器名称
    
    Returns:
        logging.Logger: 日志记录器
    """
    return logging.getLogger(name)


class DeviceLogger:
    """
    设备专用日志记录器
    
    为设备操作提供独立的日志文件。
    """
    
    def __init__(self, device_id: str, log_dir: str = "logs"):
        """
        初始化设备日志记录器
        
        Args:
            device_id: 设备ID
            log_dir: 日志目录
        """
        self.device_id = device_id
        self.logger = logging.getLogger(f"device.{device_id}")
        
        if not self.logger.handlers:
            log_path = Path(log_dir) / "devices"
            log_path.mkdir(parents=True, exist_ok=True)
            
            log_filename = f"{device_id}_{datetime.now().strftime('%Y%m%d')}.log"
            file_path = log_path / log_filename
            
            handler = RotatingFileHandler(
                file_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding='utf-8'
            )
            
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)
    
    def debug(self, msg: str):
        self.logger.debug(msg)
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)
    
    def critical(self, msg: str):
        self.logger.critical(msg)
    
    def log_data(self, data: dict):
        """记录设备数据"""
        import json
        self.info(f"DATA: {json.dumps(data, ensure_ascii=False)}")
    
    def log_command(self, command: str, value, success: bool):
        """记录命令执行"""
        status = "SUCCESS" if success else "FAILED"
        self.info(f"COMMAND: {command}={value} [{status}]")
