"""
MKM-AH1E microwave Modbus register constants.

The source spreadsheet uses 40001-style holding register addresses. The
ModbusRTUProtocol APIs in this repository expect zero-based PDU addresses, so
all exported register constants below are PDU addresses.
"""

from enum import Enum
from typing import Dict


HOLDING_REGISTER_BASE = 40001
MAX_SEGMENTS = 5


class MicrowaveMode(Enum):
    """Microwave control modes exposed by the control word."""

    MANUAL_POWER = "manual_power"
    AUTO_POWER = "auto_power"
    CONSTANT_RATE = "constant_rate"

    @classmethod
    def from_value(cls, value: "MicrowaveMode | str") -> "MicrowaveMode":
        if isinstance(value, cls):
            return value
        return cls(str(value))


def holding_address(human_address: int) -> int:
    """Convert a 40001-style holding register address to a PDU address."""
    if human_address < HOLDING_REGISTER_BASE:
        raise ValueError(f"Invalid holding register address: {human_address}")
    return human_address - HOLDING_REGISTER_BASE


def _validate_segment(segment: int) -> int:
    if not 1 <= int(segment) <= MAX_SEGMENTS:
        raise ValueError(f"Invalid segment: {segment}, must be 1-{MAX_SEGMENTS}")
    return int(segment)


MANUAL_SEGMENT_START = holding_address(40001)
MANUAL_SEGMENT_SIZE = 5
MANUAL_HOLD_TIME_START = holding_address(40026)
MANUAL_HOLD_TIME_SIZE = 3

AUTO_POWER_SEGMENT_START = holding_address(40041)
AUTO_POWER_SEGMENT_SIZE = 5

CONSTANT_RATE_SEGMENT_START = holding_address(40066)
CONSTANT_RATE_SEGMENT_SIZE = 8

STATUS_CURRENT = holding_address(40106)
STATUS_MATERIAL_TEMPERATURE_RAW = holding_address(40107)
STATUS_POWER_PERCENT = holding_address(40108)
STATUS_RUNTIME_HOURS = holding_address(40109)
STATUS_RUNTIME_MINUTES = holding_address(40110)
STATUS_RUNTIME_SECONDS_PART = holding_address(40111)
STATUS_FAULT_CODE = holding_address(40112)
STATUS_CURRENT_SEGMENT = holding_address(40113)
STATUS_CURRENT_MODE_CODE = holding_address(40114)
STATUS_FLOAT_TEMPERATURE = holding_address(40118)
STATUS_BLOCK_START = STATUS_CURRENT
STATUS_BLOCK_COUNT = STATUS_CURRENT_MODE_CODE - STATUS_BLOCK_START + 1

CONTROL_WORD = holding_address(40151)

CONTROL_CONSTANT_RATE = 1 << 15
CONTROL_AUTO_POWER = 1 << 14
CONTROL_MANUAL_POWER = 1 << 13
CONTROL_MICROWAVE_START = 1 << 12
CONTROL_STOP = 0

MODE_CONTROL_MASKS: Dict[MicrowaveMode, int] = {
    MicrowaveMode.MANUAL_POWER: CONTROL_MANUAL_POWER,
    MicrowaveMode.AUTO_POWER: CONTROL_AUTO_POWER,
    MicrowaveMode.CONSTANT_RATE: CONTROL_CONSTANT_RATE,
}


def manual_segment_start(segment: int) -> int:
    """Return the first PDU address for a manual parameter segment."""
    return MANUAL_SEGMENT_START + (_validate_segment(segment) - 1) * MANUAL_SEGMENT_SIZE


def manual_hold_time_start(segment: int) -> int:
    """Return the first PDU address for a manual hold-time segment."""
    return MANUAL_HOLD_TIME_START + (_validate_segment(segment) - 1) * MANUAL_HOLD_TIME_SIZE


def auto_power_segment_start(segment: int) -> int:
    """Return the first PDU address for an auto-power segment."""
    return AUTO_POWER_SEGMENT_START + (_validate_segment(segment) - 1) * AUTO_POWER_SEGMENT_SIZE


def constant_rate_segment_start(segment: int) -> int:
    """Return the first PDU address for a constant-rate segment."""
    return CONSTANT_RATE_SEGMENT_START + (_validate_segment(segment) - 1) * CONSTANT_RATE_SEGMENT_SIZE
