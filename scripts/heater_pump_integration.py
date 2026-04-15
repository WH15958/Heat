"""
蠕动泵与加热器联动控制示例

实验流程：
1. 从当前温度5分钟升温至35°C
2. 当温度到达30°C时蠕动泵通道1和4同时定时定量运行
3. 温度在35°C稳定5分钟
4. 停止加热，停止蠕动泵

使用方法：
    python scripts/heater_pump_integration.py
"""

import sys
import os
import time
import argparse
import threading
import signal
import atexit
from datetime import datetime
from typing import Optional, Tuple, List

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.peristaltic_pump import (
    LabSmartPumpDevice, 
    PeristalticPumpConfig, 
    PumpChannelConfig,
)
from devices.base_device import DeviceInfo, DeviceType
from protocols.pump_params import PumpRunMode, PumpDirection
from utils.config import ConfigManager, SystemConfig, HeaterDeviceConfig, PumpDeviceConfig

_stop_event = threading.Event()
_experiment = None


def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n收到停止信号，正在关闭...")
    _stop_event.set()


def cleanup():
    """清理函数"""
    global _experiment
    if _experiment is not None:
        try:
            _experiment.stop_all()
            _experiment.disconnect_devices()
            print("[清理] 设备已断开")
        except Exception as e:
            print(f"[清理] 错误: {e}")


atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class ExperimentLogger:
    """实验日志记录器"""
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self.start_time = time.time()
        
        if log_file:
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"实验开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n")
    
    def log(self, msg: str, to_file: bool = True):
        """打印并记录日志"""
        elapsed = time.time() - self.start_time
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}][{elapsed:7.1f}s] {msg}"
        print(full_msg, flush=True)
        
        if to_file and self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(full_msg + "\n")


class DeviceFactory:
    """设备工厂 - 根据配置创建设备实例"""
    
    @staticmethod
    def create_heater(config: HeaterDeviceConfig) -> AIHeaterDevice:
        """创建加热器设备"""
        heater_config = HeaterConfig(
            device_id=config.device_id,
            connection_params={
                'port': config.connection.port,
                'baudrate': config.connection.baudrate,
                'address': config.connection.address,
            },
            timeout=config.connection.timeout,
            decimal_places=config.decimal_places,
        )
        
        device_info = DeviceInfo(
            name=config.name,
            device_type=DeviceType.HEATER,
            manufacturer="Yudian",
        )
        
        return AIHeaterDevice(heater_config, device_info)
    
    @staticmethod
    def create_pump(config: PumpDeviceConfig) -> LabSmartPumpDevice:
        """创建蠕动泵设备"""
        channels = []
        for ch in config.channels:
            channels.append(PumpChannelConfig(
                channel=ch.channel,
                enabled=ch.enabled,
                pump_head=ch.pump_head,
                tube_model=ch.tube_model,
                max_flow_rate=ch.max_flow_rate,
            ))
        
        pump_config = PeristalticPumpConfig(
            device_id=config.device_id,
            connection_params={
                'port': config.connection.port,
                'baudrate': config.connection.baudrate,
            },
            slave_address=config.slave_address,
            parity=config.parity,
            stopbits=config.stopbits,
            bytesize=config.bytesize,
            channels=channels
        )
        
        device_info = DeviceInfo(
            name=config.name,
            device_type=DeviceType.PUMP,
            manufacturer="LabSmart",
        )
        
        return LabSmartPumpDevice(pump_config, device_info)


class HeaterPumpExperiment:
    """加热器与蠕动泵联动实验"""
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        log_file: Optional[str] = None
    ):
        self.config_path = config_path or "config/system_config.yaml"
        self.logger = ExperimentLogger(log_file)
        
        self.heaters: List[AIHeaterDevice] = []
        self.pump: Optional[LabSmartPumpDevice] = None
        self.pump_started = False
        self.running = False
        
        self._pump_threads: List[threading.Thread] = []
        
        global _experiment
        _experiment = self
    
    def stop_all(self):
        """停止所有设备"""
        _stop_event.set()
        
        for heater in self.heaters:
            try:
                heater.stop()
            except Exception:
                pass
        
        if self.pump:
            try:
                self.pump.stop_all()
            except Exception:
                pass
        
        for thread in self._pump_threads:
            if thread.is_alive():
                thread.join(timeout=2)
    
    def setup_devices(self):
        """初始化设备"""
        self.logger.log("\n" + "=" * 60)
        self.logger.log("初始化设备...")
        self.logger.log("=" * 60)
        
        config_manager = ConfigManager(self.config_path)
        system_config = config_manager.load_config()
        
        for heater_config in system_config.heaters:
            self.logger.log(f"配置加热器: {heater_config.name} ({heater_config.connection.port})")
            heater = DeviceFactory.create_heater(heater_config)
            self.heaters.append(heater)
        
        if system_config.pumps:
            pump_config = system_config.pumps[0]
            self.logger.log(f"配置蠕动泵: {pump_config.name} ({pump_config.connection.port})")
            self.pump = DeviceFactory.create_pump(pump_config)
        
        self.logger.log(f"设备配置完成: {len(self.heaters)}个加热器, {1 if self.pump else 0}个蠕动泵")
    
    def connect_devices(self):
        """连接所有设备"""
        for i, heater in enumerate(self.heaters):
            self.logger.log(f"\n连接加热器{i+1}...")
            if not heater.connect():
                raise RuntimeError(f"加热器{i+1}连接失败")
            self.logger.log(f"[OK] 加热器{i+1}已连接: {heater.info.model}")
        
        if self.pump:
            self.logger.log("\n连接蠕动泵...")
            if not self.pump.connect():
                raise RuntimeError("蠕动泵连接失败")
            self.logger.log("[OK] 蠕动泵已连接")
    
    def disconnect_devices(self):
        """断开所有设备"""
        for heater in self.heaters:
            try:
                heater.disconnect()
                self.logger.log(f"[OK] {heater.config.device_id}已断开")
            except Exception as e:
                self.logger.log(f"[WARN] 断开加热器失败: {e}")
        
        if self.pump:
            try:
                self.pump.disconnect()
                self.logger.log("[OK] 蠕动泵已断开")
            except Exception as e:
                self.logger.log(f"[WARN] 断开蠕动泵失败: {e}")
    
    def read_temperatures(self) -> List[Tuple[float, float]]:
        """读取所有加热器温度"""
        temps = []
        for heater in self.heaters:
            pv, sv = heater.read_temperature()
            temps.append((pv, sv))
        return temps
    
    def start_pump_async(self):
        """异步启动蠕动泵分装序列"""
        def pump_thread():
            try:
                self.start_pump_dispense_sequence()
            except Exception as e:
                if not _stop_event.is_set():
                    self.logger.log(f"[ERROR] 蠕动泵线程出错: {e}")
        
        thread = threading.Thread(target=pump_thread, daemon=False)
        self._pump_threads.append(thread)
        thread.start()
        return thread
    
    def start_pump_dispense_sequence(self):
        """启动蠕动泵定时定量分装序列（通道1和通道4同时运行）"""
        self.pump_started = True
        
        channel_configs = {
            1: [
                {"volume": 10.0, "flow_rate": 20.0, "name": "CH1-小量快速"},
            ],
            4: [
                {"volume": 15.0, "flow_rate": 15.0, "name": "CH4-小量慢速"},
            ]
        }
        
        self.logger.log("\n" + "=" * 60)
        self.logger.log("启动多通道分装序列")
        self.logger.log("=" * 60)
        
        threads = []
        for channel, configs in channel_configs.items():
            thread = threading.Thread(
                target=self._run_channel_sequence,
                args=(channel, configs),
                daemon=False
            )
            self._pump_threads.append(thread)
            thread.start()
            threads.append(thread)
        
        for thread in threads:
            thread.join()
        
        if not _stop_event.is_set():
            self.logger.log("\n[OK] 所有通道分装任务完成！")
    
    def _run_channel_sequence(self, channel: int, configs: list):
        """运行单个通道的分装序列"""
        for i, config in enumerate(configs):
            if _stop_event.is_set():
                return
            
            self.logger.log(f"\n--- 通道{channel} 分装 {i+1}/{len(configs)}: {config['name']} ---")
            self.logger.log(f"参数: 流速={config['flow_rate']} mL/min, 定量={config['volume']} mL")
            
            self.run_dispense_cycle(
                channel=channel,
                volume=config['volume'],
                flow_rate=config['flow_rate']
            )
            
            if i < len(configs) - 1 and not _stop_event.is_set():
                self.logger.log(f"通道{channel}: 等待3秒后进行下一次分装...")
                for _ in range(30):
                    if _stop_event.is_set():
                        return
                    time.sleep(0.1)
        
        if not _stop_event.is_set():
            self.logger.log(f"[OK] 通道{channel} 分装序列完成")
    
    def run_dispense_cycle(
        self,
        channel: int,
        volume: float,
        flow_rate: float,
        direction: PumpDirection = PumpDirection.CLOCKWISE
    ):
        """执行一次定时定量分装"""
        if not self.pump:
            self.logger.log("[WARN] 蠕动泵未初始化")
            return
        
        if _stop_event.is_set():
            return
        
        self.pump.set_run_mode(channel, PumpRunMode.QUANTITY_SPEED)
        self.pump.set_direction(channel, direction)
        self.pump.set_flow_rate(channel, flow_rate)
        self.pump.set_dispense_volume(channel, volume)
        
        self.logger.log(f"通道{channel}: 设置完成，开始分装...")
        
        self.pump.start_channel(channel)
        
        estimated_time = volume / flow_rate * 60
        self.logger.log(f"预计分装时间: {estimated_time:.1f}秒")
        
        start_time = time.time()
        
        while not _stop_event.is_set():
            if self.pump.is_closed():
                return
            
            status = self.pump.read_channel_status(channel)
            
            if status is None:
                self.logger.log("[WARN] 无法读取泵状态")
                for _ in range(10):
                    if _stop_event.is_set():
                        return
                    time.sleep(0.1)
                continue
            
            elapsed = time.time() - start_time
            
            self.logger.log(
                f"分装中: 已分装={status.dispensed_volume:.1f}mL, "
                f"剩余={status.remaining_volume:.1f}mL, "
                f"用时={elapsed:.1f}秒"
            )
            
            if not status.running and status.dispensed_volume >= volume * 0.95:
                self.logger.log(f"[OK] 分装完成: {status.dispensed_volume:.1f}mL")
                break
            
            if elapsed > estimated_time * 2:
                self.logger.log("[WARN] 分装超时，强制停止")
                self.pump.stop_channel(channel)
                break
            
            for _ in range(10):
                if _stop_event.is_set():
                    return
                time.sleep(0.1)
        
        if _stop_event.is_set():
            self.pump.stop_channel(channel)
    
    def run_experiment(
        self,
        target_temp: float = 35.0,
        heat_duration_minutes: float = 5.0,
        hold_minutes: float = 5.0,
        pump_trigger_temp: float = 30.0
    ):
        """
        运行完整实验
        
        流程：
        1. 从当前温度5分钟升温至35°C
        2. 当温度到达30°C时蠕动泵通道1,4同时定时定量运行
        3. 温度在35°C稳定5分钟
        4. 停止加热，停止蠕动泵
        """
        self.logger.log("\n" + "=" * 60)
        self.logger.log("开始实验")
        self.logger.log("=" * 60)
        self.logger.log(f"升温目标: {target_temp}°C (预计{heat_duration_minutes}分钟)")
        self.logger.log(f"蠕动泵触发温度: {pump_trigger_temp}°C")
        self.logger.log(f"稳定保持时间: {hold_minutes} 分钟")
        self.logger.log("=" * 60 + "\n")
        
        self.running = True
        pump_thread = None
        
        try:
            self.setup_devices()
            self.connect_devices()
            
            temps = self.read_temperatures()
            temp_strs = [f"H{i+1}={pv:.1f}°C" for i, (pv, sv) in enumerate(temps)]
            self.logger.log(f"初始温度: {', '.join(temp_strs)}")
            
            self.logger.log("\n--- 阶段1: 设置目标温度 ---")
            for heater in self.heaters:
                heater.set_temperature(target_temp)
            self.logger.log(f"[OK] {len(self.heaters)}个加热器目标温度已设置为 {target_temp}°C")
            
            self.logger.log("\n--- 阶段2: 启动加热器 ---")
            for heater in self.heaters:
                heater.start()
            self.logger.log(f"[OK] {len(self.heaters)}个加热器已启动")
            
            self.logger.log(f"\n--- 阶段3: 升温至 {target_temp}°C ---")
            self.logger.log(f"当温度达到 {pump_trigger_temp}°C 时启动蠕动泵")
            
            start_time = time.time()
            heat_timeout = heat_duration_minutes * 60 + 120
            pump_triggered = False
            
            while time.time() - start_time < heat_timeout and not _stop_event.is_set():
                temps = self.read_temperatures()
                elapsed = time.time() - start_time
                
                temp_strs = [f"H{i+1}={pv:.1f}°C" for i, (pv, sv) in enumerate(temps)]
                min_temp = min(pv for pv, sv in temps)
                
                pump_status = " | 泵: 运行中" if pump_triggered else ""
                self.logger.log(f"升温中: {', '.join(temp_strs)} | 最低={min_temp:.1f}°C{pump_status}")
                
                if not pump_triggered and min_temp >= pump_trigger_temp:
                    self.logger.log(f"\n{'*'*60}")
                    self.logger.log(f"温度达到 {pump_trigger_temp}°C，启动蠕动泵！")
                    self.logger.log(f"{'*'*60}\n")
                    pump_thread = self.start_pump_async()
                    pump_triggered = True
                
                all_reached = all(pv >= target_temp - 0.5 for pv, sv in temps)
                if all_reached:
                    self.logger.log(f"[OK] 所有加热器温度都已达到 {target_temp}°C")
                    break
                
                for _ in range(20):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)
            
            if _stop_event.is_set():
                self.logger.log("\n[停止] 用户中断")
                return
            
            self.logger.log(f"\n--- 阶段4: 在 {target_temp}°C 稳定 {hold_minutes} 分钟 ---")
            hold_start = time.time()
            hold_seconds = hold_minutes * 60
            
            while time.time() - hold_start < hold_seconds and not _stop_event.is_set():
                temps = self.read_temperatures()
                elapsed = time.time() - hold_start
                remaining = hold_seconds - elapsed
                
                temp_strs = [f"H{i+1}={pv:.1f}°C" for i, (pv, sv) in enumerate(temps)]
                
                pump_status = ""
                if pump_triggered and self.pump and not self.pump.is_closed():
                    status_parts = []
                    for ch in [1, 4]:
                        status = self.pump.read_channel_status(ch)
                        if status:
                            status_parts.append(f"CH{ch}:{status.dispensed_volume:.1f}mL")
                    if status_parts:
                        pump_status = f" | 泵: {', '.join(status_parts)}"
                
                self.logger.log(
                    f"保持中: {', '.join(temp_strs)}, "
                    f"剩余: {remaining/60:.1f}分钟{pump_status}"
                )
                
                for _ in range(100):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)
            
            if _stop_event.is_set():
                self.logger.log("\n[停止] 用户中断")
                return
            
            self.logger.log("[OK] 保持阶段完成")
            
            self.logger.log("\n--- 阶段5: 停止加热器和蠕动泵 ---")
            for heater in self.heaters:
                heater.stop()
            self.logger.log("[OK] 所有加热器已停止")
            
            if pump_thread and pump_thread.is_alive():
                self.logger.log("蠕动泵仍在运行，等待完成...")
                pump_thread.join(timeout=60)
            
            if self.pump:
                self.pump.stop_channel(1)
                self.pump.stop_channel(4)
                self.logger.log("[OK] 蠕动泵已停止（通道1、4）")
            
            self.logger.log("\n--- 阶段6: 实验结束 ---")
            
            temps = self.read_temperatures()
            temp_strs = [f"H{i+1}={pv:.1f}°C" for i, (pv, sv) in enumerate(temps)]
            self.logger.log(f"最终温度: {', '.join(temp_strs)}")
            
            self.logger.log("\n" + "=" * 60)
            self.logger.log("实验完成！")
            self.logger.log("=" * 60)
            
        except Exception as e:
            self.logger.log(f"\n[ERROR] 实验出错: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.stop_all()
            self.disconnect_devices()
            self.running = False


def main():
    parser = argparse.ArgumentParser(description="加热器与蠕动泵联动实验")
    parser.add_argument(
        "--config", 
        default=None, 
        help="配置文件路径 (默认: config/system_config.yaml)"
    )
    parser.add_argument(
        "--target-temp", 
        type=float, 
        default=35.0, 
        help="升温目标温度 (默认: 35°C)"
    )
    parser.add_argument(
        "--heat-duration", 
        type=float, 
        default=5.0, 
        help="升温时间 (默认: 5分钟)"
    )
    parser.add_argument(
        "--hold-minutes", 
        type=float, 
        default=5.0, 
        help="稳定保持时间 (默认: 5分钟)"
    )
    parser.add_argument(
        "--pump-trigger-temp", 
        type=float, 
        default=30.0, 
        help="蠕动泵触发温度 (默认: 30°C)"
    )
    parser.add_argument(
        "--log-file", 
        default=None, 
        help="日志文件路径"
    )
    
    args = parser.parse_args()
    
    experiment = HeaterPumpExperiment(
        config_path=args.config,
        log_file=args.log_file
    )
    
    experiment.run_experiment(
        target_temp=args.target_temp,
        heat_duration_minutes=args.heat_duration,
        hold_minutes=args.hold_minutes,
        pump_trigger_temp=args.pump_trigger_temp
    )


if __name__ == "__main__":
    main()
