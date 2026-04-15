"""
蠕动泵单独测试脚本

功能：
1. 连接蠕动泵
2. 测试通道1和通道4的定时定量运行
3. 显示实时状态

使用方法：
    python scripts/test_pump_only.py
"""

import sys
import os
import time
import threading
import signal
import atexit

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from devices.base_device import DeviceInfo, DeviceType
from protocols.pump_params import PumpRunMode, PumpDirection

_stop_event = threading.Event()
_pump = None


def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n收到停止信号，正在关闭...")
    _stop_event.set()


def cleanup():
    """清理函数"""
    global _pump
    if _pump is not None:
        try:
            _pump.stop_all()
            _pump.disconnect()
            print("[清理] 蠕动泵已断开")
        except Exception as e:
            print(f"[清理] 错误: {e}")
        finally:
            _pump = None


atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def test_pump():
    global _pump
    
    print("\n" + "=" * 60)
    print("蠕动泵测试")
    print("=" * 60)
    
    channels = [
        PumpChannelConfig(channel=1, enabled=True, pump_head=5, tube_model=0),
        PumpChannelConfig(channel=2, enabled=True, pump_head=5, tube_model=0),
        PumpChannelConfig(channel=3, enabled=True, pump_head=5, tube_model=0),
        PumpChannelConfig(channel=4, enabled=True, pump_head=5, tube_model=0),
    ]
    
    config = PeristalticPumpConfig(
        device_id="pump1",
        connection_params={
            'port': 'COM10',
            'baudrate': 9600,
        },
        slave_address=1,
        parity='N',
        stopbits=1,
        bytesize=8,
        channels=channels
    )
    
    _pump = LabSmartPumpDevice(config)
    
    print("\n连接蠕动泵...")
    if not _pump.connect():
        print("[ERROR] 连接失败")
        return
    print("[OK] 连接成功")
    
    try:
        print("\n" + "-" * 40)
        print("测试1: 读取所有通道状态")
        print("-" * 40)
        for ch in [1, 2, 3, 4]:
            if _stop_event.is_set():
                break
            status = _pump.read_channel_status(ch)
            if status:
                print(f"通道{ch}: 运行={status.running}, 流速={status.flow_rate:.1f} mL/min")
            else:
                print(f"通道{ch}: 无法读取状态")
        
        if _stop_event.is_set():
            print("\n[停止] 用户中断")
            return
        
        print("\n" + "-" * 40)
        print("测试2: 通道1 定时定量运行 (10mL @ 20mL/min)")
        print("-" * 40)
        
        _pump.set_run_mode(1, PumpRunMode.QUANTITY_SPEED)
        _pump.set_direction(1, PumpDirection.CLOCKWISE)
        _pump.set_flow_rate(1, 20.0)
        _pump.set_dispense_volume(1, 10.0)
        
        print("启动通道1...")
        _pump.start_channel(1)
        
        estimated_time = 10.0 / 20.0 * 60
        print(f"预计时间: {estimated_time:.1f}秒")
        
        start_time = time.time()
        while time.time() - start_time < estimated_time + 10:
            if _stop_event.is_set():
                print("\n[停止] 用户中断")
                break
            
            status = _pump.read_channel_status(1)
            if status:
                elapsed = time.time() - start_time
                print(f"  已分装: {status.dispensed_volume:.1f}mL, 用时: {elapsed:.1f}s")
                if not status.running and status.dispensed_volume >= 9.5:
                    print(f"[OK] 分装完成: {status.dispensed_volume:.1f}mL")
                    break
            time.sleep(1)
        
        _pump.stop_channel(1)
        print("[OK] 通道1已停止")
        
        if _stop_event.is_set():
            return
        
        print("\n" + "-" * 40)
        print("测试3: 通道4 定时定量运行 (15mL @ 15mL/min)")
        print("-" * 40)
        
        _pump.set_run_mode(4, PumpRunMode.QUANTITY_SPEED)
        _pump.set_direction(4, PumpDirection.CLOCKWISE)
        _pump.set_flow_rate(4, 15.0)
        _pump.set_dispense_volume(4, 15.0)
        
        print("启动通道4...")
        _pump.start_channel(4)
        
        estimated_time = 15.0 / 15.0 * 60
        print(f"预计时间: {estimated_time:.1f}秒")
        
        start_time = time.time()
        while time.time() - start_time < estimated_time + 10:
            if _stop_event.is_set():
                print("\n[停止] 用户中断")
                break
            
            status = _pump.read_channel_status(4)
            if status:
                elapsed = time.time() - start_time
                print(f"  已分装: {status.dispensed_volume:.1f}mL, 用时: {elapsed:.1f}s")
                if not status.running and status.dispensed_volume >= 14.0:
                    print(f"[OK] 分装完成: {status.dispensed_volume:.1f}mL")
                    break
            time.sleep(1)
        
        _pump.stop_channel(4)
        print("[OK] 通道4已停止")
        
        if _stop_event.is_set():
            return
        
        print("\n" + "-" * 40)
        print("测试4: 双通道同时运行")
        print("-" * 40)
        
        _pump.set_run_mode(1, PumpRunMode.QUANTITY_SPEED)
        _pump.set_direction(1, PumpDirection.CLOCKWISE)
        _pump.set_flow_rate(1, 30.0)
        _pump.set_dispense_volume(1, 5.0)
        
        _pump.set_run_mode(4, PumpRunMode.QUANTITY_SPEED)
        _pump.set_direction(4, PumpDirection.CLOCKWISE)
        _pump.set_flow_rate(4, 25.0)
        _pump.set_dispense_volume(4, 8.0)
        
        print("同时启动通道1和通道4...")
        _pump.start_channel(1)
        _pump.start_channel(4)
        
        start_time = time.time()
        while time.time() - start_time < 30:
            if _stop_event.is_set():
                print("\n[停止] 用户中断")
                break
            
            status1 = _pump.read_channel_status(1)
            status4 = _pump.read_channel_status(4)
            
            s1 = f"CH1: {status1.dispensed_volume:.1f}mL" if status1 else "CH1: N/A"
            s4 = f"CH4: {status4.dispensed_volume:.1f}mL" if status4 else "CH4: N/A"
            print(f"  {s1} | {s4}")
            
            ch1_done = status1 and not status1.running and status1.dispensed_volume >= 4.5
            ch4_done = status4 and not status4.running and status4.dispensed_volume >= 7.5
            
            if ch1_done and ch4_done:
                print("[OK] 双通道分装完成")
                break
            
            time.sleep(1)
        
        _pump.stop_channel(1)
        _pump.stop_channel(4)
        print("[OK] 所有通道已停止")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] 测试出错: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        cleanup()


if __name__ == "__main__":
    test_pump()
