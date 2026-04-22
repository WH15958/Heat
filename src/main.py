"""
自动化控制系统

主程序入口，提供设备控制、数据监控和报告生成的统一接口。
"""

import argparse
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from devices import AIHeaterDevice, HeaterConfig, DeviceStatus
from devices.base_device import DeviceConfig, DeviceInfo, DeviceType
from protocols import AIBUSProtocol, ParameterCode
from reports import ReportGenerator
from utils import ConfigManager, setup_logging, get_logger, CSVDataLogger, SimpleDataPoint, data_points_to_simple


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
        self._csv_logger: Optional[CSVDataLogger] = None
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
            
            # 初始化CSV记录器
            self._csv_logger = CSVDataLogger(
                output_dir=self.config.report.output_dir,
                filename_prefix="experiment"
            )
            
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
    
    def record_device_data(self, device_id: str):
        """
        手动记录设备数据
        
        Args:
            device_id: 设备ID
        """
        heater = self._heaters.get(device_id)
        if heater and heater.is_connected():
            try:
                data = heater.read_data()
                self._csv_logger.record(
                    device_id=device_id,
                    pv=data.pv,
                    sv=data.sv,
                    mv=data.mv,
                    alarm_status=data.alarm_status,
                    alarms=data.alarms
                )
            except Exception as e:
                self._logger.warning(f"Failed to record data for {device_id}: {e}")
    
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
    
    def start_recording(self):
        """开始数据记录"""
        if self._csv_logger:
            self._csv_logger.start()
            self._logger.info("Data recording started")
    
    def stop_recording(self):
        """停止数据记录"""
        if self._csv_logger:
            self._csv_logger.stop()
            self._logger.info("Data recording stopped")
    
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
        if self._csv_logger is None:
            self._logger.error("CSV logger not initialized")
            return None
        
        # 获取数据
        data_dicts = self._csv_logger.get_data_points(device_id)
        
        # 时间过滤
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(hours=1)
        
        filtered_data = [
            d for d in data_dicts 
            if start_time <= d["timestamp"] <= end_time
        ]
        
        if not filtered_data:
            self._logger.warning(f"No data found for {device_id}")
            return None
        
        # 转换为SimpleDataPoint格式
        data_points = data_points_to_simple(filtered_data)
        
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
        
        self.stop_recording()
        
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
        print("  record <device_id>      - 手动记录数据")
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
                elif cmd[0] == "record" and len(cmd) >= 2:
                    self.record_device_data(cmd[1])
                    print(f"Data recorded for {cmd[1]}")
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
