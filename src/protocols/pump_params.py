"""
蠕动泵参数定义模块

基于《多通道蠕动泵MODBUS通信协议》定义的寄存器地址和参数。
支持LabSmart系列多通道独立控制蠕动泵。
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Optional, List


@dataclass
class RegisterDefinition:
    """寄存器定义数据类"""
    address: int
    name: str
    description: str
    data_type: str
    min_value: float = 0
    max_value: float = 65535
    unit: str = ""
    read_only: bool = False


class PumpRunMode(IntEnum):
    """运行模式枚举"""
    FLOW_MODE = 0
    TIME_QUANTITY = 1
    TIME_SPEED = 2
    QUANTITY_SPEED = 3
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "流量模式",
            1: "定时定量",
            2: "定时定速",
            3: "定量定速",
        }
        return descriptions.get(value, f"未知模式({value})")


class PumpRunStatus(IntEnum):
    """启停控制枚举"""
    STOP = 0
    START = 1
    PAUSE = 2
    FULL_SPEED = 3
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "停止",
            1: "启动",
            2: "暂停",
            3: "全速",
        }
        return descriptions.get(value, f"未知状态({value})")


class PumpDirection(IntEnum):
    """方向控制枚举"""
    CLOCKWISE = 0
    COUNTER_CLOCKWISE = 1
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "顺时针",
            1: "逆时针",
        }
        return descriptions.get(value, f"未知方向({value})")


class TimeUnit(IntEnum):
    """时间单位枚举"""
    SECOND = 0
    MINUTE = 1
    HOUR = 2
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "秒(sec)",
            1: "分(min)",
            2: "时(hour)",
        }
        return descriptions.get(value, f"未知单位({value})")


class FlowUnit(IntEnum):
    """流速单位枚举"""
    ML_MIN = 0
    RPM = 1
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "mL/min",
            1: "RPM",
        }
        return descriptions.get(value, f"未知单位({value})")


PUMP_HEAD_MODELS = {
    5: "AMC_(10)",
}

PUMP_TUBE_MODELS = {
    0: "1*1",
    1: "2*1",
    2: "2.4*0.86",
    3: "3*1",
    4: "0.13*0.86",
    5: "0.19*0.86",
    6: "0.25*0.86",
    7: "0.51*0.86",
    8: "0.89*0.86",
    9: "1.14*0.86",
    10: "1.42*0.86",
    11: "1.52*0.86",
    12: "2.06*0.86",
    13: "2.79*0.86",
}


def get_channel_address(base_address: int, channel: int) -> int:
    """
    获取通道寄存器地址
    
    寄存器地址格式为 nXXX，其中 n 为通道号(1-4)
    
    Args:
        base_address: 基地址（如 001, 002, 100 等）
        channel: 通道号(1-4)
    
    Returns:
        int: 实际寄存器地址
    """
    return channel * 1000 + base_address


CONTROL_REGISTERS: Dict[int, RegisterDefinition] = {
    10: RegisterDefinition(
        address=10,
        name="ALL_START",
        description="所有有效单元全部启动",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
}

CHANNEL_CONTROL_REGISTERS: Dict[int, RegisterDefinition] = {
    0: RegisterDefinition(
        address=0,
        name="ENABLE",
        description="单元使能",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    1: RegisterDefinition(
        address=1,
        name="RUN_STATUS",
        description="启停控制",
        data_type="uint16",
        min_value=0, max_value=3,
    ),
    2: RegisterDefinition(
        address=2,
        name="DIRECTION",
        description="方向控制",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    3: RegisterDefinition(
        address=3,
        name="PUMP_HEAD",
        description="泵头型号",
        data_type="uint16",
        min_value=0, max_value=255,
    ),
    4: RegisterDefinition(
        address=4,
        name="TUBE_MODEL",
        description="软管型号",
        data_type="uint16",
        min_value=0, max_value=255,
    ),
    5: RegisterDefinition(
        address=5,
        name="SUCK_BACK",
        description="回吸角度",
        data_type="uint16",
        min_value=0, max_value=360,
        unit="度",
    ),
    6: RegisterDefinition(
        address=6,
        name="RUN_MODE",
        description="运行模式",
        data_type="uint16",
        min_value=0, max_value=3,
    ),
}

PARAMETER_REGISTERS: Dict[int, RegisterDefinition] = {
    100: RegisterDefinition(
        address=100,
        name="REPEAT_COUNT",
        description="重复次数",
        data_type="uint16",
        min_value=0, max_value=9999,
    ),
    101: RegisterDefinition(
        address=101,
        name="INTERVAL_TIME",
        description="间隔时间",
        data_type="float",
        min_value=0.1, max_value=999,
    ),
    103: RegisterDefinition(
        address=103,
        name="INTERVAL_UNIT",
        description="间隔时间单位",
        data_type="uint16",
        min_value=0, max_value=2,
    ),
    104: RegisterDefinition(
        address=104,
        name="DISPENSE_VOLUME",
        description="分装液量",
        data_type="float",
        min_value=0.01, max_value=9999,
        unit="mL",
    ),
    106: RegisterDefinition(
        address=106,
        name="DISPENSE_UNIT",
        description="分装液量单位",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    107: RegisterDefinition(
        address=107,
        name="RUN_TIME",
        description="运行时间",
        data_type="float",
        min_value=0.1, max_value=999,
    ),
    109: RegisterDefinition(
        address=109,
        name="RUN_TIME_UNIT",
        description="运行时间单位",
        data_type="uint16",
        min_value=0, max_value=2,
    ),
    110: RegisterDefinition(
        address=110,
        name="FLOW_RATE",
        description="流速设置",
        data_type="float",
        min_value=0.1, max_value=999,
    ),
    112: RegisterDefinition(
        address=112,
        name="FLOW_UNIT",
        description="流速单位",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    113: RegisterDefinition(
        address=113,
        name="TOTAL_VOLUME",
        description="总液量",
        data_type="float",
        min_value=0.01, max_value=9999,
        unit="mL",
    ),
}

STATUS_REGISTERS: Dict[int, RegisterDefinition] = {
    300: RegisterDefinition(
        address=300,
        name="STATUS_ENABLE",
        description="单元使能状态",
        data_type="uint16",
        read_only=True,
    ),
    301: RegisterDefinition(
        address=301,
        name="STATUS_RUN",
        description="运行状态",
        data_type="uint16",
        read_only=True,
    ),
    302: RegisterDefinition(
        address=302,
        name="STATUS_DIRECTION",
        description="方向状态",
        data_type="uint16",
        read_only=True,
    ),
    303: RegisterDefinition(
        address=303,
        name="STATUS_MODE",
        description="运行模式状态",
        data_type="uint16",
        read_only=True,
    ),
    304: RegisterDefinition(
        address=304,
        name="STATUS_REMAIN_TIME",
        description="剩余时间",
        data_type="float",
        read_only=True,
    ),
    306: RegisterDefinition(
        address=306,
        name="STATUS_REMAIN_VOLUME",
        description="剩余液量",
        data_type="float",
        read_only=True,
    ),
    308: RegisterDefinition(
        address=308,
        name="STATUS_CURRENT_FLOW",
        description="当前流速",
        data_type="float",
        read_only=True,
    ),
    310: RegisterDefinition(
        address=310,
        name="STATUS_CURRENT_SPEED",
        description="当前转速",
        data_type="float",
        read_only=True,
    ),
    312: RegisterDefinition(
        address=312,
        name="STATUS_DISPENSED_VOLUME",
        description="已分装液量",
        data_type="float",
        read_only=True,
    ),
    314: RegisterDefinition(
        address=314,
        name="STATUS_REPEAT_COUNT",
        description="已分装次数",
        data_type="uint16",
        read_only=True,
    ),
}

CALIBRATION_REGISTERS: Dict[int, RegisterDefinition] = {
    200: RegisterDefinition(
        address=200,
        name="CALIB_TEST_TIME",
        description="测试时间",
        data_type="float",
        min_value=0.5, max_value=9999,
        unit="s",
    ),
    202: RegisterDefinition(
        address=202,
        name="CALIB_TEST_START",
        description="测试开始",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    203: RegisterDefinition(
        address=203,
        name="CALIB_ACTUAL_VOLUME",
        description="实际灌装量",
        data_type="float",
        min_value=0, max_value=9999,
        unit="mL",
    ),
    205: RegisterDefinition(
        address=205,
        name="CALIB_RESET",
        description="恢复校准",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
    206: RegisterDefinition(
        address=206,
        name="CALIB_FINE_TUNE",
        description="微调液量",
        data_type="uint16",
        min_value=0, max_value=1,
    ),
}


def get_register_info(address: int) -> Optional[RegisterDefinition]:
    """
    获取寄存器定义信息
    
    Args:
        address: 寄存器地址
    
    Returns:
        RegisterDefinition: 寄存器定义，如果不存在返回None
    """
    channel = address // 1000
    base_address = address % 1000
    
    if base_address == 10:
        return CONTROL_REGISTERS.get(10)
    
    if base_address in CHANNEL_CONTROL_REGISTERS:
        return CHANNEL_CONTROL_REGISTERS[base_address]
    if base_address in PARAMETER_REGISTERS:
        return PARAMETER_REGISTERS[base_address]
    if base_address in STATUS_REGISTERS:
        return STATUS_REGISTERS[base_address]
    if base_address in CALIBRATION_REGISTERS:
        return CALIBRATION_REGISTERS[base_address]
    
    return None


def get_all_channel_registers(channel: int) -> Dict[int, RegisterDefinition]:
    """
    获取指定通道的所有寄存器定义
    
    Args:
        channel: 通道号(1-4)
    
    Returns:
        Dict[int, RegisterDefinition]: 寄存器定义字典
    """
    registers = {}
    
    for base_addr, reg_def in CHANNEL_CONTROL_REGISTERS.items():
        addr = get_channel_address(base_addr, channel)
        registers[addr] = RegisterDefinition(
            address=addr,
            name=reg_def.name,
            description=reg_def.description,
            data_type=reg_def.data_type,
            min_value=reg_def.min_value,
            max_value=reg_def.max_value,
            unit=reg_def.unit,
            read_only=reg_def.read_only,
        )
    
    for base_addr, reg_def in PARAMETER_REGISTERS.items():
        addr = get_channel_address(base_addr, channel)
        registers[addr] = RegisterDefinition(
            address=addr,
            name=reg_def.name,
            description=reg_def.description,
            data_type=reg_def.data_type,
            min_value=reg_def.min_value,
            max_value=reg_def.max_value,
            unit=reg_def.unit,
            read_only=reg_def.read_only,
        )
    
    for base_addr, reg_def in STATUS_REGISTERS.items():
        addr = get_channel_address(base_addr, channel)
        registers[addr] = RegisterDefinition(
            address=addr,
            name=reg_def.name,
            description=reg_def.description,
            data_type=reg_def.data_type,
            min_value=reg_def.min_value,
            max_value=reg_def.max_value,
            unit=reg_def.unit,
            read_only=reg_def.read_only,
        )
    
    return registers
