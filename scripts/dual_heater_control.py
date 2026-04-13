"""
双加热器温度控制脚本

同时控制两个加热器设备
- 两个串口同时运行
- 升温：当前温度 → 30°C，用时5分钟
"""

import sys
import os
import time
import threading
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.base_device import DeviceInfo, DeviceType


def log(msg):
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


def ramp_temperature(heater: AIHeaterDevice, start_temp: float, end_temp: float, 
                     duration_minutes: float, interval_seconds: float = 5.0,
                     name: str = "Heater"):
    """斜率升温"""
    duration_seconds = duration_minutes * 60
    temp_diff = end_temp - start_temp
    steps = int(duration_seconds / interval_seconds)
    temp_step = temp_diff / steps if steps > 0 else 0
    
    log(f"\n[{name}] 温度控制: {start_temp}°C → {end_temp}°C, 持续 {duration_minutes} 分钟")
    
    start_time = time.time()
    
    for step in range(steps + 1):
        target_temp = start_temp + temp_step * step
        
        heater.set_temperature(target_temp)
        
        pv, sv = heater.get_temperature()
        elapsed = time.time() - start_time
        remaining = duration_seconds - elapsed
        
        log(f"[{datetime.now().strftime('%H:%M:%S')}][{name}] "
            f"目标: {target_temp:.1f}°C | 当前: {pv:.1f}°C | 设定: {sv:.1f}°C | 剩余: {remaining:.0f}秒")
        
        if step < steps:
            time.sleep(interval_seconds)
    
    log(f"[{name}] 完成! 总用时: {(time.time() - start_time)/60:.1f} 分钟")


def run_heater(port: str, address: int, name: str, target_temp: float, 
               duration_minutes: float, results: dict):
    """运行单个加热器（用于多线程）"""
    try:
        heater = create_heater(port, address, name)
        heater.connect()
        log(f"[{name}] 已连接: {heater.model_name}")
        
        pv, sv = heater.get_temperature()
        log(f"[{name}] 当前温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
        
        heater.start()
        log(f"[{name}] 启动加热器")
        
        ramp_temperature(heater, pv, target_temp, duration_minutes, 
                        interval_seconds=5.0, name=name)
        
        heater.stop()
        log(f"[{name}] 停止加热器")
        
        pv, sv = heater.get_temperature()
        log(f"[{name}] 最终温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
        
        heater.disconnect()
        results[name] = {'success': True, 'final_pv': pv, 'final_sv': sv}
        
    except Exception as e:
        log(f"[{name}] 错误: {e}")
        results[name] = {'success': False, 'error': str(e)}


def main():
    log("="*60)
    log("双加热器温度控制脚本")
    log("="*60)
    log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 加热器配置
    heaters_config = [
        {'port': 'COM3', 'address': 1, 'name': 'Heater1'},
        {'port': 'COM4', 'address': 1, 'name': 'Heater2'},
    ]
    
    # 目标温度和加热时间
    target_temp = 30.0
    duration_minutes = 5.0
    
    log(f"\n目标温度: {target_temp}°C")
    log(f"加热时间: {duration_minutes} 分钟")
    log(f"加热器数量: {len(heaters_config)}")
    
    # 存储结果
    results = {}
    
    # 创建线程
    threads = []
    for cfg in heaters_config:
        t = threading.Thread(
            target=run_heater,
            args=(cfg['port'], cfg['address'], cfg['name'], 
                  target_temp, duration_minutes, results)
        )
        threads.append(t)
    
    # 启动所有线程
    log("\n启动所有加热器...")
    for t in threads:
        t.start()
    
    # 等待所有线程完成
    for t in threads:
        t.join()
    
    # 打印结果
    log("\n" + "="*60)
    log("执行结果")
    log("="*60)
    for name, result in results.items():
        if result['success']:
            log(f"[{name}] 成功 - 最终温度: PV={result['final_pv']:.1f}°C")
        else:
            log(f"[{name}] 失败 - 错误: {result['error']}")
    
    log(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
