"""
自动化控制系统

主程序入口，提供设备控制、数据监控和报告生成的统一接口。
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

import argparse
import signal
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from devices import AIHeaterDevice, HeaterConfig, DeviceStatus
from devices.base_device import DeviceConfig, DeviceInfo, DeviceType
from protocols import AIBUSProtocol, ParameterCode
from monitor import DataMonitor, AlarmRule
from reports import ReportGenerator
from utils import ConfigManager, setup_logging, get_logger


class AutomationController:
    """
    自动化控制器
    
    统一管理所有设备、监控和报告功能。
    
    Example:
        >>> controller = AutomationController()
        >>> controller.initialize()
        >>> controller.start_heater("heater1", temperature=100.0)
        >>> # ... 运行实验 ...
        >>> controller.stop_heater("heater1")
        >>> controller.generate_report("heater1")
        >>> controller.shutdown()
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化控制器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_manager = ConfigManager(config_path)
        self.config = None
        self._heaters: Dict[str, AIHeaterDevice] = {}
        self._monitor: Optional[DataMonitor] = None
        self._report_generator: Optional[ReportGenerator] = None
        self._logger = get_logger(__name__)
        self._running = False
    
    def initialize(self) -> bool:
        """
        初始化系统
        
        加载配置、设置日志、初始化设备。
        
        Returns:
            bool: 初始化成功返回True
        """
        try:
            self.config = self.config_manager.load()
            
            setup_logging(
                level=self.config.logging.level,
                log_dir=self.config.logging.log_dir,
                console_output=self.config.logging.console_output,
                file_output=self.config.logging.file_output,
            )
            
            self._logger.info(f"Initializing {self.config.name} v{self.config.version}")
            
            self._init_heaters()
            
            if self.config.monitor.enabled:
                self._init_monitor()
            
            self._report_generator = ReportGenerator(self.config.report.output_dir)
            
            self._running = True
            self._logger.info("System initialized successfully")
            return True
            
        except Exception as e:
            self._logger.error(f"Initialization failed: {e}")
            return False
    
    def _init_heaters(self):
        """初始化加热器设备"""
        for heater_cfg in self.config.heaters:
            if not heater_cfg.enabled:
                continue
            
            device_config = HeaterConfig(
                device_id=heater_cfg.device_id,
                connection_params={
                    'port': heater_cfg.connection.port,
                    'baudrate': heater_cfg.connection.baudrate,
                    'address': heater_cfg.connection.address,
                    'parity': heater_cfg.connection.parity,
                },
                timeout=heater_cfg.connection.timeout,
                poll_interval=heater_cfg.poll_interval,
                decimal_places=heater_cfg.decimal_places,
                temperature_unit=heater_cfg.temperature_unit,
                max_temperature=heater_cfg.max_temperature,
                min_temperature=heater_cfg.min_temperature,
                safety_limit=heater_cfg.safety_limit,
            )
            
            device_info = DeviceInfo(
                name=heater_cfg.name,
                device_type=DeviceType.HEATER,
                manufacturer="Yudian",
            )
            
            heater = AIHeaterDevice(device_config, device_info)
            self._heaters[heater_cfg.device_id] = heater
            self._logger.info(f"Heater device created: {heater_cfg.device_id}")
    
    def _init_monitor(self):
        """初始化数据监控"""
        self._monitor = DataMonitor(
            storage_dir="data",
            use_database=self.config.monitor.enable_database,
            poll_interval=self.config.monitor.log_interval,
        )
        
        for device_id, heater in self._heaters.items():
            self._monitor.add_device(heater)
        
        high_temp_rule = AlarmRule(
            name="high_temperature_warning",
            device_id="heater1",
            parameter="pv",
            operator=">",
            threshold=350.0,
            description="温度过高警告"
        )
        self._monitor.add_alarm_rule(high_temp_rule)
        
        self._monitor.add_alarm_callback(self._on_alarm)
    
    def _on_alarm(self, rule_name: str, device_id: str, value: float):
        """报警回调处理"""
        self._logger.warning(f"ALARM: {rule_name} on {device_id}, value={value}")
    
    def connect_device(self, device_id: str) -> bool:
        """
        连接指定设备
        
        Args:
            device_id: 设备ID
        
        Returns:
            bool: 连接成功返回True
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            self._logger.error(f"Device not found: {device_id}")
            return False
        
        try:
            heater.connect()
            self._logger.info(f"Device connected: {device_id}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to connect device {device_id}: {e}")
            return False
    
    def disconnect_device(self, device_id: str) -> bool:
        """断开设备连接"""
        heater = self._heaters.get(device_id)
        if heater:
            heater.disconnect()
            self._logger.info(f"Device disconnected: {device_id}")
        return True
    
    def start_monitoring(self):
        """启动数据监控"""
        if self._monitor:
            self._monitor.start()
            self._logger.info("Data monitoring started")
    
    def stop_monitoring(self):
        """停止数据监控"""
        if self._monitor:
            self._monitor.stop()
            self._logger.info("Data monitoring stopped")
    
    def start_heater(self, device_id: str, temperature: float) -> bool:
        """
        启动加热器并设定温度
        
        Args:
            device_id: 设备ID
            temperature: 目标温度
        
        Returns:
            bool: 启动成功返回True
        """
        heater = self._heaters.get(device_id)
        if heater is None:
            self._logger.error(f"Heater not found: {device_id}")
            return False
        
        if not heater.is_connected():
            if not self.connect_device(device_id):
                return False
        
        try:
            heater.set_temperature(temperature)
            heater.start()
            self._logger.info(f"Heater {device_id} started at {temperature}°C")
            return True
        except Exception as e:
            self._logger.error(f"Failed to start heater {device_id}: {e}")
            return False
    
    def stop_heater(self, device_id: str) -> bool:
        """停止加热器"""
        heater = self._heaters.get(device_id)
        if heater:
            heater.stop()
            self._logger.info(f"Heater {device_id} stopped")
        return True
    
    def emergency_stop(self, device_id: str = None):
        """
        紧急停止
        
        Args:
            device_id: 设备ID，如果为None则停止所有设备
        """
        if device_id:
            heater = self._heaters.get(device_id)
            if heater:
                heater.emergency_stop()
        else:
            for heater in self._heaters.values():
                heater.emergency_stop()
        
        self._logger.warning("Emergency stop executed")
    
    def get_device_status(self, device_id: str) -> Optional[Dict]:
        """获取设备状态"""
        heater = self._heaters.get(device_id)
        if heater and heater.is_connected():
            data = heater.read_data()
            return {
                'device_id': device_id,
                'status': heater.status.value,
                'pv': data.pv,
                'sv': data.sv,
                'mv': data.mv,
                'alarms': data.alarms,
            }
        return None
    
    def get_all_status(self) -> Dict[str, Dict]:
        """获取所有设备状态"""
        status = {}
        for device_id in self._heaters:
            status[device_id] = self.get_device_status(device_id)
        return status
    
    def generate_report(self, 
                       device_id: str,
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       title: str = "Experiment Report") -> Optional[str]:
        """
        生成数据报告
        
        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间
            title: 报告标题
        
        Returns:
            str: 报告文件路径
        """
        if self._monitor is None:
            self._logger.error("Monitor not initialized")
            return None
        
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(hours=1)
        
        data_points = self._monitor.query_data(device_id, start_time, end_time)
        
        if not data_points:
            self._logger.warning(f"No data found for {device_id}")
            return None
        
        report_path = self._report_generator.generate(
            device_id=device_id,
            data_points=data_points,
            title=title,
        )
        
        return report_path
    
    def run_experiment(self, 
                      device_id: str,
                      temperature: float,
                      duration_minutes: float,
                      wait_for_temp: bool = True,
                      tolerance: float = 1.0) -> bool:
        """
        运行加热实验
        
        Args:
            device_id: 设备ID
            temperature: 目标温度
            duration_minutes: 持续时间(分钟)
            wait_for_temp: 是否等待温度达到
            tolerance: 温度容差
        
        Returns:
            bool: 实验成功返回True
        """
        self._logger.info(
            f"Starting experiment: {device_id} at {temperature}°C "
            f"for {duration_minutes} minutes"
        )
        
        if not self.start_heater(device_id, temperature):
            return False
        
        if wait_for_temp:
            heater = self._heaters[device_id]
            self._logger.info(f"Waiting for temperature to reach {temperature}°C...")
            
            def progress_callback(pv, sv):
                self._logger.info(f"Temperature: PV={pv:.1f}°C, SV={sv:.1f}°C")
            
            if not heater.wait_for_temperature(
                temperature, 
                tolerance=tolerance,
                timeout=3600,
                callback=progress_callback
            ):
                self._logger.error("Failed to reach target temperature")
                self.stop_heater(device_id)
                return False
        
        self._logger.info(f"Holding temperature for {duration_minutes} minutes...")
        time.sleep(duration_minutes * 60)
        
        self.stop_heater(device_id)
        self._logger.info("Experiment completed")
        
        return True
    
    def shutdown(self):
        """关闭系统"""
        self._logger.info("Shutting down system...")
        
        self._running = False
        
        self.stop_monitoring()
        
        for device_id in list(self._heaters.keys()):
            self.disconnect_device(device_id)
        
        self._logger.info("System shutdown complete")
    
    def interactive_mode(self):
        """交互模式"""
        print("\n" + "="*50)
        print("自动化控制系统 - 交互模式")
        print("="*50)
        print("可用命令:")
        print("  connect <device_id>     - 连接设备")
        print("  disconnect <device_id>  - 断开设备")
        print("  start <device_id> <temp> - 启动加热")
        print("  stop <device_id>        - 停止加热")
        print("  status [device_id]      - 查看状态")
        print("  report <device_id>      - 生成报告")
        print("  emergency [device_id]   - 紧急停止")
        print("  quit                    - 退出")
        print("="*50 + "\n")
        
        while self._running:
            try:
                cmd = input("> ").strip().split()
                if not cmd:
                    continue
                
                if cmd[0] == "quit":
                    break
                elif cmd[0] == "connect" and len(cmd) >= 2:
                    self.connect_device(cmd[1])
                elif cmd[0] == "disconnect" and len(cmd) >= 2:
                    self.disconnect_device(cmd[1])
                elif cmd[0] == "start" and len(cmd) >= 3:
                    self.start_heater(cmd[1], float(cmd[2]))
                elif cmd[0] == "stop" and len(cmd) >= 2:
                    self.stop_heater(cmd[1])
                elif cmd[0] == "status":
                    if len(cmd) >= 2:
                        status = self.get_device_status(cmd[1])
                        print(status)
                    else:
                        for device_id, status in self.get_all_status().items():
                            print(f"{device_id}: {status}")
                elif cmd[0] == "report" and len(cmd) >= 2:
                    path = self.generate_report(cmd[1])
                    if path:
                        print(f"Report generated: {path}")
                elif cmd[0] == "emergency":
                    device_id = cmd[1] if len(cmd) >= 2 else None
                    self.emergency_stop(device_id)
                else:
                    print("Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        self.shutdown()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="自动化控制系统")
    parser.add_argument(
        "-c", "--config",
        help="配置文件路径"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="启动交互模式"
    )
    parser.add_argument(
        "--device",
        default="heater1",
        help="设备ID"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=100.0,
        help="目标温度"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="持续时间(分钟)"
    )
    
    args = parser.parse_args()
    
    controller = AutomationController(args.config)
    
    def signal_handler(sig, frame):
        print("\nReceived interrupt signal, shutting down...")
        controller.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    if not controller.initialize():
        print("Failed to initialize system")
        sys.exit(1)
    
    if args.interactive:
        controller.interactive_mode()
    else:
        print(f"Running experiment on {args.device}")
        print(f"Temperature: {args.temperature}°C")
        print(f"Duration: {args.duration} minutes")
        
        success = controller.run_experiment(
            args.device,
            args.temperature,
            args.duration
        )
        
        if success:
            report_path = controller.generate_report(args.device)
            if report_path:
                print(f"Report generated: {report_path}")
        
        controller.shutdown()


if __name__ == "__main__":
    main()
