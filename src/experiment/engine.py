import asyncio
import time
from enum import Enum
from typing import Optional, Callable, List
from dataclasses import dataclass

from src.experiment.actions import ExperimentStep
from src.experiment.executor import StepExecutor
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExperimentState(Enum):
    """实验状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ExperimentProgress:
    """实验进度

    Attributes:
        current_step: 当前步骤索引
        total_steps: 总步骤数
        step_id: 当前步骤ID
        state: 实验状态
        elapsed: 已运行秒数
        message: 状态消息
    """
    current_step: int = 0
    total_steps: int = 0
    step_id: str = ""
    state: ExperimentState = ExperimentState.IDLE
    elapsed: float = 0.0
    message: str = ""


class ExperimentEngine:
    """实验流程引擎 - 管理实验生命周期和步骤执行

    支持启动、暂停、恢复、停止操作。
    通过回调函数通知进度更新。
    """

    def __init__(self, executor: StepExecutor):
        self._executor = executor
        self._state = ExperimentState.IDLE
        self._steps: List[ExperimentStep] = []
        self._current_step = 0
        self._start_time: Optional[float] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_flag = False
        self._on_progress: Optional[Callable] = None
        self._task: Optional[asyncio.Task] = None

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

    def on_progress(self, callback: Callable):
        """注册进度回调

        Args:
            callback: 进度回调函数，接收ExperimentProgress参数
        """
        self._on_progress = callback

    def load_steps(self, steps: List[ExperimentStep]):
        """加载实验步骤

        Args:
            steps: 步骤列表
        """
        self._steps = [s for s in steps if s.enabled]
        self._current_step = 0
        logger.info(f"Loaded {len(self._steps)} steps")

    async def start(self):
        """启动实验"""
        if self._state == ExperimentState.RUNNING:
            logger.warning("Experiment already running")
            return
        self._state = ExperimentState.RUNNING
        self._stop_flag = False
        self._pause_event.set()
        self._start_time = time.time()
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        """执行所有步骤"""
        for i in range(self._current_step, len(self._steps)):
            if self._stop_flag:
                self._state = ExperimentState.STOPPED
                self._notify()
                return

            await self._pause_event.wait()
            if self._stop_flag:
                self._state = ExperimentState.STOPPED
                self._notify()
                return

            self._current_step = i
            self._notify()

            step = self._steps[i]
            success = await self._executor.execute(step)

            if not success:
                if step.on_error == "stop":
                    self._state = ExperimentState.FAILED
                    self._notify()
                    return
                elif step.on_error == "skip":
                    logger.warning(f"Skipping failed step: {step.id}")
                    continue

        self._current_step = len(self._steps)
        self._state = ExperimentState.COMPLETED
        self._notify()

    async def pause(self):
        """暂停实验"""
        if self._state == ExperimentState.RUNNING:
            self._pause_event.clear()
            self._state = ExperimentState.PAUSED
            self._notify()

    async def resume(self):
        """恢复实验"""
        if self._state == ExperimentState.PAUSED:
            self._pause_event.set()
            self._state = ExperimentState.RUNNING
            self._notify()

    async def stop(self):
        """停止实验"""
        self._stop_flag = True
        self._pause_event.set()

    def _notify(self):
        """通知进度更新"""
        if self._on_progress:
            self._on_progress(self.progress)
