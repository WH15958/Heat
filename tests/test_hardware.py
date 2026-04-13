"""
加热器硬件连接测试脚本

用于测试与实际加热器设备的连接。
运行前请确保：
1. 加热器已正确连接到指定串口
2. 串口参数（波特率、地址等）配置正确
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

import time
from datetime import datetime


def test_serial_connection(port: str, baudrate: int = 9600, address: int = 0):
    """
    测试串口连接
    
    Args:
        port: 串口号
        baudrate: 波特率
        address: 仪表地址
    """
    print(f"\n{'='*60}")
    print(f"加热器硬件连接测试")
    print(f"{'='*60}")
    print(f"串口: {port}")
    print(f"波特率: {baudrate}")
    print(f"仪表地址: {address}")
    print(f"{'='*60}\n")
    
    from protocols.aibus import AIBUSProtocol
    from protocols.parameters import ParameterCode, get_model_name
    
    protocol = AIBUSProtocol(
        port=port,
        address=address,
        baudrate=baudrate,
        timeout=2.0
    )
    
    try:
        print("正在打开串口...")
        protocol.open()
        print("[OK] 串口打开成功\n")
        
        print("正在读取仪表型号...")
        try:
            model_value, _ = protocol.read_parameter(ParameterCode.MODEL_CODE)
            model_name = get_model_name(int(model_value))
            print(f"[OK] 仪表型号: {model_name}")
        except Exception as e:
            print(f"[!] 无法读取型号: {e}")
        
        print("\n正在读取温度数据...")
        for i in range(5):
            try:
                pv, sv, mv, alarm = protocol.read_pv_sv()
                print(f"  [{i+1}] PV={pv/10:.1f}C, SV={sv/10:.1f}C, MV={mv}%, Alarm={alarm:02X}")
            except Exception as e:
                print(f"  [{i+1}] 读取失败: {e}")
            time.sleep(0.5)
        
        print("\n测试温度设定...")
        try:
            test_sv = 50.0
            print(f"  设定温度为 {test_sv}C...")
            protocol.write_parameter(ParameterCode.SV, int(test_sv * 10), decimal_places=0)
            print(f"  [OK] 设定成功")
            
            time.sleep(0.5)
            _, sv, _, _ = protocol.read_pv_sv()
            print(f"  当前SV: {sv/10:.1f}C")
        except Exception as e:
            print(f"  [X] 设定失败: {e}")
        
        print("\n[OK] 硬件连接测试完成")
        return True
        
    except Exception as e:
        print(f"\n[X] 连接失败: {e}")
        return False
        
    finally:
        protocol.close()
        print("\n串口已关闭")


def test_heater_device(port: str, baudrate: int = 9600, address: int = 0):
    """
    测试加热器设备驱动
    
    Args:
        port: 串口号
        baudrate: 波特率
        address: 仪表地址
    """
    print(f"\n{'='*60}")
    print(f"加热器设备驱动测试")
    print(f"{'='*60}\n")
    
    from devices.heater import AIHeaterDevice, HeaterConfig
    from devices.base_device import DeviceInfo, DeviceType
    
    config = HeaterConfig(
        device_id="test_heater",
        connection_params={
            'port': port,
            'baudrate': baudrate,
            'address': address,
        },
        timeout=2.0,
        decimal_places=1,
    )
    
    info = DeviceInfo(
        name="测试加热器",
        device_type=DeviceType.HEATER,
        manufacturer="Yudian",
    )
    
    heater = AIHeaterDevice(config, info)
    
    try:
        print("正在连接设备...")
        heater.connect()
        print(f"[OK] 设备已连接: {heater.model_name}\n")
        
        print("读取设备数据...")
        data = heater.read_data()
        print(f"  PV: {data.pv:.1f}C")
        print(f"  SV: {data.sv:.1f}C")
        print(f"  MV: {data.mv}%")
        print(f"  报警: {data.alarms if data.alarms else '无'}")
        
        print("\n测试温度设定...")
        heater.set_temperature(60.0)
        print("  [OK] 温度设定为60C")
        
        time.sleep(0.5)
        pv, sv = heater.get_temperature()
        print(f"  当前: PV={pv:.1f}C, SV={sv:.1f}C")
        
        print("\n测试运行控制...")
        heater.start()
        print("  [OK] 设备已启动")
        
        time.sleep(1)
        
        heater.stop()
        print("  [OK] 设备已停止")
        
        print("\n[OK] 设备驱动测试完成")
        return True
        
    except Exception as e:
        print(f"\n[X] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        heater.disconnect()


def interactive_test():
    """交互式测试"""
    print("\n" + "="*60)
    print("加热器交互式测试")
    print("="*60)
    
    port = input("请输入串口号 (默认COM3): ").strip() or "COM3"
    baudrate = int(input("请输入波特率 (默认9600): ").strip() or "9600")
    address = int(input("请输入仪表地址 (默认0): ").strip() or "0")
    
    print("\n选择测试类型:")
    print("1. 串口连接测试")
    print("2. 设备驱动测试")
    print("3. 全部测试")
    
    choice = input("请选择 (默认3): ").strip() or "3"
    
    if choice == "1":
        test_serial_connection(port, baudrate, address)
    elif choice == "2":
        test_heater_device(port, baudrate, address)
    else:
        test_serial_connection(port, baudrate, address)
        test_heater_device(port, baudrate, address)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="加热器硬件测试")
    parser.add_argument("--port", default="COM3", help="串口号")
    parser.add_argument("--baudrate", type=int, default=9600, help="波特率")
    parser.add_argument("--address", type=int, default=0, help="仪表地址")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互模式")
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_test()
    else:
        test_serial_connection(args.port, args.baudrate, args.address)
        test_heater_device(args.port, args.baudrate, args.address)
