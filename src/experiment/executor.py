import asyncio
import time

from src.experiment.actions import (
    ExperimentStep,
    ActionType,
    WaitType,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StepExecutor:
    """步骤执行器 - 执行单个实验步骤并等待条件满足"""

    def __init__(self, device_manager):
        self._dm = device_manager

    async def execute(self, step: ExperimentStep) -> bool:
        """执行一个步骤

        Args:
            step: 实验步骤

        Returns:
            bool: 执行成功返回True
        """
        logger.info(f"Executing step: {step.id} ({step.type.value})")

        try:
            loop = asyncio.get_event_loop()

            if step.type == ActionType.HEATER_SET_TEMP:
                heater = self._dm._heaters.get(step.params["device_id"])
                if heater is None:
                    raise ValueError(f"Heater not found: {step.params['device_id']}")
                await loop.run_in_executor(
                    None, heater.set_temperature, step.params["temperature"]
                )

            elif step.type == ActionType.HEATER_START:
                heater = self._dm._heaters.get(step.params["device_id"])
                if heater is None:
                    raise ValueError(f"Heater not found: {step.params['device_id']}")
                await loop.run_in_executor(None, heater.start)

            elif step.type == ActionType.HEATER_STOP:
                heater = self._dm._heaters.get(step.params["device_id"])
                if heater is None:
                    raise ValueError(f"Heater not found: {step.params['device_id']}")
                await loop.run_in_executor(None, heater.stop)

            elif step.type == ActionType.PUMP_START:
                pump = self._dm._pumps.get(step.params["device_id"])
                if pump is None:
                    raise ValueError(f"Pump not found: {step.params['device_id']}")
                from protocols.pump_params import PumpRunMode, PumpDirection

                ch = step.params["channel"]
                direction = PumpDirection.CLOCKWISE
                if step.params.get("direction") == "CCW":
                    direction = PumpDirection.COUNTER_CLOCKWISE
                mode_map = {
                    "FLOW_MODE": PumpRunMode.FLOW_MODE,
                    "TIME_QUANTITY": PumpRunMode.TIME_QUANTITY,
                    "TIME_SPEED": PumpRunMode.TIME_SPEED,
                    "QUANTITY_SPEED": PumpRunMode.QUANTITY_SPEED,
                }
                mode = mode_map.get(
                    step.params.get("mode", "FLOW_MODE"), PumpRunMode.FLOW_MODE
                )
                await loop.run_in_executor(None, pump.set_direction, ch, direction)
                await loop.run_in_executor(None, pump.set_run_mode, ch, mode)
                await loop.run_in_executor(
                    None,
                    pump.set_flow_rate,
                    ch,
                    step.params.get("flow_rate", 10.0),
                )
                if step.params.get("run_time") and mode in (
                    PumpRunMode.TIME_QUANTITY,
                    PumpRunMode.TIME_SPEED,
                ):
                    await loop.run_in_executor(
                        None, pump.set_run_time, ch, step.params["run_time"]
                    )
                if step.params.get("dispense_volume") and mode in (
                    PumpRunMode.TIME_QUANTITY,
                    PumpRunMode.QUANTITY_SPEED,
                ):
                    await loop.run_in_executor(
                        None,
                        pump.set_dispense_volume,
                        ch,
                        step.params["dispense_volume"],
                    )
                await loop.run_in_executor(None, pump.start_channel, ch)

            elif step.type == ActionType.PUMP_STOP:
                pump = self._dm._pumps.get(step.params["device_id"])
                if pump is None:
                    raise ValueError(f"Pump not found: {step.params['device_id']}")
                await loop.run_in_executor(None, pump.stop_all)

            elif step.type == ActionType.PUMP_STOP_CHANNEL:
                pump = self._dm._pumps.get(step.params["device_id"])
                if pump is None:
                    raise ValueError(f"Pump not found: {step.params['device_id']}")
                await loop.run_in_executor(
                    None, pump.stop_channel, step.params["channel"]
                )

            elif step.type == ActionType.WAIT:
                pass

            elif step.type == ActionType.EMERGENCY_STOP:
                await loop.run_in_executor(None, self._dm.emergency_stop_all)

            elif step.type == ActionType.LOG:
                logger.info(f"[Experiment] {step.params.get('message', '')}")

            else:
                logger.warning(f"Unknown action type: {step.type}")
                return False

            if step.wait.type != WaitType.NONE:
                await self._wait_condition(step.wait)

            logger.info(f"Step completed: {step.id}")
            return True

        except Exception as e:
            logger.error(f"Step {step.id} failed: {e}")
            return False

    async def _wait_condition(self, condition):
        """等待条件满足

        Args:
            condition: 等待条件
        """
        loop = asyncio.get_event_loop()
        start_time = time.time()

        if condition.type == WaitType.DURATION:
            logger.info(f"Waiting {condition.seconds}s...")
            await asyncio.sleep(condition.seconds)

        elif condition.type == WaitType.TEMPERATURE_REACHED:
            logger.info(
                f"Waiting for {condition.device_id} to reach target "
                f"(tolerance={condition.tolerance}C, timeout={condition.timeout}s)"
            )
            while True:
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Wait timeout after {condition.timeout}s")
                    break
                try:
                    data = await loop.run_in_executor(
                        None, self._dm.read_heater_data, condition.device_id
                    )
                    pv = data["pv"]
                    sv = data["sv"]
                    if abs(pv - sv) <= condition.tolerance:
                        logger.info(f"Temperature reached: {pv:.1f}C ~ {sv:.1f}C")
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        elif condition.type == WaitType.PUMP_COMPLETE:
            logger.info(
                f"Waiting for pump {condition.device_id} CH{condition.channel} to complete"
            )
            while True:
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Pump wait timeout after {condition.timeout}s")
                    break
                try:
                    status = await loop.run_in_executor(
                        None, self._dm.read_pump_status, condition.device_id
                    )
                    ch_data = status["channels"].get(str(condition.channel))
                    if ch_data and not ch_data["running"]:
                        logger.info(
                            f"Pump channel {condition.channel} completed"
                        )
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.0)
