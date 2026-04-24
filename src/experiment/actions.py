from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional


class ActionType(Enum):
    """步骤动作类型"""
    HEATER_SET_TEMP = "heater.set_temperature"
    HEATER_START = "heater.start"
    HEATER_STOP = "heater.stop"
    PUMP_START = "pump.start"
    PUMP_STOP = "pump.stop"
    PUMP_STOP_CHANNEL = "pump.stop_channel"
    WAIT = "wait"
    EMERGENCY_STOP = "emergency_stop"
    LOG = "log"


class WaitType(Enum):
    """等待条件类型"""
    NONE = "none"
    DURATION = "duration"
    TEMPERATURE_REACHED = "temperature_reached"
    PUMP_COMPLETE = "pump_complete"


@dataclass
class WaitCondition:
    """等待条件

    Attributes:
        type: 等待类型
        seconds: 等待秒数（DURATION类型使用）
        device_id: 设备ID（TEMPERATURE_REACHED/PUMP_COMPLETE使用）
        tolerance: 温度容差（TEMPERATURE_REACHED使用）
        timeout: 超时秒数
        channel: 泵通道号（PUMP_COMPLETE使用）
    """
    type: WaitType = WaitType.NONE
    seconds: float = 0
    device_id: str = ""
    tolerance: float = 1.0
    timeout: float = 3600
    channel: int = 0


@dataclass
class ExperimentStep:
    """实验步骤

    Attributes:
        id: 步骤唯一标识
        type: 动作类型
        params: 动作参数
        wait: 等待条件
        enabled: 是否启用
        on_error: 错误处理策略 (stop/skip/continue)
    """
    id: str
    type: ActionType
    params: dict = field(default_factory=dict)
    wait: WaitCondition = field(default_factory=WaitCondition)
    enabled: bool = True
    on_error: str = "stop"
