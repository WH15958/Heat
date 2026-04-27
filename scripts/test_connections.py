"""快速测试加热器和蠕动泵连接"""
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from devices.heater import AIHeaterDevice, HeaterConfig
from devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from devices.base_device import DeviceInfo, DeviceType
from utils.serial_manager import get_serial_manager, cleanup_all_serial_ports

print("="*60)
print("设备连接测试")
print("="*60)

# 获取串口管理器
serial_manager = get_serial_manager()

# 测试加热器
heaters = []
heater_ports = ["COM7", "COM9"]

print("\n--- 测试加热器 ---")
for port in heater_ports:
    print(f"\n测试加热器: {port}")
    
    try:
        if not serial_manager.acquire_port(port):
            print(f"  [FAIL] 无法获取串口")
            continue
        
        heater = AIHeaterDevice(
            HeaterConfig(
                device_id=f"heater_{port}",
                connection_params={
                    'port': port,
                    'baudrate': 9600,
                    'address': 1,
                },
                timeout=2.0,
                decimal_places=1,
            ),
            DeviceInfo(
                name=f"加热器_{port}",
                device_type=DeviceType.HEATER,
                manufacturer="Yudian",
            )
        )
        
        if heater.connect():
            print(f"  [OK] 连接成功!")
            try:
                pv, sv = heater.get_temperature()
                print(f"  当前温度: PV={pv:.1f}°C, SV={sv:.1f}°C")
            except Exception as e:
                print(f"  [WARN] 读取温度失败: {e}")
            heaters.append((port, heater))
        else:
            print(f"  [FAIL] 连接失败")
            
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()

# 测试蠕动泵
print("\n--- 测试蠕动泵 ---")
pump = None
pump_port = "COM10"

print(f"\n测试蠕动泵: {pump_port}")

try:
    if not serial_manager.acquire_port(pump_port):
        print(f"  [FAIL] 无法获取串口")
    else:
        pump_config = PeristalticPumpConfig(
            device_id="pump1",
            connection_params={
                "port": pump_port,
                "baudrate": 9600,
                "parity": "N",
                "stopbits": 1,
                "bytesize": 8,
            },
            channels=[
                PumpChannelConfig(channel=1, enabled=True),
            ],
            slave_address=1,
            baudrate=9600,
            parity="N",
        )
        
        pump = LabSmartPumpDevice(pump_config)
        
        if pump.connect():
            print(f"  [OK] 连接成功!")
        else:
            print(f"  [FAIL] 连接失败")
            
except Exception as e:
    print(f"  [ERROR] {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("测试总结")
print("="*60)
print(f"加热器连接成功: {len(heaters)}/{len(heater_ports)}")
for port, _ in heaters:
    print(f"  - {port}")
print(f"蠕动泵连接成功: {'是' if pump else '否'}")

# 断开连接
print("\n正在断开连接...")
for _, heater in heaters:
    try:
        heater.disconnect()
    except Exception:
        pass

if pump:
    try:
        pump.disconnect()
    except Exception:
        pass

cleanup_all_serial_ports()
print("[OK] 已清理所有资源")
print("="*60)
