"""
串口通信诊断脚本

用于排查串口通信问题
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

import serial
import serial.tools.list_ports
import time


def list_ports():
    """列出所有可用串口"""
    print("\n" + "="*60)
    print("可用串口列表")
    print("="*60)
    
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("未找到任何串口!")
        return []
    
    for p in ports:
        print(f"\n串口: {p.device}")
        print(f"描述: {p.description}")
        print(f"硬件ID: {p.hwid}")
        
        if 'CH340' in p.description:
            print("  [!] 注意: CH340是USB转TTL芯片，不是RS485!")
        elif '485' in p.description.upper() or 'RS485' in p.description.upper():
            print("  [OK] 这是RS485转换器")
    
    return [p.device for p in ports]


def test_raw_serial(port, baudrate=9600):
    """测试原始串口通信"""
    print("\n" + "="*60)
    print(f"原始串口测试: {port} @ {baudrate}")
    print("="*60)
    
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2.0
        )
        print(f"[OK] 串口打开成功")
        print(f"     配置: {baudrate},8,N,1")
        
        # AIBUS读参数0指令（地址0）
        # 格式: 地址(2) + 命令(1) + 参数代号(1) + 固定值(2) + 校验和(2)
        cmd = bytes([0x80, 0x80, 0x52, 0x00, 0x00, 0x00, 0x52, 0x00])
        
        print(f"\n发送指令: {cmd.hex().upper()}")
        print("指令说明: 读参数0(给定值)，地址=0")
        
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        sent = ser.write(cmd)
        print(f"已发送: {sent} 字节")
        
        print("等待响应...")
        time.sleep(0.5)
        
        response = ser.read(100)
        print(f"收到: {len(response)} 字节")
        
        if response:
            print(f"数据(hex): {response.hex().upper()}")
            
            if len(response) == 10:
                print("\n[OK] 收到正确的10字节响应!")
                print("仪表通信正常!")
            else:
                print(f"\n[!] 响应长度不正确，期望10字节，收到{len(response)}字节")
        else:
            print("\n[X] 未收到任何响应!")
            print("\n可能的原因:")
            print("  1. 仪表未上电")
            print("  2. 接线错误（RS485 A/B接反或未接）")
            print("  3. 仪表地址不是0")
            print("  4. 波特率不匹配")
            print("  5. 使用了错误的转换器（CH340是TTL，不是RS485）")
        
        ser.close()
        return len(response) > 0
        
    except Exception as e:
        print(f"[X] 错误: {e}")
        return False


def test_different_baudrates(port):
    """测试不同波特率"""
    print("\n" + "="*60)
    print(f"测试不同波特率: {port}")
    print("="*60)
    
    baudrates = [4800, 9600, 19200, 28800]
    cmd = bytes([0x80, 0x80, 0x52, 0x00, 0x00, 0x00, 0x52, 0x00])
    
    for baud in baudrates:
        print(f"\n尝试波特率: {baud}")
        try:
            ser = serial.Serial(port, baud, timeout=0.5)
            ser.reset_input_buffer()
            ser.write(cmd)
            time.sleep(0.3)
            response = ser.read(100)
            ser.close()
            
            if response:
                print(f"  [OK] 收到 {len(response)} 字节: {response.hex().upper()}")
                print(f"  --> 波特率 {baud} 可能正确!")
                return baud
            else:
                print(f"  [ ] 无响应")
        except Exception as e:
            print(f"  [X] 错误: {e}")
    
    return None


def test_different_addresses(port, baudrate=9600):
    """测试不同仪表地址"""
    print("\n" + "="*60)
    print(f"测试不同仪表地址: {port} @ {baudrate}")
    print("="*60)
    
    for addr in range(5):
        addr_byte = 0x80 + addr
        cmd = bytes([addr_byte, addr_byte, 0x52, 0x00, 0x00, 0x00, 
                    (0x52 + addr) & 0xFF, ((0x52 + addr) >> 8) & 0xFF])
        
        print(f"\n尝试地址: {addr} (指令: {cmd.hex().upper()})")
        try:
            ser = serial.Serial(port, baudrate, timeout=0.5)
            ser.reset_input_buffer()
            ser.write(cmd)
            time.sleep(0.3)
            response = ser.read(100)
            ser.close()
            
            if response:
                print(f"  [OK] 收到 {len(response)} 字节: {response.hex().upper()}")
                print(f"  --> 仪表地址可能是 {addr}!")
                return addr
            else:
                print(f"  [ ] 无响应")
        except Exception as e:
            print(f"  [X] 错误: {e}")
    
    return None


def main():
    print("="*60)
    print("串口通信诊断工具")
    print("="*60)
    
    # 1. 列出串口
    available_ports = list_ports()
    if not available_ports:
        return
    
    # 选择串口
    if len(available_ports) == 1:
        port = available_ports[0]
        print(f"\n自动选择: {port}")
    else:
        print("\n可用串口:", available_ports)
        port = input("请输入串口号 (默认COM3): ").strip() or "COM3"
    
    # 2. 原始测试
    if not test_raw_serial(port):
        
        # 3. 尝试不同波特率
        print("\n" + "-"*60)
        print("尝试不同的波特率...")
        found_baud = test_different_baudrates(port)
        
        if found_baud:
            # 4. 尝试不同地址
            print("\n" + "-"*60)
            print("尝试不同的仪表地址...")
            test_different_addresses(port, found_baud)
    
    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)
    
    print("""
硬件检查清单:
  [ ] 仪表已上电，显示屏正常显示
  [ ] 使用USB转RS485转换器（不是CH340 TTL）
  [ ] RS485接线: A接A, B接B
  [ ] 仪表参数 Addr = 0
  [ ] 仪表参数 波特率 = 9600
  [ ] 仪表参数 AFC = 1 (AIBUS协议)
""")


if __name__ == "__main__":
    main()
