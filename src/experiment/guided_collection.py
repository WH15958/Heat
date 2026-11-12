"""Four-ring guided coordination; serial drivers remain synchronous."""
import asyncio
import time

from src.experiment.collection_layout import bottle_location, collection_plan
from src.experiment.turntable_sequence import TurntableSequence


class GuidedCollection(TurntableSequence):
    poll_seconds = 0.5

    def __init__(self, dm, stopped, changed, stage):
        super().__init__(dm, stopped, changed)
        self.stage = stage
        self.current_bottle = None
        self.expected_positions = None
        self.generations = None

    def _check_running(self):
        super()._check_running()
        if self.claimed and self.generations != [self.control.generation, self.platform.generation]:
            raise RuntimeError("停止请求已取消接样阶段")

    @property
    def platform(self):
        return self.control.peer

    def _check_claimed(self):
        super()._check_claimed()
        if self.platform is None or self.platform.owner is not self.owner:
            raise RuntimeError("引导式尚未占用移动平台")

    def invalidate_pending(self):
        super().invalidate_pending()
        if self.claimed and self.platform is not None:
            self.platform.invalidate_pending()

    async def claim(self, **kwargs):
        def reserve():
            self._check_running()
            from src.utils.config import SystemConfig
            collection_plan(SystemConfig(turntables=[self.control.config, self.platform.config]), 1)
            self.control.claim_guided_pair(self.owner)
            self.generations = [self.control.generation, self.platform.generation]
            self.claimed = True
        await self._call(reserve)

    def _read_pair(self, *, allow_reset=False, stable=True):
        with self.control.lock:
            self._check_claimed()
            self._check_running()
            states = [axis.read(force=True) for axis in (self.control, self.platform)]
            for axis, state in zip((self.control, self.platform), states):
                self._check_read(state)
                if stable:
                    reset = allow_reset and axis is self.control and state["work_state"] == 0
                    if (state["busy"] is not False or state["speed_raw"] != 0
                            or state["motion_blocked"] or (not reset and not state["stop_confirmed"])):
                        raise RuntimeError("接样双轴未确认稳定停止")
            platform_position = states[1]["position"]
            tolerance = self.platform.position_tolerance
            if not self.platform.config.ring_positions[-1] - tolerance <= platform_position <= tolerance:
                raise RuntimeError("平台超出已标定工作范围")
            return states

    def _summary(self, states, bottle=None):
        rotation, platform = states
        location = bottle_location(self.control.config, bottle) if bottle else {}
        return dict(rotation, current_bottle=bottle, collection_ring=location.get("collection_ring"),
                    ring_bottle_number=location.get("ring_bottle_number"),
                    axes={self.device_id: rotation, self.platform.config.device_id: platform})

    async def prepare_start(self):
        self._check_claimed()
        generation = self.control.generation
        self.needs_stop = True
        await self._call(self.control.prepare_guided_start, self.owner, generation)
        states = await self._call(self._read_pair, allow_reset=True)
        self.expected_positions = [state["position"] for state in states]
        self._publish(self._summary(states))

    async def verify(self, expected_bottle):
        location = bottle_location(self.control.config, expected_bottle)
        try:
            states = await self._call(self._read_pair)
            rotation, platform = states
            if (self.current_bottle != expected_bottle
                    or rotation["position"] % self.control.config.counts_per_revolution != location["rotation_offset"]
                    or abs(platform["position"] - location["platform_position"]) > self.platform.position_tolerance
                    or self.expected_positions != [state["position"] for state in states]):
                raise RuntimeError(f"接样双轴未确认停在{expected_bottle}号瓶")
            summary = self._summary(states, expected_bottle)
            self._publish(summary)
            return summary
        except (Exception, asyncio.CancelledError):
            self.needs_stop = True
            self.current_bottle = None
            raise

    async def _move_axis(self, axis, request, phase, label, target_bottle):
        async def execute():
            states = await self._call(self._read_pair, allow_reset=request["action"] == "home")
            if self.expected_positions is not None and self.expected_positions != [s["position"] for s in states]:
                raise RuntimeError("接样坐标在阶段间发生变化，禁止继续")
            self.current_bottle = None
            self.needs_stop = True
            self._publish(self._summary(states))
            if request["action"] != "home":
                request["expected_position"] = states[0 if axis is self.control else 1]["position"]
            generation = axis.generation

            def dispatch():
                self._check_running()
                return self._dm.turntable_command(axis.config.device_id, request,
                                                  expected_generation=generation, owner=self.owner)

            accepted = await self._call(dispatch)
            self._check_running()
            if not accepted.get("action_id") or accepted.get("result") not in ("accepted", "running", "completed"):
                raise RuntimeError("接样动作未被接受")
            deadline = time.monotonic() + accepted["duration_seconds"]
            peer_index = 1 if axis is self.control else 0
            while True:
                self._check_running()
                if time.monotonic() >= deadline:
                    raise TimeoutError("接样单轴动作超时")
                readings = await self._call(self._read_pair, stable=False)
                self._check_running()
                self._publish(self._summary(readings))
                moving = readings[0 if axis is self.control else 1]
                peer = readings[peer_index]
                if (peer["position"] != states[peer_index]["position"] or peer["speed_raw"] != 0
                        or peer["busy"] is not False or not peer["stop_confirmed"] or peer["motion_blocked"]):
                    raise RuntimeError("非运动轴状态改变，停止接样")
                action = moving.get("action") or {}
                if action.get("action_id") != accepted["action_id"] or action.get("target") != accepted["target"]:
                    raise RuntimeError("接样动作已改变，不能确认本次定位")
                if action.get("result") == "completed":
                    if (not moving["stop_confirmed"] or moving["busy"] is not False or moving["speed_raw"] != 0
                            or moving["motion_blocked"]
                            or not axis._target_reached(moving["position"], accepted["target"])):
                        raise RuntimeError("接样动作完成但停止或坐标未确认")
                    self.expected_positions = [s["position"] for s in readings]
                    self.needs_stop = False
                    return self._summary(readings)
                if action.get("result") not in ("accepted", "running"):
                    raise RuntimeError(action.get("error") or "接样动作失败")
                await asyncio.sleep(self.poll_seconds)
        return await self.stage(phase, label, target_bottle, axis.config.device_id, execute)

    async def home(self):
        try:
            await self._move_axis(self.control, dict(action="home", direction="negative", speed=1000),
                                  "rotation_home", "转盘机械回零", 1)
            await self._move_axis(self.platform, dict(action="select_ring", ring=1),
                                  "platform_ring", "平台返回最外圈", 1)
            self.current_bottle = 1
            return await self.verify(1)
        except (Exception, asyncio.CancelledError):
            await self.stop()
            raise

    async def next(self, target):
        location = bottle_location(self.control.config, target)
        if target <= 1:
            raise ValueError("禁止回绕到已使用的1号瓶")
        try:
            await self.verify(target - 1)
            previous = bottle_location(self.control.config, target - 1)
            if location["collection_ring"] != previous["collection_ring"]:
                await self._move_axis(self.control, dict(action="return_start"), "rotation_start",
                                      f"{target-1}→{target}：转盘回起始角度", target)
                await self._move_axis(self.platform, dict(action="select_ring", ring=location["collection_ring"]),
                                      "platform_ring", f"平台进入第{location['collection_ring']}圈", target)
            else:
                await self._move_axis(self.control, dict(action="select_bottle", bottle=target),
                                      "rotation_bottle", f"转盘定位{target}号瓶", target)
            self.current_bottle = target
            return await self.verify(target)
        except (Exception, asyncio.CancelledError):
            await self.stop()
            raise

    async def stop(self):
        self.invalidate_pending()
        self.current_bottle = None
        if not self.claimed:
            return True
        async with self._stop_lock:
            success = True
            for axis in (self.control, self.platform):
                try:
                    stopped = await self._call(axis.stop)
                    success = stopped is True and success
                except Exception as exc:
                    self.last_error = str(exc)
                    success = False
            self.needs_stop = not success
            self._publish(self._summary([self.control.summary(), self.platform.summary()]))
            return success

    async def release(self):
        if not self.claimed:
            return True
        if self.needs_stop:
            return False
        try:
            released = await self._call(self.control.release_guided_pair, self.owner)
            if released:
                self.claimed = False
            return released
        except RuntimeError:
            return False
