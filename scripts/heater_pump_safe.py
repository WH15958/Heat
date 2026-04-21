"""
安全加热器与蠕动泵联动实验脚本

功能：
1. 串口资源管理器集成
2. 进程锁文件
3. 紧急停止保障
4. 通道隔离
5. 异常恢复
6. 心跳检测

使用方法：
    python scripts/heater_pump_safe.py
"""

import sys
import os
import time
import argparse
import threading
import signal
import atexit
from datetime import datetime
from typing import Optional, List, Dict

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices import AIHeaterDevice, HeaterConfig, SafePumpDevice, ChannelTask
from devices.peristaltic_pump import PeristalticPumpConfig, PumpChannelConfig
from devices.base_device import DeviceInfo, DeviceType
from protocols.pump_params import PumpRunMode, PumpDirection
from utils import get_serial_manager, SerialPortForceRelease, cleanup_all_serial_ports, get_safety_manager, DeviceState, DeviceError

_experiment = None
_stop_event = threading.Event()


def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n" + "=" * 60)
    print("收到停止信号，正在安全关闭...")
    print("=" * 60)
    _stop_event.set()


def cleanup():
    """清理函数"""
    global _experiment
    
    if _experiment is not None:
        try:
            _experiment.emergency_stop()
            print("[清理] 设备已安全关闭")
        except Exception as e:
            print(f"[清理] 错误: {e}")
        finally:
            _experiment = None
    
    cleanup_all_serial_ports()
    print("[清理] 串口资源已释放")


class ExperimentLogger:
    """实验日志"""
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self._lock = threading.Lock()
        self._start_time = time.time()
    
    def log(self, message: str):
        """记录日志"""
        elapsed = time.time() - self._start_time
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}][{elapsed:6.1f}s] {message}"
        
        with self._lock:
            print(line)
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')


class SafeExperiment:
    """安全实验控制器"""
    
    def __init__(
        self,
        heater_ports: List[str],
        pump_port: str,
        target_temp: float = 35.0,
        pump_trigger_temp: float = 30.0,
        heat_duration: float = 300.0,
        hold_duration: float = 300.0,
        pump_volume: float = 10.0,
        pump_flow_rate: float = 20.0,
        force: bool = False,
    ):
        self.heater_ports = heater_ports
        self.pump_port = pump_port
        self.target_temp = target_temp
        self.pump_trigger_temp = pump_trigger_temp
        self.heat_duration = heat_duration
        self.hold_duration = hold_duration
        self.pump_volume = pump_volume
        self.pump_flow_rate = pump_flow_rate
        self.force = force
        
        self.logger = ExperimentLogger()
        self.heaters: List[AIHeaterDevice] = []
        self.pump: Optional[SafePumpDevice] = None
        
        self._safety_manager = get_safety_manager()
        self._serial_manager = get_serial_manager()
        self._running = False
        self._pump_triggered = False
        self._lock = threading.RLock()
        
        self._safety_manager.register_emergency_stop(self.emergency_stop)
    
    def connect_devices(self) -> bool:
        """连接所有设备"""
        self.logger.log("连接设备...")
        
        for port in self.heater_ports:
            if _stop_event.is_set():
                return False
            
            self.logger.log(f"  连接加热器 {port}...")
            
            if not self._serial_manager.acquire_port(port, force=self.force):
                self.logger.log(f"  [ERROR] 无法获取串口 {port}")
                
                if self.force:
                    SerialPortForceRelease.force_release(port)
                    time.sleep(0.5)
                    if not self._serial_manager.acquire_port(port, force=True):
                        return False
                else:
                    return False
            
            try:
                heater = AIHeaterDevice(HeaterConfig(
                    device_id=f"heater_{port}",
                    name=f"加热器_{port}",
                    port=port,
                    baudrate=9600,
                ))
                
                if heater.connect():
                    self.heaters.append(heater)
                    self.logger.log(f"  [OK] 加热器 {port} 连接成功")
                else:
                    self.logger.log(f"  [FAILED] 加热器 {port} 连接失败")
                    self._serial_manager.release_port(port)
                    return False
                    
            except Exception as e:
                self.logger.log(f"  [ERROR] 加热器 {port} 异常: {e}")
                self._serial_manager.release_port(port)
                return False
        
        if _stop_event.is_set():
            return False
        
        self.logger.log(f"  连接蠕动泵 {self.pump_port}...")
        
        if not self._serial_manager.acquire_port(self.pump_port, force=self.force):
            self.logger.log(f"  [ERROR] 无法获取串口 {self.pump_port}")
            
            if self.force:
                SerialPortForceRelease.force_release(self.pump_port)
                time.sleep(0.5)
                if not self._serial_manager.acquire_port(self.pump_port, force=True):
                    return False
            else:
                return False
        
        try:
            pump_config = PeristalticPumpConfig(
                device_id="pump1",
                connection_params={
                    "port": self.pump_port,
                    "baudrate": 9600,
                    "parity": "N",
                    "stopbits": 1,
                    "bytesize": 8,
                },
                channels=[
                    PumpChannelConfig(channel=1, enabled=True),
                    PumpChannelConfig(channel=4, enabled=True),
                ],
                slave_address=1,
                baudrate=9600,
                parity="N",
            )
            
            self.pump = SafePumpDevice(pump_config)
            
            if self.pump.connect(force=self.force):
                self.logger.log(f"  [OK] 蠕动泵 {self.pump_port} 连接成功")
            else:
                self.logger.log(f"  [FAILED] 蠕动泵 {self.pump_port} 连接失败")
                return False
                
        except Exception as e:
            self.logger.log(f"  [ERROR] 蠕动泵 {self.pump_port} 异常: {e}")
            return False
        
        self.logger.log("[OK] 所有设备连接成功")
        return True
    
    def disconnect_devices(self):
        """断开所有设备"""
        self.logger.log("断开设备连接...")
        
        for heater in self.heaters:
            try:
                heater.disconnect()
            except Exception as e:
                self.logger.log(f"  [WARNING] 加热器断开异常: {e}")
        self.heaters.clear()
        
        if self.pump:
            try:
                self.pump.disconnect()
            except Exception as e:
                self.logger.log(f"  [WARNING] 蠕动泵断开异常: {e}")
            self.pump = None
        
        for port in self.heater_ports:
            self._serial_manager.release_port(port)
        self._serial_manager.release_port(self.pump_port)
        
        self.logger.log("[OK] 所有设备已断开")
    
    def read_temperatures(self) -> List[tuple]:
        """读取所有加热器温度"""
        temps = []
        for heater in self.heaters:
            try:
                pv, sv = heater.read_temperature()
                temps.append((pv, sv))
            except Exception as e:
                self.logger.log(f"  [WARNING] 读取温度异常: {e}")
                temps.append((None, None))
        return temps
    
    def set_all_temperatures(self, temp: float):
        """设置所有加热器目标温度"""
        for heater in self.heaters:
            try:
                heater.set_temperature(temp)
            except Exception as e:
                self.logger.log(f"  [WARNING] 设置温度异常: {e}")
    
    def start_all_heaters(self):
        """启动所有加热器"""
        for heater in self.heaters:
            try:
                heater.start()
            except Exception as e:
                self.logger.log(f"  [WARNING] 启动加热器异常: {e}")
    
    def stop_all_heaters(self):
        """停止所有加热器"""
        for heater in self.heaters:
            try:
                heater.stop()
            except Exception as e:
                self.logger.log(f"  [WARNING] 停止加热器异常: {e}")
    
    def trigger_pump(self):
        """触发蠕动泵"""
        if self._pump_triggered:
            return
        
        self._pump_triggered = True
        self.logger.log(f"\n触发蠕动泵: 通道1和通道4 同时运行")
        
        task1 = ChannelTask(
            channel=1,
            volume=self.pump_volume,
            flow_rate=self.pump_flow_rate,
            direction=PumpDirection.CLOCKWISE,
            mode=PumpRunMode.QUANTITY_SPEED,
        )
        
        task4 = ChannelTask(
            channel=4,
            volume=self.pump_volume * 1.5,
            flow_rate=self.pump_flow_rate * 0.75,
            direction=PumpDirection.CLOCKWISE,
            mode=PumpRunMode.QUANTITY_SPEED,
        )
        
        if self.pump:
            self.pump.run_channel_task(task1)
            self.pump.run_channel_task(task4)
    
    def stop_pump(self):
        """停止蠕动泵"""
        if self.pump:
            try:
                self.pump.stop_all_channels()
            except Exception as e:
                self.logger.log(f"  [WARNING] 停止蠕动泵异常: {e}")
    
    def emergency_stop(self):
        """紧急停止"""
        self.logger.log("\n!!! 紧急停止 !!!")
        
        self.stop_all_heaters()
        self.stop_pump()
        self.disconnect_devices()
        
        self._running = False
    
    def run(self):
        """运行实验"""
        self._running = True
        
        try:
            self.logger.log("\n" + "=" * 60)
            self.logger.log("实验开始")
            self.logger.log("=" * 60)
            
            self.logger.log(f"目标温度: {self.target_temp}°C")
            self.logger.log(f"蠕动泵触发温度: {self.pump_trigger_temp}°C")
            self.logger.log(f"加热时间: {self.heat_duration}秒")
            self.logger.log(f"保持时间: {self.hold_duration}秒")
            
            if not self.connect_devices():
                self.logger.log("[ERROR] 设备连接失败")
                return
            
            self.logger.log("\n--- 阶段1: 启动加热器 ---")
            self.set_all_temperatures(self.target_temp)
            self.start_all_heaters()
            self.logger.log("[OK] 加热器已启动")
            
            self.logger.log("\n--- 阶段2: 加热到目标温度 ---")
            heat_start = time.time()
            reached_target = False
            pump_triggered = False
            
            while not _stop_event.is_set():
                elapsed = time.time() - heat_start
                
                if elapsed > self.heat_duration:
                    self.logger.log("[WARNING] 加热超时")
                    break
                
                temps = self.read_temperatures()
                temp_strs = []
                all_reached = True
                any_above_trigger = False
                
                for i, (pv, sv) in enumerate(temps):
                    if pv is not None:
                        temp_strs.append(f"H{i+1}={pv:.1f}°C")
                        if abs(pv - self.target_temp) > 2.0:
                            all_reached = False
                        if pv >= self.pump_trigger_temp:
                            any_above_trigger = True
                    else:
                        temp_strs.append(f"H{i+1}=N/A")
                        all_reached = False
                
                self.logger.log(f"  {', '.join(temp_strs)} | 用时: {elapsed:.0f}s")
                
                if any_above_trigger and not pump_triggered:
                    self.trigger_pump()
                    pump_triggered = True
                
                if all_reached:
                    reached_target = True
                    self.logger.log("[OK] 所有加热器达到目标温度")
                    break
                
                for _ in range(10):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)
            
            if _stop_event.is_set():
                self.logger.log("\n[停止] 用户中断")
                return
            
            self.logger.log("\n--- 阶段3: 保持温度 ---")
            hold_start = time.time()
            
            while not _stop_event.is_set():
                elapsed = time.time() - hold_start
                
                if elapsed > self.hold_duration:
                    break
                
                temps = self.read_temperatures()
                temp_strs = [f"H{i+1}={pv:.1f}°C" if pv else f"H{i+1}=N/A" 
                            for i, (pv, sv) in enumerate(temps)]
                
                pump_status = ""
                if self.pump:
                    ch1_state = self.pump.get_channel_state(1)
                    ch4_state = self.pump.get_channel_state(4)
                    pump_status = f" | 泵: CH1={ch1_state.value}, CH4={ch4_state.value}"
                
                self.logger.log(f"  {', '.join(temp_strs)}{pump_status} | 保持: {elapsed:.0f}s")
                
                for _ in range(10):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)
            
            if _stop_event.is_set():
                self.logger.log("\n[停止] 用户中断")
                return
            
            self.logger.log("[OK] 保持阶段完成")
            
            self.logger.log("\n--- 阶段4: 停止设备 ---")
            self.stop_all_heaters()
            self.stop_pump()
            self.logger.log("[OK] 所有设备已停止")
            
            self.logger.log("\n--- 阶段5: 自然降温 ---")
            cool_start = time.time()
            cool_duration = 60.0
            
            while not _stop_event.is_set():
                elapsed = time.time() - cool_start
                
                if elapsed > cool_duration:
                    break
                
                temps = self.read_temperatures()
                temp_strs = [f"H{i+1}={pv:.1f}°C" if pv else f"H{i+1}=N/A" 
                            for i, (pv, sv) in enumerate(temps)]
                self.logger.log(f"  {', '.join(temp_strs)} | 降温: {elapsed:.0f}s")
                
                for _ in range(10):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.1)
            
            self.logger.log("\n" + "=" * 60)
            self.logger.log("实验完成！")
            self.logger.log("=" * 60)
            
        except Exception as e:
            self.logger.log(f"\n[ERROR] 实验异常: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.emergency_stop()


def main():
    parser = argparse.ArgumentParser(description="安全加热器与蠕动泵联动实验")
    parser.add_argument(
        "--config",
        default="config/system_config.yaml",
        help="配置文件路径"
    )
    parser.add_argument(
        "--heater-ports",
        nargs="+",
        default=["COM7", "COM9"],
        help="加热器串口列表"
    )
    parser.add_argument(
        "--pump-port",
        default="COM10",
        help="蠕动泵串口"
    )
    parser.add_argument(
        "--target-temp",
        type=float,
        default=35.0,
        help="目标温度 (°C)"
    )
    parser.add_argument(
        "--pump-trigger-temp",
        type=float,
        default=30.0,
        help="蠕动泵触发温度 (°C)"
    )
    parser.add_argument(
        "--heat-duration",
        type=float,
        default=300.0,
        help="加热时间 (秒)"
    )
    parser.add_argument(
        "--hold-duration",
        type=float,
        default=300.0,
        help="保持时间 (秒)"
    )
    parser.add_argument(
        "--pump-volume",
        type=float,
        default=10.0,
        help="蠕动泵分装量 (mL)"
    )
    parser.add_argument(
        "--pump-flow-rate",
        type=float,
        default=20.0,
        help="蠕动泵流速 (mL/min)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制获取串口"
    )
    
    args = parser.parse_args()
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    global _experiment
    _experiment = SafeExperiment(
        heater_ports=args.heater_ports,
        pump_port=args.pump_port,
        target_temp=args.target_temp,
        pump_trigger_temp=args.pump_trigger_temp,
        heat_duration=args.heat_duration,
        hold_duration=args.hold_duration,
        pump_volume=args.pump_volume,
        pump_flow_rate=args.pump_flow_rate,
        force=args.force,
    )
    
    _experiment.run()


if __name__ == "__main__":
    main()
