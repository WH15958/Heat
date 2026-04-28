import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Callable
from enum import Enum

from src.utils.logger import get_logger

logger = get_logger(__name__)

LOGS_DIR = Path("output/experiment_logs")


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class StepLog:
    step_index: int
    step_id: str
    action_type: str
    params: dict
    status: str = StepStatus.PENDING.value
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration: float = 0.0
    result: Optional[str] = None
    error: Optional[str] = None
    wait_type: str = "none"
    wait_duration: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentRun:
    run_id: str
    experiment_name: str
    experiment_file: str
    status: str = RunStatus.RUNNING.value
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    total_duration: float = 0.0
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    steps: List[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ExperimentLogger:
    def __init__(self, save_log: bool = True):
        self._active_run: Optional[ExperimentRun] = None
        self._step_logs: dict[int, StepLog] = {}
        self._on_log: Optional[Callable] = None
        self._save_log = save_log
        if save_log:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def active_run(self) -> Optional[ExperimentRun]:
        return self._active_run

    def on_log(self, callback: Callable):
        self._on_log = callback

    def start_run(self, experiment_name: str, experiment_file: str, total_steps: int, metadata: dict = None) -> str:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self._active_run = ExperimentRun(
            run_id=run_id,
            experiment_name=experiment_name,
            experiment_file=experiment_file,
            started_at=datetime.now().isoformat(),
            total_steps=total_steps,
            metadata=metadata or {},
        )
        self._step_logs = {}
        self._emit("run_started", self._active_run.to_dict())
        logger.info(f"Experiment run started: {run_id} ({experiment_name})")
        return run_id

    def start_step(self, step_index: int, step_id: str, action_type: str, params: dict, wait_type: str = "none"):
        step_log = StepLog(
            step_index=step_index,
            step_id=step_id,
            action_type=action_type,
            params=params,
            status=StepStatus.RUNNING.value,
            started_at=datetime.now().isoformat(),
            wait_type=wait_type,
        )
        self._step_logs[step_index] = step_log
        self._emit("step_started", step_log.to_dict())
        logger.info(f"Step started: [{step_index}] {step_id} ({action_type})")

    def finish_step(self, step_index: int, success: bool, error: str = None, wait_duration: float = 0.0):
        if step_index not in self._step_logs:
            return
        step_log = self._step_logs[step_index]
        step_log.finished_at = datetime.now().isoformat()
        step_log.status = StepStatus.COMPLETED.value if success else StepStatus.FAILED.value
        step_log.error = error
        step_log.wait_duration = wait_duration
        if step_log.started_at:
            start = datetime.fromisoformat(step_log.started_at)
            step_log.duration = (datetime.now() - start).total_seconds()

        if self._active_run:
            self._active_run.steps.append(step_log.to_dict())
            self._active_run.completed_steps = sum(
                1 for s in self._step_logs.values() if s.status == StepStatus.COMPLETED.value
            )
            self._active_run.failed_steps = sum(
                1 for s in self._step_logs.values() if s.status == StepStatus.FAILED.value
            )

        self._emit("step_finished", step_log.to_dict())
        status_text = "completed" if success else f"failed: {error}"
        logger.info(f"Step {status_text}: [{step_index}] {step_log.step_id}")

    def skip_step(self, step_index: int, reason: str = ""):
        if step_index not in self._step_logs:
            return
        step_log = self._step_logs[step_index]
        step_log.status = StepStatus.SKIPPED.value
        step_log.error = reason
        if self._active_run:
            self._active_run.steps.append(step_log.to_dict())
        self._emit("step_skipped", step_log.to_dict())

    def pause_run(self):
        if self._active_run:
            self._active_run.status = RunStatus.PAUSED.value
            self._emit("run_paused", {"run_id": self._active_run.run_id})

    def resume_run(self):
        if self._active_run:
            self._active_run.status = RunStatus.RUNNING.value
            self._emit("run_resumed", {"run_id": self._active_run.run_id})

    def finish_run(self, status: str):
        if not self._active_run:
            return
        self._active_run.status = status
        self._active_run.finished_at = datetime.now().isoformat()
        if self._active_run.started_at:
            start = datetime.fromisoformat(self._active_run.started_at)
            self._active_run.total_duration = (datetime.now() - start).total_seconds()
        self._save_to_file()
        self._emit("run_finished", self._active_run.to_dict())
        logger.info(f"Experiment run {status}: {self._active_run.run_id}")

    def _save_to_file(self):
        if not self._save_log or not self._active_run:
            return
        try:
            filename = f"{self._active_run.run_id}_{self._active_run.experiment_name}.json"
            filepath = LOGS_DIR / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._active_run.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"Experiment log saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save experiment log: {e}")

    def _emit(self, event_type: str, data: dict):
        if self._on_log:
            try:
                self._on_log(event_type, data)
            except Exception as e:
                logger.error(f"Log callback error: {e}")


def list_experiment_runs() -> List[dict]:
    runs = []
    if not LOGS_DIR.exists():
        return runs
    for filepath in sorted(LOGS_DIR.glob("*.json"), reverse=True):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["log_file"] = filepath.name
            runs.append(data)
        except Exception:
            continue
    return runs


def get_experiment_run(run_id: str) -> Optional[dict]:
    if not LOGS_DIR.exists():
        return None
    for filepath in LOGS_DIR.glob("*.json"):
        if filepath.name.startswith(run_id + "_"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None


def delete_experiment_run(run_id: str) -> bool:
    if not LOGS_DIR.exists():
        return False
    for filepath in LOGS_DIR.glob("*.json"):
        if filepath.name.startswith(run_id + "_"):
            try:
                filepath.unlink(missing_ok=True)
                logger.info(f"Experiment log deleted: {filepath}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete experiment log: {e}")
                return False
    return False


def delete_all_experiment_runs() -> int:
    if not LOGS_DIR.exists():
        return 0
    count = 0
    for filepath in LOGS_DIR.glob("*.json"):
        try:
            filepath.unlink(missing_ok=True)
            count += 1
        except Exception as e:
            logger.error(f"Failed to delete experiment log {filepath}: {e}")
    logger.info(f"Deleted {count} experiment logs")
    return count
