"""
简单温度控制脚本

从当前温度加热至目标温度，然后降温
- 升温：20°C → 30°C，用时5分钟
- 降温：30°C → 20°C，用时50分钟
"""

import sys
import os
import time
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.base_device import DeviceInfo, DeviceType


def log(msg):
    """带刷新的打印"""
    print(msg, flush=True)


def ramp_temperature(heater: AIHeaterDevice, start_temp: float, end_temp: float, 
                     duration_minutes: float, interval_seconds: float = 5.0):
    """
    斜率升温/降温
    """
    duration_seconds = duration_minutes * 60
    temp_diff = end_temp - start_temp
    steps = int(duration_seconds / interval_seconds)
    temp_step = temp_diff / steps if steps > 0 else 0
    
    log(f"\n{'='*60}")
    log(f"温度控制: {start_temp}°C → {end_temp}°C")
    log(f"持续时间: {duration_minutes} 分钟")
    log(f"控制间隔: {interval_seconds} 秒")
    log(f"每步变化: {temp_step:.3f}°C")
    log(f"{'='*60}\n")
    
    start_time = time.time()
    
    for step in range(steps + 1):
        target_temp = start_temp + temp_step * step
        
        heater.set_temperature(target_temp)
        
        pv, sv = heater.get_temperature()
        elapsed = time.time() - start_time
        remaining = duration_seconds - elapsed
        
        log(f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"目标: {target_temp:.1f}°C | "
            f"当前: {pv:.1f}°C | "
            f"设定: {sv:.1f}°C | "
            f"剩余: {remaining:.0f}秒")
        
        if step < steps:
            time.sleep(interval_seconds)
    
    log(f"\n完成! 总用时: {(time.time() - start_time)/60:.1f} 分钟")


def main():
    log("="*60)
    log("温度控制脚本")
    log("="*60)
    log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    config = HeaterConfig(
        device_id="heater1",
        connection_params={
            'port': 'COM3',
            'baudrate': 9600,
            'address': 1,
        },
        timeout=2.0,
        decimal_places=1,
    )
    
    info = DeviceInfo(
        name="主加热器",
        device_type=DeviceType.HEATER,
        manufacturer="Yudian",
    )
    
    heater = AIHeaterDevice(config, info)
    
    try:
        log("\n连接设备...")
        heater.connect()
        log(f"[OK] 已连接: {heater.model_name}")
        
        pv, sv = heater.get_temperature()
        log(f"当前温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
        
        log("\n启动加热器...")
        heater.start()
        
        ramp_temperature(heater, 20.0, 30.0, 5.0, interval_seconds=5.0)
        
        log("\n等待5秒后开始降温...")
        time.sleep(5)
        
        ramp_temperature(heater, 30.0, 20.0, 50.0, interval_seconds=10.0)
        
        log("\n停止加热器...")
        heater.stop()
        
        pv, sv = heater.get_temperature()
        log(f"最终温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
        
    except KeyboardInterrupt:
        log("\n\n用户中断，停止加热器...")
        heater.stop()
        
    except Exception as e:
        log(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        heater.disconnect()
        log("\n设备已断开")
        log(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
