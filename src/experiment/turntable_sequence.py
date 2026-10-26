"""Shared bottle coordination over the existing synchronous controller."""
import asyncio
import logging
import time


logger = logging.getLogger(__name__)
POLL_SECONDS = 0.1


async def verify_collection_pumps(dm, call=asyncio.to_thread):
    status = await call(dm.read_pump_status, "pump1")
    for channel in ("3", "4"):
        data = status.get("channels", {}).get(channel, {})
        if (data.get("read_ok") is not True or data.get("running") is not False
                or data.get("run_status") != "STOP"):
            raise RuntimeError(f"转盘运动前蠕动泵通道 {channel} 未确认停止")
    for did in ("syringe_pump1", "syringe_pump2"):
        state = await call(dm.syringe(did).read)
        if state.get("read_ok") is not True or state.get("busy") is not False:
            raise RuntimeError(f"转盘运动前 {did} 未确认停止")


async def verify_collection_valve(dm, call=asyncio.to_thread):
    status = await call(dm.valve_operation, "valve1", "status")
    if status.get("read_ok") is not True or status.get("relay_energized") is not True:
        raise RuntimeError("转盘运动前废液阀位读取失败或已改变")


class TurntableSequence:
    device_id = "turntable1"
    stop_message = "实验停止已取消转盘操作"

    def __init__(self, device_manager, stopped_callable, changed_callback, device_id="turntable1"):
        self.device_id = device_id
        self._dm = device_manager
        self._stopped = stopped_callable
        self._changed = changed_callback
        self.owner = object()
        self.claimed = False
        self.needs_stop = False
        self.last_error = None
        self._invalidated = False
        self._stop_succeeded = False
        self._stop_lock = asyncio.Lock()

    @property
    def poll_seconds(self):
        return POLL_SECONDS

    @property
    def control(self):
        return self._dm.turntable(self.device_id)

    def invalidate_pending(self):
        """Fence queued commands immediately, without waiting for a serial lock."""
        self._invalidated = True
        if self.claimed:
            self.control.invalidate_pending()

    def _check_running(self):
        if self._invalidated or self._stopped():
            raise RuntimeError(self.stop_message)

    def _check_claimed(self):
        if not self.claimed or self.control.owner is not self.owner:
            raise RuntimeError("实验尚未占用转盘")

    async def _call(self, method, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(method, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.invalidate_pending()
            # A cancelled coroutine must not leave an untracked serial worker
            # that can write after the caller begins cleanup or releases locks.
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

    def _publish(self, summary):
        if self._changed is not None:
            self._changed(summary)

    @staticmethod
    def _check_read(summary):
        if not summary.get("connected") or summary.get("read_ok") is not True:
            raise OSError(summary.get("read_error") or "转盘连接或状态读取失败")

    def _check_bottle_number(self, expected_bottle):
        maximum = self.control.config.bottle_count
        if (isinstance(expected_bottle, bool) or not isinstance(expected_bottle, int)
                or not 1 <= expected_bottle <= maximum):
            raise ValueError(f"自动化瓶号须为1–{maximum}，不能循环使用产物瓶")

    def _check_bottle(self, summary, expected_bottle):
        self._check_read(summary)
        if (summary.get("busy") is not False or summary.get("stop_confirmed") is not True
                or summary.get("motion_blocked") or summary.get("bottle_ready") is not True
                or not summary.get("bottle_token")
                or summary.get("current_bottle") != expected_bottle
                or summary.get("position") != (expected_bottle - 1) * self.control.config.pulses_per_bottle):
            raise RuntimeError(f"转盘未确认停在{expected_bottle}号瓶，禁止后续收集或换瓶")

    async def claim(self, *, require_calibration=True):
        self._check_running()

        def reserve():
            self._check_running()
            control = self.control
            if (not control.config.enabled or (require_calibration and (not control.config.home_enabled
                    or not control.config.position_encoding_verified or not control.config.bottle_count))):
                raise RuntimeError("自动化需要已启用并核验原点和瓶位的转盘")
            control.claim(self.owner)
            self.claimed = True

        await self._call(reserve)

    async def verify(self, expected_bottle):
        self._check_bottle_number(expected_bottle)
        self._check_claimed()
        try:
            self._check_running()
            summary = await self._call(self.control.read)
            self._check_running()
            self._publish(summary)
            self._check_bottle(summary, expected_bottle)
            return summary
        except (Exception, asyncio.CancelledError):
            self.needs_stop = True
            raise

    async def home(self):
        return await self._move({"action": "home_bottle"}, 1)

    async def next(self, expected_bottle):
        self._check_bottle_number(expected_bottle)
        self._check_claimed()
        self._check_running()
        if expected_bottle <= 1:
            raise ValueError("自动化不得回绕到已使用的1号瓶")
        # The requested next number is a strict sequence constraint; never
        # silently move to another bottle or accept a wrapped manual position.
        try:
            summary = await self.verify(expected_bottle - 1)
        except (Exception, asyncio.CancelledError):
            await self.stop()
            raise
        return await self._move({"action": "next_bottle",
                                 "expected_position": summary["position"],
                                 "expected_bottle_token": summary["bottle_token"]}, expected_bottle)

    async def _move(self, request, expected_bottle):
        self._check_claimed()
        self._check_bottle_number(expected_bottle)
        self.needs_stop = True
        self._stop_succeeded = False
        try:
            self._check_running()
            control = self.control
            with control.gate:
                generation = control.generation

            def command():
                self._check_running()
                return self._dm.turntable_command(self.device_id, request,
                    expected_generation=generation, owner=self.owner)

            accepted = await self._call(command)
            action_id = accepted.get("action_id")
            if (not action_id or accepted.get("action") != request["action"]
                    or accepted.get("target_bottle") != expected_bottle
                    or accepted.get("result") != "accepted"):
                raise RuntimeError("转盘未接受本次瓶位动作")
            deadline = time.monotonic() + accepted["duration_seconds"]
            while True:
                self._check_running()
                if time.monotonic() >= deadline:
                    raise TimeoutError("转盘瓶位动作超时")
                summary = await self._call(control.read)
                self._check_running()
                self._publish(summary)
                self._check_read(summary)
                action = summary.get("action") or {}
                if (action.get("action_id") != action_id
                        or action.get("action") != request["action"]
                        or action.get("target_bottle") != expected_bottle):
                    raise RuntimeError("转盘动作已变化，不能确认本次瓶位")
                if action.get("result") == "completed":
                    self._check_bottle(summary, expected_bottle)
                    self.needs_stop = False
                    return summary
                if action.get("result") not in ("accepted", "running"):
                    raise RuntimeError(action.get("error") or "转盘瓶位动作未完成")
                # Pausing the batch does not pause an already-issued movement.
                await asyncio.sleep(self.poll_seconds)
        except (Exception, asyncio.CancelledError):
            await self.stop()
            raise

    async def stop(self):
        self.invalidate_pending()
        if not self.claimed:
            return True
        async with self._stop_lock:
            if self._stop_succeeded and not self.needs_stop:
                def still_stopped():
                    control = self.control
                    with control.lock:
                        control.require_idle()
                        summary = control.summary()
                        return (summary.get("read_ok") is True and summary.get("busy") is False
                                and summary.get("stop_confirmed") is True)
                try:
                    if await self._call(still_stopped):
                        return True
                except RuntimeError:
                    pass
            self.needs_stop = True
            try:
                stopped = await self._call(self.control.stop)
                summary = await self._call(self.control.summary)
                self._publish(summary)
                if stopped is not True:
                    raise RuntimeError("转盘停止未确认，保留实验占用")
                self._stop_succeeded = True
                self.needs_stop = False
                self.last_error = None
                return True
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("自动化转盘停机失败: %s", exc)
                return False

    async def release(self):
        if not self.claimed:
            return True
        if self.needs_stop:
            return False

        def release():
            if not self.control.release(self.owner):
                return False
            self.claimed = False
            return True

        return await self._call(release)
