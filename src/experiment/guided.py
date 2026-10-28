"""Fixed-plumbing guided recipes and batch orchestration over the existing engine."""
import asyncio
import hashlib
import itertools
import json
import math
import os
import tempfile
import time
import uuid
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.experiment.progress import guided_activity
from src.experiment.editor import validate_source
from src.experiment.engine import ExperimentEngine, ExperimentState
from src.experiment.executor import StepExecutor
from src.experiment.guided_turntable import GuidedTurntable
from src.experiment.experiment_logger import ExperimentLogger
from src.experiment.parser import parse_experiment_data
from src.devices.syringe_commands import SyringeCommand
from src.utils.runtime_paths import data_path


BATCH_DIR = data_path("output/guided_batches")
TERMINAL = {"completed", "failed", "stopped", "interrupted"}


class GuidedInitialization(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    direction: Literal["Z", "Y"]
    initialization_code: int

    @model_validator(mode="after")
    def check_command(self):
        SyringeCommand.model_validate(dict(action="initialize", confirm=True, **self.model_dump()))
        return self


class GuidedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    experiment_name: str

    @field_validator("experiment_name")
    @classmethod
    def check_name(cls, value):
        if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in value):
            raise ValueError("实验名称不能包含换行或控制字符")
        value = value.strip()
        if not 1 <= len(value) <= 80:
            raise ValueError("实验名称须为 1–80 个字符")
        return value

    # A/B temperatures, A/B volumes, reaction temperature, holding minutes.
    axes: list[list[float]] = Field(min_length=6, max_length=6)
    repeats: int = Field(default=1, ge=1, le=200)
    speed_a: int = Field(default=100, ge=5, le=5000)
    speed_b: int = Field(default=100, ge=5, le=5000)
    product_port: Literal["NO"] = "NO"
    drain_flow: float = Field(ge=0.01, le=9999)
    product_drain_seconds: float = Field(ge=0.1, le=9999)
    clean_drain_seconds: float = Field(ge=0.1, le=9999)
    clean_volume: float = Field(ge=0.01, le=9999)
    clean_flow: float = Field(ge=0.01, le=9999)
    clean_dwell: float = Field(ge=0, le=3600)
    clean_cycles: int = Field(ge=1, le=10)
    turntable_drip_seconds: float = Field(ge=0, le=3600)
    bottles_confirmed: bool = False
    drain_direction: Literal["CW", "CCW"] = "CW"
    clean_direction: Literal["CW", "CCW"] = "CW"
    heating_timeout: float = Field(default=600, gt=0, le=7200)
    precursor_timeout: float = Field(default=3600, gt=0, le=7200)
    cooling_timeout: float = Field(default=3600, gt=0, le=7200)
    syringe_timeout: float = Field(default=120, gt=0, le=3600)
    plumbing_confirmed: bool = False
    prime_volume_a: float = Field(default=2, gt=0, le=5)
    prime_volume_b: float = Field(default=2, gt=0, le=5)
    prime_heat_minutes: float = Field(ge=0, le=1440)
    prime_cycles: int = Field(default=2, ge=1, le=10)
    prime_drain_seconds: float = Field(ge=0.1, le=9999)
    prime_drain_flow: float = Field(ge=0.01, le=9999)
    reactor_available_ml: float = Field(gt=0)
    source_available_a_ml: float = Field(gt=0)
    source_available_b_ml: float = Field(gt=0)
    waste_available_ml: float = Field(gt=0)
    priming_confirmed: bool = False
    initialization_a: GuidedInitialization
    initialization_b: GuidedInitialization
    initialization_confirmed: bool = False
    priming_batch_id: str | None = None

    @model_validator(mode="after")
    def check_axes(self):
        hold_seconds(self.prime_heat_minutes)
        count = self.repeats
        for index, values in enumerate(self.axes):
            if not values or len(values) > 200:
                raise ValueError("每项条件须包含 1–200 个数值")
            if len(values) != len(set(values)):
                raise ValueError("同一条件不能重复数值；请使用重复次数")
            if any(v <= 0 if index in (2, 3) else v < 0 for v in values):
                raise ValueError("进样量须大于零，温度和时间不能为负")
            count *= len(values)
            if count > 200:
                raise ValueError("整批最多 200 组")
        if max(self.axes[5]) > 1440:
            raise ValueError("单组保温时间最多 1440 分钟")
        if any(value != int(value) for value in self.axes[4]):
            raise ValueError("微波目标温度必须为整数℃")
        for minutes in self.axes[5]:
            hold_seconds(minutes)
        if self.clean_volume > self.reactor_available_ml:
            raise ValueError("每次清洗液量超出反应仪现场确认的可用容积")
        total = self.prime_cycles * (self.prime_volume_a + self.prime_volume_b)
        if total > self.reactor_available_ml:
            raise ValueError("累计预充量超出反应仪现场确认的可用容积")
        rows = self.rows()
        if any(row[2]+row[3] > self.reactor_available_ml for row in rows):
            raise ValueError("正式单组总进样量超出反应仪可用容积")
        for i, (volume, available) in enumerate(((self.prime_volume_a, self.source_available_a_ml),
                                                (self.prime_volume_b, self.source_available_b_ml))):
            if volume * self.prime_cycles + sum(row[i+2] for row in rows) > available:
                raise ValueError(f"前驱体 {i+1} 可用量不足以完成预充及整批进料")
        if total + len(rows) * self.clean_volume * self.clean_cycles > self.waste_available_ml:
            raise ValueError("废液瓶可用容量不足以容纳预充及整批清洗废液")
        return self

    def rows(self):
        return [list(row) for row in itertools.product(*self.axes) for _ in range(self.repeats)]


def hold_seconds(minutes):
    seconds = minutes * 60
    if not math.isclose(seconds, round(seconds), rel_tol=0, abs_tol=1e-9):
        raise ValueError("保温分钟必须能转换为整秒，不能截断小数秒")
    return int(round(seconds))


def drain_seconds(volume, flow):
    seconds = volume / flow * 60
    if not math.isfinite(seconds) or not 0.1 <= seconds <= 9999:
        raise ValueError("泵液时长须为 0.1–9999 秒，请调整体积或流量")
    return seconds


def priming_signature(spec):
    from src.utils.config import ConfigManager
    fields = spec.model_dump(exclude={"plumbing_confirmed", "priming_confirmed", "initialization_confirmed", "priming_batch_id", "bottles_confirmed"})
    config = ConfigManager().load()
    fields["priming_protocol"] = "turntable_collection_v6"
    fields["devices"] = [device.to_dict() for group in (config.syringe_pumps, config.valves,
        config.pumps, config.microwaves, config.heaters, config.turntables) for device in group
        if device.device_id in ("syringe_pump1", "syringe_pump2", "valve1", "pump1", "microwave1", "heater1", "heater2", "turntable1")]
    return hashlib.sha256(json.dumps(fields, sort_keys=True, allow_nan=False).encode()).hexdigest()


def priming_recipe(spec, batch_id):
    steps = []
    def add(sid, action, params=None, wait=None):
        steps.append(dict(id=sid, type=action, params=params or {}, on_error="stop",
                          **({"wait": wait} if wait else {})))
    # Check temperature without starting microwave output; hot residual liquid is unsafe to drain.
    add("prime_temperature", "wait", wait=dict(type="microwave_temperature_below",
        device_id="microwave1", target_temperature=45, timeout=spec.cooling_timeout))
    for n, initialization in enumerate((spec.initialization_a, spec.initialization_b), 1):
        add(f"prime_initialize_{n}", "syringe_pump.initialize",
            dict(device_id=f"syringe_pump{n}", confirm=True, timeout=spec.syringe_timeout,
                 **initialization.model_dump()))
    # Prime with the first group's heated precursors, retaining heat for formal feeding.
    for n in (0, 1):
        add(f"prime_heat_{n}_set", "heater.set_temperature",
            dict(device_id=f"heater{n+1}", temperature=spec.axes[n][0]))
        add(f"prime_heat_{n}_start", "heater.start", dict(device_id=f"heater{n+1}"))
    add("prime_heat_both_reached", "wait", wait=dict(type="heater_pair_reached",
        targets=[dict(device_id=f"heater{n+1}", target_temperature=spec.axes[n][0]) for n in (0, 1)],
        timeout=spec.precursor_timeout))
    add("prime_heat_duration", "wait", wait=dict(type="duration",
        seconds=hold_seconds(spec.prime_heat_minutes)))
    for n, (volume, speed) in enumerate(((spec.prime_volume_a, spec.speed_a),
                                       (spec.prime_volume_b, spec.speed_b)), 1):
        for cycle in range(1, spec.prime_cycles+1):
            params = dict(device_id=f"syringe_pump{n}", volume=volume, unit="mL",
                          speed=speed, timeout=spec.syringe_timeout)
            for action in ("aspirate", "dispense"):
                add(f"prime_{n}_{cycle}_{action}", "syringe_pump."+action, params)
    waste = "NC"
    add("prime_waste_route", "valve.switch", dict(device_id="valve1", position=waste))
    add("prime_recheck_temperature", "wait", wait=dict(type="microwave_temperature_below",
        device_id="microwave1", target_temperature=45, timeout=spec.cooling_timeout))
    seconds = spec.prime_drain_seconds
    add("prime_drain", "pump.start", dict(device_id="pump1", channel=4, mode="FLOW_MODE",
        flow_rate=spec.prime_drain_flow, flow_unit=1, flow_duration_seconds=seconds,
        direction=spec.drain_direction))
    return dict(name=f"{spec.experiment_name} · 预充", steps=steps,
                metadata=dict(batch_id=batch_id, experiment_name=spec.experiment_name, run_kind="priming", condition_id="PRIMING",
                              notes="前驱体预充维护记录，非正式样品，不用于表征或 planner 反馈",
                              priming_signature=priming_signature(spec),
                              theoretical_volume_ml=(spec.prime_volume_a+spec.prime_volume_b)*spec.prime_cycles,
                              drain_seconds=seconds, waste_port=waste))


def recipe(row, spec: GuidedRequest, batch_id, index):
    steps = []

    def add(step_id, action, params=None, wait=None):
        steps.append(dict(id=step_id, type=action, params=params or {},
                          on_error="stop", **({"wait": wait} if wait else {})))

    def pump(step_id, channel, volume, flow, direction, seconds=None):
        if seconds is None:
            seconds = drain_seconds(volume, flow)
        else:
            add(step_id, "pump.start", dict(device_id="pump1", channel=channel,
                mode="FLOW_MODE", flow_rate=flow, flow_unit=1,
                flow_duration_seconds=seconds, direction=direction))
            return
        add(step_id, "pump.start", dict(device_id="pump1", channel=channel,
            mode="TIME_QUANTITY", flow_rate=flow, flow_unit=1, run_time=seconds,
            time_unit=0, dispense_volume=volume, volume_unit=1,
            direction=direction, repeat_count=1),
            dict(type="pump_complete", device_id="pump1", channel=channel,
                 timeout=seconds + 60))
        add(step_id + "_stop", "pump.stop_channel", dict(device_id="pump1", channel=channel))

    for n in (0, 1):
        did = f"heater{n+1}"
        add(f"heat_{n}_set", "heater.set_temperature", dict(device_id=did, temperature=row[n]))
        add(f"heat_{n}_start", "heater.start", dict(device_id=did))
    add("heat_both_stable", "wait", wait=dict(type="heater_pair_stable",
        targets=[dict(device_id=f"heater{n+1}", target_temperature=row[n]) for n in (0, 1)],
        tolerance=5, seconds=30, timeout=spec.precursor_timeout))
    feeds = []
    for n, speed in enumerate((spec.speed_a, spec.speed_b)):
        feed = dict(device_id=f"syringe_pump{n+1}", volume=row[n+2], unit="mL",
                    speed=speed, timeout=spec.syringe_timeout)
        add(f"aspirate_{n}", "syringe_pump.aspirate", feed)
        feeds.append(feed)
    add("feed_both", "syringe_pair.dispense", dict(feeds=feeds))
    seconds = hold_seconds(row[5])
    # Cover retained HMI slot selections; the host owns the actual hold and stop.
    guard = math.ceil(spec.heating_timeout) + seconds + 60
    if guard > 99*3600 + 59*60 + 59:
        raise ValueError("阶段时间加设备保护计时超出99小时59分59秒")
    add("microwave_config", "microwave.configure_auto_power", dict(device_id="microwave1",
        segments=[dict(segment=n, heating_temperature=row[4], holding_temperature=row[4],
                       hours=guard//3600, minutes=guard%3600//60, seconds=guard%60)
                  for n in range(1, 6)]))
    add("microwave_start", "microwave.start", dict(device_id="microwave1", mode="auto_power"),
        dict(type="microwave_temperature_reached", device_id="microwave1",
             target_temperature=row[4], tolerance=5, seconds=15, timeout=spec.heating_timeout))
    add("hold", "wait", wait=dict(type="microwave_monitored_hold", device_id="microwave1", seconds=seconds,
        target_temperature=row[4], tolerance=5, hold_mode="timed", timeout=max(1, seconds)))
    add("microwave_stop", "microwave.stop", dict(device_id="microwave1"))
    cool = dict(type="microwave_temperature_below", device_id="microwave1",
                target_temperature=45, timeout=spec.cooling_timeout)
    add("cool_before_collection", "wait", wait=cool)
    add("recheck_temperature", "wait", wait=cool)
    add("product_route", "valve.switch", dict(device_id="valve1", position=spec.product_port))
    pump("collect_product", 4, row[2]+row[3], spec.drain_flow, spec.drain_direction,
         spec.product_drain_seconds)
    waste = "NC"
    for cycle in range(spec.clean_cycles):
        add(f"clean_{cycle}_route", "valve.switch", dict(device_id="valve1", position=waste))
        pump(f"clean_{cycle}_in", 3, spec.clean_volume, spec.clean_flow, spec.clean_direction)
        add(f"clean_{cycle}_dwell", "wait", wait=dict(type="duration", seconds=spec.clean_dwell))
        pump(f"clean_{cycle}_out", 4, spec.clean_volume, spec.drain_flow, spec.drain_direction,
             spec.clean_drain_seconds)
    return dict(name=f"{spec.experiment_name} · 第 {index+1} 组", steps=steps, metadata=dict(
        batch_id=batch_id, experiment_name=spec.experiment_name, condition_id=f"C{index//spec.repeats+1:03d}", sample_index=index+1,
        guided_parameters=row, product_port=spec.product_port,
        bottle_number=index+1, collection_device_id="turntable1",
        collection_status="pending",
        microwave_hold_policy=dict(hold_mode="timed", tolerance=5, stable_seconds=15, excursion="continue_timing"),
        theoretical_product_volume_ml=row[2]+row[3],
        product_drain_seconds=spec.product_drain_seconds, clean_drain_seconds=spec.clean_drain_seconds,
        recipe_file=f"output/guided_batches/plans/{batch_id}.json", recipe_group=index+1))


def compile_plan(spec, batch_id="preview"):
    from src.utils.config import ConfigManager
    config = ConfigManager().load()
    validate_fixed_channels(config, spec)
    turntable = next((t for t in config.turntables if t.device_id == "turntable1" and t.enabled), None)
    if (turntable is None or not turntable.home_enabled or not turntable.position_encoding_verified
            or turntable.bottle_count < 1 or turntable.pulses_per_bottle <= 0):
        raise ValueError("固定接样转盘 turntable1 未启用或瓶位、机械回零配置未完成")
    if len(spec.rows()) > turntable.bottle_count:
        raise ValueError(f"本批共 {len(spec.rows())} 组，超过转盘 {turntable.bottle_count} 个瓶位；禁止循环覆盖产物瓶")
    for i, did in enumerate(("heater1", "heater2")):
        heater = next((h for h in config.heaters if h.device_id == did and h.enabled), None)
        if heater is None or any(not heater.min_temperature <= t <= heater.max_temperature for t in spec.axes[i]):
            raise ValueError(f"{did} 未配置或温度超出设备范围")
    microwave = next((m for m in config.microwaves if m.device_id == "microwave1" and m.enabled), None)
    if microwave is None or max(spec.axes[4]) > microwave.max_temperature:
        raise ValueError("微波温度超出已配置设备范围")
    for i, did in enumerate(("syringe_pump1", "syringe_pump2")):
        pump = next((p for p in config.syringe_pumps if p.device_id == did and p.enabled), None)
        if pump is None or max(max(spec.axes[i+2]), (spec.prime_volume_a, spec.prime_volume_b)[i]) > pump.capacity_ml:
            raise ValueError(f"{did} 未配置或进样量超出额定容量")
        code = (spec.initialization_a, spec.initialization_b)[i].initialization_code
        if ((code == 0 or 10 <= code <= 40) and pump.capacity_ml < 2.5
                or code == 1 and pump.capacity_ml < 0.5):
            raise ValueError(f"{did} 初始化代码不适用于当前注射器容量")
    recipes = [recipe(row, spec, batch_id, i) for i, row in enumerate(spec.rows())]
    for data in [priming_recipe(spec, batch_id), *recipes]:
        result = validate_source(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        if not result["valid"]:
            raise ValueError("；".join(e["message"] for e in result["errors"]))
    return recipes


def validate_fixed_channels(config, spec):
    pump = next((p for p in config.pumps if p.device_id == "pump1" and p.enabled), None)
    valve = next((v for v in config.valves if v.device_id == "valve1" and v.enabled), None)
    if pump is None or valve is None:
        raise ValueError("固定蠕动泵 pump1 或三通阀 valve1 未配置或未启用")
    for number, flows in ((3, (spec.clean_flow,)), (4, (spec.drain_flow, spec.prime_drain_flow))):
        channel = next((c for c in pump.channels if c.channel == number and c.enabled), None)
        if channel is None:
            raise ValueError(f"蠕动泵通道 {number} 未配置或未启用")
        if any(flow > channel.max_flow_rate for flow in flows):
            raise ValueError(f"蠕动泵通道 {number} 流量超出配置上限 {channel.max_flow_rate} mL/min")


def atomic_record(record, directory=None):
    directory = Path(directory or BATCH_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (record["batch_id"] + ".json")
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class GuidedStepExecutor(StepExecutor):
    """Bind collection to this batch's reserved, verified bottle position."""

    def __init__(self, dm, batch):
        super().__init__(dm)
        self.batch = batch

    async def check_flow_interlock(self, device_id, channel):
        if self._activity_step and self._activity_step.id == "collect_product":
            try:
                await self.batch.turntable.verify(self.batch.record["current_group"])
            except Exception as exc:
                self._last_error = "收取期间瓶位校验失败：" + str(exc)
                return False
        return True

    async def execute(self, step):
        collecting = step.id == "collect_product"
        self.last_device_result = None
        try:
            if step.id in ("product_route", "collect_product"):
                if self.batch.stopping or self._should_stop():
                    return False
                # A pause before the valve/pump may be long: read again after resume.
                while True:
                    if await self._wait_for_resume() is None:
                        return False
                    await self.batch.turntable.verify(self.batch.record["current_group"])
                    if not self._is_paused():
                        break
            if collecting:
                # Durable intent precedes the first possible pump write.
                self.batch.collection_state("collecting")
            success = await super().execute(step)
            if collecting:
                if success:
                    await self.batch.turntable.verify(self.batch.record["current_group"])
                self.batch.collection_state("collected" if success else "possibly_partial")
                self.last_device_result = dict(self.last_device_result or {},
                    bottle_number=self.batch.record["current_group"],
                    collection_status="collected" if success else "possibly_partial")
            return success
        except Exception as exc:
            self._last_error = str(exc)
            self.last_device_result = dict(error=str(exc), bottle_number=self.batch.record["current_group"],
                turntable=self.batch.record["turntable"]["status"])
            if collecting:
                self.batch.mark_partial_collection(str(exc))
            return False

class GuidedBatch:
    """One supervised batch; registry ownership spans all constituent runs."""
    def __init__(self, dm, spec, batch_id=None, directory=None):
        self.dm, self.spec = dm, spec
        self.batch_id = batch_id or "guided_" + uuid.uuid4().hex
        self.directory = directory
        self.recipes = compile_plan(spec, self.batch_id)
        self.priming = priming_recipe(spec, self.batch_id)
        self.engine = None
        self.executor = GuidedStepExecutor(dm, self)
        self.executor.release_resources_on_cleanup = False
        self.state = ExperimentState.IDLE
        self.stopping = False
        self.task = None
        self._stop_task = None
        self.persistence_failure = None
        self.priming_stop_pending = False
        self._priming_cleanup_count = 0
        self._orchestration_step = None
        self._motion_active = False
        self._motion_pause_pending = False
        self._batch_paused_at = None
        self._batch_paused_total = 0.0
        self._elapsed_started_at = None
        self._elapsed_finished_at = None
        self.turntable = GuidedTurntable(dm, lambda: self.stopping, self.turntable_changed)
        self.record = dict(batch_id=self.batch_id, experiment_name=spec.experiment_name, state="idle", request=spec.model_dump(),
            created_at=datetime.now(timezone.utc).isoformat(), current_group=0,
            total_groups=len(self.recipes), groups=[], elapsed_seconds=0.0,
            error=None, persistence_status="ok", phase="preparing", recovery_required=False,
            preparation=dict(status="pending", error=None),
            finalization=dict(status="pending", error=None),
            turntable=dict(device_id="turntable1", current_bottle=None, target_bottle=1,
                           operation="pending", status=None), turntable_events=[],
            priming=dict(status="pending", signature=priming_signature(spec), completed_cycles=[0, 0]),
            plan_file=f"plans/{self.batch_id}.json")

    @property
    def cleanup_pending(self):
        return bool((self.engine and self.engine.cleanup_pending)
                    or self.executor._active_heaters or self.executor._active_microwaves
                    or self.executor._active_pumps or self.executor._active_syringes
                    or self.executor._reserved_syringes or self.executor._reserved_valves
                    or self.turntable.claimed or self.turntable.needs_stop
                    or self.record["persistence_status"] == "error" or self.record["recovery_required"]
                    or self.priming_stop_pending)

    @property
    def exp_logger(self):
        return self.engine.exp_logger if self.engine else None

    @property
    def progress(self):
        return self.engine.progress if self.engine else None

    def elapsed_clock(self):
        return time.monotonic()

    @property
    def elapsed_seconds(self):
        if self._elapsed_started_at is None:
            return 0.0
        end = self._elapsed_finished_at if self._elapsed_finished_at is not None else self.elapsed_clock()
        return max(0.0, end - self._elapsed_started_at)

    def finish_elapsed(self):
        if self._elapsed_started_at is not None and self._elapsed_finished_at is None:
            self._elapsed_finished_at = self.elapsed_clock()
        self.record["elapsed_seconds"] = self.elapsed_seconds

    def save(self):
        self.record["state"] = self.state.value
        self.record["elapsed_seconds"] = self.elapsed_seconds
        self.record["progress"] = self.snapshot()["progress"]
        self.record["pause_pending"] = self._motion_pause_pending or bool(self.engine and self.engine.pause_pending)
        self.record["cleanup_required"] = bool((self.engine and self.engine.cleanup_pending)
            or self.executor._active_heaters or self.executor._active_microwaves
            or self.executor._active_pumps or self.executor._active_syringes
            or self.turntable.claimed or self.turntable.needs_stop)
        try:
            self.record["persistence_status"] = "ok"
            atomic_record(self.record, self.directory)
        except Exception as exc:
            self.record["persistence_status"] = "error"
            self.persistence_failure = str(exc)
            raise

    def retry_persistence(self):
        """Repair terminal storage without changing execution or recovery state."""
        if self.exp_logger is None:
            return False
        saved = self.exp_logger.retry_persistence()
        run = self.exp_logger.active_run
        if run is None or not run.finished_at:
            return False
        for entry in [self.record["priming"], *self.record["groups"]]:
            if entry.get("run_id") == run.run_id:
                entry["persistence_status"] = run.persistence_status
                entry["persistence_errors"] = list(run.persistence_errors)
        self.save()
        return saved

    def snapshot(self):
        result = dict(self.record)
        result["state"] = self.state.value
        result["elapsed_seconds"] = self.elapsed_seconds
        result["pause_pending"] = self._motion_pause_pending or bool(self.engine and self.engine.pause_pending)
        result["cleanup_pending"] = self.cleanup_pending
        result["stop_requested"] = self.stopping
        result["cleanup_in_progress"] = bool(getattr(self.executor, "cleanup_in_progress", False) or self._priming_cleanup_count)
        p = self.progress
        result["progress"] = dict(current_step=p.current_step, total_steps=p.total_steps,
                                  step_id=p.step_id, elapsed=p.elapsed) if p else None
        if p and getattr(p, "activity", None):
            result["progress"]["activity"] = guided_activity(self.executor._activity_step, p.activity)
        if p:
            labels = {"feed_both": "两路前驱体进料", "microwave_config": "设置微波反应温度",
                "heat_both_stable": "两路温度同时在目标 ±5℃ 内持续 30 秒",
                "microwave_start": "微波升温", "hold": "反应保温", "microwave_stop": "停止微波",
                "cool_before_collection": "等待降温至45℃",
                "recheck_temperature": "收取前复查温度", "product_route": "切向产物出口",
                "collect_product": "抽取产物", "collect_product_stop": "停止产物抽取"}
            label = labels.get(p.step_id)
            if label is None:
                label = ("预充与排废液：" + p.step_id if p.step_id.startswith("prime_") else
                         "前驱体加热" if p.step_id.startswith("heat_") else
                         "前驱体吸液" if p.step_id.startswith("aspirate_") else
                         "停止前驱体加热" if p.step_id.startswith("heater") else
                         "清洗与排废液" if p.step_id.startswith("clean_") else "本组结束")
            result["progress"]["step_label"] = label
            if p.step_id.startswith("prime_"):
                parts = p.step_id.split("_")
                prime_labels = {"prime_temperature": "预充前检查反应液温度 ≤45℃",
                    "prime_initialize_1": "初始化注射泵 A", "prime_initialize_2": "初始化注射泵 B",
                    "prime_heat_duration": f"到温后脱气：等待 {self.spec.prime_heat_minutes:g} 分钟",
                    "prime_heat_both_reached": "等待两路达到各自目标温度，随后计时脱气",
                    "prime_heat_both_stable": "等待两路目标 ±3℃ 并稳定 30 秒，随后计时脱气",
                    **{f"prime_heat_{n}_{action}": f"预充前{verb}前驱体 {name}"
                       for n, name in enumerate(("A", "B"))
                       for action, verb in (("set", "设置温度："), ("start", "开始加热："))},
                    "prime_waste_route": "切向废液端", "prime_recheck_temperature": "排液前复查温度 ≤45℃",
                    "prime_drain": "预充排废液", "prime_drain_stop": "停止预充排液"}
                result["progress"]["step_label"] = prime_labels.get(p.step_id, label)
                if p.step_id in ("prime_initialize_1", "prime_initialize_2"):
                    result["progress"]["device_id"] = "syringe_pump" + parts[2]
                elif p.step_id in ("prime_heat_both_reached", "prime_heat_both_stable", "prime_heat_duration"):
                    result["progress"]["device_id"] = "heater1 / heater2"
                elif p.step_id.startswith("prime_heat_"):
                    result["progress"]["device_id"] = f"heater{int(parts[2])+1}"
                elif len(parts) == 4 and parts[1] in ("1", "2"):
                    result["progress"].update(device_id="syringe_pump"+parts[1], cycle=int(parts[2]),
                        step_label=f"注射泵{parts[1]} 第{parts[2]}次 " + ("吸取" if parts[3] == "aspirate" else "排出"))
                elif p.step_id.startswith("prime_drain"):
                    result["progress"]["device_id"] = "pump1 / 通道4"
                elif p.step_id == "prime_waste_route":
                    result["progress"]["device_id"] = "valve1"
                else:
                    result["progress"]["device_id"] = "microwave1（只读温度）"
        if self._orchestration_step:
            result["progress"] = dict(current_step=0, total_steps=1, elapsed=0,
                step_id=self._orchestration_step[0], step_label=self._orchestration_step[1],
                device_id="turntable1")
        return result

    def turntable_changed(self, status):
        self.record["turntable"].update(status=status, current_bottle=status.get("current_bottle"))
        # Live telemetry does not fsync at polling frequency. Movement intent,
        # completion and collection boundaries below persist the relevant state.
        # Restart handling always invalidates the saved bottle position.

    def collection_state(self, status):
        group = self.record["groups"][-1]
        group["collection_status"] = status
        run = self.exp_logger.active_run if self.exp_logger else None
        if run:
            run.metadata["collection_status"] = status
        self.save()

    def mark_partial_collection(self, error=None):
        if self.record["groups"] and self.record["groups"][-1].get("collection_status") == "collecting":
            group = self.record["groups"][-1]
            group["collection_status"] = "possibly_partial"
            group["collection_error"] = error or "收取中断，可能已有部分产物进入瓶中"
            run = self.exp_logger.active_run if self.exp_logger else None
            if run:
                run.metadata["collection_status"] = "possibly_partial"

    async def boundary(self):
        while self.state == ExperimentState.PAUSED and not self.stopping:
            await asyncio.sleep(0.05)
        if self.stopping:
            raise RuntimeError("批次已停止")
        if self.persistence_failure:
            raise RuntimeError("批次记录保存失败：" + self.persistence_failure)

    def set_batch_paused(self, paused):
        now = time.monotonic()
        if paused and self._batch_paused_at is None:
            self._batch_paused_at = now
        elif not paused and self._batch_paused_at is not None:
            self._batch_paused_total += now - self._batch_paused_at
            self._batch_paused_at = None

    def batch_wait_clock(self):
        now = time.monotonic()
        return (self._batch_paused_at if self._batch_paused_at is not None else now) - self._batch_paused_total

    async def pumps_stopped(self):
        from src.experiment.turntable_sequence import verify_collection_pumps
        await verify_collection_pumps(self.dm)

    async def waste_route(self):
        while True:
            await self.boundary()
            await self.pumps_stopped()
            if self.state != ExperimentState.PAUSED:
                break
        status = await asyncio.to_thread(self.dm.valve_operation, "valve1", "switch", True,
            self.executor._valve_owner, lambda: self.stopping)
        if status.get("read_ok") is not True or status.get("relay_energized") is not True:
            raise RuntimeError("转盘运动前未确认三通阀处于 NC 废液位")

    async def verify_waste_route(self):
        from src.experiment.turntable_sequence import verify_collection_valve
        await verify_collection_valve(self.dm)

    async def move_turntable(self, *, home, target, step_id, label):
        while True:
            await self.boundary()
            await self.pumps_stopped()
            await self.verify_waste_route()
            if self.state != ExperimentState.PAUSED:
                break
        await self.boundary()
        self._orchestration_step = (step_id, label)
        self.record["turntable"].update(operation="homing" if home else "indexing", target_bottle=target)
        event = dict(action="home" if home else "next", target_bottle=target,
                     status="started", at=datetime.now(timezone.utc).isoformat())
        self.record["turntable_events"].append(event)
        self.save()  # Intent is durable before dispatch, even for the first home.
        self._motion_active = True
        try:
            status = await (self.turntable.home() if home else self.turntable.next(target))
            event.update(status="completed", current_bottle=status["current_bottle"])
            self.record["turntable"].update(operation="ready")
            self.save()
        except Exception as exc:
            event.update(status="failed", error=str(exc))
            self.record["turntable"].update(operation="failed", current_bottle=None)
            raise
        finally:
            self._motion_active = False
        if self._motion_pause_pending and not self.stopping:
            self._motion_pause_pending = False
            self.state = ExperimentState.PAUSED
            self.set_batch_paused(True)
            self.save()
        await self.boundary()

    async def settle(self):
        self._orchestration_step = ("turntable_settle", "清洗排液后等待滴液结束")
        self.record["turntable"]["operation"] = "settling"
        self.save()
        deadline = self.batch_wait_clock() + self.spec.turntable_drip_seconds
        remaining = self.spec.turntable_drip_seconds
        while remaining > 0:
            await asyncio.sleep(min(0.05, remaining))
            remaining = deadline - self.batch_wait_clock()
            if self.stopping:
                raise RuntimeError("滴液等待期间批次已停止")
        await self.boundary()

    async def prepare_collection(self):
        self.record["phase"] = "preparing"
        self.record["preparation"]["status"] = "running"
        self.save()
        await self.pumps_stopped()
        await self.waste_route()
        await self.move_turntable(home=True, target=1, step_id="turntable_home_start", label="批次开始：回机械原点，确认1号瓶")
        self.record["preparation"]["status"] = "completed"
        self._orchestration_step = None
        self.save()

    async def finish_collection(self):
        self.record["phase"] = "finishing"
        self.record["finalization"]["status"] = "running"
        self._orchestration_step = ("turntable_home_finish", "整批收尾：停止设备，准备回机械原点")
        self.save()
        await self.boundary()
        # Keep all ownership until the final move and its checkpoint have succeeded.
        if not await self.executor.stop_active_devices(source="normal_cleanup"):
            raise RuntimeError("收尾停机未确认，禁止回零")
        await self.waste_route()
        await self.move_turntable(home=True, target=1, step_id="turntable_home_finish", label="整批收尾：回机械原点")
        self.record["finalization"]["status"] = "completed"
        self.save()

    async def start(self, prime_only=False):
        self._elapsed_started_at = self.elapsed_clock()
        self.prime_only = prime_only
        self.state = ExperimentState.RUNNING
        try:
            # Immutable recipe snapshot, separate from small mutable checkpoints.
            atomic_record(dict(batch_id=self.batch_id, experiment_name=self.spec.experiment_name, request=self.spec.model_dump(),
                               priming=self.priming, recipes=self.recipes,
                               collection=dict(device_id="turntable1", home_before_priming=True,
                                   advance_after="cleaning_and_settle", drip_seconds=self.spec.turntable_drip_seconds,
                                   home_after_normal_completion=True, home_on_failure=False,
                                   bottle_numbers=list(range(1, len(self.recipes)+1)))), Path(self.directory or BATCH_DIR) / "plans")
            self.save()  # Do not dispatch hardware if the plan cannot be recorded.
        except Exception as exc:
            self.record["persistence_status"] = "error"
            self.persistence_failure = str(exc)
            self.finish_elapsed()
            raise
        all_steps = [s for data in [self.priming, *self.recipes] for s in parse_experiment_data(data)["steps"]]
        try:
            await self.executor.reserve_valves(all_steps)
            await self.executor.reserve_syringes(all_steps)
            await self.turntable.claim()
        except BaseException:
            self.executor.release_resources_on_cleanup = True
            self.executor.release_unused_syringes()
            await self.executor.release_valves()
            if not await self.turntable.release():
                self.record["recovery_required"] = True
            self.state = ExperimentState.FAILED
            self.finish_elapsed()
            self.save()
            raise
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            if self.record["preparation"]["status"] != "completed":
                await self.prepare_collection()
            if self.record["priming"]["status"] != "completed":
                await self.boundary()
                self.record["phase"] = "priming"
                self.record["priming"]["status"] = "running"
                self.engine = ExperimentEngine(self.executor, ExperimentLogger(save_log=True),
                                               keep_heaters_on_completion=True)
                self.engine.load_steps(parse_experiment_data(self.priming)["steps"], self.priming["name"],
                    filename=self.batch_id+"_priming.yaml", metadata=self.priming["metadata"])
                self.engine.on_progress(self.checkpoint)
                self.save()
                await self.engine.start()
                if self.stopping:
                    self.engine.request_stop()
                elif self.state == ExperimentState.PAUSED:
                    await self.engine.pause()
                await self.engine.wait_finished()
                run = self.engine.exp_logger.active_run
                self.record["priming"].update(run_id=run.run_id, steps=run.steps,
                    persistence_status=run.persistence_status)
                if self.stopping or self.engine.state != ExperimentState.COMPLETED or run.persistence_status == "error" or self.persistence_failure:
                    raise RuntimeError(self.executor.last_error or "预充停止、失败或记录保存失败")
                self.record["priming"]["status"] = "completed"
                self.record["priming"]["completed_cycles"] = [self.spec.prime_cycles]*2
                self.save()
                if self.prime_only:
                    self.record["phase"] = "ready"
                    self.state = ExperimentState.PAUSED
                    self.save()
                    return
                if self.stopping:
                    raise RuntimeError("预充后批次已停止")
                if priming_signature(self.spec) != self.record["priming"]["signature"]:
                    raise RuntimeError("预充后设备配置变化，禁止开始正式实验")
                await preflight(self.dm, self.spec, owner=self.executor._syringe_owner,
                                turntable_owner=self.turntable.owner)
            self.record["phase"] = "experiments"
            for i, data in enumerate(self.recipes):
                if self.stopping:
                    break
                while self.state == ExperimentState.PAUSED and not self.stopping:
                    await asyncio.sleep(0.05)
                if self.stopping:
                    break
                self.record["phase"] = "experiments"
                self._orchestration_step = None
                self.record["current_group"] = i+1
                await self.turntable.verify(i+1)
                executor = self.executor
                self.engine = ExperimentEngine(executor, ExperimentLogger(save_log=True),
                                               finish_reaction_before_pause=True,
                                               keep_heaters_on_completion=True)
                parsed = parse_experiment_data(data)
                self.engine.load_steps(parsed["steps"], data["name"],
                    filename=self.batch_id + f"_{i+1}.yaml", metadata=data["metadata"])
                self.engine.on_progress(lambda p: self.checkpoint(p))
                self.save()
                await self.engine.start()
                if self.stopping:
                    self.engine.request_stop()
                elif self.state == ExperimentState.PAUSED:
                    await self.engine.pause()
                run = self.engine.exp_logger.active_run
                group = dict(index=i+1, parameters=data["metadata"]["guided_parameters"],
                    run_id=run.run_id, sample_id=run.metadata.get("sample_id"), state="running",
                    bottle_number=i+1, collection_status="pending")
                self.record["groups"].append(group)
                self.save()
                await self.engine.wait_finished()
                group["state"] = self.engine.state.value
                group["persistence_status"] = run.persistence_status
                group["persistence_errors"] = run.persistence_errors
                if self.persistence_failure:
                    raise RuntimeError("批次记录保存失败：" + self.persistence_failure)
                if run.persistence_status == "error":
                    raise RuntimeError("本组实验记录持久化失败，批次不再继续")
                if self.engine.state != ExperimentState.COMPLETED:
                    self.state = self.engine.state
                    self.record["error"] = executor.last_error
                    self.record["recovery_required"] = True
                    self.mark_partial_collection(executor.last_error)
                    self.save()
                    return
                self.save()
                self.record["phase"] = "indexing" if i+1 < len(self.recipes) else "finishing"
                await self.pumps_stopped()
                await self.verify_waste_route()
                await self.settle()
                if i+1 < len(self.recipes):
                    await self.move_turntable(home=False, target=i+2, step_id="turntable_next",
                                             label=f"清洗完成：换至{i+2}号瓶")
            if not self.stopping:
                await self.finish_collection()
            # Keep the batch active until final resource cleanup has also succeeded.
            self.state = ExperimentState.STOPPED if self.stopping else ExperimentState.RUNNING
            self.save()
        except Exception as exc:
            requested_stop = self.stopping
            self.record["error"] = str(exc)
            self.record["recovery_required"] = True
            self.mark_partial_collection(str(exc))
            if self.record["phase"] == "preparing":
                self.record["preparation"].update(status="failed", error=str(exc))
            if self.record["phase"] == "finishing":
                self.record["finalization"].update(status="failed", error=str(exc))
                self.record["error"] = "实验组已完成，收尾回零失败：" + str(exc)
            if self.record["phase"] in ("priming", "ready"):
                self.record["priming"]["status"] = "failed"
                self.record["recovery_required"] = True
                self.request_stop()
                await self.stop_priming_devices()
            if self.engine:
                try:
                    await self.engine.stop()
                except Exception as cleanup_exc:
                    self.record["error"] += "; cleanup: " + str(cleanup_exc)
            self.state = ExperimentState.STOPPED if requested_stop else ExperimentState.FAILED
            try:
                self.save()
            except Exception:
                pass  # Exposed through the live snapshot; never report persisted success.
        finally:
            if self.record["phase"] != "ready" or self.stopping or self.state != ExperimentState.PAUSED:
                self.executor.release_resources_on_cleanup = True
                try:
                    normal = self.record["finalization"]["status"] == "completed" and not self.stopping
                    if not normal and self.turntable.claimed:
                        self.record["recovery_required"] = True
                        await self.turntable.stop()
                        self.record["turntable"]["operation"] = "stopped" if not self.turntable.needs_stop else "failed"
                    clean = await self.executor.stop_active_devices(source="user_stop" if self.stopping else (
                            "normal_cleanup" if normal else "failure_cleanup"))
                    if self.stopping and self.turntable.claimed:
                        clean = await self.turntable.stop() and clean
                        self.record["turntable"]["operation"] = "stopped" if not self.turntable.needs_stop else "failed"
                    released = await self.turntable.release()
                    if not clean or not released:
                        self.state = ExperimentState.FAILED
                        self.record["recovery_required"] = True
                        self.record["error"] = (self.record["error"] or "") + "; 停机未确认"
                    elif self.stopping:
                        self.state = ExperimentState.STOPPED if self.state != ExperimentState.FAILED else self.state
                        self.record["recovery_required"] = True
                    elif normal:
                        self.state = ExperimentState.COMPLETED
                    self.finish_elapsed()
                    self.save()
                except Exception as exc:
                    self.state = ExperimentState.FAILED
                    self.record["recovery_required"] = True
                    self.record["error"] = str(exc)
                    self.finish_elapsed()

    def checkpoint(self, progress):
        if progress.state in (ExperimentState.RUNNING, ExperimentState.PAUSED):
            self.state = progress.state
        self.record["last_step"] = progress.step_id
        if self.record["phase"] == "priming" and self.engine:
            run = self.engine.exp_logger.active_run
            if run:
                self.record["priming"]["steps"] = list(run.steps)
                self.record["priming"]["completed_cycles"] = [sum(
                    s.get("step_id", "").startswith(f"prime_{n}_") and
                    s.get("step_id", "").endswith("_dispense") and s.get("status") == "completed"
                    for s in run.steps) for n in (1, 2)]
        try:
            self.save()
        except Exception:
            self.request_stop()

    async def pause(self):
        if self.stopping or self.state != ExperimentState.RUNNING:
            raise ValueError("批次当前不可暂停")
        if self._motion_active:
            self._motion_pause_pending = True
        elif self.engine and self.engine.state == ExperimentState.RUNNING:
            await self.engine.pause()
            self.state = self.engine.state
        else:
            # No running engine yet (or a group just ended): pause the batch boundary.
            self.state = ExperimentState.PAUSED
        self.set_batch_paused(self.state == ExperimentState.PAUSED)
        self.save()

    async def resume(self):
        if self.record["phase"] == "ready":
            raise ValueError("请在批次确认页启动正式实验，不能通过继续跳过签名检查")
        if self.stopping or (self.state != ExperimentState.PAUSED and not self._motion_pause_pending
                             and not (self.engine and self.engine.pause_pending)):
            raise ValueError("批次当前不可继续")
        self.state = ExperimentState.RUNNING
        self._motion_pause_pending = False
        try:
            self.save()
        except Exception:
            self.state = ExperimentState.PAUSED
            raise
        self.set_batch_paused(False)
        if self.engine:
            await self.engine.resume()

    def request_stop(self):
        self.stopping = True
        self._motion_pause_pending = False
        if self.turntable.claimed:
            self.turntable.invalidate_pending()
        self.executor.cancel_pending_valve_operations()
        if self.engine:
            self.engine.request_stop()

    async def stop(self):
        self.request_stop()
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop())
        return await asyncio.shield(self._stop_task)

    async def _stop(self):
        if self.task and not self.task.done():
            await asyncio.shield(self.task)
        success = await self.engine.stop() if self.engine else True
        self.executor.release_resources_on_cleanup = True
        success = await self.executor.stop_active_devices(source="user_stop") and success
        if self.turntable.claimed:
            success = await self.turntable.stop() and success
            success = await self.turntable.release() and success
        if self.priming_stop_pending:
            success = await self.stop_priming_devices() and success
        if success and self.state not in (ExperimentState.COMPLETED, ExperimentState.FAILED):
            self.state = ExperimentState.STOPPED
        self.finish_elapsed()
        try:
            self.save()
        except Exception:
            return False
        return success

    async def stop_priming_devices(self):
        self._priming_cleanup_count += 1
        try:
            return await self._stop_priming_devices()
        finally:
            self._priming_cleanup_count -= 1

    async def _stop_priming_devices(self):
        """Failure stops both syringe pumps, including the not-yet-started one."""
        success = True
        for did in ("syringe_pump1", "syringe_pump2"):
            try:
                stopped = await asyncio.to_thread(self.dm.syringe(did).stop)
                success = bool(stopped) and success
            except Exception:
                success = False
        try:
            stopped = await asyncio.to_thread(self.dm.stop_pump_channel, "pump1", 4)
            success = bool(stopped) and success
        except Exception:
            success = False
        self.priming_stop_pending = not success
        self.record["priming"]["stop_confirmed"] = success
        return success

    async def begin_experiments(self, spec, before_start=None):
        if (not spec.plumbing_confirmed or not spec.priming_confirmed
                or not spec.initialization_confirmed or not spec.bottles_confirmed):
            raise ValueError("请重新确认现场预充和液路条件")
        if (self.stopping or self.record["phase"] != "ready" or self.record["priming"]["status"] != "completed"
                or self.record["recovery_required"] or self.persistence_failure):
            raise ValueError("当前批次尚未成功预充或需要现场恢复")
        if priming_signature(spec) != self.record["priming"]["signature"]:
            raise ValueError("参数已改变，原预充签名失效；请停止当前批次并重新预充")
        try:
            await preflight(self.dm, spec, owner=self.executor._syringe_owner,
                            turntable_owner=self.turntable.owner)
            await self.turntable.verify(1)
        except (ValueError, RuntimeError, OSError) as exc:
            self.record["priming"]["status"] = "invalidated"
            self.record["recovery_required"] = True
            self.record["error"] = "预充后设备状态变化：" + str(exc)
            self.state = ExperimentState.FAILED
            # Lost bottle evidence also invalidates a ready batch. Stop retained
            # heaters and all owned devices before returning the startup error.
            await self.stop()
            raise
        if before_start:
            before_start()
        self.state = ExperimentState.RUNNING
        self.record["phase"] = "experiments"
        self.save()
        self.task = asyncio.create_task(self.run())


async def preflight(dm, spec, owner=None, *, before_initialization=False, turntable_owner=None):
    """Read-only checks: preparation permits uninitialized pumps; formal start requires zero."""
    compile_plan(spec)  # Recheck current configuration before any reagent-consuming write.
    if not spec.plumbing_confirmed:
        raise ValueError("请确认进液、排液方向及三通阀实际出口接管")
    if not spec.priming_confirmed:
        raise ValueError("请确认前驱体相容性、液路排气、容积及废液条件")
    if not spec.initialization_confirmed:
        raise ValueError("请明确确认本批次初始化运动及切阀")
    if not spec.bottles_confirmed:
        raise ValueError("请确认本批所需产物瓶已清空或更换，并已按瓶号就位")
    control = dm.turntable("turntable1")
    if (not control.config.enabled or not control.config.home_enabled
            or not control.config.position_encoding_verified
            or control.config.bottle_count < len(spec.rows())):
        raise ValueError("运行中的转盘配置未启用或瓶位不足，请核对当前服务配置")
    if not control.device.is_connected() or control.owner not in (None, turntable_owner):
        raise ValueError("接样转盘未连接或已被其他任务占用")
    state = await asyncio.to_thread(control.read)
    if (not state.get("read_ok") or state.get("busy") is not False
            or state.get("work_state") != 0x20 or state.get("motion_blocked")):
        raise ValueError("接样转盘未确认停止，不能开始批次")
    for devices, ids in ((dm.get_all_heaters(), ("heater1", "heater2")),
                         (dm.get_all_pumps(), ("pump1",)),
                         (dm.get_all_microwaves(), ("microwave1",)),
                         (dm.valves, ("valve1",))):
        for did in ids:
            if did not in devices or not devices[did].is_connected():
                raise ValueError(f"装置 {did} 未配置或未连接")
    for i in (0, 1):
        control = dm.syringe(f"syringe_pump{i+1}")
        if not control.device.is_connected() or control.owner not in (None, owner):
            raise ValueError(f"注射泵 {i+1} 未连接或已占用")
        state = await asyncio.to_thread(control.read)
        allowed_faults = (0, 7) if before_initialization else (0,)
        if not state.get("read_ok") or state.get("busy") is not False or state.get("fault_code") not in allowed_faults:
            raise ValueError(f"注射泵 {i+1} 未就绪")
        if not before_initialization and (not state.get("initialized") or not state.get("position_trusted") or state.get("position") != 0):
            raise ValueError(f"注射泵 {i+1} 未确认初始化及可信零位")
        if max(max(spec.axes[i+2]), (spec.prime_volume_a, spec.prime_volume_b)[i]) > control.config.capacity_ml:
            raise ValueError(f"进样量超出注射泵 {i+1} 额定容量")
    microwave = await asyncio.to_thread(dm.read_microwave_data, "microwave1")
    if (microwave.get("fault_code") != 0 or microwave.get("output_active") is not False
            or microwave.get("control_active") is not False or microwave.get("stop_confirmed") is not True):
        raise ValueError("微波仪有故障或输出未确认停止")
    pump_status = await asyncio.to_thread(dm.read_pump_status, "pump1")
    for channel in ("3", "4"):
        status = pump_status.get("channels", {}).get(channel, {})
        if (status.get("read_ok") is not True or status.get("running") is not False
                or status.get("run_status") != "STOP"):
            raise ValueError(f"蠕动泵通道 {channel} 未确认停止")
