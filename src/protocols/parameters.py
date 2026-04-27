"""
宇电AI系列仪表参数代号定义

基于《宇电单回路测量控制仪表通讯协议说明》V9.3版本
参数代号表包含所有可读写的参数定义。
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Optional


@dataclass
class ParameterDefinition:
    """参数定义数据类"""
    code: int
    name: str
    description: str
    unit: str = ""
    decimal_places: int = 0
    min_value: float = -32768
    max_value: float = 32767
    read_only: bool = False


class ParameterCode(IntEnum):
    """
    参数代号枚举
    
    10进制代号、16进制代号、MODBUS寄存器号是同一个参数的不同写法。
    """
    
    SV = 0
    HIAL = 1
    LOAL = 2
    DHAL = 3
    DLAL = 4
    AHYS = 5
    CTR_L = 6
    HB = 7
    D_P = 8
    OPL = 9
    OPH = 10
    CR_L = 11
    CR_H = 12
    ADDR = 23
    FILT = 24
    AMAN = 25
    MV = 26
    SRUN = 27
    CHYS = 28
    AT = 29
    SPL = 30
    SPH = 31
    FRU = 32
    OEF = 33
    ACT = 34
    ADIS = 35
    AUT = 36
    P2 = 37
    I2 = 38
    D2 = 39
    CTI2 = 40
    ET = 41
    SPR = 42
    PNO = 43
    PON = 44
    PAF = 45
    STEP = 46
    RUN_TIME = 47
    EVENT_OUTPUT = 48
    OPRT = 49
    STRT = 50
    SPSL = 51
    SPSH = 52
    ERO = 53
    AF2 = 54
    NONC = 55
    SPRL = 56
    EFP1 = 57
    EFP2 = 58
    EFP3 = 59
    EFP4 = 60
    NONC_8 = 61
    EAF = 62
    PRN = 63
    EP1 = 64
    EP2 = 65
    EP3 = 66
    EP4 = 67
    EP5 = 68
    EP6 = 69
    EP7 = 70
    EP8 = 71
    L5 = 72
    SUB_PV = 73
    PV = 74
    PV_HIGH = 75
    SV_READ = 76
    MV_ALARM = 77
    OUTPUT_STATUS = 78
    ROOM_TEMP = 79
    MODEL_CODE = 21

    SP1 = 80
    T1 = 81
    SP2 = 82
    T2 = 83
    SP3 = 84
    T3 = 85
    SP4 = 86
    T4 = 87
    SP5 = 88
    T5 = 89
    SP6 = 90
    T6 = 91
    SP7 = 92
    T7 = 93
    SP8 = 94
    T8 = 95
    SP9 = 96
    T9 = 97
    SP10 = 98
    T10 = 99


PARAMETER_DEFINITIONS: Dict[int, ParameterDefinition] = {
    ParameterCode.SV: ParameterDefinition(
        code=0, name="SV", description="给定值(设定值)", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.HIAL: ParameterDefinition(
        code=1, name="HIAL", description="上限报警值", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.LOAL: ParameterDefinition(
        code=2, name="LoAL", description="下限报警值", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.DHAL: ParameterDefinition(
        code=3, name="dHAL", description="偏差上限报警值", 
        decimal_places=1, min_value=0, max_value=9999
    ),
    ParameterCode.DLAL: ParameterDefinition(
        code=4, name="dLAL", description="偏差下限报警值", 
        decimal_places=1, min_value=0, max_value=9999
    ),
    ParameterCode.AHYS: ParameterDefinition(
        code=5, name="AHYS", description="报警回差", 
        decimal_places=1, min_value=0, max_value=999.9
    ),
    ParameterCode.CTR_L: ParameterDefinition(
        code=6, name="CtrL", description="控制方式",
        decimal_places=0, min_value=0, max_value=4
    ),
    ParameterCode.HB: ParameterDefinition(
        code=7, name="Hb", description="滞后补偿", 
        decimal_places=0, min_value=0, max_value=100
    ),
    ParameterCode.D_P: ParameterDefinition(
        code=8, name="dPt", description="小数点位置",
        decimal_places=0, min_value=0, max_value=3
    ),
    ParameterCode.OPL: ParameterDefinition(
        code=9, name="oPL", description="输出下限", 
        decimal_places=0, min_value=0, max_value=110
    ),
    ParameterCode.OPH: ParameterDefinition(
        code=10, name="oPH", description="输出上限", 
        decimal_places=0, min_value=0, max_value=110
    ),
    ParameterCode.CR_L: ParameterDefinition(
        code=11, name="CrL", description="冷端补偿下限", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.CR_H: ParameterDefinition(
        code=12, name="CrH", description="冷端补偿上限", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.ADDR: ParameterDefinition(
        code=23, name="Addr", description="通讯地址",
        decimal_places=0, min_value=0, max_value=80
    ),
    ParameterCode.FILT: ParameterDefinition(
        code=24, name="FILt", description="数字滤波",
        decimal_places=0, min_value=0, max_value=20
    ),
    ParameterCode.AMAN: ParameterDefinition(
        code=25, name="AMAn", description="手动/自动选择",
        decimal_places=0, min_value=0, max_value=3
    ),
    ParameterCode.MV: ParameterDefinition(
        code=26, name="MV", description="手动输出值",
        decimal_places=0, min_value=0, max_value=100
    ),
    ParameterCode.SRUN: ParameterDefinition(
        code=27, name="Srun", description="运行/停止/保持",
        decimal_places=0, min_value=0, max_value=2
    ),
    ParameterCode.CHYS: ParameterDefinition(
        code=28, name="CHYS", description="控制回差", 
        decimal_places=1, min_value=0, max_value=999.9
    ),
    ParameterCode.AT: ParameterDefinition(
        code=29, name="At", description="自整定选择",
        decimal_places=0, min_value=0, max_value=3
    ),
    ParameterCode.SPL: ParameterDefinition(
        code=30, name="SPL", description="给定值下限", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.SPH: ParameterDefinition(
        code=31, name="SPH", description="给定值上限", 
        decimal_places=1, min_value=-999, max_value=9999
    ),
    ParameterCode.MODEL_CODE: ParameterDefinition(
        code=21, name="Model", description="仪表型号特征字",
        decimal_places=0, read_only=True
    ),
    ParameterCode.PV: ParameterDefinition(
        code=74, name="PV", description="测量值(只读)", 
        decimal_places=1, read_only=True
    ),
    ParameterCode.SV_READ: ParameterDefinition(
        code=76, name="SV", description="实时给定值(只读)", 
        decimal_places=1, read_only=True
    ),
    ParameterCode.MV_ALARM: ParameterDefinition(
        code=77, name="MV+Alarm", description="输出值+报警状态",
        decimal_places=0, read_only=True
    ),
    ParameterCode.OUTPUT_STATUS: ParameterDefinition(
        code=78, name="Status", description="输出端口状态+工作状态",
        decimal_places=0, read_only=True
    ),
    ParameterCode.ROOM_TEMP: ParameterDefinition(
        code=79, name="RoomTemp", description="室温补偿(只读)", 
        decimal_places=1, read_only=True
    ),
}


class ControlMode(IntEnum):
    """控制方式枚举"""
    ON_OFF = 0
    APID = 1
    NPID = 2
    POP = 3
    SOP = 4
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "位式控制(ON/OFF)",
            1: "AI人工智能调节(APID)",
            2: "带模糊控制的AI调节(nPID)",
            3: "加热/冷却双输出(PoP)",
            4: "加热/冷却双输出",
        }
        return descriptions.get(value, f"未知模式({value})")


class RunStatus(IntEnum):
    """运行状态枚举"""
    RUN = 0
    STOP = 1
    HOLD = 2
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "运行",
            1: "停止",
            2: "保持",
        }
        return descriptions.get(value, f"未知状态({value})")


class AutoTuneMode(IntEnum):
    """自整定模式枚举"""
    OFF = 0
    ON = 1
    FOFF = 2
    AAT = 3
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "关闭(OFF)",
            1: "开启(ON)",
            2: "模糊控制关闭",
            3: "高级自整定",
        }
        return descriptions.get(value, f"未知模式({value})")


class ManualAutoMode(IntEnum):
    """手动/自动模式枚举"""
    MAN = 0
    AUTO = 1
    FSV = 2
    FAUT = 3
    
    @classmethod
    def get_description(cls, value: int) -> str:
        descriptions = {
            0: "手动(MAN)",
            1: "自动(Auto)",
            2: "外给定(FSV)",
            3: "外给定自动",
        }
        return descriptions.get(value, f"未知模式({value})")


MODEL_CODES = {
    0x8080: "AI-8X8系列人工智能调节器/温控器",
    0x8090: "AI-8X9系列串级型人工智能调节器/温控器",
    0x6080: "AI-8X6系列人工智能调节器/温控器",
    0x5010: "AI-500/AI-501单回路通用型测量仪表",
    0x5160: "AI-516智能温控器",
    0x5167: "AI-516P程序型智能温控器",
    0x5260: "AI-526智能温控器",
    0x5267: "AI-526P程序型智能温控器",
    0x5180: "AI-518智能温控器",
    0x5187: "AI-518P程序型智能温控器",
    0x7010: "AI-700/AI-701单回路通用型测量仪表",
    0x7160: "AI-716高精度智能温控器",
    0x7167: "AI-716P高精度程序型智能温控器",
    0x7190: "AI-719高精度智能温控器/调节器",
    0x7197: "AI-719P高精度程序型智能温控器/调节器",
    0x9980: "AI-998高性能多功能人工智能工业调节器",
}


def get_parameter_info(code: int) -> Optional[ParameterDefinition]:
    """
    获取参数定义信息
    
    Args:
        code: 参数代号
    
    Returns:
        ParameterDefinition: 参数定义，如果不存在返回None
    """
    return PARAMETER_DEFINITIONS.get(code)


def get_model_name(model_code: int) -> str:
    """
    根据型号特征字获取仪表型号名称
    
    Args:
        model_code: 型号特征字
    
    Returns:
        str: 型号名称
    """
    return MODEL_CODES.get(model_code, f"未知型号(特征字: 0x{model_code:04X})")
