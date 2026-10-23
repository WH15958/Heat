"""Strict manual CL-01A requests. Validation never accesses hardware."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


MIN_POSITION = -9_999_999
MAX_POSITION = 99_999_999
MIN_SPEED = 400
MAX_SPEED = 40_000


class TurntableCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    action: Literal["move_relative", "move_absolute", "run", "home", "stop"]
    steps: StrictInt | None = Field(default=None, ge=MIN_POSITION, le=MAX_POSITION)
    position: StrictInt | None = Field(default=None, ge=MIN_POSITION, le=MAX_POSITION)
    speed: StrictInt | None = Field(default=None, ge=MIN_SPEED, le=MAX_SPEED)
    direction: Literal["positive", "negative"] | None = None
    duration_seconds: float = Field(default=10.0, ge=1, le=60)

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def numeric_duration(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("duration_seconds must be a number, not boolean/string")
        return value

    @model_validator(mode="after")
    def check_action_fields(self):
        required = {
            "move_relative": {"steps", "speed"},
            "move_absolute": {"position", "speed"},
            "run": {"direction", "speed"},
            "home": {"direction", "speed"},
            "stop": set(),
        }[self.action]
        for name in required:
            if getattr(self, name) is None:
                raise ValueError(f"{self.action} requires {name}")
        allowed = required | {"action"}
        if self.action == "run":
            allowed.add("duration_seconds")
        irrelevant = self.model_fields_set - allowed
        if irrelevant:
            raise ValueError(f"Fields not applicable: {sorted(irrelevant)}")
        return self
