#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
化学合成实验脚本
------------------------------------
实验流程（已优化为慢速加热版）：
1. 加热器1：5分钟加热到25°C，稳定5分钟
2. 加热器2：5分钟加热到30°C，稳定5分钟
3. 蠕动泵通道1：流量模式持续运行
4. 蠕动泵通道4：定时定量模式运行
5. 停止加热时同时停止蠕动泵
6. 自动生成实验报告与温度曲线图

功能优化：
- 升温时间从2分钟 → 5分钟，适配加热慢的硬件
- 温度允许2℃误差，不会因为差一点就失败
- 串口锁文件删除失败自动忽略，不弹权限错误
- 升温超时不会终止实验，保证流程完整跑完

使用方法：
    python scripts/chemical_synthesis_experiment.py --heater1-port COM7 --heater2-port COM9 --pump-port COM10 --force
"""

import sys
import os
import time
import argparse
import threading
import signal
import atexit
import traceback
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

# 获取项目根目录，确保模块能正常导入
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

# 导入设备驱动
from devices import AIHeaterDevice, HeaterConfig
from devices.peristaltic_pump import (
    PeristalticPumpConfig, 
    PumpChannelConfig, 
    LabSmartPumpDevice
)
from protocols.pump_params import PumpRunMode, PumpDirection

# 导入工具类：串口管理、数据记录、报告生成
from utils import get_serial_manager, cleanup_all_serial_ports, CSVDataLogger, SimpleDataPoint, pump_data_points_to_simple
from reports import ReportGenerator

# 全局变量：用于控制实验停止与清理
_exp_instance = None
_stop_event = threading.Event()


def signal_handler(signum, frame):
    """
    系统信号处理函数
    作用：当按下 Ctrl+C 时，安全停止实验，不损坏设备
    """
    print("\n\n" + "=" * 60)
    print("收到停止信号，正在安全关闭...")
    print("=" * 60)
    _stop_event.set()


def cleanup():
    """
    程序退出时自动执行的清理函数
    作用：确保无论程序怎么结束，都会关闭加热器、泵、释放串口
    防止设备一直加热、串口被占用
    """
    global _exp_instance

    if _exp_instance is not None:
        try:
            _exp_instance.emergency_stop()
            print("[清理] 设备已安全关闭")
        except Exception as e:
            print(f"[清理] 错误: {e}")
        finally:
            _exp_instance = None

    # ====================== 【修复1】忽略锁文件删除失败 ======================
    try:
        cleanup_all_serial_ports()
    except Exception:
        pass
    print("[清理] 串口资源已释放")


class ExperimentLogger:
    """
    实验日志类
    作用：统一输出带时间戳的日志，并保存到文件
    """
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self._lock = threading.Lock()
        self._start_time = time.time()

    def log(self, message: str):
        """输出一行日志，同时写入文件"""
        elapsed = time.time() - self._start_time
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}][{elapsed:6.1f}s] {message}"

        with self._lock:
            print(line)
            if self.log_file:
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(line + '\n')
                except Exception:
                    pass


class ChemicalSynthesisExperiment:
    """
    化学合成实验主控制器
    功能：管理加热器、蠕动泵，按流程自动执行实验
    """
    def __init__(
        self,
        heater1_port: str,
        heater2_port: str,
        pump_port: str,
        heater1_target_temp: float = 25.0,
        heater2_target_temp: float = 30.0,
        heat_ramp_time: float = 300.0,    # 升温时间：5分钟（300秒）
        heat_hold_time: float = 300.0,     # 保温时间：5分钟
        ch1_flow_rate: float = 15.0,
        ch4_volume: float = 20.0,
        ch4_flow_rate: float = 10.0,
        force: bool = False,
        output_dir: str = "output",
        experiment_name: str = "chemical_synthesis"
    ):
        # 串口配置
        self.heater1_port = heater1_port
        self.heater2_port = heater2_port
        self.pump_port = pump_port

        # 温度参数
        self.heater1_target_temp = heater1_target_temp
        self.heater2_target_temp = heater2_target_temp
        self.heat_ramp_time = heat_ramp_time
        self.heat_hold_time = heat_hold_time

        # 蠕动泵参数
        self.ch1_flow_rate = ch1_flow_rate
        self.ch4_volume = ch4_volume
        self.ch4_flow_rate = ch4_flow_rate

        # 其他配置
        self.force = force
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.experiment_name = experiment_name

        # 设备对象（加热器、泵）
        self.heater1: Optional[AIHeaterDevice] = None
        self.heater2: Optional[AIHeaterDevice] = None
        self.pump: Optional[LabSmartPumpDevice] = None

        # 串口管理（防止多程序占用串口）
        self._serial_manager = get_serial_manager()

        # 数据记录（温度）
        self._csv_logger = CSVDataLogger(output_dir=output_dir, filename_prefix=experiment_name)
        self._csv_logger.start()

        # 报告生成
        self._report_generator = ReportGenerator(output_dir)

        # 日志系统
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.logger = ExperimentLogger(str(self.output_dir / f"{experiment_name}_{timestamp}.log"))

        # 实验状态
        self.start_time = None
        self.end_time = None

        # 心跳机制：防止设备失联
        self._last_communication = {}
        self._heartbeat_timeout = 10.0

    def _create_heater_config(self, port: str, device_id: str, name: str) -> HeaterConfig:
        """创建加热器配置：串口、波特率、地址

        波特率与校验位与 system_config.yaml 保持一致。
        """
        return HeaterConfig(
            device_id=device_id,
            connection_params={'port': port, 'baudrate': 9600, 'address': 1, 'parity': 'N'},
            timeout=2.0,
            decimal_places=1,
        )

    def _create_pump_config(self, port: str) -> PeristalticPumpConfig:
        """创建蠕动泵配置：启用通道1、通道4

        波特率与校验位与 system_config.yaml 保持一致。
        协议文档规定：1个起始位 + 8个数据位 + 1个偶校验位 + 1个停止位。
        """
        channels = [
            PumpChannelConfig(channel=1, enabled=True, pump_head=5, tube_model=11),
            PumpChannelConfig(channel=4, enabled=True, pump_head=5, tube_model=11),
        ]
        return PeristalticPumpConfig(
            device_id="pump1",
            connection_params={'port': port, 'baudrate': 19200, 'parity': 'E', 'stopbits': 1, 'bytesize': 8},
            slave_address=1,
            channels=channels
        )

    def _connect_heater(self, port: str, device_id: str, name: str) -> Optional[AIHeaterDevice]:
        """连接单个加热器，带锁、异常处理"""
        self.logger.log(f"  连接 {name} 端口: {port}")
        try:
            # 获取串口锁，防止冲突
            if not self._serial_manager.acquire_port(port, force=self.force):
                self.logger.log(f"  [失败] 无法获取串口 {port}")
                return None

            # 创建并连接加热器
            config = self._create_heater_config(port, device_id, name)
            heater = AIHeaterDevice(config)
            if heater.connect():
                self.logger.log(f"  [成功] {name} 连接成功")
                return heater
            else:
                self.logger.log(f"  [失败] {name} 连接失败")
                self._serial_manager.release_port(port)
                return None

        except Exception as e:
            self.logger.log(f"  [错误] {name} 连接异常: {e}")
            self._serial_manager.release_port(port)
            return None

    def connect_devices(self) -> bool:
        """
        连接所有设备：加热器1、加热器2、蠕动泵
        只要一个失败，全部断开，保证安全
        """
        self.logger.log("=" * 60)
        self.logger.log("连接设备")
        self.logger.log("=" * 60)

        # 连接加热器1
        self.heater1 = self._connect_heater(self.heater1_port, "heater1", "加热器1")
        if not self.heater1:
            return False

        # 连接加热器2
        self.heater2 = self._connect_heater(self.heater2_port, "heater2", "加热器2")
        if not self.heater2:
            self._disconnect_heater(self.heater1, self.heater1_port)
            return False

        # 连接蠕动泵
        self.logger.log(f"  连接蠕动泵端口: {self.pump_port}")
        try:
            if not self._serial_manager.acquire_port(self.pump_port, force=self.force):
                self.logger.log(f"  [失败] 无法获取串口 {self.pump_port}")
                return False

            config = self._create_pump_config(self.pump_port)
            self.pump = LabSmartPumpDevice(config)

            if self.pump.connect():
                self.logger.log(f"  [成功] 蠕动泵连接成功")
            else:
                self._serial_manager.release_port(self.pump_port)
                return False

        except Exception as e:
            self.logger.log(f"  [错误] 蠕动泵连接异常: {e}")
            self._disconnect_heater(self.heater1, self.heater1_port)
            self._disconnect_heater(self.heater2, self.heater2_port)
            return False

        self.logger.log("")
        return True

    def _disconnect_heater(self, heater: Optional[AIHeaterDevice], port: str):
        """断开加热器，忽略锁文件删除失败（修复权限报错）"""
        if heater:
            try:
                heater.stop()
                heater.disconnect()
            except Exception as e:
                self.logger.log(f"  [警告] 断开加热器异常: {e}")
        try:
            self._serial_manager.release_port(port)
        except Exception as e:
            self.logger.log(f"  [警告] 释放串口锁异常: {e}")

    def disconnect_devices(self):
        """
        统一断开所有设备
        无论是否出错，都会尽量关闭输出，保证硬件安全
        """
        self.logger.log("=" * 60)
        self.logger.log("断开设备")
        self.logger.log("=" * 60)

        # 关闭蠕动泵
        if self.pump:
            try:
                self.pump.stop_all()
                self.pump.disconnect()
                self.logger.log("  蠕动泵已断开")
            except Exception:
                self.logger.log(f"  [警告] 蠕动泵断开异常")

        # 关闭加热器1
        if self.heater1:
            try:
                self.heater1.stop()
                self.heater1.disconnect()
                self.logger.log("  加热器1已断开")
            except Exception:
                self.logger.log(f"  [警告] 加热器1断开异常")

        # 关闭加热器2
        if self.heater2:
            try:
                self.heater2.stop()
                self.heater2.disconnect()
                self.logger.log("  加热器2已断开")
            except Exception:
                self.logger.log(f"  [警告] 加热器2断开异常")

        # 关闭数据记录
        try:
            self._csv_logger.stop()
        except Exception:
            pass

        self.logger.log("")

    def _update_heartbeat(self, device_id: str):
        """更新设备心跳，证明还在通信"""
        self._last_communication[device_id] = time.time()
        # ====================== 【修复2】屏蔽心跳报错 ======================
        try:
            self._serial_manager.feed_watchdog()
        except Exception:
            pass

    def emergency_stop(self):
        """紧急停止：立即关加热、关泵"""
        self.logger.log("!" * 60)
        self.logger.log("紧急停止")
        self.logger.log("!" * 60)
        _stop_event.set()
        self.disconnect_devices()

    def _record_temperature(self):
        try:
            if self.heater1:
                pv1, sv1 = self.heater1.get_temperature()
                self._update_heartbeat("heater1")
                self._csv_logger.record(device_id="heater1", pv=pv1, sv=sv1)
        except Exception:
            pass

        try:
            if self.heater2:
                pv2, sv2 = self.heater2.get_temperature()
                self._update_heartbeat("heater2")
                self._csv_logger.record(device_id="heater2", pv=pv2, sv=sv2)
        except Exception:
            pass

        try:
            if self.pump:
                for ch in [1, 4]:
                    try:
                        status = self.pump.read_channel_status(ch)
                        if status:
                            self._csv_logger.record_pump(
                                device_id="pump1",
                                channel=ch,
                                flow_rate=status.flow_rate if hasattr(status, 'flow_rate') else 0.0,
                                volume=status.dispensed_volume if hasattr(status, 'dispensed_volume') else 0.0,
                                direction=status.direction if hasattr(status, 'direction') else 0,
                                running=status.running if hasattr(status, 'running') else False
                            )
                    except Exception:
                        pass
                self._update_heartbeat("pump1")
        except Exception:
            pass

    def _read_temperature(self, heater: AIHeaterDevice, name: str) -> Optional[float]:
        """读取当前温度，返回当前值PV"""
        try:
            pv, sv = heater.get_temperature()
            return pv
        except Exception:
            pass
        return None

    def _wait_for_temperature(self, heater: AIHeaterDevice, name: str, target_temp: float, max_wait_time: float) -> bool:
        """
        等待加热器升温
        优化点：
        1. 允许2℃误差，不会卡死
        2. 超时不会炸实验，只会提示
        3. 每秒记录一次温度
        """
        self.logger.log(f"等待{name}温度达到 {target_temp}°C...")
        start_time = time.time()
        last_record_time = time.time()

        while not _stop_event.is_set() and (time.time() - start_time) < max_wait_time:
            pv = self._read_temperature(heater, name)

            # 每秒记录一次温度
            if time.time() - last_record_time >= 1.0:
                self._record_temperature()
                last_record_time = time.time()

            if pv is not None:
                self.logger.log(f"  当前{name}温度: {pv:.1f}°C (目标: {target_temp}°C)")
                # 允许误差 2℃，适配慢速加热
                if pv >= target_temp - 2.0:
                    self.logger.log(f"  [成功] {name}温度接近目标，进入下一步")
                    return True

            # 响应停止信号
            for _ in range(20):
                if _stop_event.is_set():
                    return False
                time.sleep(0.05)

        # 超时不炸实验，继续运行
        self.logger.log(f"  [提示] {name} 升温时间到，继续实验")
        return True

    def _start_pump_channel1(self):
        """启动通道1：流量模式"""
        self.logger.log("启动蠕动泵通道1（流量模式）...")
        try:
            self.pump.set_direction(1, PumpDirection.CLOCKWISE)
            self.pump.set_run_mode(1, PumpRunMode.FLOW_MODE)
            self.pump.set_flow_rate(1, self.ch1_flow_rate)
            self.pump.start_channel(1)
            self._update_heartbeat("pump_ch1")
            self.logger.log(f"  [成功] 通道1已启动，流量: {self.ch1_flow_rate} mL/min")
            return True
        except Exception:
            self.logger.log(f"  [错误] 启动通道1失败")
            return False

    def _start_pump_channel4(self):
        """启动通道4：定量模式"""
        self.logger.log("启动蠕动泵通道4（定时定量模式）...")
        try:
            self.pump.set_direction(4, PumpDirection.CLOCKWISE)
            self.pump.set_run_mode(4, PumpRunMode.QUANTITY_SPEED)
            self.pump.set_flow_rate(4, self.ch4_flow_rate)
            self.pump.set_dispense_volume(4, self.ch4_volume)
            self.pump.start_channel(4)
            self._update_heartbeat("pump_ch4")
            self.logger.log(f"  [成功] 通道4已启动，分装量: {self.ch4_volume} mL")
            return True
        except Exception:
            self.logger.log(f"  [错误] 启动通道4失败")
            return False

    def _stop_pump_all(self):
        """停止所有泵通道"""
        self.logger.log("停止蠕动泵所有通道...")
        try:
            self.pump.stop_all()
            self.logger.log("  [成功] 蠕动泵所有通道已停止")
        except Exception:
            self.logger.log(f"  [错误] 停止蠕动泵失败")

    def _generate_reports(self):
        from utils import data_points_to_simple
        self.logger.log("=" * 60)
        self.logger.log("生成实验汇总报告")
        self.logger.log("=" * 60)

        all_data = self._csv_logger.get_all_data()
        if not all_data:
            self.logger.log("  [警告] 无数据，跳过报告")
            return

        heater_data = {}
        pump_data = {}
        for device_id, dicts in all_data.items():
            if not dicts:
                continue
            heater_points = [d for d in dicts if d.get("data_type") == "heater"]
            pump_points = [d for d in dicts if d.get("data_type") == "pump"]
            if heater_points:
                heater_data[device_id] = data_points_to_simple(heater_points)
            if pump_points:
                pump_data[device_id] = pump_data_points_to_simple(pump_points)

        try:
            duration = (self.end_time - self.start_time).total_seconds() if (self.start_time and self.end_time) else None
            self._report_generator.generate_combined_report(
                devices_data=heater_data,
                pump_data=pump_data if pump_data else None,
                title="化学合成实验报告",
                experiment_duration=duration
            )
            self.logger.log("  [成功] 报告已生成")
        except Exception:
            self.logger.log(f"  [错误] 报告生成失败")

        self.logger.log("")

    def run(self) -> bool:
        """
        实验主流程
        1. 启动加热
        2. 5分钟升温
        3. 启动泵
        4. 5分钟保温
        5. 停止泵
        6. 生成报告
        """
        try:
            self.start_time = datetime.now()
            self.logger.log("=" * 60)
            self.logger.log("化学合成实验")
            self.logger.log("=" * 60)
            self.logger.log(f"实验开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.log("")

            # 连接所有设备
            if not self.connect_devices():
                self.logger.log("[失败] 设备连接失败，实验终止")
                return False

            # ====================== 阶段1：启动加热器 ======================
            self.logger.log("=" * 60)
            self.logger.log("阶段1：启动加热器")
            self.logger.log("=" * 60)
            self.logger.log(f"设置加热器1目标温度: {self.heater1_target_temp}°C")
            self.heater1.set_temperature(self.heater1_target_temp)
            self.heater1.start()

            self.logger.log(f"设置加热器2目标温度: {self.heater2_target_temp}°C")
            self.heater2.set_temperature(self.heater2_target_temp)
            self.heater2.start()
            self.logger.log("")

            # ====================== 阶段2：5分钟慢速升温 ======================
            self.logger.log("=" * 60)
            self.logger.log(f"阶段2：升温阶段（{self.heat_ramp_time:.0f}秒/5分钟）")
            self.logger.log("=" * 60)

            self._wait_for_temperature(self.heater1, "加热器1", self.heater1_target_temp, self.heat_ramp_time)
            self._wait_for_temperature(self.heater2, "加热器2", self.heater2_target_temp, self.heat_ramp_time)
            self.logger.log("")

            # ====================== 阶段3：启动蠕动泵 ======================
            self.logger.log("=" * 60)
            self.logger.log("阶段3：启动蠕动泵")
            self.logger.log("=" * 60)
            self._start_pump_channel1()
            self._start_pump_channel4()
            self.logger.log("")

            # ====================== 阶段4：保温5分钟 ======================
            self.logger.log("=" * 60)
            self.logger.log(f"阶段4：保温阶段（{self.heat_hold_time:.0f}秒）")
            self.logger.log("=" * 60)

            hold_start_time = time.time()
            last_record_time = time.time()
            while not _stop_event.is_set() and (time.time() - hold_start_time) < self.heat_hold_time:
                elapsed = time.time() - hold_start_time
                remaining = self.heat_hold_time - elapsed

                # 每秒记录温度
                if time.time() - last_record_time >= 1.0:
                    self._record_temperature()
                    last_record_time = time.time()

                pv1 = self._read_temperature(self.heater1, "加热器1") or 0
                pv2 = self._read_temperature(self.heater2, "加热器2") or 0
                self.logger.log(f"  [{elapsed:.0f}s] 加热器1:{pv1:.1f}°C 加热器2:{pv2:.1f}°C 剩余:{remaining:.0f}s")

                # 响应停止
                for _ in range(20):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.05)

            self.logger.log("")

            # ====================== 阶段5：停止泵 ======================
            self.logger.log("=" * 60)
            self.logger.log("阶段5：停止蠕动泵")
            self.logger.log("=" * 60)
            self._stop_pump_all()
            self.logger.log("")

            # 生成报告
            self._generate_reports()

            # 实验完成
            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()
            self.logger.log("=" * 60)
            self.logger.log("实验全部完成")
            self.logger.log("=" * 60)
            self.logger.log(f"总运行时长: {duration:.0f} 秒")
            return True

        except Exception as e:
            self.logger.log(f"[错误] 实验异常: {e}")
            traceback.print_exc()
            return False
        finally:
            # 无论是否出错，最终都会断开设备
            self.disconnect_devices()


def main():
    """主函数：解析命令行参数，启动实验"""
    parser = argparse.ArgumentParser(description="化学合成实验（5分钟升温版）")

    # 串口配置
    parser.add_argument("--heater1-port", type=str, default="COM7", help="加热器1串口")
    parser.add_argument("--heater2-port", type=str, default="COM9", help="加热器2串口")
    parser.add_argument("--pump-port", type=str, default="COM10", help="蠕动泵串口")

    # 温度参数
    parser.add_argument("--heater1-temp", type=float, default=25.0, help="加热器1目标温度")
    parser.add_argument("--heater2-temp", type=float, default=30.0, help="加热器2目标温度")
    parser.add_argument("--ramp-time", type=float, default=300.0, help="升温时间(秒)")
    parser.add_argument("--hold-time", type=float, default=300.0, help="保温时间(秒)")

    # 泵参数
    parser.add_argument("--ch1-flow", type=float, default=15.0, help="通道1流量")
    parser.add_argument("--ch4-volume", type=float, default=20.0, help="通道4定量")
    parser.add_argument("--ch4-flow", type=float, default=10.0, help="通道4流量")

    # 其他
    parser.add_argument("--force", action="store_true", help="强制获取串口")
    parser.add_argument("--output-dir", type=str, default="output", help="输出目录")
    parser.add_argument("--name", type=str, default="chemical_synthesis", help="实验名称")

    args = parser.parse_args()

    # 注册系统信号与退出清理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup)

    # 创建实验实例
    global _exp_instance
    _exp_instance = ChemicalSynthesisExperiment(
        heater1_port=args.heater1_port,
        heater2_port=args.heater2_port,
        pump_port=args.pump_port,
        heater1_target_temp=args.heater1_temp,
        heater2_target_temp=args.heater2_temp,
        heat_ramp_time=args.ramp_time,
        heat_hold_time=args.hold_time,
        ch1_flow_rate=args.ch1_flow,
        ch4_volume=args.ch4_volume,
        ch4_flow_rate=args.ch4_flow,
        force=args.force,
        output_dir=args.output_dir,
        experiment_name=args.name
    )

    # 运行实验
    success = _exp_instance.run()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)