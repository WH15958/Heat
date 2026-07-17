"""Request-model regressions for strict numeric device API fields."""

import math

import pytest
from pydantic import ValidationError

from src.web.api.devices import (
    MicrowaveConfigureRequest,
    MicrowaveSegmentRequest,
    MicrowaveStartRequest,
    SetTemperatureRequest,
    StartPumpRequest,
    StopPumpRequest,
)


def test_heater_request_rejects_boolean_temperature():
    with pytest.raises(ValidationError):
        SetTemperatureRequest.model_validate({"temperature": True})


@pytest.mark.parametrize(
    "field_name",
    [
        "channel",
        "flow_rate",
        "run_time",
        "dispense_volume",
        "tube_model",
        "flow_unit",
        "time_unit",
        "volume_unit",
        "repeat_count",
        "interval_time",
        "interval_time_unit",
    ],
)
def test_pump_request_rejects_boolean_numeric_fields(field_name):
    payload = {"flow_rate": 1.0, field_name: True}

    with pytest.raises(ValidationError):
        StartPumpRequest.model_validate(payload)


def test_stop_pump_request_rejects_boolean_channel():
    with pytest.raises(ValidationError):
        StopPumpRequest.model_validate({"channel": True})


@pytest.mark.parametrize(
    "field_name",
    [
        "segment",
        "heating_temperature",
        "target_temperature",
        "holding_temperature",
        "heating_power_percent",
        "holding_power_percent",
        "holding_deviation",
        "hours",
        "minutes",
        "seconds",
        "ramp_hours",
        "ramp_minutes",
        "ramp_seconds",
    ],
)
def test_microwave_segment_rejects_boolean_numeric_fields(field_name):
    payload = {"segment": 1, field_name: True}

    with pytest.raises(ValidationError):
        MicrowaveSegmentRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"segment": 0},
        {"segment": 6},
        {"segment": 1, "heating_temperature": math.inf},
        {"segment": 1, "target_temperature": math.nan},
        {"segment": 1, "heating_power_percent": -1},
        {"segment": 1, "holding_power_percent": 101},
        {"segment": 1, "hours": -1},
        {"segment": 1, "ramp_seconds": 0x10000},
    ],
)
def test_microwave_segment_rejects_invalid_ranges(payload):
    with pytest.raises(ValidationError):
        MicrowaveSegmentRequest.model_validate(payload)


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [{"segment": 1}] * 6,
    ],
)
def test_microwave_configure_requires_one_to_five_segments(segments):
    with pytest.raises(ValidationError):
        MicrowaveConfigureRequest.model_validate({"segments": segments})


def test_microwave_start_request_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        MicrowaveStartRequest.model_validate({"mode": "unknown"})


def test_strict_float_fields_still_accept_json_integer_numbers():
    heater = SetTemperatureRequest.model_validate({"temperature": 25})
    pump = StartPumpRequest.model_validate({"channel": 1, "flow_rate": 1})
    segment = MicrowaveSegmentRequest.model_validate(
        {
            "segment": 1,
            "heating_temperature": 25,
            "target_temperature": 30,
            "holding_temperature": 25,
            "holding_deviation": 1,
        }
    )

    assert heater.temperature == 25.0
    assert pump.flow_rate == 1.0
    assert segment.heating_temperature == 25.0
