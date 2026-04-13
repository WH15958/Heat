"""
TTL串口诊断脚本

用于测试TTL串口连接的仪表
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

import serial
import serial.tools.list_ports
import time


def scan_all_params(port):
    """扫描所有可能的波特率和地址组合"""
    print("\n" + "="*60)
    print(f"扫描所有参数组合: {port}")
    print("="*60)
    
    baudrates = [4800, 9600, 19200, 38400, 57600, 115200]
    addresses = list(range(5))  # 地址0-4
    
    results = []
    
    for baud in baudrates:
        print(f"\n波特率: {baud}")
        for addr in addresses:
            addr_byte = 0x80 + addr
            checksum = (0x52 + addr) & 0xFF
            cmd = bytes([addr_byte, addr_byte, 0x52, 0x00, 0x00, 0x00, 
                        checksum, 0x00])
            
            try:
                ser = serial.Serial(
                    port=port,
                    baudrate=baud,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.3
                )
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                ser.write(cmd)
                time.sleep(0.1)
                response = ser.read(100)
                ser.close()
                
                if response and len(response) >= 8:
                    print(f"  地址{addr}: [OK] 收到{len(response)}字节 - {response[:10].hex().upper()}")
                    results.append({
                        'baudrate': baud,
                        'address': addr,
                        'response': response
                    })
                else:
                    print(f"  地址{addr}: 无响应")
                    
            except Exception as e:
                print(f"  地址{addr}: 错误 - {e}")
    
    return results


def test_with_params(port, baudrate, address):
    """使用指定参数测试"""
    print("\n" + "="*60)
    print(f"测试参数: {port} @ {baudrate}, 地址={address}")
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
        print("[OK] 串口打开成功")
        
        addr_byte = 0x80 + address
        checksum = (0x52 + address) & 0xFF
        cmd = bytes([addr_byte, addr_byte, 0x52, 0x00, 0x00, 0x00, 
                    checksum, 0x00])
        
        print(f"发送指令: {cmd.hex().upper()}")
        
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(cmd)
        
        print("等待响应...")
        time.sleep(0.2)
        
        response = ser.read(100)
        print(f"收到: {len(response)} 字节")
        
        if response:
            print(f"数据: {response.hex().upper()}")
            
            if len(response) == 10:
                pv = (response[0] << 8) | response[1]
                sv = (response[2] << 8) | response[3]
                mv = response[4]
                alarm = response[5]
                
                print(f"\n解析结果:")
                print(f"  PV(测量值): {pv/10:.1f} C")
                print(f"  SV(设定值): {sv/10:.1f} C")
                print(f"  MV(输出值): {mv} %")
                print(f"  报警状态: {alarm:02X}")
                print("\n[OK] 通信成功!")
                return True
            else:
                print(f"[!] 响应长度不正确: {len(response)}字节")
        else:
            print("[X] 无响应")
        
        ser.close()
        return False
        
    except Exception as e:
        print(f"[X] 错误: {e}")
        return False


def test_different_formats(port, baudrate=9600):
    """测试不同的数据格式"""
    print("\n" + "="*60)
    print(f"测试不同数据格式: {port} @ {baudrate}")
    print("="*60)
    
    formats = [
        ('8N1', serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE),
        ('8E1', serial.EIGHTBITS, serial.PARITY_EVEN, serial.STOPBITS_ONE),
        ('8O1', serial.EIGHTBITS, serial.PARITY_ODD, serial.STOPBITS_ONE),
        ('7E1', serial.SEVENBITS, serial.PARITY_EVEN, serial.STOPBITS_ONE),
    ]
    
    cmd = bytes([0x80, 0x80, 0x52, 0x00, 0x00, 0x00, 0x52, 0x00])
    
    for name, databits, parity, stopbits in formats:
        print(f"\n格式: {name}")
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=databits,
                parity=parity,
                stopbits=stopbits,
                timeout=0.3
            )
            ser.reset_input_buffer()
            ser.write(cmd)
            time.sleep(0.1)
            response = ser.read(100)
            ser.close()
            
            if response:
                print(f"  [OK] 收到 {len(response)} 字节: {response[:10].hex().upper()}")
            else:
                print(f"  [ ] 无响应")
        except Exception as e:
            print(f"  [X] 错误: {e}")


def main():
    print("="*60)
    print("TTL串口诊断工具")
    print("="*60)
    
    print("""
接线检查:
  CH340 TX  → 仪表 RX
  CH340 RX  → 仪表 TX
  CH340 GND → 仪表 GND
  
  注意: TX和RX要交叉连接!
""")
    
    # 列出串口
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("未找到串口!")
        return
    
    print("可用串口:")
    for p in ports:
        print(f"  {p.device} - {p.description}")
    
    # 选择串口
    if len(ports) == 1:
        port = ports[0].device
    else:
        port = input("\n请输入串口号 (默认COM3): ").strip() or "COM3"
    
    print(f"\n选择测试模式:")
    print("1. 快速扫描 (测试所有波特率和地址)")
    print("2. 指定参数测试")
    print("3. 测试不同数据格式")
    
    mode = input("请选择 (默认1): ").strip() or "1"
    
    if mode == "1":
        results = scan_all_params(port)
        if results:
            print("\n" + "="*60)
            print("找到有效参数:")
            for r in results:
                print(f"  波特率={r['baudrate']}, 地址={r['address']}")
        else:
            print("\n未找到有效响应，请检查:")
            print("  1. 接线是否正确 (TX接RX, RX接TX)")
            print("  2. 仪表是否上电")
            print("  3. 仪表是否支持AIBUS协议")
            
    elif mode == "2":
        baud = int(input("波特率 (默认9600): ").strip() or "9600")
        addr = int(input("仪表地址 (默认0): ").strip() or "0")
        test_with_params(port, baud, addr)
        
    elif mode == "3":
        baud = int(input("波特率 (默认9600): ").strip() or "9600")
        test_different_formats(port, baud)


if __name__ == "__main__":
    main()
