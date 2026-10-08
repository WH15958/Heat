"""Fixed-plumbing guided recipes and batch orchestration over the existing engine."""
import asyncio
import itertools
import json
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.experiment.editor import validate_source
from src.experiment.engine import ExperimentEngine, ExperimentState
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger
from src.experiment.parser import parse_experiment_data


BATCH_DIR = Path("output/guided_batches")
TERMINAL = {"completed", "failed", "stopped", "interrupted"}


class GuidedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    # A/B temperatures, A/B volumes, reaction temperature, holding minutes.
    axes: list[list[float]] = Field(min_length=6, max_length=6)
    repeats: int = Field(default=1, ge=1, le=200)
    speed_a: int = Field(default=100, ge=5, le=5000)
    speed_b: int = Field(default=100, ge=5, le=5000)
    product_port: Literal["NO", "NC"]
    drain_flow: float = Field(ge=0.01, le=9999)
    clean_volume: float = Field(ge=0.01, le=9999)
    clean_flow: float = Field(ge=0.01, le=9999)
    clean_dwell: float = Field(ge=0, le=3600)
    clean_cycles: int = Field(ge=1, le=10)
    drain_direction: Literal["CW", "CCW"] = "CW"
    clean_direction: Literal["CW", "CCW"] = "CW"
    heating_timeout: float = Field(default=600, gt=0, le=7200)
    cooling_timeout: float = Field(default=3600, gt=0, le=7200)
    syringe_timeout: float = Field(default=120, gt=0, le=3600)
    plumbing_confirmed: bool = False

    @model_validator(mode="after")
    def check_axes(self):
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
        return self

    def rows(self):
        return [list(row) for row in itertools.product(*self.axes) for _ in range(self.repeats)]


def drain_seconds(volume, flow):
    seconds = volume / flow * 60
    if not math.isfinite(seconds) or not 0.1 <= seconds <= 9999:
        raise ValueError("泵液时长须为 0.1–9999 秒，请调整体积或流量")
    return seconds


def recipe(row, spec: GuidedRequest, batch_id, index):
    steps = []

    def add(step_id, action, params=None, wait=None):
        steps.append(dict(id=step_id, type=action, params=params or {},
                          on_error="stop", **({"wait": wait} if wait else {})))

    def pump(step_id, channel, volume, flow, direction):
        seconds = drain_seconds(volume, flow)
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
    for n in (0, 1):
        add(f"heat_{n}_wait", "wait", wait=dict(type="temperature_reached",
            device_id=f"heater{n+1}", tolerance=1, timeout=spec.heating_timeout))
    feeds = []
    for n, speed in enumerate((spec.speed_a, spec.speed_b)):
        feed = dict(device_id=f"syringe_pump{n+1}", volume=row[n+2], unit="mL",
                    speed=speed, timeout=spec.syringe_timeout)
        add(f"aspirate_{n}", "syringe_pump.aspirate", feed)
        feeds.append(feed)
    add("feed_both", "syringe_pair.dispense", dict(feeds=feeds))
    for n in (1, 2):
        add(f"heater{n}_stop", "heater.stop", dict(device_id=f"heater{n}"))
    add("microwave_config", "microwave.configure_auto_power", dict(device_id="microwave1",
        segments=[dict(segment=1, heating_temperature=row[4], holding_temperature=row[4])]))
    add("microwave_start", "microwave.start", dict(device_id="microwave1", mode="auto_power"),
        dict(type="microwave_temperature_reached", device_id="microwave1",
             target_temperature=row[4], tolerance=1, timeout=spec.heating_timeout))
    add("hold", "wait", wait=dict(type="duration", seconds=row[5]*60))
    add("microwave_stop", "microwave.stop", dict(device_id="microwave1"))
    cool = dict(type="microwave_temperature_below", device_id="microwave1",
                target_temperature=45, timeout=spec.cooling_timeout)
    add("cool_before_collection", "wait", wait=cool)
    add("recheck_temperature", "wait", wait=cool)
    add("product_route", "valve.switch", dict(device_id="valve1", position=spec.product_port))
    pump("collect_product", 4, row[2]+row[3], spec.drain_flow, spec.drain_direction)
    waste = "NC" if spec.product_port == "NO" else "NO"
    for cycle in range(spec.clean_cycles):
        pump(f"clean_{cycle}_in", 3, spec.clean_volume, spec.clean_flow, spec.clean_direction)
        add(f"clean_{cycle}_dwell", "wait", wait=dict(type="duration", seconds=spec.clean_dwell))
        add(f"clean_{cycle}_route", "valve.switch", dict(device_id="valve1", position=waste))
        pump(f"clean_{cycle}_out", 4, spec.clean_volume, spec.drain_flow, spec.drain_direction)
    return dict(name=f"引导式实验 第{index+1}组", steps=steps, metadata=dict(
        batch_id=batch_id, condition_id=f"C{index//spec.repeats+1:03d}", sample_index=index+1,
        guided_parameters=row, product_port=spec.product_port,
        recipe_file=f"output/guided_batches/plans/{batch_id}.json", recipe_group=index+1))


def compile_plan(spec, batch_id="preview"):
    from src.utils.config import ConfigManager
    config = ConfigManager().load()
    for i, did in enumerate(("heater1", "heater2")):
        heater = next((h for h in config.heaters if h.device_id == did and h.enabled), None)
        if heater is None or any(not heater.min_temperature <= t <= heater.max_temperature for t in spec.axes[i]):
            raise ValueError(f"{did} 未配置或温度超出设备范围")
    microwave = next((m for m in config.microwaves if m.device_id == "microwave1" and m.enabled), None)
    if microwave is None or max(spec.axes[4]) > microwave.max_temperature:
        raise ValueError("微波温度超出已配置设备范围")
    for i, did in enumerate(("syringe_pump1", "syringe_pump2")):
        pump = next((p for p in config.syringe_pumps if p.device_id == did and p.enabled), None)
        if pump is None or max(spec.axes[i+2]) > pump.capacity_ml:
            raise ValueError(f"{did} 未配置或进样量超出额定容量")
    recipes = [recipe(row, spec, batch_id, i) for i, row in enumerate(spec.rows())]
    for data in recipes:
        result = validate_source(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        if not result["valid"]:
            raise ValueError("；".join(e["message"] for e in result["errors"]))
    return recipes


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


class GuidedBatch:
    """One supervised batch; registry ownership spans all constituent runs."""
    def __init__(self, dm, spec, batch_id=None, directory=None):
        self.dm, self.spec = dm, spec
        self.batch_id = batch_id or "guided_" + uuid.uuid4().hex
        self.directory = directory
        self.recipes = compile_plan(spec, self.batch_id)
        self.engine = None
        self.executor = StepExecutor(dm)
        self.executor.release_resources_on_cleanup = False
        self.state = ExperimentState.IDLE
        self.stopping = False
        self.task = None
        self.persistence_failure = None
        self.record = dict(batch_id=self.batch_id, state="idle", request=spec.model_dump(),
            created_at=datetime.now(timezone.utc).isoformat(), current_group=0,
            total_groups=len(self.recipes), groups=[],
            error=None, persistence_status="ok", plan_file=f"plans/{self.batch_id}.json")

    @property
    def cleanup_pending(self):
        return bool((self.engine and self.engine.cleanup_pending)
                    or self.executor._reserved_syringes or self.executor._reserved_valves
                    or self.record["persistence_status"] == "error")

    @property
    def exp_logger(self):
        return self.engine.exp_logger if self.engine else None

    @property
    def progress(self):
        return self.engine.progress if self.engine else None

    def save(self):
        self.record["state"] = self.state.value
        self.record["cleanup_required"] = bool(self.engine and self.engine.cleanup_pending)
        try:
            self.record["persistence_status"] = "ok"
            atomic_record(self.record, self.directory)
        except Exception as exc:
            self.record["persistence_status"] = "error"
            self.persistence_failure = str(exc)
            raise

    def snapshot(self):
        result = dict(self.record)
        result["state"] = self.state.value
        result["cleanup_pending"] = self.cleanup_pending
        p = self.progress
        result["progress"] = dict(current_step=p.current_step, total_steps=p.total_steps,
                                  step_id=p.step_id, elapsed=p.elapsed) if p else None
        if p:
            labels = {"feed_both": "两路前驱体进料", "microwave_config": "设置微波反应温度",
                "microwave_start": "微波升温", "hold": "反应保温", "microwave_stop": "停止微波",
                "cool_before_collection": "等待降温至45℃",
                "recheck_temperature": "收取前复查温度", "product_route": "切向产物出口",
                "collect_product": "抽取产物", "collect_product_stop": "停止产物抽取"}
            label = labels.get(p.step_id)
            if label is None:
                label = ("前驱体加热" if p.step_id.startswith("heat_") else
                         "前驱体吸液" if p.step_id.startswith("aspirate_") else
                         "停止前驱体加热" if p.step_id.startswith("heater") else
                         "清洗与排废液" if p.step_id.startswith("clean_") else "本组结束")
            result["progress"]["step_label"] = label
        return result

    async def start(self):
        self.state = ExperimentState.RUNNING
        try:
            # Immutable recipe snapshot, separate from small mutable checkpoints.
            atomic_record(dict(batch_id=self.batch_id, request=self.spec.model_dump(),
                               recipes=self.recipes), Path(self.directory or BATCH_DIR) / "plans")
        except Exception as exc:
            self.record["persistence_status"] = "error"
            self.persistence_failure = str(exc)
            raise
        self.save()  # Do not dispatch hardware if the plan cannot be recorded.
        all_steps = [s for data in self.recipes for s in parse_experiment_data(data)["steps"]]
        try:
            await self.executor.reserve_valves(all_steps)
            await self.executor.reserve_syringes(all_steps)
        except Exception:
            self.executor.release_resources_on_cleanup = True
            self.executor.release_unused_syringes()
            await self.executor.release_valves()
            self.state = ExperimentState.FAILED
            self.save()
            raise
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            for i, data in enumerate(self.recipes):
                if self.stopping:
                    break
                while self.state == ExperimentState.PAUSED and not self.stopping:
                    await asyncio.sleep(0.05)
                if self.stopping:
                    break
                self.record["current_group"] = i+1
                executor = self.executor
                self.engine = ExperimentEngine(executor, ExperimentLogger(save_log=True))
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
                    run_id=run.run_id, sample_id=run.metadata.get("sample_id"), state="running")
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
                    self.save()
                    return
                self.save()
            self.state = ExperimentState.STOPPED if self.stopping else ExperimentState.COMPLETED
            self.save()
        except Exception as exc:
            self.record["error"] = str(exc)
            if self.engine:
                try:
                    await self.engine.stop()
                except Exception as cleanup_exc:
                    self.record["error"] += "; cleanup: " + str(cleanup_exc)
            self.state = ExperimentState.FAILED
            try:
                self.save()
            except Exception:
                pass  # Exposed through the live snapshot; never report persisted success.
        finally:
            self.executor.release_resources_on_cleanup = True
            try:
                if not await self.executor.stop_active_devices():
                    self.state = ExperimentState.FAILED
                    self.record["error"] = (self.record["error"] or "") + "; 停机未确认"
                self.save()
            except Exception as exc:
                self.state = ExperimentState.FAILED
                self.record["error"] = str(exc)

    def checkpoint(self, progress):
        self.record["last_step"] = progress.step_id
        try:
            self.save()
        except Exception:
            self.request_stop()

    async def pause(self):
        if self.stopping or self.state != ExperimentState.RUNNING:
            raise ValueError("批次当前不可暂停")
        self.state = ExperimentState.PAUSED
        if self.engine:
            await self.engine.pause()
        self.save()

    async def resume(self):
        if self.stopping or self.state != ExperimentState.PAUSED:
            raise ValueError("批次当前不可继续")
        self.state = ExperimentState.RUNNING
        try:
            self.save()
        except Exception:
            self.state = ExperimentState.PAUSED
            raise
        if self.engine:
            await self.engine.resume()

    def request_stop(self):
        self.stopping = True
        if self.engine:
            self.engine.request_stop()

    async def stop(self):
        self.request_stop()
        if self.task and not self.task.done():
            await self.task
        success = await self.engine.stop() if self.engine else True
        self.executor.release_resources_on_cleanup = True
        success = await self.executor.stop_active_devices() and success
        if success and self.state not in (ExperimentState.COMPLETED, ExperimentState.FAILED):
            self.state = ExperimentState.STOPPED
        try:
            self.save()
        except Exception:
            return False
        return success


async def preflight(dm, spec):
    """Read-only device readiness check. Never connect or initialize implicitly."""
    if not spec.plumbing_confirmed:
        raise ValueError("请确认进液、排液方向及三通阀实际出口接管")
    for devices, ids in ((dm.get_all_heaters(), ("heater1", "heater2")),
                         (dm.get_all_pumps(), ("pump1",)),
                         (dm.get_all_microwaves(), ("microwave1",)),
                         (dm.valves, ("valve1",))):
        for did in ids:
            if did not in devices or not devices[did].is_connected():
                raise ValueError(f"装置 {did} 未配置或未连接")
    for i in (0, 1):
        control = dm.syringe(f"syringe_pump{i+1}")
        if not control.device.is_connected() or control.owner:
            raise ValueError(f"注射泵 {i+1} 未连接或已占用")
        state = await asyncio.to_thread(control.read)
        if not state.get("read_ok") or state.get("busy") is not False or state.get("fault_code") != 0:
            raise ValueError(f"注射泵 {i+1} 未就绪")
        if not state.get("initialized") or not state.get("position_trusted") or state.get("position") != 0:
            raise ValueError(f"请先初始化注射泵 {i+1} 并确认空行程位置；本功能不自动初始化")
        if max(spec.axes[i+2]) > control.config.capacity_ml:
            raise ValueError(f"进样量超出注射泵 {i+1} 额定容量")
    microwave = await asyncio.to_thread(dm.read_microwave_data, "microwave1")
    if (microwave.get("fault_code") != 0 or microwave.get("output_active") is not False
            or microwave.get("control_active") is not False or microwave.get("stop_confirmed") is not True):
        raise ValueError("微波仪有故障或输出未确认停止")
    pump_status = await asyncio.to_thread(dm.read_pump_status, "pump1")
    for channel in ("3", "4"):
        status = pump_status.get("channels", {}).get(channel, {})
        if status.get("read_ok") is not True or status.get("running") is not False:
            raise ValueError(f"蠕动泵通道 {channel} 未确认停止")
