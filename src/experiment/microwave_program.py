"""Computer-owned logical microwave stages; drivers remain synchronous."""
import asyncio
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine, ExperimentState
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger
from src.utils.config import ConfigManager

PROGRAM_DIR = Path(__file__).resolve().parents[2] / "output" / "microwave_programs"
TERMINAL = {"completed", "failed", "stopped"}


class LogicalStage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    temperature: float = Field(ge=0, le=300, allow_inf_nan=False)
    hold_seconds: int = Field(ge=0, le=359999)
    power_percent: int = Field(default=0, ge=0, le=100)


class ProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    mode: Literal["auto_power", "manual_power"]
    stages: list[LogicalStage] = Field(min_length=1, max_length=5)
    heating_timeout: int = Field(default=600, ge=1, le=3600)
    hardware_confirmed: bool = False


def compile_steps(device_id, spec):
    config = next((m for m in ConfigManager().load().microwaves
                   if m.device_id == device_id and m.enabled), None)
    if config is None or any(s.temperature > config.max_temperature for s in spec.stages):
        raise ValueError("微波仪未配置、未启用或温度超出设备范围")
    steps = []
    for index, stage in enumerate(spec.stages, 1):
        # All five firmware slots share one logical target, regardless of HMI range.
        # Device hold exceeds the entire host stage; zero-time skipping is not used.
        guard = spec.heating_timeout + stage.hold_seconds + 60
        if guard > 99 * 3600 + 59 * 60 + 59:
            raise ValueError("阶段时间加设备保护计时超出99小时59分59秒")
        params = dict(heating_temperature=stage.temperature, target_temperature=stage.temperature,
                      holding_temperature=stage.temperature, hours=guard // 3600,
                      minutes=guard % 3600 // 60, seconds=guard % 60)
        if spec.mode == "manual_power":
            params.update(heating_power_percent=stage.power_percent,
                          holding_power_percent=stage.power_percent, holding_deviation=0)
        config_action = (ActionType.MICROWAVE_CONFIGURE_AUTO_POWER if spec.mode == "auto_power"
                         else ActionType.MICROWAVE_CONFIGURE_MANUAL)
        steps.extend([
            ExperimentStep(f"stage_{index}_configure", config_action, dict(device_id=device_id,
                segments=[dict(segment=n, **params) for n in range(1, 6)])),
            ExperimentStep(f"stage_{index}_heat", ActionType.MICROWAVE_START,
                dict(device_id=device_id, mode=spec.mode), WaitCondition(
                    type=WaitType.MICROWAVE_TEMPERATURE_REACHED, device_id=device_id,
                    target_temperature=stage.temperature, tolerance=1, timeout=spec.heating_timeout)),
            ExperimentStep(f"stage_{index}_hold", ActionType.WAIT, wait=WaitCondition(
                type=WaitType.MICROWAVE_MONITORED_HOLD, device_id=device_id, seconds=stage.hold_seconds)),
            ExperimentStep(f"stage_{index}_stop", ActionType.MICROWAVE_STOP, dict(device_id=device_id)),
        ])
    return steps


async def preflight(dm, device_id):
    data = await asyncio.to_thread(dm.read_microwave_data, device_id)
    temperature = data.get("material_temperature")
    if (data.get("error") or data.get("read_ok") is False or data.get("fault_code") != 0
            or data.get("status_confirmed") is not True or data.get("stop_confirmed") is not True
            or data.get("control_active") is not False or data.get("output_active") is not False
            or not isinstance(temperature, (int, float)) or isinstance(temperature, bool)
            or not math.isfinite(temperature) or temperature < 0):
        raise ValueError("微波状态未知、存在故障或未确认停止，请先检查设备")


def write_record(record):
    PROGRAM_DIR.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=PROGRAM_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, PROGRAM_DIR / (record["program_id"] + ".json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stored_records(live):
    records = []
    for path in PROGRAM_DIR.glob("mwprogram_*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["program_id"] not in live and (record["state"] not in TERMINAL or record.get("cleanup_required")):
            record.update(state="interrupted", recovery_required=True)
        records.append(record)
    return records


class MicrowaveProgramRun:
    def __init__(self, dm, device_id, spec):
        self.executor = StepExecutor(dm)
        self.engine = ExperimentEngine(self.executor, ExperimentLogger(save_log=True))
        self.engine.load_steps(compile_steps(device_id, spec), "电脑托管微波程序",
            metadata=dict(run_kind="microwave_program", program_id="mwprogram_" + spec.request_id,
                device_id=device_id, mode=spec.mode, heating_timeout=spec.heating_timeout,
                logical_stages=[s.model_dump() for s in spec.stages]))
        self.engine.on_progress(self.checkpoint)
        self.task = None
        self.record = dict(program_id="mwprogram_" + spec.request_id, device_id=device_id,
            request=spec.model_dump(), created_at=datetime.now(timezone.utc).isoformat(),
            state="idle", current_stage=0, phase="ready", total_stages=len(spec.stages),
            recovery_required=False, cleanup_required=False, error=None, persistence_status="ok")

    @property
    def state(self):
        return self.engine.state

    @property
    def progress(self):
        return self.engine.progress

    @property
    def exp_logger(self):
        return self.engine.exp_logger

    @property
    def cleanup_pending(self):
        return (self.engine.cleanup_pending or self.record["recovery_required"]
                or self.record["persistence_status"] == "error")

    def request_stop(self):
        self.engine.request_stop()

    def save(self):
        self.record["state"] = self.state.value
        self.record["cleanup_required"] = bool(self.executor._active_microwaves or self.engine.cleanup_pending)
        if self.exp_logger.active_run:
            self.record["run_id"] = self.exp_logger.active_run.run_id
        self.record["persistence_status"] = "ok"
        try:
            write_record(self.record)
        except Exception:
            self.record["persistence_status"] = "error"
            self.record["recovery_required"] = True
            self.request_stop()
            raise

    def checkpoint(self, progress):
        match = re.fullmatch(r"stage_(\d+)_(\w+)", progress.step_id)
        if match:
            self.record.update(current_stage=int(match[1]), phase=match[2])
            if match[2] == "configure" and progress.state == ExperimentState.RUNNING:
                self.executor._active_microwaves.add(self.record["device_id"])
        if progress.state == ExperimentState.FAILED:
            self.record["recovery_required"] = True
        if self.executor.last_device_result is not None:
            self.record["last_device_result"] = self.executor.last_device_result
        self.save()  # Before each hardware step; failure prevents the next command.

    async def start(self):
        self.record.update(state="running", cleanup_required=True)
        write_record(self.record)  # Durable intent must precede any hardware write.
        await self.engine.start()
        self.task = asyncio.create_task(self.finish())

    async def finish(self):
        try:
            await self.engine.wait_finished()
        except Exception as exc:
            self.record["error"] = str(exc)
        finally:
            self.record["recovery_required"] = (self.state == ExperimentState.FAILED
                or self.engine.cleanup_pending or self.record["persistence_status"] == "error")
            run = self.exp_logger.active_run
            if self.state == ExperimentState.FAILED:
                self.record["error"] = self.record["error"] or self.executor.last_error or "程序执行或停机失败"
            if run and run.persistence_status == "error":
                self.record.update(recovery_required=True, error="运行日志保存失败")
            self.record["phase"] = self.state.value
            try:
                self.save()
            except Exception:
                pass  # Live lock remains; the last durable intent also locks after restart.

    async def stop(self):
        success = False
        try:
            success = await self.engine.stop()
        except Exception as exc:
            self.record.update(recovery_required=True, error=str(exc))
        try:
            if self.task and self.task is not asyncio.current_task():
                await self.task
            self.save()
            return success
        except Exception as exc:
            self.record.update(recovery_required=True, error=str(exc))
            return False

    def snapshot(self):
        p = self.progress
        return dict(self.record, state=self.state.value, cleanup_pending=self.cleanup_pending,
                    elapsed=p.elapsed, step_id=p.step_id,
                    run_id=self.exp_logger.active_run.run_id if self.exp_logger.active_run else None)
