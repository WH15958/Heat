"""
协议模块

包含各种设备通信协议的实现。
"""

from .aibus import AIBUSProtocol, AIBUSResponse, AIBUSCommand, AlarmStatus
from .parameters import (
    ParameterCode,
    ParameterDefinition,
    ControlMode,
    RunStatus,
    AutoTuneMode,
    ManualAutoMode,
    MODEL_CODES,
    PARAMETER_DEFINITIONS,
    get_parameter_info,
    get_model_name,
)
from .modbus_rtu import (
    ModbusRTUProtocol,
    ModbusFunction,
    ModbusException,
    ModbusResponse,
)
from .pump_params import (
    PumpRunMode,
    PumpRunStatus,
    PumpDirection,
    TimeUnit,
    FlowUnit,
    RegisterDefinition,
    get_channel_address,
    get_register_info,
    get_all_channel_registers,
    CHANNEL_CONTROL_REGISTERS,
    PARAMETER_REGISTERS,
    CALIBRATION_REGISTERS,
    PUMP_HEAD_MODELS,
    PUMP_TUBE_MODELS,
)

__all__ = [
    'AIBUSProtocol',
    'AIBUSResponse', 
    'AIBUSCommand',
    'AlarmStatus',
    'ParameterCode',
    'ParameterDefinition',
    'ControlMode',
    'RunStatus',
    'AutoTuneMode',
    'ManualAutoMode',
    'MODEL_CODES',
    'PARAMETER_DEFINITIONS',
    'get_parameter_info',
    'get_model_name',
    'ModbusRTUProtocol',
    'ModbusFunction',
    'ModbusException',
    'ModbusResponse',
    'PumpRunMode',
    'PumpRunStatus',
    'PumpDirection',
    'TimeUnit',
    'FlowUnit',
    'RegisterDefinition',
    'get_channel_address',
    'get_register_info',
    'get_all_channel_registers',
    'CHANNEL_CONTROL_REGISTERS',
    'PARAMETER_REGISTERS',
    'CALIBRATION_REGISTERS',
    'PUMP_HEAD_MODELS',
    'PUMP_TUBE_MODELS',
]
