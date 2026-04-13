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
]
