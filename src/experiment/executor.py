import asyncio
import math
import time

from src.experiment.actions import (
    ExperimentStep,
    ActionType,
    WaitType,
    validate_flow_duration,
    validate_turntable_step,
)
from src.experiment.recipe_turntable import RecipeTurntable, turntable_steps, check_turntable_connections
from src.experiment.progress import ActivityProgress
from src.devices.microwave import MicrowaveSegment
from src.devices.syringe_pump import is_initialization_pending
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _is_nonnegative_finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except (TypeError, ValueError, OverflowError):
        return False


class StepExecutor:
    """步骤执行器 - 执行单个实验步骤并等待条件满足"""

    def __init__(self, device_manager):
        self._dm = device_manager
        self._should_stop = lambda: False
        self._is_paused = lambda: False
        self._paused_at = None
        self._paused_total = 0.0
        self._pause_generation = 0
        self._active_heaters = set()
        self._active_pumps = set()
        self._pump_repeat_counts = {}
        self._active_microwaves = set()
        self._pump_start_confirmed = set()
        self._active_syringes = set()
        self._reserved_syringes = set()
        self._syringe_owner = object()
        self._reserved_valves = set()
        self._valve_owner = object()
        self._turntables = {}
        self._last_error = None
        self._current_step = None
        self.last_device_result = None
        self.release_resources_on_cleanup = True
        self.activity = ActivityProgress(self._wait_clock)
        self._activity_step = None
        self._activity_children = []
        self._cleanup_count = 0
        self._microwave_event_cursors = {}
        self.microwave_event_recorder = None
        self._step_microwave_events = []

    def begin_microwave_diagnostics(self, steps):
        self._microwave_event_cursors = {}
        getter = getattr(self._dm, "get_microwave_events", None)
        if not callable(getter):
            return
        ids = {s.params.get("device_id") or s.wait.device_id for s in steps
               if s.type.value.startswith("microwave.") or s.wait.type.value.startswith("microwave_")}
        for device_id in ids:
            result = getter(device_id)
            if isinstance(result, tuple) and len(result) == 2:
                self._microwave_event_cursors[device_id] = result[0]

    def capture_microwave_events(self, device_id=None):
        getter = getattr(self._dm, "get_microwave_events", None)
        if not callable(getter):
            return []
        events = []
        for did in ([device_id] if device_id else list(self._microwave_event_cursors)):
            result = getter(did, self._microwave_event_cursors.get(did, 0))
            if not isinstance(result, tuple) or len(result) != 2:
                continue
            self._microwave_event_cursors[did], new_events = result
            events.extend(new_events)
        if events and callable(self.microwave_event_recorder):
            self.microwave_event_recorder(events)
        self._step_microwave_events.extend(events)
        return events

    async def _read_microwave_data(self, device_id):
        try:
            return await asyncio.to_thread(self._dm.read_microwave_data, device_id)
        finally:
            self.capture_microwave_events(device_id)

    async def reserve_valves(self, steps):
        ids = {s.params["device_id"] for s in steps if s.enabled and s.type == ActionType.VALVE_SWITCH}
        if any(s.type != ActionType.TURNTABLE_STOP for s in turntable_steps(steps)):
            ids.add("valve1")
        try:
            for device_id in sorted(ids):
                def claim(did=device_id):
                    self._dm.claim_valve(did, self._valve_owner)
                    self._reserved_valves.add(did)
                await self._reserve_resource(claim)
        except Exception:
            await self.release_valves()
            raise

    async def release_valves(self):
        for device_id in list(self._reserved_valves):
            await asyncio.to_thread(self._dm.release_valve, device_id, self._valve_owner)
            self._reserved_valves.discard(device_id)

    def cancel_pending_valve_operations(self):
        cancel = getattr(self._dm, "cancel_valve_operations", None)
        if callable(cancel):
            cancel(self._reserved_valves)

    async def reserve_syringes(self, steps):
        ids = set()
        if any(s.type != ActionType.TURNTABLE_STOP for s in turntable_steps(steps)):
            ids.update(("syringe_pump1", "syringe_pump2"))
        for step in steps:
            if not step.enabled:
                continue
            if step.type.value.startswith("syringe_pump."):
                ids.add(step.params["device_id"])
            if step.type == ActionType.SYRINGE_PAIR_DISPENSE:
                ids.update(feed["device_id"] for feed in step.params["feeds"])
            if step.wait.type == WaitType.SYRINGE_PUMP_COMPLETE:
                ids.add(step.wait.device_id)
        try:
            for device_id in sorted(ids):
                def claim(did=device_id):
                    self._dm.syringe(did).claim(self._syringe_owner)
                    self._reserved_syringes.add(did)
                await self._reserve_resource(claim)
        except Exception:
            self.release_unused_syringes()
            raise

    async def _reserve_resource(self, claim):
        # Track a completed synchronous claim even if startup is cancelled.
        task = asyncio.create_task(asyncio.to_thread(claim))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            raise

    def release_unused_syringes(self):
        if not self.release_resources_on_cleanup:
            return
        for device_id in self._reserved_syringes - self._active_syringes:
            self._dm.syringe(device_id).release(self._syringe_owner)
        self._reserved_syringes.intersection_update(self._active_syringes)

    async def reserve_turntables(self, steps):
        check_turntable_connections(self._dm, steps)
        selected = turntable_steps(steps)
        for did in sorted({s.params["device_id"] for s in selected}):
            def changed(state, device_id=did):
                self.activity.device(device_id, state)
            helper = RecipeTurntable(self._dm, self._should_stop, changed, device_id=did)
            self._turntables[did] = helper
            calibrated = any(s.params["device_id"] == did and s.type != ActionType.TURNTABLE_STOP for s in selected)
            await helper.claim(require_calibration=calibrated)

    def cancel_pending_turntable_operations(self):
        for helper in self._turntables.values():
            helper.invalidate_pending()

    async def _execute_turntable(self, step):
        validate_turntable_step(step)
        helper = self._turntables.get(step.params["device_id"])
        if helper is None:
            raise RuntimeError("转盘尚未被本次配方占用")
        before = helper.bottle
        target = (1 if step.type == ActionType.TURNTABLE_HOME else
                  before + 1 if step.type == ActionType.TURNTABLE_NEXT and before is not None else None)
        details = {"operation": step.type.value, "from_bottle": before,
                   "target_position": (target - 1) * helper.control.config.pulses_per_bottle if target else None}
        helper._changed = lambda state: self.activity.device(helper.device_id, {**state, **details})
        try:
            if step.type != ActionType.TURNTABLE_STOP:
                if step.type == ActionType.TURNTABLE_HOME:
                    helper.rearm_home()
                while True:
                    if await self._wait_for_resume() is None:
                        return False
                    pause_generation = self._pause_generation
                    await helper.verify_liquid_route()
                    if pause_generation == self._pause_generation and not self._is_paused():
                        break
            state = await helper.execute_action(step.type)
            self.activity.device(helper.device_id, {**state, **details})
            return True
        finally:
            state = await helper._call(helper.control.summary)
            self.last_device_result = {**state, **details, "device_type": "turntable",
                                       "to_bottle": helper.bottle}

    @property
    def last_error(self):
        if self._current_step is not None:
            get_detail = getattr(self._dm, "get_last_command_error", None)
            device_id = self._current_step.params.get("device_id")
            if callable(get_detail) and device_id:
                detail = get_detail(device_id)
                if detail:
                    return detail
        return self._last_error

    def set_stop_checker(self, checker):
        self._should_stop = checker

    def set_pause_checker(self, checker):
        self._is_paused = checker

    def notify_pause(self, paused):
        """Timestamp actual orchestration pause transitions, never pending requests."""
        if paused and self._paused_at is None:
            self._pause_generation += 1
            self.activity.stable_seconds = 0.0
            self._paused_at = time.monotonic()
        elif not paused and self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    def _wait_clock(self):
        now = time.monotonic()
        return now - self._paused_total - (now - self._paused_at if self._paused_at is not None else 0)

    async def _wait_for_resume(self):
        if not self._is_paused():
            return 0.0
        self.notify_pause(True)
        paused_at = time.monotonic()
        while self._is_paused():
            if self._should_stop():
                return None
            await asyncio.sleep(0.05)
        self.notify_pause(False)
        return time.monotonic() - paused_at

    async def _pause_aware_sleep(self, seconds):
        if not _is_nonnegative_finite_number(seconds):
            logger.error(f"Invalid sleep duration: {seconds}")
            return None
        deadline = self._wait_clock() + seconds
        paused_total = 0.0
        while True:
            paused_duration = await self._wait_for_resume()
            if paused_duration is None or self._should_stop():
                return None
            paused_total += paused_duration
            remaining = deadline - self._wait_clock()
            if remaining <= 0:
                return paused_total
            sleep_time = min(remaining, 0.05)
            await asyncio.sleep(sleep_time)

    @property
    def activity_snapshot(self):
        if self._activity_step is None or self.activity.step_id != self._activity_step.id:
            return None
        observation = self.activity.snapshot()
        for child in self._activity_children:
            observation["devices"].update(child.activity.snapshot()["devices"])
        return observation

    @property
    def cleanup_in_progress(self):
        return self._cleanup_count > 0

    async def execute(self, step: ExperimentStep) -> bool:
        self._activity_step = step
        self._step_microwave_events = []
        self.activity.reset(step)
        self._activity_children = []
        success = False
        try:
            success = await self._execute(step)
            return success
        finally:
            if not success:
                # Cleanup commands may replace the driver's last command error.
                self._last_error = self.last_error
                self._current_step = None
            if step.type.value.startswith("microwave."):
                self.capture_microwave_events(step.params.get("device_id"))
            if self._step_microwave_events:
                self.last_device_result = dict(self.last_device_result or {},
                    microwave_events=list(self._step_microwave_events))
            self.activity.finish(success)
            if step.wait.type == WaitType.MICROWAVE_MONITORED_HOLD:
                snapshot = self.activity.snapshot()
                self.last_device_result = dict(self.last_device_result or {}, hold_summary=dict(
                    target_temperature=step.wait.target_temperature, tolerance=step.wait.tolerance,
                    seconds=step.wait.seconds, timeout=step.wait.timeout, hold_mode=snapshot["hold_mode"],
                    **{key: snapshot[key] for key in (
                        "elapsed_seconds", "qualified_seconds", "hold_in_band", "state")}))

    async def _execute(self, step: ExperimentStep) -> bool:
        """执行一个步骤

        Args:
            step: 实验步骤

        Returns:
            bool: 执行成功返回True
        """
        logger.info(f"Executing step: {step.id} ({step.type.value})")
        self._current_step = step
        if step.type == ActionType.PUMP_START:
            self._pump_start_confirmed.discard((step.params.get("device_id"), step.params.get("channel")))
        if step.wait.type == WaitType.MICROWAVE_MONITORED_HOLD and (not step.enabled or step.on_error != "stop"):
            self._last_error = "微波保护保温必须启用且失败停止"
            return False
        self.last_device_result = None
        target = step.params.get("device_id", "system")
        channel = step.params.get("channel")
        channel_text = f" CH{channel}" if channel is not None else ""
        self._last_error = (
            f"{step.type.value} failed for {target}{channel_text}; "
            "see device log for command/readback details"
        )

        try:
            flow_duration = validate_flow_duration(step)
            loop = asyncio.get_event_loop()
            if self._should_stop():
                return False

            if step.type.value.startswith("turntable."):
                if not await self._execute_turntable(step):
                    return False
            elif step.type == ActionType.SYRINGE_PAIR_DISPENSE:
                if not await self._dispense_pair(step):
                    return False
            elif step.type.value.startswith("syringe_pump."):
                if self._should_stop():
                    return False
                device_id = step.params["device_id"]
                control = self._dm.syringe(device_id)
                if device_id not in self._active_syringes:
                    await asyncio.to_thread(control.claim, self._syringe_owner)
                    self._active_syringes.add(device_id)
                params = {k: v for k, v in step.params.items() if k != "device_id"}
                params["action"] = step.type.value.split(".", 1)[1]
                if self._should_stop():
                    return False
                try:
                    result = await asyncio.to_thread(self._dm.syringe_command, device_id, params, self._syringe_owner)
                finally:
                    self.last_device_result = control.summary()
                if result.get("result") == "stop_unconfirmed":
                    return False
                if params["action"] in ("initialize", "configure", "move", "aspirate", "dispense", "valve", "program_run", "repeat"):
                    if not await self._wait_syringe(device_id, params.get("timeout", 120)):
                        return False
                if params["action"] == "initialize":
                    state = await asyncio.to_thread(control.read)
                    self.last_device_result = state
                    if (not state.get("read_ok") or state.get("busy") is not False
                            or state.get("fault_code") != 0 or not state.get("initialized")
                            or not state.get("position_trusted") or state.get("position") != 0):
                        self._last_error = "注射泵初始化后未确认可信零位"
                        return False

            elif step.type == ActionType.VALVE_SWITCH:
                if self._should_stop() or await self._wait_for_resume() is None:
                    return False
                device_id = step.params["device_id"]
                position = step.params["position"]
                try:
                    result = await asyncio.to_thread(self._dm.valve_operation, device_id, "switch",
                                                     position == "NC", self._valve_owner, self._should_stop)
                    self.last_device_result = {"device_type": "valve", "target_position": position, **result}
                    self.activity.device(device_id, result)
                    if not result.get("read_ok") or result.get("relay_energized") is not (position == "NC"):
                        return False
                except Exception:
                    state = await asyncio.to_thread(self._dm.valve_status, device_id)
                    self.last_device_result = {"device_type": "valve", "target_position": position, **state}
                    self.activity.device(device_id, state)
                    raise

            elif step.type == ActionType.HEATER_SET_TEMP:
                result = await loop.run_in_executor(
                    None, self._dm.set_temperature, step.params["device_id"], step.params["temperature"]
                )
                if not result:
                    logger.error(f"Step {step.id}: set_temperature returned False")
                    return False

            elif step.type == ActionType.HEATER_START:
                self._active_heaters.add(step.params["device_id"])
                result = await loop.run_in_executor(None, self._dm.start_heater, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: start_heater returned False")
                    return False

            elif step.type == ActionType.HEATER_STOP:
                result = await loop.run_in_executor(None, self._dm.stop_heater, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: stop_heater returned False")
                    return False
                self._active_heaters.discard(step.params["device_id"])

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
                self._active_microwaves.add(step.params["device_id"])
                result = await loop.run_in_executor(
                    None, lambda: self._dm.start_microwave(
                        step.params["device_id"], step.params["mode"], should_stop=self._should_stop),
                )
                if not result:
                    logger.error(f"Step {step.id}: start_microwave returned False")
                    return False

            elif step.type == ActionType.MICROWAVE_STOP:
                result = await loop.run_in_executor(
                    None, lambda: self._dm.stop_microwave(step.params["device_id"], source="experiment_step")
                )
                if not result:
                    logger.error(f"Step {step.id}: stop_microwave returned False")
                    return False
                self._active_microwaves.discard(step.params["device_id"])

            elif step.type == ActionType.PUMP_START:
                from src.protocols.pump_params import PumpRunMode, PumpDirection

                ch = step.params["channel"]
                direction_map = {
                    "CW": PumpDirection.CLOCKWISE,
                    "CCW": PumpDirection.COUNTER_CLOCKWISE,
                }
                direction_name = step.params.get("direction", "CW")
                if direction_name not in direction_map:
                    logger.error(
                        f"Step {step.id}: invalid pump direction={direction_name!r}; "
                        "expected CW or CCW"
                    )
                    return False
                direction = direction_map[direction_name]
                mode_map = {
                    "FLOW_MODE": PumpRunMode.FLOW_MODE,
                    "TIME_QUANTITY": PumpRunMode.TIME_QUANTITY,
                    "TIME_SPEED": PumpRunMode.TIME_SPEED,
                    "QUANTITY_SPEED": PumpRunMode.QUANTITY_SPEED,
                }
                mode_name = step.params.get("mode", "FLOW_MODE")
                if mode_name not in mode_map:
                    logger.error(
                        f"Step {step.id}: invalid pump mode={mode_name!r}; "
                        f"expected one of {', '.join(mode_map)}"
                    )
                    return False
                mode = mode_map[mode_name]
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
                pump_key = (step.params["device_id"], ch)
                self._active_pumps.add(pump_key)
                self._pump_repeat_counts[pump_key] = (
                    1 if repeat_count is None else repeat_count
                )
                result = await loop.run_in_executor(
                    None, self._dm.start_pump_channel, step.params["device_id"],
                    ch, step.params.get("flow_rate", 10.0), direction, mode,
                    run_time, dispense_volume, tube_model, flow_unit,
                    time_unit, volume_unit, repeat_count, interval_time, interval_time_unit,
                )
                if not result:
                    logger.error(f"Step {step.id}: start_pump_channel returned False")
                    return False
                # The synchronous driver returned success only after START readback.
                self._pump_start_confirmed.add(pump_key)
                if run_time is not None and time_unit in (0, 1, 2):
                    self.activity.pump_started(run_time * (1, 60, 3600)[time_unit])
                if flow_duration is not None:
                    if not await self._run_timed_flow(step.params["device_id"], ch, flow_duration):
                        return False

            elif step.type == ActionType.PUMP_STOP:
                device_id = step.params["device_id"]
                self._pump_start_confirmed = {key for key in self._pump_start_confirmed if key[0] != device_id}
                result = await loop.run_in_executor(None, self._dm.stop_pump_channel, step.params["device_id"])
                if not result:
                    logger.error(f"Step {step.id}: stop_pump_channel returned False")
                    return False
                self._active_pumps = {
                    item for item in self._active_pumps if item[0] != device_id
                }
                self._pump_repeat_counts = {
                    key: repeat_count
                    for key, repeat_count in self._pump_repeat_counts.items()
                    if key[0] != device_id
                }

            elif step.type == ActionType.PUMP_STOP_CHANNEL:
                self._pump_start_confirmed.discard((step.params["device_id"], step.params["channel"]))
                result = await loop.run_in_executor(
                    None, self._dm.stop_pump_channel, step.params["device_id"], step.params["channel"]
                )
                if not result:
                    logger.error(f"Step {step.id}: stop_pump_channel returned False")
                    return False
                self._active_pumps.discard(
                    (step.params["device_id"], step.params["channel"])
                )
                self._pump_repeat_counts.pop(
                    (step.params["device_id"], step.params["channel"]), None
                )

            elif step.type == ActionType.WAIT:
                pass

            elif step.type == ActionType.EMERGENCY_STOP:
                for helper in self._turntables.values():
                    helper.bottle = None
                self._pump_start_confirmed.clear()
                result = await loop.run_in_executor(None, self._dm.emergency_stop_all)
                if not result:
                    logger.error(f"Step {step.id}: emergency_stop_all returned False")
                    return False
                self._active_heaters.clear()
                self._active_pumps.clear()
                self._pump_repeat_counts.clear()
                self._active_microwaves.clear()

            elif step.type == ActionType.LOG:
                logger.info(f"[Experiment] {step.params.get('message', '')}")

            else:
                logger.warning(f"Unknown action type: {step.type}")
                return False

            if step.wait.type != WaitType.NONE:
                if step.wait.type in {WaitType.MICROWAVE_TEMPERATURE_REACHED, WaitType.MICROWAVE_TEMPERATURE_BELOW}:
                    # The action succeeded; subsequent failures belong to its temperature wait.
                    self._current_step = None
                if not await self._wait_condition(step.wait):
                    return False

            logger.info(f"Step completed: {step.id}")
            self._last_error = None
            self._current_step = None
            return True

        except Exception as e:
            self._last_error = f"{step.type.value} failed: {e}"
            logger.error(f"Step {step.id} failed: {e}")
            return False

    async def check_flow_interlock(self, device_id, channel):
        """Optional orchestration interlock; plain YAML retains its existing behavior."""
        return True

    async def _run_timed_flow(self, device_id, channel, seconds):
        """Finish the issued flow run even while paused; always confirm STOP before return."""
        started = time.monotonic()
        deadline = started + seconds
        next_read = started
        self.activity.pump_started(seconds)
        self.activity.state = "waiting"
        self.activity.wait_type = "flow_duration"
        success = False
        stopped = False
        try:
            while True:
                if self._should_stop():
                    self._last_error = "流量排液收到停止请求"
                    break
                now = time.monotonic()
                if now >= deadline:
                    success = True
                    break
                if now >= next_read:
                    if not await self.check_flow_interlock(device_id, channel):
                        break
                    status = await asyncio.to_thread(self._dm.read_pump_status, device_id)
                    data = status.get("channels", {}).get(str(channel), {})
                    self.activity.device(device_id, data)
                    self.last_device_result = data
                    if (data.get("read_ok") is not True or data.get("running") is not True
                            or data.get("run_status") != "START"):
                        self._last_error = "流量排液状态读取失败或设备提前停止"
                        break
                    next_read = time.monotonic() + 1
                await asyncio.sleep(max(0, min(0.05, deadline - time.monotonic())))
        except Exception as exc:
            self.activity.device(device_id, {"read_ok": False})
            self._last_error = "流量排液状态读取失败：" + str(exc)
        finally:
            self.activity.state = "stopping"
            try:
                stopped = await asyncio.to_thread(self._dm.stop_pump_channel, device_id, channel)
            except Exception as exc:
                self._last_error = "流量排液停止异常：" + str(exc)
            key = (device_id, channel)
            self._pump_start_confirmed.discard(key)
            if stopped:
                self._active_pumps.discard(key)
                self._pump_repeat_counts.pop(key, None)
            else:
                self._last_error = (self._last_error or "流量排液") + "；停止未确认"
            self.last_device_result = dict(device_id=device_id, channel=channel,
                read_ok=bool(stopped), running=False if stopped else None, stop_confirmed=bool(stopped))
            self.activity.device(device_id, self.last_device_result)
        return success and stopped and not self._should_stop()

    async def stop_active_devices(self, *, preserve_heaters: bool = False, source="failure_cleanup") -> bool:
        self._cleanup_count += 1
        try:
            return await self._stop_active_devices(preserve_heaters=preserve_heaters, source=source)
        finally:
            self._cleanup_count -= 1

    async def _stop_active_devices(self, *, preserve_heaters: bool = False, source="failure_cleanup") -> bool:
        """Stop attempted devices; successful guided groups may retain batch heaters."""
        self._pump_start_confirmed.clear()
        loop = asyncio.get_running_loop()
        success = True
        for did, helper in list(self._turntables.items()):
            try:
                if await helper.cleanup(normal=source == "normal_cleanup"):
                    del self._turntables[did]
                else:
                    success = False
                    self._last_error = helper.last_error or "转盘停止或释放未确认"
            except Exception as exc:
                self._last_error = str(exc)
                success = False
        if success:
            self.release_unused_syringes()

        for device_id in list(self._active_syringes):
            control = self._dm.syringe(device_id)
            try:
                state = await asyncio.to_thread(control.read)
                clean = (state.get("read_ok") and state.get("busy") is False
                         and state.get("fault_code") == 0
                         and state.get("action", {}).get("result") in ("completed", "sent_unverified"))
                stopped = clean or await asyncio.to_thread(control.stop)
                if stopped:
                    if self.release_resources_on_cleanup and not self._turntables:
                        control.release(self._syringe_owner)
                    self._active_syringes.discard(device_id)
                    if self.release_resources_on_cleanup and not self._turntables:
                        self._reserved_syringes.discard(device_id)
                else:
                    success = False
            except Exception as exc:
                self._last_error = str(exc)
                success = False

        for device_id, channel in list(self._active_pumps):
            try:
                stopped = await loop.run_in_executor(
                    None, self._dm.stop_pump_channel, device_id, channel
                )
            except Exception as e:
                logger.error(
                    f"Failed to stop active pump {device_id} channel {channel}: {e}"
                )
                stopped = False
            if stopped:
                self._active_pumps.discard((device_id, channel))
                self._pump_repeat_counts.pop((device_id, channel), None)
            else:
                success = False

        for device_id in ([] if preserve_heaters else list(self._active_heaters)):
            try:
                stopped = await loop.run_in_executor(
                    None, self._dm.stop_heater, device_id
                )
            except Exception as e:
                logger.error(f"Failed to stop active heater {device_id}: {e}")
                stopped = False
            if stopped:
                self._active_heaters.discard(device_id)
            else:
                success = False

        for device_id in list(self._active_microwaves):
            try:
                stopped = await loop.run_in_executor(
                    None, lambda did=device_id: self._dm.stop_microwave(did, source=source)
                )
            except Exception as e:
                logger.error(f"Failed to stop active microwave {device_id}: {e}")
                stopped = False
            if stopped:
                self._active_microwaves.discard(device_id)
            else:
                success = False
            self.capture_microwave_events(device_id)

        if success and self.release_resources_on_cleanup:
            await self.release_valves()

        return success

    async def _dispense_pair(self, step):
        """Upper-layer coordination; each synchronous controller retains its own lock."""
        abort = False
        children = []
        self._activity_children = children
        tasks = []
        feeds = step.params["feeds"]
        if self._should_stop() or await self._wait_for_resume() is None:
            return False
        for feed in feeds:
            child = StepExecutor(self._dm)
            child._syringe_owner = self._syringe_owner
            child._active_syringes = self._active_syringes
            child.set_stop_checker(lambda: abort or self._should_stop())
            # The pair is one action boundary: a pause lets both issued actions finish.
            child.set_pause_checker(lambda: False)
            children.append(child)
            tasks.append(asyncio.create_task(child.execute(ExperimentStep(
                id=step.id + "_" + feed["device_id"], type=ActionType.SYRINGE_DISPENSE,
                params=feed,
            ))))
        pending = set(tasks)
        success = True
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if any(not task.result() for task in done):
                abort = True
                success = False
                # Stop both immediately, even if the other is still dispatching/finishing.
                stopped = await asyncio.gather(*(
                    asyncio.to_thread(self._dm.syringe(feed["device_id"]).stop)
                    for feed in feeds
                ), return_exceptions=True)
                if any(result is not True for result in stopped):
                    self._last_error = "Parallel feed failed; STOP UNCONFIRMED"
                break
        await asyncio.gather(*tasks)
        self.last_device_result = {"device_type": "syringe_pair", "pumps": {
            feed["device_id"]: {"action_result": child.last_device_result,
                                "final_state": self._dm.syringe(feed["device_id"]).summary()}
            for feed, child in zip(feeds, children)
        }}
        if not success and "STOP UNCONFIRMED" not in (self._last_error or ""):
            self._last_error = "; ".join(child.last_error or "" for child in children)
        return success and not self._should_stop()

    async def _wait_syringe(self, device_id, timeout):
        self.activity.state = "waiting"
        deadline = time.monotonic() + timeout
        control = self._dm.syringe(device_id)
        while time.monotonic() < deadline:
            if self._should_stop():
                return False
            try:
                state = await asyncio.to_thread(control.read)
            except Exception:
                self.activity.device(device_id, {"read_ok": False})
                raise
            self.last_device_result = state
            self.activity.device(device_id, state)
            pending = is_initialization_pending(state.get("action"), state.get("busy"), state.get("fault_code"))
            if not state.get("read_ok") or (state.get("fault_code") and not pending):
                self._last_error = state.get("fault_description") or state.get("read_error")
                return False
            result = state.get("action", {}).get("result")
            if result in ("failed", "unknown", "stopped"):
                self._last_error = f"Syringe action {result}"
                return False
            if state.get("busy") is False and result in ("completed", "sent_unverified"):
                return True
            # Keep checking faults during experiment pause; do not dispatch another action.
            await asyncio.sleep(0.1)
        self._last_error = "Syringe completion timeout"
        stopped = await asyncio.to_thread(control.stop)
        self._last_error += "; stop confirmed" if stopped else "; STOP UNCONFIRMED"
        self.last_device_result = control.summary()
        return False

    async def check_syringe_health(self):
        for device_id in self._active_syringes:
            state = await asyncio.to_thread(self._dm.syringe(device_id).read)
            pending = is_initialization_pending(state.get("action"), state.get("busy"), state.get("fault_code"))
            if not state.get("read_ok") or (state.get("fault_code") and not pending) or state.get("action", {}).get("result") in ("failed", "unknown", "stopped"):
                self.last_device_result = state
                self._last_error = "Syringe fault or unknown state during experiment pause"
                return False
        return True

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

    def _valid_microwave_state(self, data, *, require_control=True):
        if (("read_ok" in data and data["read_ok"] is not True) or data.get("fault_code") != 0
                or not _is_nonnegative_finite_number(data.get("material_temperature"))
                or (data.get("control_active") is not True and data.get("control_active") is not False)
                or data.get("status_confirmed") is not True
                or (require_control and data.get("control_active") is not True)):
            self._last_error = "微波故障、温度无效、状态读取失败或提前退出控制"
            return False
        return True

    async def _monitored_hold(self, condition):
        if (not condition.device_id or not _is_nonnegative_finite_number(condition.seconds)
                or condition.seconds != round(condition.seconds)):
            self._last_error = "微波保护保温必须指定设备并使用非负整秒"
            return False
        if condition.hold_mode not in ("qualified", "timed"):
            self._last_error = "微波保温计时方式无效"
            return False
        supervised = condition.target_temperature is not None
        qualified = supervised and condition.hold_mode == "qualified"
        if supervised and (not _is_nonnegative_finite_number(condition.target_temperature)
                or not _is_nonnegative_finite_number(condition.tolerance)
                or not _is_nonnegative_finite_number(condition.timeout)
                or condition.timeout <= 0 or condition.timeout < condition.seconds):
            self._last_error = "微波温度保温必须使用有效目标、容差及不小于保温时长的正超时"
            return False
        budget_getter = getattr(self._dm, "microwave_read_budget", None)
        budget = budget_getter(condition.device_id) if callable(budget_getter) else 7.0
        if not _is_nonnegative_finite_number(budget) or budget <= 0:
            budget = 7.0
        started = self._wait_clock()
        self.activity.started = started
        self.activity.hold_mode = "qualified" if qualified else "timed"
        self.activity.qualified_seconds = 0.0 if qualified else None
        self.activity.hold_timeout_seconds = condition.timeout if supervised else None
        previous_sample = None
        previous_in_band = False
        pause_generation = self._pause_generation
        while True:
            if self._should_stop():
                return False
            paused = await self._wait_for_resume()
            if paused is None:
                return False
            if pause_generation != self._pause_generation:
                previous_sample = None
                pause_generation = self._pause_generation
            next_poll = self._wait_clock() + 1.0
            try:
                read_started = time.monotonic()
                data = await self._read_microwave_data(condition.device_id)
                read_duration = time.monotonic() - read_started
                sampled = self._wait_clock()
                self.last_device_result = data
                self.activity.device(condition.device_id, data)
                self.activity.temperatures([{"device_id": condition.device_id, "target_temperature": condition.target_temperature}],
                    {condition.device_id: data.get("material_temperature") if data.get("read_ok") is not False else None},
                    condition.tolerance if supervised else None)
                if not self._valid_microwave_state(data, require_control=False):
                    return False
                elapsed = sampled - started
                if data.get("control_active") is not True:
                    credited = self.activity.qualified_seconds if qualified else elapsed
                    stop_event = next((event for event in reversed(self._step_microwave_events)
                                       if event.get("action") == "stop"), None)
                    source = (f"本系统最近STOP请求来源={stop_event['source']}" if stop_event else
                              "设备侧退出或外部来源未确认")
                    self._last_error = (f"微波仪提前退出控制，保温失败：已保温 {credited:.1f} 秒，"
                                        f"剩余 {max(0, condition.seconds-credited):.1f} 秒；控制字={data.get('control_word')}，"
                                        f"当前段={data.get('current_segment')}，设备运行秒数={data.get('runtime_seconds')}，"
                                        f"故障码={data.get('fault_code')}；{source}")
                    return False
                if self._should_stop():
                    return False
                if pause_generation != self._pause_generation:
                    previous_sample = None
                    pause_generation = self._pause_generation
                if read_duration > budget or (previous_sample is not None and sampled-previous_sample > budget):
                    self._last_error = f"微波保温状态超过通讯预算 {budget:g} 秒，不能确认保温状态"
                    return False
                if self._is_paused():
                    previous_sample = None
                    continue
                if supervised:
                    in_band = abs(data['material_temperature']-condition.target_temperature) <= condition.tolerance
                    self.activity.hold_in_band = in_band
                if qualified:
                    if elapsed > condition.timeout:
                        self._last_error = f"微波保温超时：已等待 {elapsed:.1f} 秒，上限 {condition.timeout:g} 秒"
                        return False
                    if previous_sample is not None and previous_in_band and in_band:
                        self.activity.qualified_seconds = min(condition.seconds,
                            self.activity.qualified_seconds + max(0, sampled-previous_sample))
                    remaining = condition.seconds - self.activity.qualified_seconds
                    if remaining <= 0 and in_band:
                        return True
                    if elapsed >= condition.timeout:
                        self._last_error = (f"微波保温超时：有效保温 {self.activity.qualified_seconds:.1f}/{condition.seconds:g} 秒，"
                                            f"已等待 {elapsed:.1f} 秒；目标 {condition.target_temperature:g}±{condition.tolerance:g}℃，"
                                            f"末次温度 {data['material_temperature']:g}℃")
                        return False
                    previous_in_band = in_band
                else:
                    remaining = condition.seconds - elapsed
                if not qualified and remaining <= 0:
                    return True
                previous_sample = sampled
            except Exception as exc:
                self.activity.device(condition.device_id, {"read_ok": False})
                self.activity.temperatures([{"device_id": condition.device_id, "target_temperature": None}], {})
                self._last_error = "微波保温状态读取失败：" + str(exc)
                return False
            sleep_seconds = min(max(0, next_poll - self._wait_clock()), remaining if remaining > 0 else 1)
            if qualified:
                sleep_seconds = min(sleep_seconds, max(0, condition.timeout-(self._wait_clock()-started)))
            paused = await self._pause_aware_sleep(sleep_seconds)
            if paused is None:
                return False

    async def _wait_heater_pair_stable(self, condition):
        reached = condition.type == WaitType.HEATER_PAIR_REACHED
        tolerance = None if reached else condition.tolerance
        timeout_error = "两路前驱体到温等待超时" if reached else "两路前驱体温度稳定等待超时"
        start = self._wait_clock()
        stable_since = None
        pause_generation = self._pause_generation
        while True:
            if self._should_stop() or await self._wait_for_resume() is None:
                return False
            generation = self._pause_generation
            if generation != pause_generation:
                stable_since = None
                pause_generation = generation
            if self._wait_clock() - start > condition.timeout:
                self._last_error = timeout_error
                return False
            readings = {}
            try:
                for target in condition.targets:
                    if self._should_stop():
                        return False
                    if self._is_paused():
                        break
                    data = await asyncio.to_thread(self._dm.read_heater_data, target["device_id"])
                    if (data.get("read_ok") is False or data.get("fault_code", 0) != 0
                            or not _is_nonnegative_finite_number(data.get("pv"))):
                        raise ValueError(f'{target["device_id"]} 温度无效或读取失败')
                    readings[target["device_id"]] = data
            except Exception as exc:
                self.activity.temperatures(condition.targets, {k: v["pv"] for k, v in readings.items()}, tolerance)
                self._last_error = "前驱体温度读取失败：" + str(exc)
                return False
            if len(readings) == len(condition.targets):
                self.activity.temperatures(condition.targets, {k: v["pv"] for k, v in readings.items()}, tolerance)
            self.last_device_result = {"device_type": "heater_pair", "heaters": readings}
            if self._should_stop():
                return False
            if self._is_paused() or self._pause_generation != pause_generation:
                stable_since = None
                continue
            now = self._wait_clock()
            if now - start > condition.timeout:
                self._last_error = timeout_error
                return False
            if reached:
                if all(readings[t["device_id"]]["pv"] >= t["target_temperature"] for t in condition.targets):
                    return True
                if await self._pause_aware_sleep(1.0) is None:
                    return False
                continue
            if all(abs(readings[t["device_id"]]["pv"] - t["target_temperature"]) <= condition.tolerance
                   for t in condition.targets):
                if stable_since is None:
                    stable_since = now
                self.activity.stable_seconds = now - stable_since
                if now - stable_since >= condition.seconds:
                    return True
            else:
                stable_since = None
                self.activity.stable_seconds = 0.0
            if await self._pause_aware_sleep(1.0) is None:
                return False

    async def _wait_condition(self, condition):
        """等待条件满足

        Args:
            condition: 等待条件
        """
        self.activity.wait(condition)
        if condition.type == WaitType.SYRINGE_PUMP_COMPLETE:
            return await self._wait_syringe(condition.device_id, condition.timeout)
        if condition.type == WaitType.MICROWAVE_MONITORED_HOLD:
            return await self._monitored_hold(condition)
        if condition.type in (WaitType.HEATER_PAIR_REACHED, WaitType.HEATER_PAIR_STABLE):
            return await self._wait_heater_pair_stable(condition)
        loop = asyncio.get_event_loop()
        start_time = self._wait_clock()

        if condition.type == WaitType.DURATION:
            if not _is_nonnegative_finite_number(condition.seconds):
                logger.error(f"Invalid duration wait seconds: {condition.seconds}")
                return False
        elif condition.type in {
            WaitType.TEMPERATURE_REACHED,
            WaitType.MICROWAVE_TEMPERATURE_REACHED,
            WaitType.MICROWAVE_TEMPERATURE_BELOW,
            WaitType.MICROWAVE_COMPLETE,
            WaitType.PUMP_COMPLETE,
        }:
            if not _is_nonnegative_finite_number(condition.timeout):
                logger.error(f"Invalid wait timeout: {condition.timeout}")
                return False

        if condition.type in {
            WaitType.TEMPERATURE_REACHED,
            WaitType.MICROWAVE_TEMPERATURE_REACHED,
        } and not _is_nonnegative_finite_number(condition.tolerance):
            logger.error(f"Invalid wait tolerance: {condition.tolerance}")
            return False
        if (
            condition.type in {WaitType.MICROWAVE_TEMPERATURE_REACHED, WaitType.MICROWAVE_TEMPERATURE_BELOW}
            and not _is_nonnegative_finite_number(condition.target_temperature)
        ):
            logger.error(
                f"Invalid microwave target temperature: {condition.target_temperature}"
            )
            return False

        if condition.type == WaitType.DURATION:
            logger.info(f"Waiting {condition.seconds}s...")
            return not self._should_stop() and await self._pause_aware_sleep(condition.seconds) is not None

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
                elapsed = self._wait_clock() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Wait timeout after {condition.timeout}s")
                    return False
                try:
                    data = await loop.run_in_executor(
                        None, self._dm.read_heater_data, condition.device_id
                    )
                    if self._should_stop():
                        return False
                    if self._is_paused():
                        continue
                    if self._wait_clock() - start_time > condition.timeout:
                        return False
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

        elif condition.type in {WaitType.MICROWAVE_TEMPERATURE_REACHED, WaitType.MICROWAVE_TEMPERATURE_BELOW}:
            cooling = condition.type == WaitType.MICROWAVE_TEMPERATURE_BELOW
            target_temperature = condition.target_temperature
            last_data = {}
            stable_since = None
            previous_sample = None
            pause_generation = self._pause_generation
            stable_required = condition.seconds if not cooling else 0
            if not _is_nonnegative_finite_number(stable_required):
                self._last_error = "微波连续稳定时间必须为非负数"
                return False
            budget_getter = getattr(self._dm, "microwave_read_budget", None)
            budget = budget_getter(condition.device_id) if callable(budget_getter) else 7.0
            if not _is_nonnegative_finite_number(budget) or budget <= 0:
                budget = 7.0

            def timed_out():
                elapsed = self._wait_clock() - start_time
                if elapsed <= condition.timeout:
                    return False
                temperature = last_data.get("material_temperature")
                temperature_text = f"{temperature:g}℃" if _is_nonnegative_finite_number(temperature) else "未知"
                target_text = f"≤{target_temperature:g}℃" if cooling else f"{target_temperature:g}±{condition.tolerance:g}℃"
                self._last_error = (
                    f"微波{'降温' if cooling else '到温'}等待超时：目标 {target_text}，"
                    f"最后温度 {temperature_text}，已等待 {elapsed:.1f} 秒（上限 {condition.timeout:g} 秒）；"
                    f"控制状态={last_data.get('control_active', '未知')}，"
                    f"控制字={last_data.get('control_word', '未知')}"
                )
                logger.warning(self._last_error)
                return True

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
                if pause_generation != self._pause_generation:
                    stable_since = previous_sample = None
                    self.activity.stable_seconds = 0.0
                    pause_generation = self._pause_generation
                if timed_out():
                    return False
                try:
                    read_started = time.monotonic()
                    data = await self._read_microwave_data(condition.device_id)
                    read_duration = time.monotonic() - read_started
                    sampled = self._wait_clock()
                    last_data = data
                    self.activity.device(condition.device_id, data)
                    material_temperature = data.get("material_temperature")
                    self.activity.temperatures([{"device_id": condition.device_id, "target_temperature": target_temperature}],
                        {condition.device_id: material_temperature if data.get("read_ok") is not False else None}, None if cooling else condition.tolerance)
                    self.last_device_result = data
                    if not cooling and not self._valid_microwave_state(data):
                        return False
                    if self._should_stop():
                        return False
                    if stable_required and (read_duration > budget or
                            (previous_sample is not None and sampled - previous_sample > budget)):
                        self._last_error = f"微波稳定到温状态超过通讯预算 {budget:g} 秒"
                        return False
                    if pause_generation != self._pause_generation:
                        stable_since = previous_sample = None
                        self.activity.stable_seconds = 0.0
                        pause_generation = self._pause_generation
                    if self._is_paused():
                        stable_since = previous_sample = None
                        self.activity.stable_seconds = 0.0
                        continue
                    if timed_out():
                        return False
                    if cooling:
                        if (data.get("read_ok") is False or data.get("fault_code") != 0
                                or data.get("status_confirmed") is not True
                                or data.get("control_active") is not False
                                or data.get("output_active") is not False
                                or data.get("stop_confirmed") is not True):
                            self._last_error = "微波降温检查失败：读取、故障状态或停止状态未确认，禁止排液"
                            return False
                        if not _is_nonnegative_finite_number(material_temperature):
                            self._last_error = "微波降温检查失败：物料温度无效，禁止排液"
                            logger.error("Cooling wait failed: invalid material temperature")
                            return False
                        if self._should_stop():
                            return False
                        if self._is_paused():
                            continue
                        if timed_out():
                            return False
                        if material_temperature <= target_temperature:
                            logger.info(f"Cooling complete: {material_temperature}C <= {target_temperature}C")
                            return True
                    if not cooling and material_temperature is not None and abs(
                        float(material_temperature) - float(target_temperature)
                    ) <= condition.tolerance:
                        if stable_since is None:
                            stable_since = sampled
                        self.activity.stable_seconds = min(stable_required, max(0, sampled - stable_since))
                        if self.activity.stable_seconds >= stable_required:
                            logger.info(
                                f"Microwave temperature reached: "
                                f"{float(material_temperature):.1f}C ~ "
                                f"{float(target_temperature):.1f}C, stable {stable_required:g}s"
                            )
                            return True
                    elif not cooling:
                        stable_since = None
                        self.activity.stable_seconds = 0.0
                    previous_sample = sampled
                except Exception as e:
                    self.activity.device(condition.device_id, {"read_ok": False})
                    self.activity.temperatures([{"device_id": condition.device_id, "target_temperature": target_temperature}], {})
                    logger.warning(
                        f"Microwave temperature wait read failed for "
                        f"{condition.device_id}: {e}"
                    )
                    self._last_error = "微波温度读取失败：" + str(e)
                    return False
                paused_duration = await self._pause_aware_sleep(0.2)
                if paused_duration is None:
                    return False

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
                elapsed = self._wait_clock() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Microwave complete wait timeout after {condition.timeout}s")
                    return False
                try:
                    data = await self._read_microwave_data(condition.device_id)
                    if data.get("fault_code"):
                        self._last_error = f"Microwave fault: {data['fault_code']}"
                        return False
                    if self._should_stop():
                        return False
                    if self._is_paused():
                        continue
                    if self._wait_clock() - start_time > condition.timeout:
                        return False
                    if self._microwave_completion_confirmed(data):
                        logger.info(f"Microwave {condition.device_id} completed")
                        return True
                    if self._microwave_is_running(data):
                        seen_running = True
                    elif seen_running and data.get("stop_confirmed") is True and data.get("fault_code") == 0:
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

        elif condition.type == WaitType.PUMP_COMPLETE:
            pump_key = (condition.device_id, condition.channel)
            if pump_key in self._pump_repeat_counts:
                repeat_count = self._pump_repeat_counts[pump_key]
                if isinstance(repeat_count, bool) or repeat_count != 1:
                    logger.error(
                        f"Pump {condition.device_id} CH{condition.channel}: "
                        f"pump_complete cannot track repeat_count={repeat_count}; "
                        "use a bounded duration and explicit stop"
                    )
                    return False
            logger.info(
                f"Waiting for pump {condition.device_id} CH{condition.channel} to complete"
            )
            seen_running = pump_key in self._pump_start_confirmed
            self._pump_start_confirmed.discard(pump_key)  # Evidence belongs to this wait only.
            while True:
                if self._should_stop():
                    logger.info("Pump wait interrupted by stop request")
                    return False
                paused_duration = await self._wait_for_resume()
                if paused_duration is None:
                    return False
                elapsed = self._wait_clock() - start_time
                if elapsed > condition.timeout:
                    logger.warning(f"Pump wait timeout after {condition.timeout}s")
                    return False
                try:
                    status = await loop.run_in_executor(
                        None, self._dm.read_pump_status, condition.device_id
                    )
                    if self._should_stop():
                        return False
                    if self._is_paused():
                        continue
                    if self._wait_clock() - start_time > condition.timeout:
                        return False
                    ch_data = status["channels"].get(str(condition.channel))
                    self.activity.device(condition.device_id, ch_data or {"read_ok": False})
                    if not ch_data or ch_data.get("read_ok") is not True:
                        paused_duration = await self._pause_aware_sleep(1.0)
                        if paused_duration is None:
                            return False
                        continue
                    if ch_data.get("running") is True and ch_data.get("run_status") in ("START", "FULL_SPEED"):
                        seen_running = True
                    elif seen_running and ch_data.get("running") is False and ch_data.get("run_status") == "STOP":
                        logger.info(
                            f"Pump channel {condition.channel} completed"
                        )
                        return True
                except Exception as e:
                    self.activity.device(condition.device_id, {"read_ok": False})
                    logger.warning(f"Pump wait read failed for {condition.device_id} CH{condition.channel}: {e}")
                paused_duration = await self._pause_aware_sleep(1.0)
                if paused_duration is None:
                    return False

        return True
