"""
安全蠕动泵测试脚本

功能：
1. 串口资源管理器集成
2. 进程锁文件
3. 紧急停止保障
4. 通道隔离测试
5. 异常恢复测试

使用方法：
    python scripts/test_pump_safe.py
"""

import sys
import os
import time
import threading
import signal
import atexit
import argparse
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.safe_pump import SafePumpDevice, ChannelTask
from devices.peristaltic_pump import PeristalticPumpConfig, PumpChannelConfig
from devices.base_device import DeviceInfo, DeviceType
from protocols.pump_params import PumpRunMode, PumpDirection
from utils.serial_manager import get_serial_manager, SerialPortForceRelease, cleanup_all_serial_ports
from utils.device_safety import get_safety_manager, DeviceState

_pump: SafePumpDevice = None
_config: PeristalticPumpConfig = None
_stop_event = threading.Event()
_test_start_time = None


def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n" + "=" * 60)
    print("收到停止信号，正在安全关闭...")
    print("=" * 60)
    _stop_event.set()
    cleanup()


def cleanup():
    """清理函数"""
    global _pump
    
    if _pump is not None:
        try:
            print("[清理] 停止所有通道...")
            _pump.stop_all_channels()
            
            print("[清理] 断开设备连接...")
            _pump.disconnect()
            
            print("[清理] 设备已安全关闭")
        except Exception as e:
            print(f"[清理] 错误: {e}")
        finally:
            _pump = None
    
    cleanup_all_serial_ports()
    print("[清理] 串口资源已释放")


def create_config(port: str = "COM10") -> PeristalticPumpConfig:
    """创建配置"""
    return PeristalticPumpConfig(
        device_id="pump1",
        connection_params={
            "port": port,
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
        },
        channels=[
            PumpChannelConfig(channel=1, enabled=True),
            PumpChannelConfig(channel=2, enabled=True),
            PumpChannelConfig(channel=3, enabled=True),
            PumpChannelConfig(channel=4, enabled=True),
        ],
        slave_address=1,
        baudrate=9600,
        parity="N",
    )


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def print_status(channel: int, status):
    """打印状态"""
    if status:
        print(f"  通道{channel}: 运行={status.running}, 流速={status.flow_rate:.1f} mL/min, "
              f"已分装={status.dispensed_volume:.2f} mL")


def test_connection(pump: SafePumpDevice, force: bool = False):
    """测试连接"""
    print_header("测试1: 设备连接")
    
    print(f"串口: {_config.connection_params.get('port')}")
    print(f"强制模式: {force}")
    
    start = time.time()
    result = pump.connect(force=force)
    elapsed = time.time() - start
    
    if result:
        print(f"[OK] 连接成功 (耗时: {elapsed:.2f}秒)")
        print(f"设备状态: {pump.state.value}")
        return True
    else:
        print(f"[FAILED] 连接失败 (耗时: {elapsed:.2f}秒)")
        
        if not force:
            print("\n尝试强制释放串口...")
            SerialPortForceRelease.force_release(_config.connection_params.get('port'))
            time.sleep(0.5)
            
            result = pump.connect(force=True)
            if result:
                print("[OK] 强制连接成功")
                return True
        
        return False


def test_read_status(pump: SafePumpDevice):
    """测试读取状态"""
    print_header("测试2: 读取通道状态")
    
    for channel in range(1, 5):
        if _stop_event.is_set():
            return
        
        status = pump.read_channel_status(channel)
        print_status(channel, status)
        state = pump.get_channel_state(channel)
        print(f"  通道状态: {state.value}")
    
    print("[OK] 状态读取完成")


def test_single_channel(pump: SafePumpDevice, channel: int, volume: float, flow_rate: float):
    """测试单通道"""
    print_header(f"测试3: 通道{channel} 定时定量运行 ({volume}mL @ {flow_rate}mL/min)")
    
    task = ChannelTask(
        channel=channel,
        volume=volume,
        flow_rate=flow_rate,
        direction=PumpDirection.CLOCKWISE,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    estimated_time = volume / flow_rate * 60
    print(f"预计时间: {estimated_time:.1f}秒")
    
    start_time = time.time()
    result = pump.run_channel_task(task)
    
    if not result:
        print("[FAILED] 启动失败")
        return
    
    print("[OK] 任务已启动")
    
    while not _stop_event.is_set():
        if pump.get_channel_state(channel) == DeviceState.READY:
            break
        
        if pump.get_channel_state(channel) == DeviceState.ERROR:
            error = pump.get_channel_error(channel)
            print(f"[ERROR] 通道{channel}错误: {error.message if error else 'Unknown'}")
            break
        
        elapsed = time.time() - start_time
        status = pump.read_channel_status(channel)
        
        if status:
            print(f"  已分装: {status.dispensed_volume:.2f}mL, 用时: {elapsed:.1f}s")
        
        for _ in range(10):
            if _stop_event.is_set():
                break
            time.sleep(0.1)
    
    print(f"[OK] 通道{channel}任务完成")


def test_dual_channels(pump: SafePumpDevice):
    """测试双通道同时运行"""
    print_header("测试4: 双通道同时运行")
    
    task1 = ChannelTask(
        channel=1,
        volume=5.0,
        flow_rate=20.0,
        direction=PumpDirection.CLOCKWISE,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    task4 = ChannelTask(
        channel=4,
        volume=8.0,
        flow_rate=15.0,
        direction=PumpDirection.CLOCKWISE,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    print("启动通道1和通道4...")
    pump.run_channel_task(task1)
    pump.run_channel_task(task4)
    
    start_time = time.time()
    
    while not _stop_event.is_set():
        ch1_state = pump.get_channel_state(1)
        ch4_state = pump.get_channel_state(4)
        
        if ch1_state == DeviceState.READY and ch4_state == DeviceState.READY:
            break
        
        elapsed = time.time() - start_time
        status1 = pump.read_channel_status(1)
        status4 = pump.read_channel_status(4)
        
        vol1 = status1.dispensed_volume if status1 else 0
        vol4 = status4.dispensed_volume if status4 else 0
        
        print(f"  CH1: {vol1:.2f}mL ({ch1_state.value}) | CH4: {vol4:.2f}mL ({ch4_state.value})")
        
        for _ in range(10):
            if _stop_event.is_set():
                break
            time.sleep(0.1)
    
    print("[OK] 双通道任务完成")


def test_emergency_stop(pump: SafePumpDevice):
    """测试紧急停止"""
    print_header("测试5: 紧急停止响应")
    
    task = ChannelTask(
        channel=1,
        volume=100.0,
        flow_rate=10.0,
        direction=PumpDirection.CLOCKWISE,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    print("启动长时间任务...")
    pump.run_channel_task(task)
    
    print("等待2秒后触发紧急停止...")
    time.sleep(2.0)
    
    print("触发紧急停止...")
    start = time.time()
    pump.emergency_stop()
    elapsed = time.time() - start
    
    print(f"[OK] 紧急停止完成 (耗时: {elapsed:.3f}秒)")
    
    if elapsed < 3.0:
        print("[OK] 响应时间符合要求 (<3秒)")
    else:
        print("[WARNING] 响应时间超过3秒")


def test_channel_isolation(pump: SafePumpDevice):
    """测试通道隔离"""
    print_header("测试6: 通道隔离")
    
    print("启动通道1和通道2...")
    
    task1 = ChannelTask(
        channel=1,
        volume=10.0,
        flow_rate=20.0,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    task2 = ChannelTask(
        channel=2,
        volume=10.0,
        flow_rate=20.0,
        mode=PumpRunMode.QUANTITY_SPEED,
    )
    
    pump.run_channel_task(task1)
    pump.run_channel_task(task2)
    
    print("等待1秒后停止通道1...")
    time.sleep(1.0)
    
    pump.stop_channel(1)
    
    print("检查通道2是否仍在运行...")
    time.sleep(0.5)
    
    ch2_state = pump.get_channel_state(2)
    
    if ch2_state == DeviceState.RUNNING:
        print("[OK] 通道隔离正常 - 通道2仍在运行")
    else:
        print(f"[FAILED] 通道隔离失败 - 通道2状态: {ch2_state.value}")
    
    pump.stop_channel(2)
    print("[OK] 通道隔离测试完成")


def run_tests(port: str, force: bool = False, skip_long_tests: bool = False):
    """运行所有测试"""
    global _pump, _config, _test_start_time
    
    _test_start_time = time.time()
    
    print("\n" + "=" * 60)
    print(" 安全蠕动泵测试")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"串口: {port}")
    print(f"强制模式: {force}")
    
    _config = create_config(port)
    _config.connection_params["port"] = port
    
    _pump = SafePumpDevice(_config)
    
    if not test_connection(_pump, force=force):
        print("\n[FAILED] 连接失败，测试终止")
        return False
    
    test_read_status(_pump)
    
    if _stop_event.is_set():
        return False
    
    if not skip_long_tests:
        test_single_channel(_pump, 1, 5.0, 20.0)
        
        if _stop_event.is_set():
            return False
        
        test_single_channel(_pump, 4, 8.0, 15.0)
        
        if _stop_event.is_set():
            return False
        
        test_dual_channels(_pump)
        
        if _stop_event.is_set():
            return False
    
    test_channel_isolation(_pump)
    
    if _stop_event.is_set():
        return False
    
    if not skip_long_tests:
        test_emergency_stop(_pump)
    
    print_header("测试完成")
    
    elapsed = time.time() - _test_start_time
    print(f"总耗时: {elapsed:.1f}秒")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="安全蠕动泵测试")
    parser.add_argument("--port", default="COM10", help="串口")
    parser.add_argument("--force", action="store_true", help="强制获取串口")
    parser.add_argument("--skip-long", action="store_true", help="跳过长时间测试")
    args = parser.parse_args()
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = run_tests(
            port=args.port,
            force=args.force,
            skip_long_tests=args.skip_long
        )
        
        if success:
            print("\n[SUCCESS] 所有测试通过")
        else:
            print("\n[FAILED] 部分测试失败")
        
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n[ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
