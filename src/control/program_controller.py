"""
程序控制模块

实现温度和流量的联动控制，支持：
- 温度触发泵启动
- 程序段控制
- 多步骤实验流程
- 自动化实验序列
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class StepType(IntEnum):
    """步骤类型"""
    HEAT = 1
    HOLD = 2
    COOL = 3
    PUMP_START = 4
    PUMP_STOP = 5
    PUMP_DISPENSE = 6
    WAIT = 7
    LOOP = 8
    END = 9


class TriggerType(IntEnum):
    """触发类型"""
    NONE = 0
    TEMPERATURE_REACHED = 1
    TIME_ELAPSED = 2
    PUMP_COMPLETE = 3
    MANUAL = 4


@dataclass
class ProgramStep:
    """程序步骤"""
    step_id: int
    step_type: StepType
    name: str = ""
    description: str = ""

    temperature: float = 0.0
    hold_time: float = 0.0
    ramp_rate: float = 5.0

    pump_channel: int = 1
    pump_flow_rate: float = 0.0
    pump_volume: float = 0.0
    pump_direction: int = 0

    wait_time: float = 0.0

    trigger: TriggerType = TriggerType.NONE
    trigger_value: float = 0.0

    next_step: int = -1
    loop_count: int = 1
    loop_start: int = -1


@dataclass
class ProgramConfig:
    """程序配置"""
    name: str
    description: str = ""
    steps: List[ProgramStep] = field(default_factory=list)
    auto_start: bool = False
    safety_temperature: float = 450.0
    max_duration: float = 86400.0


@dataclass
class ProgramStatus:
    """程序运行状态"""
    running: bool = False
    paused: bool = False
    current_step: int = 0
    step_start_time: Optional[datetime] = None
    elapsed_time: float = 0.0
    remaining_time: float = 0.0
    loop_counter: int = 0
    completed: bool = False
    error: Optional[str] = None


class ProgramController:
    """
    程序控制器

    实现温度和流量的联动控制，支持多步骤程序执行。
    使用asyncio架构，串口操作通过run_in_executor调度，
    确保与Web层共享同一事件循环，避免并发串口访问。

    Example:
        >>> controller = ProgramController(heater, pump)
        >>> program = ProgramConfig(
        ...     name="实验程序",
        ...     steps=[
        ...         ProgramStep(step_id=1, step_type=StepType.HEAT, temperature=100),
        ...         ProgramStep(step_id=2, step_type=StepType.PUMP_START, pump_channel=1, pump_flow_rate=50),
        ...         ProgramStep(step_id=3, step_type=StepType.HOLD, hold_time=300),
        ...         ProgramStep(step_id=4, step_type=StepType.PUMP_STOP, pump_channel=1),
        ...         ProgramStep(step_id=5, step_type=StepType.END),
        ...     ]
        ... )
        >>> controller.load_program(program)
        >>> await controller.start()
    """

    def __init__(self, heater=None, pump=None):
        """
        初始化程序控制器

        Args:
            heater: 加热器设备实例
            pump: 蠕动泵设备实例
        """
        self._heater = heater
        self._pump = pump
        self._program: Optional[ProgramConfig] = None
        self._status = ProgramStatus()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._callbacks: Dict[str, List[Callable]] = {
            'on_step_start': [],
            'on_step_complete': [],
            'on_program_complete': [],
            'on_error': [],
        }
        self._logger = logging.getLogger(__name__)

    @property
    def status(self) -> ProgramStatus:
        return self._status

    @property
    def program(self) -> Optional[ProgramConfig]:
        """获取当前程序"""
        return self._program

    def set_devices(self, heater=None, pump=None):
        """
        设置设备实例

        Args:
            heater: 加热器设备
            pump: 蠕动泵设备
        """
        self._heater = heater
        self._pump = pump

    def add_callback(self, event: str, callback: Callable):
        """
        添加事件回调

        Args:
            event: 事件名称
            callback: 回调函数
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callbacks(self, event: str, *args, **kwargs):
        """触发事件回调"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                self._logger.error(f"Callback error: {e}")

    def load_program(self, program: ProgramConfig):
        """
        加载程序

        Args:
            program: 程序配置
        """
        self._program = program
        self._status = ProgramStatus()
        self._logger.info(f"Program loaded: {program.name}")

    async def start(self) -> bool:
        """
        启动程序

        Returns:
            bool: 启动成功返回True
        """
        if self._program is None:
            self._logger.error("No program loaded")
            return False

        if self._status.running:
            self._logger.warning("Program already running")
            return False

        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._stop_event.clear()
        self._pause_event.set()
        self._status.running = True
        self._status.paused = False
        self._status.completed = False
        self._status.current_step = 0
        self._status.error = None

        self._task = asyncio.create_task(self._run_program())

        self._logger.info("Program started")
        return True

    async def stop(self):
        """停止程序"""
        self._stop_event.set()
        self._pause_event.set()

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._status.running = False
        self._status.paused = False

        if self._pump is not None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._pump.stop_all)

        self._logger.info("Program stopped")

    async def pause(self):
        """暂停程序执行"""
        self._pause_event.clear()
        self._status.paused = True
        self._logger.info("Program paused")

    async def resume(self):
        """恢复程序执行"""
        self._pause_event.set()
        self._status.paused = False
        self._logger.info("Program resumed")

    async def _run_program(self):
        try:
            while not self._stop_event.is_set():
                await self._pause_event.wait()

                if self._stop_event.is_set():
                    break

                if self._status.current_step >= len(self._program.steps):
                    self._complete_program()
                    break

                step = self._program.steps[self._status.current_step]

                if not await self._execute_step(step):
                    break

                self._status.current_step += 1

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._status.error = str(e)
            self._logger.error(f"Program error: {e}")
            self._trigger_callbacks('on_error', e)
        finally:
            self._status.running = False
            self._task = None

    async def _execute_step(self, step: ProgramStep) -> bool:
        """
        执行单个步骤

        Args:
            step: 程序步骤

        Returns:
            bool: 成功返回True
        """
        self._status.step_start_time = datetime.now()
        self._trigger_callbacks('on_step_start', step)

        self._logger.info(f"Executing step {step.step_id}: {step.name or step.step_type.name}")

        try:
            if step.step_type == StepType.HEAT:
                return await self._execute_heat(step)
            elif step.step_type == StepType.HOLD:
                return await self._execute_hold(step)
            elif step.step_type == StepType.COOL:
                return await self._execute_cool(step)
            elif step.step_type == StepType.PUMP_START:
                return await self._execute_pump_start(step)
            elif step.step_type == StepType.PUMP_STOP:
                return await self._execute_pump_stop(step)
            elif step.step_type == StepType.PUMP_DISPENSE:
                return await self._execute_pump_dispense(step)
            elif step.step_type == StepType.WAIT:
                return await self._execute_wait(step)
            elif step.step_type == StepType.LOOP:
                return self._execute_loop(step)
            elif step.step_type == StepType.END:
                return await self._execute_end(step)
            else:
                self._logger.warning(f"Unknown step type: {step.step_type}")
                return True

        except Exception as e:
            self._logger.error(f"Step execution error: {e}")
            self._status.error = str(e)
            return False
        finally:
            self._trigger_callbacks('on_step_complete', step)

    async def _execute_heat(self, step: ProgramStep) -> bool:
        """执行加热步骤"""
        if self._heater is None:
            self._logger.warning("No heater configured")
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._heater.set_temperature, step.temperature)
        await loop.run_in_executor(None, self._heater.start)

        if step.trigger == TriggerType.TEMPERATURE_REACHED:
            tolerance = step.trigger_value if step.trigger_value > 0 else 2.0
            while not self._stop_event.is_set():
                await self._pause_event.wait()
                data = await loop.run_in_executor(None, self._heater.read_data)
                if abs(data.pv - step.temperature) <= tolerance:
                    break
                await asyncio.sleep(0.5)

        return True

    async def _execute_hold(self, step: ProgramStep) -> bool:
        import time
        start_time = time.time()

        while not self._stop_event.is_set():
            await self._pause_event.wait()
            elapsed = time.time() - start_time
            self._status.elapsed_time = elapsed
            self._status.remaining_time = max(0, step.hold_time - elapsed)

            if elapsed >= step.hold_time:
                break

            await asyncio.sleep(0.5)

        return True

    async def _execute_cool(self, step: ProgramStep) -> bool:
        """执行冷却步骤"""
        if self._heater is None:
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._heater.stop)

        if step.trigger == TriggerType.TEMPERATURE_REACHED:
            tolerance = step.trigger_value if step.trigger_value > 0 else 5.0
            while not self._stop_event.is_set():
                await self._pause_event.wait()
                data = await loop.run_in_executor(None, self._heater.read_data)
                if data.pv <= step.temperature + tolerance:
                    break
                await asyncio.sleep(1.0)

        return True

    async def _execute_pump_start(self, step: ProgramStep) -> bool:
        """执行泵启动步骤"""
        if self._pump is None:
            self._logger.warning("No pump configured")
            return True

        loop = asyncio.get_event_loop()
        if step.pump_flow_rate > 0:
            await loop.run_in_executor(None, self._pump.set_flow_rate, step.pump_channel, step.pump_flow_rate)

        await loop.run_in_executor(None, self._pump.set_direction, step.pump_channel, step.pump_direction)
        await loop.run_in_executor(None, self._pump.start_channel, step.pump_channel)

        return True

    async def _execute_pump_stop(self, step: ProgramStep) -> bool:
        """执行泵停止步骤"""
        if self._pump is None:
            return True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._pump.stop_channel, step.pump_channel)
        return True

    async def _execute_pump_dispense(self, step: ProgramStep) -> bool:
        """执行定量分装步骤"""
        if self._pump is None:
            return True

        from protocols.pump_params import PumpRunMode
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._pump.set_run_mode, step.pump_channel, PumpRunMode.TIME_QUANTITY)
        await loop.run_in_executor(None, self._pump.set_dispense_volume, step.pump_channel, step.pump_volume)
        await loop.run_in_executor(None, self._pump.set_flow_rate, step.pump_channel, step.pump_flow_rate)
        await loop.run_in_executor(None, self._pump.start_channel, step.pump_channel)

        if step.trigger == TriggerType.PUMP_COMPLETE:
            while not self._stop_event.is_set():
                await self._pause_event.wait()
                data = await loop.run_in_executor(None, self._pump.read_channel_status, step.pump_channel)
                if data is not None and not data.running:
                    break
                await asyncio.sleep(0.5)

        return True

    async def _execute_wait(self, step: ProgramStep) -> bool:
        import time
        start_time = time.time()

        while not self._stop_event.is_set():
            await self._pause_event.wait()
            elapsed = time.time() - start_time
            self._status.elapsed_time = elapsed
            self._status.remaining_time = max(0, step.wait_time - elapsed)

            if elapsed >= step.wait_time:
                break

            await asyncio.sleep(0.5)

        return True

    def _execute_loop(self, step: ProgramStep) -> bool:
        if step.loop_start < 0:
            return True

        self._status.loop_counter += 1

        if self._status.loop_counter < step.loop_count:
            self._status.current_step = step.loop_start - 1
        else:
            self._status.loop_counter = 0

        return True

    async def _execute_end(self, step: ProgramStep) -> bool:
        """执行结束步骤"""
        loop = asyncio.get_event_loop()
        if self._pump is not None:
            await loop.run_in_executor(None, self._pump.stop_all)
        if self._heater is not None:
            await loop.run_in_executor(None, self._heater.stop)

        return True

    def _complete_program(self):
        self._status.completed = True
        self._status.running = False
        self._logger.info("Program completed")
        self._trigger_callbacks('on_program_complete')

    def create_simple_program(
        self,
        temperature: float,
        hold_time: float,
        pump_channel: int = 1,
        pump_flow_rate: float = 0.0,
        pump_volume: float = 0.0,
    ) -> ProgramConfig:
        """
        创建简单程序

        Args:
            temperature: 目标温度
            hold_time: 保持时间(秒)
            pump_channel: 泵通道
            pump_flow_rate: 流速
            pump_volume: 分装量

        Returns:
            ProgramConfig: 程序配置
        """
        steps = [
            ProgramStep(
                step_id=1,
                step_type=StepType.HEAT,
                name="加热",
                temperature=temperature,
                trigger=TriggerType.TEMPERATURE_REACHED,
                trigger_value=2.0,
            ),
        ]

        if pump_flow_rate > 0:
            steps.append(ProgramStep(
                step_id=2,
                step_type=StepType.PUMP_START,
                name="启动泵",
                pump_channel=pump_channel,
                pump_flow_rate=pump_flow_rate,
            ))

        steps.append(ProgramStep(
            step_id=3,
            step_type=StepType.HOLD,
            name="保持",
            hold_time=hold_time,
        ))

        if pump_flow_rate > 0:
            steps.append(ProgramStep(
                step_id=4,
                step_type=StepType.PUMP_STOP,
                name="停止泵",
                pump_channel=pump_channel,
            ))

        steps.append(ProgramStep(
            step_id=5,
            step_type=StepType.END,
            name="结束",
        ))

        return ProgramConfig(
            name="简单程序",
            description=f"加热到{temperature}°C，保持{hold_time}秒",
            steps=steps,
        )
