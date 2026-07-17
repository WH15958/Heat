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
        self._executor.set_stop_checker(lambda: self._stop_flag)
        self._exp_logger = exp_logger or ExperimentLogger()
        self._state = ExperimentState.IDLE
        self._steps: List[ExperimentStep] = []
        self._current_step = 0
        self._start_time: Optional[float] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        if hasattr(self._executor, "set_pause_checker"):
            self._executor.set_pause_checker(lambda: not self._pause_event.is_set())
        self._stop_flag = False
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_result: Optional[bool] = None
        self._stop_result: Optional[bool] = None
        self._completion_notified = False
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

    @property
    def cleanup_pending(self) -> bool:
        """Whether a prior terminal cleanup failed and still needs retrying."""
        return self._cleanup_result is False

    def on_progress(self, callback: Callable):
        self._on_progress = callback

    def on_complete(self, callback: Callable):
        self._on_complete = callback

    def load_steps(self, steps: List[ExperimentStep], name: str = "", filename: str = "", metadata: dict = None):
        self._steps = [s for s in steps if s.enabled]
        self._current_step = 0
        self._experiment_name = name
        self._experiment_file = filename
        self._metadata = metadata or {}
        logger.info(f"Loaded {len(self._steps)} steps")

    async def start(self):
        if self._state in (ExperimentState.RUNNING, ExperimentState.PAUSED):
            logger.warning("Experiment already active")
            return
        if self.cleanup_pending and not await self._cleanup_active_devices():
            error = "Cannot start experiment while prior device cleanup still fails"
            logger.error(error)
            raise RuntimeError(error)
        self._stop_flag = False
        self._cleanup_task = None
        self._cleanup_result = None
        self._stop_result = None
        self._completion_notified = False
        self._pause_event.set()
        self._exp_logger.start_run(
            experiment_name=self._experiment_name,
            experiment_file=self._experiment_file,
            total_steps=len(self._steps),
            metadata=self._metadata,
        )
        self._state = ExperimentState.RUNNING
        self._start_time = time.time()
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        for i in range(self._current_step, len(self._steps)):
            if self._stop_flag:
                await self._finish_stopped_run()
                return

            await self._pause_event.wait()
            if self._stop_flag:
                await self._finish_stopped_run()
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

            if not self._stop_flag:
                await self._pause_event.wait()

            if self._stop_flag:
                cleanup_ok = await self._cleanup_active_devices()
                error = "Stopped by user"
                if not cleanup_ok:
                    error += "; failed to stop one or more experiment devices"
                self._exp_logger.finish_step(
                    i, success=False, error=error, wait_duration=wait_duration
                )
                self._finish_terminal_run(
                    ExperimentState.STOPPED if cleanup_ok else ExperimentState.FAILED,
                    RunStatus.STOPPED.value if cleanup_ok else RunStatus.FAILED.value,
                    cleanup_complete=cleanup_ok,
                )
                self._stop_result = cleanup_ok
                return

            if not success:
                if step.on_error == "stop":
                    cleanup_ok = await self._cleanup_active_devices()
                    error = "Execution failed"
                    if not cleanup_ok:
                        error += "; failed to stop one or more experiment devices"
                    self._exp_logger.finish_step(
                        i, success=False, error=error, wait_duration=wait_duration
                    )
                    self._finish_terminal_run(
                        ExperimentState.FAILED,
                        RunStatus.FAILED.value,
                        cleanup_complete=cleanup_ok,
                    )
                    self._stop_result = cleanup_ok
                    return
                elif step.on_error == "skip":
                    self._exp_logger.skip_step(i, reason="Skipped due to error")
                    logger.warning(f"Skipping failed step: {step.id}")
                    continue
            else:
                self._exp_logger.finish_step(i, success=True, wait_duration=wait_duration)

        self._current_step = len(self._steps)
        cleanup_ok = await self._cleanup_active_devices()
        if not cleanup_ok:
            logger.error(
                "Experiment completion failed to stop one or more active devices"
            )
        self._finish_terminal_run(
            ExperimentState.COMPLETED if cleanup_ok else ExperimentState.FAILED,
            RunStatus.COMPLETED.value if cleanup_ok else RunStatus.FAILED.value,
            cleanup_complete=cleanup_ok,
        )
        self._stop_result = cleanup_ok

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
        running_task = self._task
        waited_for_running_task = running_task is not None and not running_task.done()
        if waited_for_running_task:
            await running_task
            if self._stop_result is not None:
                return self._stop_result

        if self._stop_result is True:
            return True

        self._stop_result = await self._cleanup_active_devices()
        if self._stop_result:
            self._notify_complete()
        return self._stop_result

    async def _finish_stopped_run(self) -> bool:
        cleanup_ok = await self._cleanup_active_devices()
        if not cleanup_ok:
            logger.error("Experiment stop failed to stop one or more active devices")
        self._finish_terminal_run(
            ExperimentState.STOPPED if cleanup_ok else ExperimentState.FAILED,
            RunStatus.STOPPED.value if cleanup_ok else RunStatus.FAILED.value,
            cleanup_complete=cleanup_ok,
        )
        self._stop_result = cleanup_ok
        return cleanup_ok

    async def _cleanup_active_devices(self) -> bool:
        if self._cleanup_result is True:
            return True

        cleanup_task = self._cleanup_task
        if cleanup_task is None:
            stop_active_devices = getattr(self._executor, "stop_active_devices", None)
            if not callable(stop_active_devices):
                logger.error("Experiment executor does not support active-device cleanup")
                self._cleanup_result = False
                return False
            try:
                cleanup_task = asyncio.create_task(stop_active_devices())
                self._cleanup_task = cleanup_task
            except Exception as e:
                logger.error(f"Failed to start experiment active-device cleanup: {e}")
                self._cleanup_result = False
                return False

        try:
            cleanup_result = bool(await cleanup_task)
        except Exception as e:
            logger.error(f"Experiment active-device cleanup failed: {e}")
            cleanup_result = False
        finally:
            if self._cleanup_task is cleanup_task:
                self._cleanup_task = None

        self._cleanup_result = cleanup_result
        return self._cleanup_result

    def _finish_terminal_run(
        self,
        state: ExperimentState,
        run_status: str,
        cleanup_complete: bool = True,
    ):
        self._state = state
        self._exp_logger.finish_run(run_status)
        self._notify()
        if cleanup_complete:
            self._notify_complete()

    def _notify(self):
        if self._on_progress:
            self._on_progress(self.progress)

    def _notify_complete(self):
        if self._completion_notified:
            return
        self._completion_notified = True
        if self._on_complete:
            try:
                self._on_complete()
            except Exception as e:
                logger.error(f"on_complete callback error: {e}")
