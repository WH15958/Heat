"""Pure parameter contracts shared by device REST and experiment editing."""
import math
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator
from src.protocols.microwave_params import MAX_SEGMENTS


class SetTemperatureRequest(BaseModel):
    """设置温度请求"""
    temperature: float = Field(strict=True, allow_inf_nan=False)


class StartPumpRequest(BaseModel):
    """启动泵请求"""
    channel: int = Field(default=1, strict=True, ge=1, le=4)
    flow_rate: float = Field(
        default=10.0, strict=True, ge=0.01, le=9999, allow_inf_nan=False
    )
    direction: Literal["CW", "CCW"] = "CW"
    mode: Literal[
        "FLOW_MODE", "TIME_QUANTITY", "TIME_SPEED", "QUANTITY_SPEED"
    ] = "FLOW_MODE"
    run_time: Optional[float] = Field(
        default=None, strict=True, ge=0.1, le=9999, allow_inf_nan=False
    )
    dispense_volume: Optional[float] = Field(
        default=None, strict=True, ge=0.01, le=9999, allow_inf_nan=False
    )
    tube_model: Optional[int] = Field(default=None, strict=True, ge=0, le=13)
    flow_unit: Optional[int] = Field(default=None, strict=True, ge=0, le=3)
    time_unit: Optional[int] = Field(default=None, strict=True, ge=0, le=2)
    volume_unit: Optional[int] = Field(default=None, strict=True, ge=0, le=2)
    repeat_count: Optional[int] = Field(
        default=None, strict=True, ge=0, le=9999
    )
    interval_time: Optional[float] = Field(
        default=None, strict=True, ge=0, le=999, allow_inf_nan=False
    )
    interval_time_unit: Optional[int] = Field(
        default=None, strict=True, ge=0, le=2
    )

    @model_validator(mode="after")
    def validate_mode_parameters(self):
        if self.mode in ("TIME_QUANTITY", "TIME_SPEED") and self.run_time is None:
            raise ValueError(f"{self.mode} requires run_time")
        if self.mode in ("TIME_QUANTITY", "QUANTITY_SPEED") and self.dispense_volume is None:
            raise ValueError(f"{self.mode} requires dispense_volume")
        if self.flow_unit == 3 and self.flow_rate > 150:
            raise ValueError("RPM flow_rate must be <= 150")
        if self.mode == "TIME_QUANTITY":
            if self.flow_unit == 3:
                raise ValueError("TIME_QUANTITY requires a volumetric flow_unit")
            time_minutes = self.run_time / 60.0
            if self.time_unit == 1:
                time_minutes = self.run_time
            elif self.time_unit == 2:
                time_minutes = self.run_time * 60.0
            volume_ml = self.dispense_volume
            if self.volume_unit == 0:
                volume_ml = self.dispense_volume / 1000.0
            elif self.volume_unit == 2:
                volume_ml = self.dispense_volume * 1000.0
            implied_flow = volume_ml / time_minutes
            declared_flow = self.flow_rate
            if self.flow_unit == 0:
                declared_flow = self.flow_rate / 1000.0
            elif self.flow_unit == 2:
                declared_flow = self.flow_rate * 1000.0
            if not math.isclose(
                declared_flow, implied_flow, rel_tol=1e-6, abs_tol=1e-9
            ):
                raise ValueError("TIME_QUANTITY flow_rate must match dispense_volume/run_time")
        if self.interval_time is not None and 0 < self.interval_time < 0.1:
            raise ValueError("interval_time must be 0 or at least 0.1 seconds")
        if self.repeat_count is not None and self.repeat_count != 1:
            if self.interval_time is None or self.interval_time <= 0:
                raise ValueError("repeat_count other than 1 requires interval_time > 0")
        return self


class StopPumpRequest(BaseModel):
    """停止泵请求"""
    channel: Optional[int] = Field(default=None, strict=True, ge=1, le=4)


class MicrowaveSegmentRequest(BaseModel):
    """微波仪段参数请求"""
    segment: int = Field(strict=True, ge=1, le=MAX_SEGMENTS)
    heating_temperature: float = Field(
        default=0.0, strict=True, ge=0, le=0xFFFF, allow_inf_nan=False
    )
    target_temperature: Optional[float] = Field(
        default=None, strict=True, ge=0, le=0xFFFF, allow_inf_nan=False
    )
    holding_temperature: float = Field(
        default=0.0, strict=True, ge=0, le=0xFFFF, allow_inf_nan=False
    )
    heating_power_percent: Optional[int] = Field(
        default=None, strict=True, ge=0, le=100
    )
    holding_power_percent: Optional[int] = Field(
        default=None, strict=True, ge=0, le=100
    )
    holding_deviation: float = Field(
        default=0.0, strict=True, ge=0, le=0xFFFF, allow_inf_nan=False
    )
    hours: int = Field(default=0, strict=True, ge=0, le=0xFFFF)
    minutes: int = Field(default=0, strict=True, ge=0, le=0xFFFF)
    seconds: int = Field(default=0, strict=True, ge=0, le=0xFFFF)
    ramp_hours: int = Field(default=0, strict=True, ge=0, le=0xFFFF)
    ramp_minutes: int = Field(default=0, strict=True, ge=0, le=0xFFFF)
    ramp_seconds: int = Field(default=0, strict=True, ge=0, le=0xFFFF)


class MicrowaveConfigureRequest(BaseModel):
    """微波仪配置请求"""
    segments: List[MicrowaveSegmentRequest] = Field(
        min_length=1, max_length=MAX_SEGMENTS
    )
    confirm_real_hardware_write: bool = Field(default=False, strict=True)


class MicrowaveStartRequest(BaseModel):
    """微波仪启动请求"""
    mode: Literal["manual_power", "auto_power", "constant_rate"]
