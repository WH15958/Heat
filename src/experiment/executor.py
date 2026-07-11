import asyncio
import time

from src.experiment.actions import (
    ExperimentStep,
    ActionType,
    WaitType,
)
from src.devices.microwave import MicrowaveSegment
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StepExecutor:
    """步骤执行器 - 执行单个实验步骤并等待条件满足"""

    def __init__(self, device_manager):
        self._dm = device_manager
        self._should_stop = lambda: False
        self._is_paused = lambda: False

    def set_stop_checker(self, checker):
        self._should_stop = checker

    def set_pause_checker(self, checker):
        self._is_paused = checker

    async def _wait_for_resume(self):
        if not self._is_paused():
            return 0.0
        paused_at = time.monotonic()
        while self._is_paused():
            if self._should_stop():
                return None
            await asyncio.sleep(0.05)
        return time.monotonic() - paused_at

    async def _pause_aware_sleep(self, seconds):
        remaining = max(float(seconds), 0.0)
        paused_total = 0.0
        while remaining > 0:
            paused_duration = await self._wait_for_resume()
            if paused_duration is None or self._should_stop():
                return None
            paused_total += paused_duration
            sleep_time = min(remaining, 0.05)
            await asyncio.sleep(sleep_time)
            if not self._is_paused():
                remaining -= sleep_time
        return paused_total

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
                result = await loop.run_in_executor(
                    None, self._dm.set_temperature, step.params["device_id"], step.params["temperature"]
                )
                if not result:
                    logger.error(f"Step {step.id}: set_temperature returned False")
                    return False

            elif step.type == ActionType.HEATER_START:
                result = await loop.run_in_executor(None, self._dm.start_heater, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: start_heater returned False")
                    return False

            elif step.type == ActionType.HEATER_STOP:
                result = await loop.run_in_executor(None, self._dm.stop_heater, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: stop_heater returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_CONFIGURE_MANUAL:
                segments = self._microwave_segments(step.params.get("segments", []))
                result = await loop.run_in_executor(
                    None,
                    self._dm.configure_microwave_manual,
                    step.params["device_id"],
                    segments,
                )
                if not result:
                    logger.error(f"Step {step.id}: configure_microwave_manual returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_CONFIGURE_AUTO_POWER:
                segments = self._microwave_segments(step.params.get("segments", []))
                result = await loop.run_in_executor(
                    None,
                    self._dm.configure_microwave_auto_power,
                    step.params["device_id"],
                    segments,
                )
                if not result:
                    logger.error(f"Step {step.id}: configure_microwave_auto_power returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_CONFIGURE_CONSTANT_RATE:
                segments = self._microwave_segments(step.params.get("segments", []))
                result = await loop.run_in_executor(
                    None,
                    self._dm.configure_microwave_constant_rate,
                    step.params["device_id"],
                    segments,
                )
                if not result:
                    logger.error(f"Step {step.id}: configure_microwave_constant_rate returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_START:
                result = await loop.run_in_executor(
                    None,
                    self._dm.start_microwave,
                    step.params["device_id"],
                    step.params["mode"],
                )
                if not result:
                    logger.error(f"Step {step.id}: start_microwave returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_STOP:
                result = await loop.run_in_executor(
                    None, self._dm.stop_microwave, step.params["device_id"]
                )
                if not result:
                    logger.error(f"Step {step.id}: stop_microwave returned False")
                    return False

            elif step.type == ActionType.PUMP_START:
                from src.protocols.pump_params import PumpRunMode, PumpDirection

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
                run_time = step.params.get("run_time") if mode in (
                    PumpRunMode.TIME_QUANTITY,
                    PumpRunMode.TIME_SPEED,
                ) else None
                dispense_volume = step.params.get("dispense_volume") if mode in (
                    PumpRunMode.TIME_QUANTITY,
                    PumpRunMode.QUANTITY_SPEED,
                ) else None
                tube_model = step.params.get("tube_model")
                flow_unit = step.params.get("flow_unit")
                time_unit = step.params.get("time_unit")
                volume_unit = step.params.get("volume_unit")
                repeat_count = step.params.get("repeat_count")
                interval_time = step.params.get("interval_time")
                interval_time_unit = step.params.get("interval_time_unit")
                if run_time is not None and time_unit is None:
                    logger.warning(f"Step {step.id}: run_time={run_time} provided but time_unit not specified, defaulting to SECOND")
                    time_unit = 0
                if dispense_volume is not None and volume_unit is None:
                    logger.warning(f"Step {step.id}: dispense_volume={dispense_volume} provided but volume_unit not specified, defaulting to ML")
                    volume_unit = 1
                if interval_time is not None and interval_time_unit is None:
                    logger.warning(f"Step {step.id}: interval_time={interval_time} provided but interval_time_unit not specified, defaulting to SECOND")
                    interval_time_unit = 0
                if repeat_count is not None and repeat_count != 1 and (not interval_time or interval_time <= 0):
                    logger.error(f"Step {step.id}: repeat_count={repeat_count} (0=infinite) requires interval_time > 0")
                    return False
                result = await loop.run_in_executor(
                    None, self._dm.start_pump_channel, step.params["device_id"],
                    ch, step.params.get("flow_rate", 10.0), direction, mode,
                    run_time, dispense_volume, tube_model, flow_unit,
                    time_unit, volume_unit, repeat_count, interval_time, interval_time_unit,
                )
                if not result:
                    logger.error(f"Step {step.id}: start_pump_channel returned False")
                    return False

            elif step.type == ActionType.PUMP_STOP:
                result = await loop.run_in_executor(None, self._dm.stop_pump_channel, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: stop_pump_channel returned False")
                    return False

            elif step.type == ActionType.PUMP_STOP_CHANNEL:
                result = await loop.run_in_executor(
                    None, self._dm.stop_pump_channel, step.params["device_id"], step.params["channel"]
                )
                if not result:
                    logger.error(f"Step {step.id}: stop_pump_channel returned False")
                    return False

            elif step.type == ActionType.WAIT:
                pass

            elif step.type == ActionType.EMERGENCY_STOP:
                result = await loop.run_in_executor(None, self._dm.emergency_stop_all)
                if not result:
                    logger.error(f"Step {step.id}: emergency_stop_all returned False")
                    return False

            elif step.type == ActionType.LOG:
                logger.info(f"[Experiment] {step.params.get('message', '')}")

            else:
                logger.warning(f"Unknown action type: {step.type}")
                return False

            if step.wait.type != WaitType.NONE:
                if not await self._wait_condition(step.wait):
                    return False

            logger.info(f"Step completed: {step.id}")
            return True

        except Exception as e:
            logger.error(f"Step {step.id} failed: {e}")
            return False

    def _microwave_segments(self, raw_segments):
        segments = []
        for raw in raw_segments:
            if isinstance(raw, MicrowaveSegment):
                segments.append(raw)
                continue
            segments.append(MicrowaveSegment(
                segment=raw["segment"],
                heating_temperature=self._value(
                    raw,
                    "heating_temperature",
                    "heat_temperature",
                    "ramp_target_temperature",
                    "target_temperature",
                    default=0.0,
                ),
                heating_power_percent=self._value(
                    raw, "heating_power_percent", "heat_power", default=0
                ),
                holding_temperature=self._value(
                    raw,
                    "holding_temperature",
                    "hold_temperature",
                    "hold_target_temperature",
                    default=0.0,
                ),
                holding_power_percent=self._value(
                    raw, "holding_power_percent", "hold_power", default=0
                ),
                holding_deviation=self._value(
                    raw, "holding_deviation", "hold_deviation", default=0.0
                ),
                hours=self._value(raw, "hours", "hold_hours", default=0),
                minutes=self._value(raw, "minutes", "hold_minutes", default=0),
                seconds=self._value(raw, "seconds", "hold_seconds", default=0),
                target_temperature=self._value(
                    raw, "target_temperature", "ramp_target_temperature", default=None
                ),
                ramp_hours=self._value(raw, "ramp_hours", default=0),
                ramp_minutes=self._value(raw, "ramp_minutes", default=0),
                ramp_seconds=self._value(raw, "ramp_seconds", default=0),
            ))
        return segments

    @staticmethod
    def _value(data, *names, default=None):
        for name in names:
            if name in data:
                return data[name]
        return default

    @staticmethod
    def _microwave_completion_confirmed(data) -> bool:
        if data.get("completed") is True:
            return True
        state = data.get("completion_state")
        if isinstance(state, str) and state.lower() in {"complete", "completed"}:
            return True
        return False

    @staticmethod
    def _microwave_is_running(data) -> bool:
        if data.get("running") is True:
            return True
        try:
            if float(data.get("power_percent", 0) or 0) > 0:
                return True
            if float(data.get("current", 0) or 0) > 0:
                return True
        except (TypeError, ValueError):
            return False
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
            remaining = max(condition.seconds, 0)
            while remaining > 0:
                if self._should_stop():
                    logger.info("Wait interrupted by stop request")
                    return False
                if await self._wait_for_resume() is None:
                    return False
                sleep_time = min(remaining, 0.2)
                if await self._pause_aware_sleep(sleep_time) is None:
                    return False
                remaining -= sleep_time
            return True

        elif condition.type == WaitType.TEMPERATURE_REACHED:
            logger.info(
                f"Waiting for {condition.device_id} to reach target "
                f"(tolerance={condition.tolerance}C, timeout={condition.timeout}s)"
            )
            while True:
                if self._should_stop():
                    logger.info("Temperature wait interrupted by stop request")
                    return False
                paused_duration = await self._wait_for_resume()
                if paused_duration is None:
                    return False
                start_time += paused_duration
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Wait timeout after {condition.timeout}s")
                    return False
                try:
                    data = await loop.run_in_executor(
                        None, self._dm.read_heater_data, condition.device_id
                    )
                    pv = data["pv"]
                    sv = data["sv"]
                    if abs(pv - sv) <= condition.tolerance:
                        logger.info(f"Temperature reached: {pv:.1f}C ~ {sv:.1f}C")
                        return True
                except Exception as e:
                    logger.warning(f"Temperature wait read failed for {condition.device_id}: {e}")
                paused_duration = await self._pause_aware_sleep(1.0)
                if paused_duration is None:
                    return False
                start_time += paused_duration

        elif condition.type == WaitType.MICROWAVE_TEMPERATURE_REACHED:
            target_temperature = condition.target_temperature
            if target_temperature is None:
                logger.error("Microwave temperature wait requires target_temperature")
                return False
            logger.info(
                f"Waiting for microwave {condition.device_id} to reach "
                f"{target_temperature}C (tolerance={condition.tolerance}C, "
                f"timeout={condition.timeout}s)"
            )
            while True:
                if self._should_stop():
                    logger.info("Microwave temperature wait interrupted by stop request")
                    return False
                paused_duration = await self._wait_for_resume()
                if paused_duration is None:
                    return False
                start_time += paused_duration
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Microwave temperature wait timeout after {condition.timeout}s")
                    return False
                try:
                    data = await loop.run_in_executor(
                        None, self._dm.read_microwave_data, condition.device_id
                    )
                    material_temperature = data.get("material_temperature")
                    if material_temperature is not None and abs(
                        float(material_temperature) - float(target_temperature)
                    ) <= condition.tolerance:
                        logger.info(
                            f"Microwave temperature reached: "
                            f"{float(material_temperature):.1f}C ~ "
                            f"{float(target_temperature):.1f}C"
                        )
                        return True
                except Exception as e:
                    logger.warning(
                        f"Microwave temperature wait read failed for "
                        f"{condition.device_id}: {e}"
                    )
                paused_duration = await self._pause_aware_sleep(0.2)
                if paused_duration is None:
                    return False
                start_time += paused_duration

        elif condition.type == WaitType.MICROWAVE_COMPLETE:
            logger.info(
                f"Waiting for microwave {condition.device_id} to complete "
                f"(timeout={condition.timeout}s)"
            )
            seen_running = False
            while True:
                if self._should_stop():
                    logger.info("Microwave complete wait interrupted by stop request")
                    return False
                paused_duration = await self._wait_for_resume()
                if paused_duration is None:
                    return False
                start_time += paused_duration
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Microwave complete wait timeout after {condition.timeout}s")
                    return False
                try:
                    data = await loop.run_in_executor(
                        None, self._dm.read_microwave_data, condition.device_id
                    )
                    if self._microwave_completion_confirmed(data):
                        logger.info(f"Microwave {condition.device_id} completed")
                        return True
                    if self._microwave_is_running(data):
                        seen_running = True
                    elif seen_running:
                        logger.info(
                            f"Microwave {condition.device_id} completed "
                            f"(running transitioned to false)"
                        )
                        return True
                except Exception as e:
                    logger.warning(
                        f"Microwave complete wait read failed for {condition.device_id}: {e}"
                    )
                paused_duration = await self._pause_aware_sleep(0.2)
                if paused_duration is None:
                    return False
                start_time += paused_duration

        elif condition.type == WaitType.PUMP_COMPLETE:
            logger.info(
                f"Waiting for pump {condition.device_id} CH{condition.channel} to complete"
            )
            seen_running = False
            while True:
                if self._should_stop():
                    logger.info("Pump wait interrupted by stop request")
                    return False
                paused_duration = await self._wait_for_resume()
                if paused_duration is None:
                    return False
                start_time += paused_duration
                elapsed = time.time() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Pump wait timeout after {condition.timeout}s")
                    return False
                try:
                    status = await loop.run_in_executor(
                        None, self._dm.read_pump_status, condition.device_id
                    )
                    ch_data = status["channels"].get(str(condition.channel))
                    if not ch_data or ch_data.get("read_ok") is not True:
                        paused_duration = await self._pause_aware_sleep(1.0)
                        if paused_duration is None:
                            return False
                        start_time += paused_duration
                        continue
                    if ch_data.get("running") is True:
                        seen_running = True
                    elif seen_running:
                        logger.info(
                            f"Pump channel {condition.channel} completed"
                        )
                        return True
                except Exception as e:
                    logger.warning(f"Pump wait read failed for {condition.device_id} CH{condition.channel}: {e}")
                paused_duration = await self._pause_aware_sleep(1.0)
                if paused_duration is None:
                    return False
                start_time += paused_duration

        return True
