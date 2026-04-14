"""
蠕动泵与加热器联动控制示例

实验流程：
1. 加热到30°C
2. 到达30°C时，蠕动泵通道1开始定时定量运行
3. 同时保持温度20分钟
4. 保持结束后开始降温

使用方法：
    python scripts/heater_pump_integration.py
"""

import sys
import os
import time
import argparse
import threading
from datetime import datetime
from typing import Optional, Tuple

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.peristaltic_pump import (
    LabSmartPumpDevice, 
    PeristalticPumpConfig, 
    PumpChannelConfig,
    PumpChannelData
)
from devices.base_device import DeviceInfo, DeviceType
from protocols.pump_params import PumpRunMode, PumpDirection


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


class HeaterPumpExperiment:
    """加热器与蠕动泵联动实验"""
    
    def __init__(
        self,
        heater_port: str = "COM3",
        pump_port: str = "COM4",
        log_file: Optional[str] = None
    ):
        self.logger = ExperimentLogger(log_file)
        
        self.heater_port = heater_port
        self.pump_port = pump_port
        
        self.heater: Optional[AIHeaterDevice] = None
        self.pump: Optional[LabSmartPumpDevice] = None
        
        self.running = False
        self.pump_started = False
    
    def setup_devices(self):
        """初始化设备"""
        self.logger.log("=" * 60)
        self.logger.log("初始化设备...")
        self.logger.log("=" * 60)
        
        heater_config = HeaterConfig(
            device_id="heater1",
            connection_params={
                'port': self.heater_port,
                'baudrate': 9600,
                'address': 1,
            },
            timeout=2.0,
            decimal_places=1,
        )
        
        heater_info = DeviceInfo(
            name="主加热器",
            device_type=DeviceType.HEATER,
            manufacturer="Yudian",
        )
        
        self.heater = AIHeaterDevice(heater_config, heater_info)
        
        pump_config = PeristalticPumpConfig(
            device_id="pump1",
            connection_params={
                'port': self.pump_port,
                'baudrate': 9600,
            },
            slave_address=1,
            channels=[
                PumpChannelConfig(channel=1, enabled=True, max_flow_rate=100.0),
            ]
        )
        
        self.pump = LabSmartPumpDevice(pump_config)
        
        self.logger.log("设备配置完成")
    
    def connect_devices(self):
        """连接设备"""
        self.logger.log("\n连接加热器...")
        if self.heater.connect():
            self.logger.log(f"[OK] 加热器已连接: {self.heater.model_name}")
        else:
            raise RuntimeError("加热器连接失败")
        
        self.logger.log("\n连接蠕动泵...")
        if self.pump.connect():
            self.logger.log("[OK] 蠕动泵已连接")
        else:
            raise RuntimeError("蠕动泵连接失败")
    
    def disconnect_devices(self):
        """断开设备连接"""
        if self.heater:
            self.heater.disconnect()
            self.logger.log("[OK] 加热器已断开")
        
        if self.pump:
            self.pump.disconnect()
            self.logger.log("[OK] 蠕动泵已断开")
    
    def read_temperature(self) -> Tuple[float, float]:
        """读取当前温度"""
        data = self.heater.read_data()
        return data.pv, data.sv
    
    def wait_for_temperature(
        self, 
        target: float, 
        tolerance: float = 0.5,
        timeout: float = 600,
        check_interval: float = 2.0
    ) -> bool:
        """等待温度达到目标值"""
        self.logger.log(f"等待温度达到 {target}°C (容差: ±{tolerance}°C)...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            pv, sv = self.read_temperature()
            elapsed = time.time() - start_time
            
            self.logger.log(f"温度: PV={pv:.1f}°C, SV={sv:.1f}°C, 目标={target}°C")
            
            if abs(pv - target) <= tolerance:
                self.logger.log(f"[OK] 温度已稳定在 {target}°C")
                return True
            
            time.sleep(check_interval)
        
        self.logger.log(f"[WARN] 等待超时，当前温度: {pv:.1f}°C")
        return False
    
    def hold_temperature_with_pump(
        self, 
        duration_minutes: float, 
        check_interval: float = 10.0
    ):
        """保持当前温度一段时间，同时监控蠕动泵状态"""
        self.logger.log(f"\n保持温度 {duration_minutes} 分钟（蠕动泵同时运行）...")
        
        duration_seconds = duration_minutes * 60
        start_time = time.time()
        
        while time.time() - start_time < duration_seconds:
            pv, sv = self.read_temperature()
            elapsed = time.time() - start_time
            remaining = duration_seconds - elapsed
            
            pump_status = ""
            if self.pump_started:
                status = self.pump.get_channel_status(1)
                if status:
                    pump_status = f" | 泵: {status.dispensed_volume:.1f}mL"
            
            self.logger.log(
                f"保持中: PV={pv:.1f}°C, SV={sv:.1f}°C, "
                f"剩余: {remaining/60:.1f}分钟{pump_status}"
            )
            
            time.sleep(check_interval)
        
        self.logger.log("[OK] 保持阶段完成")
    
    def start_pump_async(self):
        """异步启动蠕动泵分装序列"""
        def pump_thread():
            try:
                self.start_pump_dispense_sequence()
            except Exception as e:
                self.logger.log(f"[ERROR] 蠕动泵线程出错: {e}")
        
        thread = threading.Thread(target=pump_thread, daemon=True)
        thread.start()
        return thread
    
    def ramp_temperature(
        self,
        start_temp: float,
        end_temp: float,
        duration_minutes: float,
        interval_seconds: float = 10.0
    ):
        """斜率升温/降温"""
        self.logger.log(f"\n{'='*60}")
        self.logger.log(f"温度变化: {start_temp}°C → {end_temp}°C")
        self.logger.log(f"持续时间: {duration_minutes} 分钟")
        self.logger.log(f"{'='*60}")
        
        duration_seconds = duration_minutes * 60
        temp_diff = end_temp - start_temp
        steps = max(1, int(duration_seconds / interval_seconds))
        temp_step = temp_diff / steps
        
        start_time = time.time()
        
        for step in range(steps + 1):
            target_temp = start_temp + temp_step * step
            self.heater.set_temperature(target_temp)
            
            pv, sv = self.read_temperature()
            elapsed = time.time() - start_time
            remaining = duration_seconds - elapsed
            
            self.logger.log(
                f"目标: {target_temp:.1f}°C | "
                f"当前: PV={pv:.1f}°C | "
                f"设定: SV={sv:.1f}°C | "
                f"剩余: {remaining:.0f}秒"
            )
            
            if step < steps:
                time.sleep(interval_seconds)
        
        self.logger.log(f"[OK] 温度变化完成")
    
    def cooldown_to_target(
        self,
        target_temp: float,
        check_interval: float = 5.0,
        pump_trigger_temp: float = 3.0
    ):
        """降温到目标温度，并在触发温度启动蠕动泵"""
        self.logger.log(f"\n{'='*60}")
        self.logger.log(f"降温阶段: 目标 {target_temp}°C")
        self.logger.log(f"蠕动泵触发温度: {pump_trigger_temp}°C")
        self.logger.log(f"{'='*60}")
        
        self.heater.set_temperature(target_temp)
        
        while True:
            pv, sv = self.read_temperature()
            
            self.logger.log(f"降温中: PV={pv:.1f}°C, SV={sv:.1f}°C")
            
            if not self.pump_started and pv <= pump_trigger_temp:
                self.logger.log(f"\n{'*'*60}")
                self.logger.log(f"温度达到 {pump_trigger_temp}°C，启动蠕动泵！")
                self.logger.log(f"{'*'*60}\n")
                self.start_pump_dispense_sequence()
            
            if pv <= target_temp + 0.5:
                self.logger.log(f"[OK] 降温完成，当前温度: {pv:.1f}°C")
                break
            
            time.sleep(check_interval)
    
    def start_pump_dispense_sequence(self):
        """启动蠕动泵定时定量分装序列"""
        self.pump_started = True
        
        dispense_configs = [
            {"volume": 10.0, "flow_rate": 20.0, "name": "小量快速"},
            {"volume": 25.0, "flow_rate": 30.0, "name": "中量中速"},
            {"volume": 50.0, "flow_rate": 50.0, "name": "大量高速"},
            {"volume": 15.0, "flow_rate": 15.0, "name": "小量慢速"},
        ]
        
        for i, config in enumerate(dispense_configs):
            self.logger.log(f"\n--- 分装 {i+1}/{len(dispense_configs)}: {config['name']} ---")
            self.logger.log(f"参数: 流速={config['flow_rate']} mL/min, 定量={config['volume']} mL")
            
            self.run_dispense_cycle(
                channel=1,
                volume=config['volume'],
                flow_rate=config['flow_rate']
            )
            
            if i < len(dispense_configs) - 1:
                self.logger.log("等待5秒后进行下一次分装...")
                time.sleep(5)
        
        self.logger.log("\n[OK] 所有分装任务完成！")
    
    def run_dispense_cycle(
        self,
        channel: int,
        volume: float,
        flow_rate: float,
        direction: PumpDirection = PumpDirection.CLOCKWISE
    ):
        """执行一次定时定量分装"""
        self.pump.set_run_mode(channel, PumpRunMode.QUANTITY_SPEED)
        self.pump.set_direction(channel, direction)
        self.pump.set_flow_rate(channel, flow_rate)
        self.pump.set_dispense_volume(channel, volume)
        
        self.logger.log(f"通道{channel}: 设置完成，开始分装...")
        
        self.pump.start_channel(channel)
        
        estimated_time = volume / flow_rate * 60
        self.logger.log(f"预计分装时间: {estimated_time:.1f}秒")
        
        start_time = time.time()
        
        while True:
            status = self.pump.get_channel_status(channel)
            
            if status is None:
                self.logger.log("[WARN] 无法读取泵状态")
                time.sleep(1)
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
            
            time.sleep(1)
    
    def run_experiment(
        self,
        heat_temp: float = 30.0,
        hold_minutes: float = 20.0,
        cooldown_target: float = 3.0
    ):
        """运行完整实验"""
        self.logger.log("\n" + "=" * 60)
        self.logger.log("开始实验")
        self.logger.log("=" * 60)
        self.logger.log(f"加热目标: {heat_temp}°C")
        self.logger.log(f"保持时间: {hold_minutes} 分钟")
        self.logger.log(f"降温目标: {cooldown_target}°C")
        self.logger.log(f"蠕动泵触发: 到达 {heat_temp}°C 时启动")
        self.logger.log("=" * 60 + "\n")
        
        self.running = True
        pump_thread = None
        
        try:
            self.setup_devices()
            self.connect_devices()
            
            pv, sv = self.read_temperature()
            self.logger.log(f"初始温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
            
            self.logger.log("\n--- 阶段1: 启动加热器 ---")
            self.heater.start()
            self.logger.log("[OK] 加热器已启动")
            
            self.logger.log(f"\n--- 阶段2: 加热到 {heat_temp}°C ---")
            self.heater.set_temperature(heat_temp)
            self.wait_for_temperature(heat_temp, tolerance=0.5, timeout=600)
            
            self.logger.log(f"\n{'*'*60}")
            self.logger.log(f"温度达到 {heat_temp}°C，启动蠕动泵！")
            self.logger.log(f"{'*'*60}\n")
            
            self.logger.log("\n--- 阶段3: 启动蠕动泵（异步） ---")
            pump_thread = self.start_pump_async()
            self.logger.log("[OK] 蠕动泵线程已启动")
            
            self.logger.log("\n--- 阶段4: 保持温度（蠕动泵同时运行） ---")
            self.hold_temperature_with_pump(hold_minutes)
            
            self.logger.log("\n--- 阶段5: 等待蠕动泵完成 ---")
            if pump_thread and pump_thread.is_alive():
                self.logger.log("蠕动泵仍在运行，等待完成...")
                pump_thread.join(timeout=300)
                if pump_thread.is_alive():
                    self.logger.log("[WARN] 蠕动泵运行超时，强制停止")
                    self.pump.stop_channel(1)
            
            self.logger.log("\n--- 阶段6: 降温 ---")
            self.heater.stop()
            self.logger.log(f"开始降温到 {cooldown_target}°C...")
            
            while True:
                pv, sv = self.read_temperature()
                self.logger.log(f"降温中: PV={pv:.1f}°C")
                
                if pv <= cooldown_target + 0.5:
                    self.logger.log(f"[OK] 降温完成，当前温度: {pv:.1f}°C")
                    break
                
                time.sleep(5)
            
            self.logger.log("\n--- 阶段7: 实验结束 ---")
            self.heater.stop()
            
            if self.pump_started:
                self.pump.stop_channel(1)
                self.logger.log("[OK] 蠕动泵已停止")
            
            self.logger.log("\n" + "=" * 60)
            self.logger.log("实验完成！")
            self.logger.log("=" * 60)
            
        except KeyboardInterrupt:
            self.logger.log("\n\n[WARN] 用户中断实验")
            self.heater.stop()
            if self.pump:
                self.pump.stop_channel(1)
        
        except Exception as e:
            self.logger.log(f"\n[ERROR] 实验出错: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.disconnect_devices()
            self.running = False


def main():
    parser = argparse.ArgumentParser(description="加热器与蠕动泵联动实验")
    parser.add_argument(
        "--heater-port", 
        default="COM3", 
        help="加热器串口 (默认: COM3)"
    )
    parser.add_argument(
        "--pump-port", 
        default="COM4", 
        help="蠕动泵串口 (默认: COM4)"
    )
    parser.add_argument(
        "--heat-temp", 
        type=float, 
        default=30.0, 
        help="加热目标温度，蠕动泵在此温度启动 (默认: 30°C)"
    )
    parser.add_argument(
        "--hold-minutes", 
        type=float, 
        default=20.0, 
        help="保持时间 (默认: 20分钟)"
    )
    parser.add_argument(
        "--cooldown-target", 
        type=float, 
        default=3.0, 
        help="降温目标温度 (默认: 3°C)"
    )
    parser.add_argument(
        "--log-file", 
        default=None, 
        help="日志文件路径"
    )
    
    args = parser.parse_args()
    
    experiment = HeaterPumpExperiment(
        heater_port=args.heater_port,
        pump_port=args.pump_port,
        log_file=args.log_file
    )
    
    experiment.run_experiment(
        heat_temp=args.heat_temp,
        hold_minutes=args.hold_minutes,
        cooldown_target=args.cooldown_target
    )


if __name__ == "__main__":
    main()
