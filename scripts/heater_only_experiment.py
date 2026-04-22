#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加热器实验脚本（仅加热器）

实验流程：
1. 加热器1：2分钟加热到25°C，稳定5分钟
2. 加热器2：2分钟加热到30°C，稳定5分钟
3. 生成报告和曲线图

使用方法：
    python scripts/heater_only_experiment.py --heater1-port COM7 --heater2-port COM9 --force
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
from typing import Optional, List
from pathlib import Path

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src'))

from devices import AIHeaterDevice, HeaterConfig
from utils import get_serial_manager, cleanup_all_serial_ports, CSVDataLogger, SimpleDataPoint
from reports import ReportGenerator, ChartGenerator

# 全局变量
_exp_instance = None
_stop_event = threading.Event()


def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n" + "=" * 60)
    print("收到停止信号，正在安全关闭...")
    print("=" * 60)
    _stop_event.set()


def cleanup():
    """清理函数"""
    global _exp_instance

    if _exp_instance is not None:
        try:
            _exp_instance.emergency_stop()
            print("[清理] 设备已安全关闭")
        except Exception as e:
            print(f"[清理] 错误: {e}")
        finally:
            _exp_instance = None

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
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(line + '\n')
                except:
                    pass


class HeaterOnlyExperiment:
    """加热器实验控制器"""

    def __init__(
        self,
        heater1_port: str,
        heater2_port: str,
        heater1_target_temp: float = 25.0,
        heater2_target_temp: float = 30.0,
        heat_ramp_time: float = 120.0,
        heat_hold_time: float = 300.0,
        force: bool = False,
        output_dir: str = "output",
        experiment_name: str = "heater_only"
    ):
        self.heater1_port = heater1_port
        self.heater2_port = heater2_port
        self.heater1_target_temp = heater1_target_temp
        self.heater2_target_temp = heater2_target_temp
        self.heat_ramp_time = heat_ramp_time
        self.heat_hold_time = heat_hold_time
        self.force = force

        # 设备对象
        self.heater1: Optional[AIHeaterDevice] = None
        self.heater2: Optional[AIHeaterDevice] = None

        # 串口管理器
        self._serial_manager = get_serial_manager()

        # CSV记录器
        self._csv_logger = CSVDataLogger(
            output_dir=output_dir,
            filename_prefix=experiment_name
        )
        self._csv_logger.start()
        
        self._report_generator = ReportGenerator(output_dir)

        # 输出目录
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.experiment_name = experiment_name

        # 日志
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.logger = ExperimentLogger(
            str(self.output_dir / f"{experiment_name}_{timestamp}.log")
        )

        # 实验状态
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        
        # 弱心跳机制 - 记录最后通信时间
        self._last_communication: dict[str, float] = {}
        self._heartbeat_timeout = 10.0  # 10秒无通信算超时

    def _create_heater_config(self, port: str, device_id: str) -> HeaterConfig:
        """创建加热器配置"""
        return HeaterConfig(
            device_id=device_id,
            connection_params={
                'port': port,
                'baudrate': 9600,
                'address': 1,
            },
            timeout=2.0,
            decimal_places=1,
        )

    def _connect_heater(self, port: str, device_id: str, name: str) -> Optional[AIHeaterDevice]:
        """连接单个加热器"""
        self.logger.log(f"  连接{name}串口: {port}")

        try:
            # 获取串口锁
            if not self._serial_manager.acquire_port(port, force=self.force):
                self.logger.log(f"  [失败] 无法获取串口 {port}")
                return None

            # 创建加热器对象
            config = self._create_heater_config(port, device_id)
            heater = AIHeaterDevice(config)

            # 连接设备
            if heater.connect():
                self.logger.log(f"  [成功] {name}连接成功")
                return heater
            else:
                self.logger.log(f"  [失败] {name}连接失败")
                self._serial_manager.release_port(port)
                return None

        except Exception as e:
            self.logger.log(f"  [错误] {name}连接异常: {e}")
            traceback.print_exc()
            self._serial_manager.release_port(port)
            return None

    def connect_devices(self) -> bool:
        """连接所有设备"""
        self.logger.log("=" * 60)
        self.logger.log("连接设备")
        self.logger.log("=" * 60)

        # 连接加热器1
        self.heater1 = self._connect_heater(
            self.heater1_port,
            "heater1",
            "加热器1"
        )
        if not self.heater1:
            return False

        # 连接加热器2
        self.heater2 = self._connect_heater(
            self.heater2_port,
            "heater2",
            "加热器2"
        )
        if not self.heater2:
            self._disconnect_heater(self.heater1, self.heater1_port)
            return False

        self.logger.log("")
        return True

    def _disconnect_heater(self, heater: Optional[AIHeaterDevice], port: str):
        """断开单个加热器"""
        if heater:
            try:
                heater.stop()
                heater.disconnect()
            except:
                pass
        try:
            self._serial_manager.release_port(port)
        except:
            pass

    def disconnect_devices(self):
        """断开所有设备"""
        self.logger.log("=" * 60)
        self.logger.log("断开设备")
        self.logger.log("=" * 60)

        # 停止加热器1
        if self.heater1:
            try:
                self.heater1.stop()
                self.heater1.disconnect()
                self.logger.log("  加热器1已断开")
            except Exception as e:
                self.logger.log(f"  [警告] 加热器1断开异常: {e}")
            finally:
                try:
                    self._serial_manager.release_port(self.heater1_port)
                except:
                    pass

        # 停止加热器2
        if self.heater2:
            try:
                self.heater2.stop()
                self.heater2.disconnect()
                self.logger.log("  加热器2已断开")
            except Exception as e:
                self.logger.log(f"  [警告] 加热器2断开异常: {e}")
            finally:
                try:
                    self._serial_manager.release_port(self.heater2_port)
                except:
                    pass
        
        # 停止CSV记录器
        try:
            self._csv_logger.stop()
        except:
            pass

        self.logger.log("")

    def _update_heartbeat(self, device_id: str):
        """更新最后通信时间（弱心跳）+ 喂看门狗"""
        self._last_communication[device_id] = time.time()
        self._serial_manager.feed_watchdog()
    
    def _check_heartbeat(self, device_id: str) -> bool:
        """检查心跳是否超时"""
        last = self._last_communication.get(device_id)
        if last is None:
            return True  # 首次通信
        elapsed = time.time() - last
        if elapsed > self._heartbeat_timeout:
            self.logger.log(f"  [警告] {device_id} 心跳超时（{elapsed:.1f}秒无通信）")
            return False
        return True

    def emergency_stop(self):
        """紧急停止"""
        self.logger.log("!" * 60)
        self.logger.log("紧急停止")
        self.logger.log("!" * 60)
        _stop_event.set()
        self.disconnect_devices()

    def _record_temperature(self):
        """记录两个加热器的温度"""
        try:
            if self.heater1:
                pv1, sv1 = self.heater1.get_temperature()
                # 更新心跳（成功读取后）
                self._update_heartbeat("heater1")
                # 记录到CSV
                self._csv_logger.record(
                    device_id="heater1",
                    pv=pv1,
                    sv=sv1
                )
        except Exception as e:
            self.logger.log(f"  [警告] 读取加热器1温度失败: {e}")
        
        try:
            if self.heater2:
                pv2, sv2 = self.heater2.get_temperature()
                # 更新心跳（成功读取后）
                self._update_heartbeat("heater2")
                # 记录到CSV
                self._csv_logger.record(
                    device_id="heater2",
                    pv=pv2,
                    sv=sv2
                )
        except Exception as e:
            self.logger.log(f"  [警告] 读取加热器2温度失败: {e}")

    def _read_temperature(self, heater: AIHeaterDevice, name: str) -> Optional[float]:
        """读取温度"""
        try:
            pv, sv = heater.get_temperature()
            if pv is not None:
                return pv
        except Exception as e:
            self.logger.log(f"  [警告] 读取{name}温度失败: {e}")
        return None

    def _wait_for_temperature(self, heater: AIHeaterDevice, name: str,
                         target_temp: float, max_wait_time: float) -> bool:
        """等待温度达到目标"""
        self.logger.log(f"等待{name}温度达到 {target_temp}°C...")

        start_time = time.time()
        last_record_time = time.time()
        while not _stop_event.is_set() and (time.time() - start_time) < max_wait_time:
            pv = self._read_temperature(heater, name)

            # 定期记录温度（每秒一次）
            if time.time() - last_record_time >= 1.0:
                self._record_temperature()
                last_record_time = time.time()

            if pv is not None:
                self.logger.log(f"  当前{name}温度: {pv:.1f}°C (目标: {target_temp}°C)")
                if pv >= target_temp - 0.5:
                    self.logger.log(f"  [成功] {name}温度达到目标值")
                    return True

            # 检查停止信号
            for _ in range(20):
                if _stop_event.is_set():
                    return False
                time.sleep(0.05)

        self.logger.log(f"  [超时] 等待{name}温度超时")
        return False

    def _generate_reports(self):
        """生成实验报告"""
        from utils import data_points_to_simple
        
        self.logger.log("=" * 60)
        self.logger.log("生成实验报告")
        self.logger.log("=" * 60)

        all_data = self._csv_logger.get_all_data()
        if not all_data:
            self.logger.log("  [警告] 没有记录到温度数据，无法生成报告")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 生成加热器1报告
        try:
            heater1_dicts = all_data.get("heater1", [])
            if heater1_dicts:
                heater1_data = data_points_to_simple(heater1_dicts)
                report1_path = self._report_generator.generate(
                    device_id="heater1",
                    data_points=heater1_data,
                    title=f"加热器实验 - 加热器1 - {timestamp}",
                    include_charts=True,
                    include_data_table=True
                )
                self.logger.log(f"  [成功] 加热器1报告已生成: {report1_path}")

                # 单独保存温度曲线图
                chart1_path = self.output_dir / f"{self.experiment_name}_heater1_temp_{timestamp}.png"
                ChartGenerator.generate_temperature_chart(
                    heater1_data,
                    title="加热器1 - 温度曲线",
                    output_path=str(chart1_path)
                )
                self.logger.log(f"  [成功] 加热器1温度曲线图已保存: {chart1_path}")
        except Exception as e:
            self.logger.log(f"  [错误] 生成加热器1报告失败: {e}")
            traceback.print_exc()

        # 生成加热器2报告
        try:
            heater2_dicts = all_data.get("heater2", [])
            if heater2_dicts:
                heater2_data = data_points_to_simple(heater2_dicts)
                report2_path = self._report_generator.generate(
                    device_id="heater2",
                    data_points=heater2_data,
                    title=f"加热器实验 - 加热器2 - {timestamp}",
                    include_charts=True,
                    include_data_table=True
                )
                self.logger.log(f"  [成功] 加热器2报告已生成: {report2_path}")

                chart2_path = self.output_dir / f"{self.experiment_name}_heater2_temp_{timestamp}.png"
                ChartGenerator.generate_temperature_chart(
                    heater2_data,
                    title="加热器2 - 温度曲线",
                    output_path=str(chart2_path)
                )
                self.logger.log(f"  [成功] 加热器2温度曲线图已保存: {chart2_path}")
        except Exception as e:
            self.logger.log(f"  [错误] 生成加热器2报告失败: {e}")
            traceback.print_exc()

        self.logger.log("")

    def run(self) -> bool:
        """运行实验"""
        try:
            self.start_time = datetime.now()

            self.logger.log("=" * 60)
            self.logger.log("加热器实验")
            self.logger.log("=" * 60)
            self.logger.log(f"实验开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.log("")

            # 连接设备
            if not self.connect_devices():
                self.logger.log("[失败] 设备连接失败，实验终止")
                return False

            self.logger.log("=" * 60)
            self.logger.log("阶段1：启动加热器")
            self.logger.log("=" * 60)

            # 设置加热器1目标温度并启动
            self.logger.log(f"设置加热器1目标温度: {self.heater1_target_temp}°C")
            self.heater1.set_temperature(self.heater1_target_temp)
            self.heater1.start()

            # 设置加热器2目标温度并启动
            self.logger.log(f"设置加热器2目标温度: {self.heater2_target_temp}°C")
            self.heater2.set_temperature(self.heater2_target_temp)
            self.heater2.start()

            self.logger.log("")

            # 等待温度升高
            self.logger.log("=" * 60)
            self.logger.log(f"阶段2：升温阶段（{self.heat_ramp_time}秒）")
            self.logger.log("=" * 60)

            # 等待加热器1温度
            if not self._wait_for_temperature(
                self.heater1,
                "加热器1",
                self.heater1_target_temp,
                self.heat_ramp_time
            ):
                self.logger.log("[警告] 加热器1升温超时，继续实验")

            # 等待加热器2温度
            if not self._wait_for_temperature(
                self.heater2,
                "加热器2",
                self.heater2_target_temp,
                self.heat_ramp_time
            ):
                self.logger.log("[警告] 加热器2升温超时，继续实验")

            self.logger.log("")

            # 保温阶段
            self.logger.log("=" * 60)
            self.logger.log(f"阶段3：保温阶段（{self.heat_hold_time}秒）")
            self.logger.log("=" * 60)

            # 同时保持两个加热器温度
            hold_start_time = time.time()
            last_record_time = time.time()
            while not _stop_event.is_set() and (time.time() - hold_start_time) < self.heat_hold_time:
                elapsed = time.time() - hold_start_time
                remaining = self.heat_hold_time - elapsed

                # 定期记录温度（每秒一次）
                if time.time() - last_record_time >= 1.0:
                    self._record_temperature()
                    last_record_time = time.time()

                # 读取加热器1温度
                pv1 = self._read_temperature(self.heater1, "加热器1")

                # 读取加热器2温度
                pv2 = self._read_temperature(self.heater2, "加热器2")

                self.logger.log(f"  [{elapsed:.0f}s/{self.heat_hold_time:.0f}s] "
                            f"加热器1: {pv1:.1f}°C, 加热器2: {pv2:.1f}°C "
                            f"(剩余: {remaining:.0f}s)")

                # 检查停止信号
                for _ in range(20):
                    if _stop_event.is_set():
                        break
                    time.sleep(0.05)

            self.logger.log("")

            # 生成报告
            self._generate_reports()

            # 实验完成
            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()

            self.logger.log("=" * 60)
            self.logger.log("实验完成")
            self.logger.log("=" * 60)
            self.logger.log(f"实验结束时间: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.log(f"实验总时长: {duration:.0f} 秒")
            self.logger.log("=" * 60)

            return True

        except Exception as e:
            self.logger.log(f"[错误] 实验异常: {e}")
            traceback.print_exc()
            return False
        finally:
            self.disconnect_devices()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="加热器实验脚本")

    # 串口参数
    parser.add_argument("--heater1-port", type=str, default="COM7", help="加热器1串口")
    parser.add_argument("--heater2-port", type=str, default="COM9", help="加热器2串口")

    # 温度参数
    parser.add_argument("--heater1-temp", type=float, default=25.0, help="加热器1目标温度 (°C)")
    parser.add_argument("--heater2-temp", type=float, default=30.0, help="加热器2目标温度 (°C)")
    parser.add_argument("--ramp-time", type=float, default=120.0, help="升温时间 (秒)")
    parser.add_argument("--hold-time", type=float, default=300.0, help="保温时间 (秒)")

    # 其他参数
    parser.add_argument("--force", action="store_true", help="强制获取串口")
    parser.add_argument("--output-dir", type=str, default="output", help="输出目录")
    parser.add_argument("--name", type=str, default="heater_only", help="实验名称")

    args = parser.parse_args()

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup)

    # 创建实验实例
    global _exp_instance
    _exp_instance = HeaterOnlyExperiment(
        heater1_port=args.heater1_port,
        heater2_port=args.heater2_port,
        heater1_target_temp=args.heater1_temp,
        heater2_target_temp=args.heater2_temp,
        heat_ramp_time=args.ramp_time,
        heat_hold_time=args.hold_time,
        force=args.force,
        output_dir=args.output_dir,
        experiment_name=args.name
    )

    # 运行实验
    success = _exp_instance.run()

    # 返回状态码
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
