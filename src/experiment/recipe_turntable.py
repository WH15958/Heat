"""Recipe-scoped bottle reference and fixed-apparatus interlocks."""
from src.experiment.actions import ActionType
from src.experiment.turntable_sequence import (
    TurntableSequence, verify_collection_pumps, verify_collection_valve,
)


def turntable_steps(steps):
    return [s for s in steps if s.enabled and s.type.value.startswith("turntable.")]


def check_turntable_connections(dm, steps):
    """Preflight only; never connect, move or change a flow route."""
    selected = turntable_steps(steps)
    for step in selected:
        control = dm.turntable(step.params["device_id"])
        if not control.config.enabled or not control.device.is_connected():
            raise RuntimeError("配方转盘未启用或未连接")
        if step.type != ActionType.TURNTABLE_STOP and (
                not control.config.home_enabled or not control.config.position_encoding_verified
                or not control.config.bottle_count):
            raise RuntimeError("配方转盘原点和瓶位标定未启用")
    if not any(s.type != ActionType.TURNTABLE_STOP for s in selected):
        return
    pump = dm.get_pump("pump1")
    valve = dm.valves.get("valve1")
    if pump is None or not pump.is_connected() or valve is None or not valve.is_connected():
        raise RuntimeError("转盘运动需要已连接的 pump1 和 valve1")
    for did in ("syringe_pump1", "syringe_pump2"):
        if not dm.syringe(did).device.is_connected():
            raise RuntimeError(f"转盘运动需要已连接的 {did}")


class RecipeTurntable(TurntableSequence):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bottle = None
        self.stopped_by_step = False

    async def verify_liquid_route(self):
        self._check_running()
        await verify_collection_pumps(self._dm, self._call)
        await verify_collection_valve(self._dm, self._call)
        self._check_running()

    def rearm_home(self):
        # Only an explicitly completed STOP step can be followed by a new home.
        # Failure/experiment-stop cancellation never clears itself this way.
        if self.stopped_by_step and self._stop_succeeded and not self.needs_stop and not self._stopped():
            self._invalidated = False
            self.stopped_by_step = False

    async def execute_action(self, action):
        if action == ActionType.TURNTABLE_STOP:
            self.bottle = None
            if not await self.stop():
                raise RuntimeError(self.last_error or "转盘停止未确认")
            self.stopped_by_step = True
            return await self._call(self.control.summary)
        before = self.bottle
        self.bottle = None
        if action == ActionType.TURNTABLE_HOME:
            status = await self.home()
        else:
            if before is None:
                raise RuntimeError("下一瓶前须在本次配方中回原点")
            status = await self.next(before + 1)
        self.bottle = status["current_bottle"]
        return status

    async def cleanup(self, normal=False):
        if not self.claimed:
            return True
        if normal and not self.needs_stop:
            try:
                summary = await self._call(self.control.read)
                self._check_read(summary)
                if (summary.get("busy") is False and summary.get("stop_confirmed") is True
                        and not summary.get("motion_blocked")):
                    return await self.release()
            except Exception as exc:
                self.last_error = str(exc)
            # A successful run cannot be reported when its final read is unknown.
            await self.stop()
            return False
        self.bottle = None
        return await self.stop() and await self.release()
