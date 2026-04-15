"""
蠕动泵连接诊断脚本

用于诊断蠕动泵MODBUS通信问题
"""

import sys
import os
import time

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from protocols.modbus_rtu import ModbusRTUProtocol


def test_pump_connection(port: str, baudrate: int = 9600, parity: str = 'N'):
    """测试蠕动泵连接"""
    print(f"\n{'='*60}")
    print(f"蠕动泵连接诊断")
    print(f"端口: {port}, 波特率: {baudrate}, 校验位: {parity}")
    print(f"{'='*60}\n")
    
    protocol = ModbusRTUProtocol(
        port=port,
        baudrate=baudrate,
        parity=parity,
        stopbits=1,
        bytesize=8,
        timeout=2.0,
    )
    
    if not protocol.connect():
        print("[ERROR] 无法打开串口")
        return
    
    print("[OK] 串口已打开\n")
    
    print("尝试读取不同地址的寄存器...")
    print("根据MODBUS协议文档，寄存器地址为十进制")
    
    for slave_addr in [1, 2, 3]:
        print(f"\n--- 从站地址: {slave_addr} ---")
        
        for reg_addr in [10, 100, 1000, 1001, 1002, 1003, 1004, 1005, 1006]:
            try:
                result = protocol.read_holding_registers(slave_addr, reg_addr, 1)
                if result:
                    print(f"  寄存器 {reg_addr} (0x{reg_addr:04X}): {result}")
                else:
                    print(f"  寄存器 {reg_addr} (0x{reg_addr:04X}): 无响应")
            except Exception as e:
                print(f"  寄存器 {reg_addr} (0x{reg_addr:04X}): 错误 - {e}")
        
        time.sleep(0.5)
    
    protocol.disconnect()
    print("\n[OK] 诊断完成")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="蠕动泵连接诊断")
    parser.add_argument("--port", default="COM6", help="串口")
    parser.add_argument("--baudrate", type=int, default=9600, help="波特率")
    parser.add_argument("--parity", default="N", help="校验位 (N/E/O)")
    
    args = parser.parse_args()
    
    test_pump_connection(args.port, args.baudrate, args.parity)
