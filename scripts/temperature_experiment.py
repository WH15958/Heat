"""
完整温度控制实验脚本

实验流程：
1. 升温：20°C → 30°C，用时10分钟
2. 维持：30°C，维持10分钟
3. 降温：30°C → 室温，自然降温
4. 生成报告和曲线图
"""

import sys
import os
import time
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.base_device import DeviceInfo, DeviceType
from reports.report_generator import ReportGenerator, ChartGenerator


@dataclass
class DataPoint:
    """数据点"""
    timestamp: datetime
    pv: float
    sv: float
    mv: int
    alarms: List[str]


def log(msg: str):
    """带刷新的打印"""
    print(msg, flush=True)


def create_heater(port: str, address: int, name: str) -> AIHeaterDevice:
    """创建加热器设备"""
    config = HeaterConfig(
        device_id=name,
        connection_params={
            'port': port,
            'baudrate': 9600,
            'address': address,
        },
        timeout=2.0,
        decimal_places=1,
    )
    
    info = DeviceInfo(
        name=name,
        device_type=DeviceType.HEATER,
        manufacturer="Yudian",
    )
    
    return AIHeaterDevice(config, info)


class TemperatureExperiment:
    """温度实验控制器"""
    
    def __init__(self, heater: AIHeaterDevice, report_dir: str = "reports"):
        self.heater = heater
        self.report_dir = report_dir
        self.data_points: List[DataPoint] = []
        self._start_time: Optional[datetime] = None
    
    def record_data(self):
        """记录当前数据点"""
        try:
            data = self.heater.read_data()
            point = DataPoint(
                timestamp=datetime.now(),
                pv=data.pv,
                sv=data.sv,
                mv=data.mv,
                alarms=data.alarms if data.alarms else []
            )
            self.data_points.append(point)
            return point
        except Exception as e:
            log(f"  [警告] 数据记录失败: {e}")
            return None
    
    def ramp_temperature(self, start_temp: float, end_temp: float,
                         duration_minutes: float, interval_seconds: float = 5.0,
                         phase_name: str = ""):
        """斜率升温/降温"""
        duration_seconds = duration_minutes * 60
        temp_diff = end_temp - start_temp
        steps = int(duration_seconds / interval_seconds)
        temp_step = temp_diff / steps if steps > 0 else 0
        
        log(f"\n{'='*60}")
        log(f"[{phase_name}] 温度控制: {start_temp:.1f}°C → {end_temp:.1f}°C")
        log(f"持续时间: {duration_minutes:.1f} 分钟")
        log(f"{'='*60}\n")
        
        start_time = time.time()
        
        for step in range(steps + 1):
            target_temp = start_temp + temp_step * step
            
            self.heater.set_temperature(target_temp)
            
            point = self.record_data()
            if point:
                elapsed = time.time() - start_time
                remaining = duration_seconds - elapsed
                log(f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"目标: {target_temp:.1f}°C | "
                    f"当前: {point.pv:.1f}°C | "
                    f"设定: {point.sv:.1f}°C | "
                    f"输出: {point.mv}% | "
                    f"剩余: {remaining:.0f}秒")
            
            if step < steps:
                time.sleep(interval_seconds)
        
        log(f"\n[{phase_name}] 完成! 用时: {(time.time() - start_time)/60:.1f} 分钟")
    
    def hold_temperature(self, target_temp: float, duration_minutes: float,
                         interval_seconds: float = 5.0, phase_name: str = ""):
        """维持温度"""
        duration_seconds = duration_minutes * 60
        steps = int(duration_seconds / interval_seconds)
        
        log(f"\n{'='*60}")
        log(f"[{phase_name}] 维持温度: {target_temp:.1f}°C")
        log(f"持续时间: {duration_minutes:.1f} 分钟")
        log(f"{'='*60}\n")
        
        self.heater.set_temperature(target_temp)
        
        start_time = time.time()
        
        for step in range(steps + 1):
            point = self.record_data()
            if point:
                elapsed = time.time() - start_time
                remaining = duration_seconds - elapsed
                log(f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"目标: {target_temp:.1f}°C | "
                    f"当前: {point.pv:.1f}°C | "
                    f"设定: {point.sv:.1f}°C | "
                    f"输出: {point.mv}% | "
                    f"剩余: {remaining:.0f}秒")
            
            if step < steps:
                time.sleep(interval_seconds)
        
        log(f"\n[{phase_name}] 完成! 用时: {(time.time() - start_time)/60:.1f} 分钟")
    
    def cool_down(self, target_temp: float, interval_seconds: float = 10.0,
                  phase_name: str = "降温"):
        """自然降温"""
        log(f"\n{'='*60}")
        log(f"[{phase_name}] 自然降温至: {target_temp:.1f}°C")
        log(f"{'='*60}\n")
        
        self.heater.stop()
        self.heater.set_temperature(target_temp)
        
        start_time = time.time()
        
        while True:
            point = self.record_data()
            if point:
                elapsed = time.time() - start_time
                log(f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"当前: {point.pv:.1f}°C | "
                    f"目标: {target_temp:.1f}°C | "
                    f"输出: {point.mv}% | "
                    f"用时: {elapsed/60:.1f}分钟")
                
                if point.pv <= target_temp:
                    log(f"\n[{phase_name}] 已达到目标温度!")
                    break
            
            time.sleep(interval_seconds)
        
        log(f"\n[{phase_name}] 完成! 总用时: {(time.time() - start_time)/60:.1f} 分钟")
    
    def generate_report(self, title: str = "温度控制实验报告") -> str:
        """生成报告"""
        log(f"\n{'='*60}")
        log("生成实验报告...")
        log(f"{'='*60}\n")
        
        os.makedirs(self.report_dir, exist_ok=True)
        
        generator = ReportGenerator(self.report_dir)
        
        report_path = generator.generate(
            device_id=self.heater.config.device_id,
            data_points=self.data_points,
            title=title,
            include_charts=True,
            include_data_table=True
        )
        
        chart_path = os.path.join(self.report_dir, 
            f"temperature_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        ChartGenerator.generate_temperature_chart(
            self.data_points,
            title=title,
            output_path=chart_path
        )
        
        log(f"报告已生成: {report_path}")
        log(f"温度曲线图: {chart_path}")
        
        return report_path
    
    def print_summary(self):
        """打印实验摘要"""
        if not self.data_points:
            log("没有数据记录")
            return
        
        pv_values = [dp.pv for dp in self.data_points]
        sv_values = [dp.sv for dp in self.data_points]
        
        log(f"\n{'='*60}")
        log("实验摘要")
        log(f"{'='*60}")
        log(f"数据点数量: {len(self.data_points)}")
        log(f"开始时间: {self.data_points[0].timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"结束时间: {self.data_points[-1].timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        
        duration = (self.data_points[-1].timestamp - self.data_points[0].timestamp).total_seconds()
        log(f"总时长: {duration/60:.1f} 分钟")
        
        log(f"\n温度统计:")
        log(f"  PV 平均: {sum(pv_values)/len(pv_values):.2f}°C")
        log(f"  PV 最高: {max(pv_values):.2f}°C")
        log(f"  PV 最低: {min(pv_values):.2f}°C")
        log(f"  SV 范围: {min(sv_values):.1f}°C ~ {max(sv_values):.1f}°C")
        log(f"{'='*60}\n")


def main():
    log("="*60)
    log("温度控制实验脚本")
    log("="*60)
    log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    heater = create_heater('COM3', 1, 'Heater1')
    
    experiment = TemperatureExperiment(
        heater=heater,
        report_dir=os.path.join(_project_root, 'reports')
    )
    
    try:
        log("\n连接加热器...")
        heater.connect()
        log(f"已连接: {heater.model_name}")
        
        pv, sv = heater.get_temperature()
        log(f"当前温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
        
        start_temp = 20.0
        target_temp = 30.0
        
        heater.start()
        log("加热器已启动")
        
        experiment.ramp_temperature(
            start_temp=start_temp,
            end_temp=target_temp,
            duration_minutes=5.0,
            interval_seconds=5.0,
            phase_name="升温阶段"
        )
        
        experiment.hold_temperature(
            target_temp=target_temp,
            duration_minutes=5.0,
            interval_seconds=5.0,
            phase_name="维持阶段"
        )
        
        log("\n停止加热，开始记录降温...")
        heater.stop()
        
        log(f"\n{'='*60}")
        log("[记录阶段] 记录降温数据 5 分钟")
        log(f"{'='*60}\n")
        
        record_start = time.time()
        record_duration = 5.0 * 60
        
        while (time.time() - record_start) < record_duration:
            point = experiment.record_data()
            if point:
                elapsed = time.time() - record_start
                remaining = record_duration - elapsed
                log(f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"当前: {point.pv:.1f}°C | "
                    f"输出: {point.mv}% | "
                    f"剩余: {remaining:.0f}秒")
            time.sleep(5.0)
        
        log("\n[记录阶段] 完成!")
        
        experiment.print_summary()
        
        report_path = experiment.generate_report(
            title="温度控制实验报告"
        )
        
        log(f"\n实验完成!")
        log(f"报告路径: {report_path}")
        
    except KeyboardInterrupt:
        log("\n用户中断实验")
    except Exception as e:
        log(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if experiment.data_points:
            log("\n保存已收集的数据...")
            experiment.print_summary()
            try:
                report_path = experiment.generate_report(
                    title="温度控制实验报告"
                )
                log(f"报告已保存: {report_path}")
            except Exception as e:
                log(f"报告生成失败: {e}")
        
        log("\n关闭加热器...")
        try:
            heater.stop()
            heater.disconnect()
            log("加热器已关闭")
        except Exception as e:
            log(f"  [警告] 关闭加热器异常: {e}")
    
    log(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
