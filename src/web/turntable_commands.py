"""Bottle operations belong to the Web coordinator, not the serial protocol."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from src.devices.turntable_commands import MAX_POSITION, MIN_POSITION, TurntableCommand


class BottleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["home_bottle", "next_bottle"]
    expected_position: StrictInt | None = Field(default=None, ge=MIN_POSITION, le=MAX_POSITION)
    expected_bottle_token: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def check_fields(self):
        if self.action == "next_bottle":
            if self.expected_position is None or self.expected_bottle_token is None:
                raise ValueError("next_bottle requires expected_position and expected_bottle_token")
        elif self.model_fields_set - {"action"}:
            raise ValueError("home_bottle accepts no additional fields")
        return self


class CollectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["select_ring", "select_bottle", "return_start", "platform_absolute", "platform_relative"]
    ring: StrictInt | None = Field(default=None, ge=1, le=4)
    bottle: StrictInt | None = Field(default=None, ge=1, le=72)
    expected_position: StrictInt
    position: StrictInt | None = Field(default=None, ge=MIN_POSITION, le=MAX_POSITION)
    steps: StrictInt | None = Field(default=None, ge=MIN_POSITION, le=MAX_POSITION)

    @model_validator(mode="after")
    def check_fields(self):
        allowed = {"action", "expected_position"}
        required = {"select_ring": "ring", "select_bottle": "bottle",
                    "return_start": None,
                    "platform_absolute": "position", "platform_relative": "steps"}[self.action]
        if ((required is not None and getattr(self, required) is None)
                or self.model_fields_set - (allowed | ({required} if required else set()))):
            raise ValueError("接样指令参数不完整或包含无关字段")
        if self.action == "platform_relative" and self.steps == 0:
            raise ValueError("相对位移不能为0")
        return self


def parse_turntable_command(request):
    if isinstance(request, (BottleCommand, TurntableCommand, CollectionCommand)):
        return request
    if isinstance(request, dict) and request.get("action") in ("home_bottle", "next_bottle"):
        return BottleCommand.model_validate(request)
    if isinstance(request, dict) and request.get("action") in ("select_ring", "select_bottle", "return_start", "platform_absolute", "platform_relative"):
        return CollectionCommand.model_validate(request)
    return TurntableCommand.model_validate(request)
