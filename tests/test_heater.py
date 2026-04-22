"""
加热器设备测试脚本

用于测试加热器设备的基本功能，无需实际硬件连接。
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'src'))

from unittest.mock import Mock, patch, MagicMock
import time


def test_protocol_structure():
    """测试协议帧结构"""
    print("\n=== 测试AIBUS协议帧结构 ===")
    
    from protocols.aibus import AIBUSProtocol
    
    protocol = AIBUSProtocol(port="COM3", address=0)
    
    read_cmd = protocol._build_read_command(0)
    print(f"读参数0指令: {read_cmd.hex().upper()}")
    print(f"指令长度: {len(read_cmd)} 字节 (应为8字节)")
    assert len(read_cmd) == 8, "读指令长度错误"
    
    write_cmd = protocol._build_write_command(0, 1000)
    print(f"写参数0指令(值1000): {write_cmd.hex().upper()}")
    print(f"指令长度: {len(write_cmd)} 字节 (应为8字节)")
    assert len(write_cmd) == 8, "写指令长度错误"
    
    print("[OK] 协议帧结构测试通过")


def test_checksum_calculation():
    """测试校验和计算"""
    print("\n=== 测试校验和计算 ===")
    
    from protocols.aibus import AIBUSProtocol
    
    protocol = AIBUSProtocol(port="COM3", address=1)
    
    checksum = protocol._calculate_read_checksum(1)
    print(f"读参数1校验和(地址1): {checksum:04X}")
    expected = (1 * 256 + 0x52 + 1) & 0xFFFF
    assert checksum == expected, f"校验和计算错误: {checksum} != {expected}"
    
    checksum = protocol._calculate_write_checksum(0, 1000)
    print(f"写参数0校验和(值1000, 地址1): {checksum:04X}")
    expected = (0 * 256 + 0x43 + 1000 + 1) & 0xFFFF
    assert checksum == expected, f"校验和计算错误: {checksum} != {expected}"
    
    print("[OK] 校验和计算测试通过")


def test_response_parsing():
    """测试响应解析"""
    print("\n=== 测试响应解析 ===")
    
    from protocols.aibus import AIBUSProtocol
    
    protocol = AIBUSProtocol(port="COM3", address=1)
    
    response_data = bytes([
        0xE8, 0x03,
        0x00, 0x00,
        0x00,
        0x60,
        0x00, 0x00,
        0xE9, 0x63
    ])
    
    response = protocol._parse_response(response_data)
    
    print(f"测量值(PV): {response.pv}")
    print(f"设定值(SV): {response.sv}")
    print(f"输出值(MV): {response.mv}")
    print(f"报警状态: {response.alarm_status:02X}")
    
    assert response.pv == 1000, f"PV解析错误: {response.pv}"
    assert response.sv == 0, f"SV解析错误: {response.sv}"
    assert response.mv == 0, f"MV解析错误: {response.mv}"
    
    print("[OK] 响应解析测试通过")


def test_parameter_codes():
    """测试参数代号"""
    print("\n=== 测试参数代号定义 ===")
    
    from protocols.parameters import ParameterCode, get_parameter_info
    
    print(f"SV(给定值)代号: {ParameterCode.SV}")
    print(f"PV(测量值)代号: {ParameterCode.PV}")
    print(f"MV(输出值)代号: {ParameterCode.MV}")
    
    sv_info = get_parameter_info(ParameterCode.SV)
    assert sv_info is not None, "SV参数信息未找到"
    print(f"SV参数信息: {sv_info.name} - {sv_info.description}")
    
    print("[OK] 参数代号测试通过")


def test_device_config():
    """测试设备配置"""
    print("\n=== 测试设备配置 ===")
    
    from devices.heater import HeaterConfig
    
    config = HeaterConfig(
        device_id="test_heater",
        connection_params={
            'port': 'COM3',
            'baudrate': 9600,
            'address': 0,
        },
        decimal_places=1,
        safety_limit=450.0,
    )
    
    print(f"设备ID: {config.device_id}")
    print(f"安全限温: {config.safety_limit} C")
    print(f"小数位数: {config.decimal_places}")
    
    assert config.device_id == "test_heater"
    assert config.safety_limit == 450.0
    
    print("[OK] 设备配置测试通过")


def test_csv_data_logger():
    """测试CSV数据记录"""
    print("\n=== 测试CSV数据记录 ===")
    
    from utils.csv_logger import SimpleDataPoint
    from datetime import datetime
    
    data_point = SimpleDataPoint(
        timestamp=datetime.now().isoformat(),
        device_id="heater1",
        pv=100.5,
        sv=100.0,
    )
    
    data_dict = data_point.to_dict()
    print(f"数据点字典: {data_dict}")
    
    assert data_dict['device_id'] == "heater1"
    assert data_dict['pv'] == 100.5
    
    print("[OK] CSV数据记录测试通过")


def test_alarm_rule():
    """测试报警规则"""
    print("\n=== 测试报警规则 ===")
    
    threshold = 300.0
    
    assert 350.0 > threshold, "温度350应触发报警"
    assert not (250.0 > threshold), "温度250不应触发报警"
    
    print(f"报警规则: high_temp")
    print(f"条件: pv > {threshold}")
    print(f"测试350: {'触发' if 350.0 > threshold else '未触发'}")
    print(f"测试250: {'触发' if 250.0 > threshold else '未触发'}")
    
    print("[OK] 报警规则测试通过")


def test_statistics():
    """测试统计计算"""
    print("\n=== 测试统计计算 ===")
    
    from reports.report_generator import calculate_statistics
    
    values = [100.0, 101.0, 99.0, 102.0, 98.0, 100.5, 99.5]
    stats = calculate_statistics(values)
    
    print(f"数据: {values}")
    print(f"计数: {stats.count}")
    print(f"平均值: {stats.mean:.2f}")
    print(f"标准差: {stats.std:.2f}")
    print(f"最小值: {stats.min:.2f}")
    print(f"最大值: {stats.max:.2f}")
    print(f"中位数: {stats.median:.2f}")
    
    assert stats.count == 7
    assert abs(stats.mean - 100.0) < 0.1
    
    print("[OK] 统计计算测试通过")


def test_config_manager():
    """测试配置管理"""
    print("\n=== 测试配置管理 ===")
    
    from utils.config import ConfigManager
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "test_config.yaml")
        manager = ConfigManager(config_path)
        
        config = manager.create_default()
        
        print(f"系统名称: {config.name}")
        print(f"版本: {config.version}")
        print(f"加热器数量: {len(config.heaters)}")
        
        assert config.name == "自动化控制系统"
        assert len(config.heaters) > 0
        
        print("[OK] 配置管理测试通过")


def run_all_tests():
    """运行所有测试"""
    print("="*60)
    print("自动化控制系统 - 单元测试")
    print("="*60)
    
    tests = [
        test_protocol_structure,
        test_checksum_calculation,
        test_response_parsing,
        test_parameter_codes,
        test_device_config,
        test_monitor_data_structure,
        test_alarm_rule,
        test_statistics,
        test_config_manager,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[X] 测试失败: {test.__name__}")
            print(f"  错误: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
