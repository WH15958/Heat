from enum import Enum
import math
from dataclasses import dataclass, field
from typing import Any, Optional


class ActionType(Enum):
    """步骤动作类型"""
    HEATER_SET_TEMP = "heater.set_temperature"
    HEATER_START = "heater.start"
    HEATER_STOP = "heater.stop"
    MICROWAVE_CONFIGURE_MANUAL = "microwave.configure_manual"
    MICROWAVE_CONFIGURE_AUTO_POWER = "microwave.configure_auto_power"
    MICROWAVE_CONFIGURE_CONSTANT_RATE = "microwave.configure_constant_rate"
    MICROWAVE_START = "microwave.start"
    MICROWAVE_STOP = "microwave.stop"
    PUMP_START = "pump.start"
    PUMP_STOP = "pump.stop"
    PUMP_STOP_CHANNEL = "pump.stop_channel"
    SYRINGE_INITIALIZE = "syringe_pump.initialize"
    SYRINGE_CONFIGURE = "syringe_pump.configure"
    SYRINGE_MOVE = "syringe_pump.move"
    SYRINGE_ASPIRATE = "syringe_pump.aspirate"
    SYRINGE_DISPENSE = "syringe_pump.dispense"
    SYRINGE_VALVE = "syringe_pump.valve"
    SYRINGE_STOP = "syringe_pump.stop"
    SYRINGE_PAUSE = "syringe_pump.pause"
    SYRINGE_RESUME = "syringe_pump.resume"
    SYRINGE_IO = "syringe_pump.io"
    SYRINGE_PROGRAM_LOAD = "syringe_pump.program_load"
    SYRINGE_PROGRAM_STORE = "syringe_pump.program_store"
    SYRINGE_PROGRAM_RUN = "syringe_pump.program_run"
    SYRINGE_REPEAT = "syringe_pump.repeat"
    VALVE_SWITCH = "valve.switch"
    SYRINGE_PAIR_DISPENSE = "syringe_pair.dispense"
    WAIT = "wait"
    EMERGENCY_STOP = "emergency_stop"
    LOG = "log"


class WaitType(Enum):
    """等待条件类型"""
    NONE = "none"
    DURATION = "duration"
    TEMPERATURE_REACHED = "temperature_reached"
    HEATER_PAIR_REACHED = "heater_pair_reached"
    HEATER_PAIR_STABLE = "heater_pair_stable"
    MICROWAVE_TEMPERATURE_REACHED = "microwave_temperature_reached"
    MICROWAVE_TEMPERATURE_BELOW = "microwave_temperature_below"
    MICROWAVE_COMPLETE = "microwave_complete"
    MICROWAVE_MONITORED_HOLD = "microwave_monitored_hold"
    PUMP_COMPLETE = "pump_complete"
    SYRINGE_PUMP_COMPLETE = "syringe_pump_complete"


@dataclass
class WaitCondition:
    """等待条件

    Attributes:
        type: 等待类型
        seconds: 等待秒数，微波到温等待时表示连续稳定时长（默认0）
        device_id: 设备ID（TEMPERATURE_REACHED/PUMP_COMPLETE使用）
        tolerance: 温度容差（TEMPERATURE_REACHED使用）
        timeout: 超时秒数
        channel: 泵通道号（PUMP_COMPLETE使用）
        target_temperature: 目标温度（MICROWAVE_TEMPERATURE_REACHED使用）
        targets: 两路设备及目标温度（HEATER_PAIR_REACHED/HEATER_PAIR_STABLE使用）
        hold_mode: 微波保温计时方式，qualified兼容旧YAML，timed为固定计时
    """
    type: WaitType = WaitType.NONE
    seconds: float = 0
    device_id: str = ""
    tolerance: float = 1.0
    timeout: float = 3600
    channel: int = 0
    target_temperature: Optional[float] = None
    targets: list[dict] = field(default_factory=list)
    hold_mode: str = "qualified"


@dataclass
class ExperimentStep:
    """实验步骤

    Attributes:
        id: 步骤唯一标识
        type: 动作类型
        params: 动作参数
        wait: 等待条件
        enabled: 是否启用
        on_error: 错误处理策略 (stop/skip)
    """
    id: str
    type: ActionType
    params: dict = field(default_factory=dict)
    wait: WaitCondition = field(default_factory=WaitCondition)
    enabled: bool = True
    on_error: str = "stop"


def validate_flow_duration(step):
    """Optional host-owned bounded flow run; never sent as a pump register."""
    if "flow_duration_seconds" not in step.params:
        return None
    seconds = step.params["flow_duration_seconds"]
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or not 0.1 <= seconds <= 9999):
        raise ValueError("flow_duration_seconds must be finite and in [0.1, 9999]")
    if (step.type != ActionType.PUMP_START or step.params.get("mode") != "FLOW_MODE"
            or step.wait.type != WaitType.NONE or not step.enabled or step.on_error != "stop"):
        raise ValueError("Timed flow requires enabled pump.start, FLOW_MODE, no wait and on_error=stop")
    if any(key in step.params for key in ("run_time", "time_unit", "dispense_volume", "volume_unit",
                                         "repeat_count", "interval_time", "interval_time_unit")):
        raise ValueError("Timed flow cannot include device time, volume or repeat parameters")
    return seconds
