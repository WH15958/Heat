import asyncio
import time
from enum import Enum
from typing import Optional, Callable, List
from dataclasses import dataclass

from src.experiment.actions import ExperimentStep
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger, RunStatus
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExperimentState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ExperimentProgress:
    current_step: int = 0
    total_steps: int = 0
    step_id: str = ""
    state: ExperimentState = ExperimentState.IDLE
    elapsed: float = 0.0
    message: str = ""


class ExperimentEngine:
    def __init__(self, executor: StepExecutor, exp_logger: Optional[ExperimentLogger] = None):
        self._executor = executor
        self._exp_logger = exp_logger or ExperimentLogger()
        self._state = ExperimentState.IDLE
        self._steps: List[ExperimentStep] = []
        self._current_step = 0
        self._start_time: Optional[float] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_flag = False
        self._on_progress: Optional[Callable] = None
        self._task: Optional[asyncio.Task] = None
        self._experiment_name: str = ""
        self._experiment_file: str = ""

    @property
    def state(self) -> ExperimentState:
        return self._state

    @property
    def progress(self) -> ExperimentProgress:
        step = (
            self._steps[self._current_step]
            if self._current_step < len(self._steps)
            else None
        )
        elapsed = time.time() - self._start_time if self._start_time else 0
        return ExperimentProgress(
            current_step=self._current_step,
            total_steps=len(self._steps),
            step_id=step.id if step else "",
            state=self._state,
            elapsed=elapsed,
        )

    @property
    def exp_logger(self) -> ExperimentLogger:
        return self._exp_logger

    def on_progress(self, callback: Callable):
        self._on_progress = callback

    def load_steps(self, steps: List[ExperimentStep], name: str = "", filename: str = ""):
        self._steps = [s for s in steps if s.enabled]
        self._current_step = 0
        self._experiment_name = name
        self._experiment_file = filename
        logger.info(f"Loaded {len(self._steps)} steps")

    async def start(self):
        if self._state == ExperimentState.RUNNING:
            logger.warning("Experiment already running")
            return
        self._state = ExperimentState.RUNNING
        self._stop_flag = False
        self._pause_event.set()
        self._start_time = time.time()
        self._exp_logger.start_run(
            experiment_name=self._experiment_name,
            experiment_file=self._experiment_file,
            total_steps=len(self._steps),
        )
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        for i in range(self._current_step, len(self._steps)):
            if self._stop_flag:
                self._state = ExperimentState.STOPPED
                self._exp_logger.finish_run(RunStatus.STOPPED.value)
                self._notify()
                return

            await self._pause_event.wait()
            if self._stop_flag:
                self._state = ExperimentState.STOPPED
                self._exp_logger.finish_run(RunStatus.STOPPED.value)
                self._notify()
                return

            self._current_step = i
            self._notify()

            step = self._steps[i]
            self._exp_logger.start_step(
                step_index=i,
                step_id=step.id,
                action_type=step.type.value,
                params=step.params,
                wait_type=step.wait.type.value,
            )

            step_start = time.time()
            success = await self._executor.execute(step)
            wait_duration = time.time() - step_start

            if not success:
                self._exp_logger.finish_step(i, success=False, error="Execution failed", wait_duration=wait_duration)
                if step.on_error == "stop":
                    self._state = ExperimentState.FAILED
                    self._exp_logger.finish_run(RunStatus.FAILED.value)
                    self._notify()
                    return
                elif step.on_error == "skip":
                    self._exp_logger.skip_step(i, reason="Skipped due to error")
                    logger.warning(f"Skipping failed step: {step.id}")
                    continue
            else:
                self._exp_logger.finish_step(i, success=True, wait_duration=wait_duration)

        self._current_step = len(self._steps)
        self._state = ExperimentState.COMPLETED
        self._exp_logger.finish_run(RunStatus.COMPLETED.value)
        self._notify()

    async def pause(self):
        if self._state == ExperimentState.RUNNING:
            self._pause_event.clear()
            self._state = ExperimentState.PAUSED
            self._exp_logger.pause_run()
            self._notify()

    async def resume(self):
        if self._state == ExperimentState.PAUSED:
            self._pause_event.set()
            self._state = ExperimentState.RUNNING
            self._exp_logger.resume_run()
            self._notify()

    async def stop(self):
        self._stop_flag = True
        self._pause_event.set()

    def _notify(self):
        if self._on_progress:
            self._on_progress(self.progress)
