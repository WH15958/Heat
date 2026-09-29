"""Shared REST/YAML input contract. No serial access."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from src.protocols.syringe_pump import SETTINGS, integer


class SyringeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["initialize", "configure", "move", "aspirate", "dispense", "valve",
                    "stop", "pause", "resume", "io", "program_load", "program_store",
                    "program_run", "program_validate", "repeat"]
    position: StrictInt | None = None
    volume: float | None = Field(default=None, gt=0)
    unit: Literal["uL", "mL", "steps"] = "uL"
    speed: StrictInt = Field(default=100, ge=5, le=5000)
    direction: Literal["Z", "Y"] = "Z"
    initialization_code: StrictInt = 0
    valve: Literal["input", "output", "bypass"] = "input"
    settings: dict[str, StrictInt] = Field(default_factory=dict)
    output: StrictInt | None = Field(default=None, ge=0, le=7)
    program: str | None = None
    name: str = Field(default="", max_length=80)
    slot: StrictInt | None = Field(default=None, ge=0, le=14)
    timeout: float = Field(default=120, gt=0, le=3600)
    confirm: bool = False

    @field_validator("volume", "timeout", mode="before")
    @classmethod
    def numeric(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("Expected a numeric value, not boolean/string")
        return value

    @model_validator(mode="after")
    def check(self):
        if self.action == "move" and self.position is None:
            raise ValueError("move requires position")
        if self.action in ("aspirate", "dispense") and self.volume is None:
            raise ValueError("aspirate/dispense requires volume")
        if self.action == "initialize" and self.initialization_code not in (0, 1, 2, *range(10, 41)):
            raise ValueError("Invalid initialization code")
        if self.action == "configure":
            if not self.settings:
                raise ValueError("No settings supplied")
            if "speed" in self.settings and "speed_code" in self.settings:
                raise ValueError("Use speed or speed_code, not both")
            for name, value in self.settings.items():
                if name not in SETTINGS:
                    raise ValueError(f"Unknown setting: {name}")
                _, low, high = SETTINGS[name]
                integer(value, low, high, name)
        if self.action == "io" and self.output is None:
            raise ValueError("io requires output")
        if self.action in ("program_load", "program_store", "program_validate") and not self.program:
            raise ValueError("Program text required")
        if self.action == "program_store" and (self.slot is None or not self.name.strip()):
            raise ValueError("Storage requires slot and name")
        if self.action in ("initialize", "program_store") and not self.confirm:
            raise ValueError("Explicit confirmation required")
        # Reject irrelevant values rather than silently accepting a mistyped request.
        relevant = {
            "initialize": {"direction", "initialization_code", "confirm"},
            "configure": {"settings"}, "move": {"position", "speed"},
            "aspirate": {"volume", "unit", "speed"}, "dispense": {"volume", "unit", "speed"},
            "valve": {"valve"}, "io": {"output"},
            "program_load": {"program", "name"},
            "program_store": {"program", "name", "slot", "confirm"},
            "program_validate": {"program", "name"}, "program_run": {"slot"},
            "stop": set(), "pause": set(), "resume": set(), "repeat": set(),
        }[self.action] | {"action", "timeout"}
        if self.model_fields_set - relevant:
            raise ValueError(f"Fields not applicable: {sorted(self.model_fields_set - relevant)}")
        return self
