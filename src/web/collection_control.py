"""Shared collection axes; cross-ring sequencing lives in guided orchestration."""
import logging
import time

from src.experiment.collection_layout import bottle_location
from src.protocols.turntable import STATUS_QUERY_GAP_SECONDS
from src.web.turntable_control import TurntableController, PENDING
from src.web.turntable_commands import CollectionCommand, parse_turntable_command

logger = logging.getLogger(__name__)


class CollectionAxisController(TurntableController):
    stable_reads = 3

    def __init__(self, config, device=None):
        self.peer = None
        self._last_query = float("-inf")
        super().__init__(config, device)

    def claim(self, owner):
        raise RuntimeError("四圈接样仅允许引导式成对占用，不支持旧单圈/YAML占用")

    def claim_guided_pair(self, owner):
        """Internal reservation only; ordinary claim keeps YAML unsupported."""
        with self.lock:
            if self.config.collection_axis != "rotation" or self.peer is None:
                raise RuntimeError("引导式需要完整接样双轴")
            axes = (self, self.peer)
            previous = [axis.owner for axis in axes]
            try:
                for axis in axes:
                    TurntableController.claim(axis, owner)
            except Exception:
                for axis, old_owner in zip(axes, previous):
                    axis.owner = old_owner
                raise

    def release_guided_pair(self, owner):
        with self.lock:
            axes = (self, self.peer)
            if self.peer is None or any(axis.owner is not owner for axis in axes):
                return False
            for axis in axes:
                axis.require_idle()
                state = axis.summary()
                if (not state["connected"] or not state["read_ok"] or not state["stop_confirmed"]
                        or state["busy"] is not False or axis.stopping):
                    return False
            with self.gate, self.peer.gate:
                if any(axis.stopping for axis in axes):
                    return False
                for axis in axes:
                    axis.owner = None
            return True

    def _is_stopped(self, status):
        return status.get("work_state") == 0x20 and status.get("speed_raw") == 0

    @property
    def position_tolerance(self):
        return 10 if self.config.collection_axis == "radial" else 0

    def _target_reached(self, position, target):
        return abs(position - target) <= self.position_tolerance

    def _ring_index(self, position):
        return next((i for i, target in enumerate(self.config.ring_positions)
                     if self._target_reached(position, target)), -1)

    def _observe(self, status):
        # Preserve raw work_state: this platform reports 0x20 while moving.
        if status.get("read_ok"):
            status["busy"] = status.get("work_state") not in (0, 0x20) or status.get("speed_raw") != 0
            status["state_name"] = "positioning" if status["busy"] else status["state_name"]
            self.device.snapshot.update(status)
        super()._observe(status)
        if (self._is_stopped(status) and self._stable_count >= self.stable_reads
                and not self._requires_stop and not (self.action and self.action["result"] in PENDING)):
            self.stop_confirmed = True

    def read(self, force=False):
        with self.lock:
            if (self.config.collection_axis == "radial" and not force
                    and time.monotonic() - self._last_query < 0.5):
                return self.summary()
            super().read()
            self._last_query = time.monotonic()
            return self.summary()

    def _read_status(self):
        # Guided motion shares one retry budget across both axes per segment.
        retry_idle = (self.stop_confirmed and not self._requires_stop
                      and not self._stability_pending and not self.stopping
                      and self.device.snapshot.get("read_ok") is True
                      and self.device.snapshot.get("busy") is False
                      and not (self.action and self.action["result"] in PENDING))
        if self.owner is not None and self.peer is not None:
            # During guided motion, a quiet peer is still part of a moving pair.
            retry_idle = retry_idle and not (
                self.peer.device.snapshot.get("busy") is not False
                or (self.peer.action and self.peer.action["result"] in PENDING))
        generation = self.generation
        peer_generation = self.peer.generation if self.peer else None
        motion = None
        if self.owner is not None and self.peer is not None and self.peer.owner is self.owner:
            motion = next((axis.action for axis in (self, self.peer)
                           if axis.action and axis.action["result"] in ("accepted", "running")), None)
        try:
            return self.device.read_status()
        except TimeoutError as exc:
            # Include protocol pacing, write budget and final short serial read.
            timeout = self.config.connection.timeout
            query_budget = timeout + min(1.0, timeout) + min(0.05, timeout) + STATUS_QUERY_GAP_SECONDS
            retry_motion = (motion is not None and not motion.get("status_retry")
                            and time.monotonic() + query_budget < motion["deadline"])
            if (not (retry_idle or retry_motion) or self.stopping or self.generation != generation
                    or not self.device.is_connected()
                    or (self.peer is not None and (self.peer.stopping or self.peer.generation != peer_generation))):
                raise
            retry = dict(device_id=self.config.device_id, first_error=str(exc), result="retrying")
            if retry_motion:
                motion["status_retry"] = retry
                if self.action is motion:
                    self._reset_stability()
            logger.warning("Collection %s status timed out; retrying observation once: %s",
                           self.config.device_id, exc)
            # Existing protocol pacing applies. A timed-out query has already
            # consumed its response budget; do not add a blocking sleep here.
            try:
                status = self.device.read_status()
                if (self.stopping or self.generation != generation
                        or (self.peer is not None and (self.peer.stopping or self.peer.generation != peer_generation))):
                    raise RuntimeError("停止请求已取消状态重查")
                if retry_motion and time.monotonic() >= motion["deadline"]:
                    raise TimeoutError("状态重查超过原动作期限")
                retry.update(result="received", position=status.get("position"), speed_raw=status.get("speed_raw"))
            except Exception as retry_error:
                retry.update(result="failed", error=str(retry_error))
                logger.warning("Collection %s status retry failed: %s", self.config.device_id, retry_error)
                raise
            logger.info("Collection %s status retry received: position=%s speed=%s",
                        self.config.device_id, status.get("position"), status.get("speed_raw"))
            return status

    def begin_stop(self):
        super().begin_stop()
        if self.peer is not None:
            self.peer.invalidate_pending()

    def summary(self):
        state = super().summary()
        state.update(collection_axis=self.config.collection_axis,
                     collection_peer=self.config.collection_peer,
                     position_tolerance=self.position_tolerance,
                     ring_counts=self.config.ring_counts,
                     ring_positions=self.config.ring_positions,
                     counts_per_revolution=self.config.counts_per_revolution)
        return state

    def _ready(self, axis, *, reset_allowed=False, owner=None):
        state = axis.read(force=True)
        axis.require_idle()
        if (not state["connected"] or not state["read_ok"] or state["speed_raw"] != 0
                or state["busy"] is not False or state["motion_blocked"]):
            raise RuntimeError("接样两轴须连接、状态有效且停止")
        if not state["stop_confirmed"] and not (reset_allowed and state["work_state"] == 0):
            raise RuntimeError("等待连续三次稳定停止读回，再操作")
        axis._check_owner(owner)
        return state

    def command(self, request, expected_generation=None, owner=None):
        req = parse_turntable_command(request)
        if req.action == "stop":
            return super().command(req, expected_generation, owner)
        if owner is not None:
            if self.owner is not owner or self.peer is None or self.peer.owner is not owner:
                raise RuntimeError("引导式尚未占用接样双轴")
            if req.action not in ("home", "return_start", "select_ring", "select_bottle"):
                raise ValueError("引导式不支持此接样动作")
        # Both paired controllers share this lock; keep peer checks and write atomic.
        with self.lock:
            generation = self.generation if expected_generation is None else expected_generation
            if generation != self.generation or self.stopping:
                raise RuntimeError("停止请求已取消待执行操作")
            if self.peer is None:
                raise RuntimeError("接样配对轴未注册")
            peer_generation = self.peer.generation
            peer_state = self._ready(self.peer, reset_allowed=owner is None, owner=owner)
            state = self._ready(self, reset_allowed=req.action == "home", owner=owner)
            if self.generation != generation or self.stopping or self.peer.stopping or self.peer.generation != peer_generation:
                raise RuntimeError("停止请求已取消待执行操作")
            radial = self.config.collection_axis == "radial"
            motion = None
            if isinstance(req, CollectionCommand):
                if req.expected_position != state["position"]:
                    raise RuntimeError("坐标已变化，请刷新")
                if req.action in ("select_ring", "platform_absolute", "platform_relative"):
                    if not radial:
                        raise ValueError("仅移动平台支持圈位及平台定位")
                    if req.action == "select_ring":
                        target = self.config.ring_positions[req.ring - 1]
                    elif req.action == "platform_absolute":
                        target = req.position
                    else:
                        target = state["position"] + req.steps
                    if not self.config.ring_positions[-1] <= target <= 0:
                        raise ValueError("平台目标超出已标定工作范围")
                    motion = dict(action="move_absolute", position=target,
                                  speed=5000 if req.action == "select_ring" else 1000)
                elif req.action == "return_start":
                    if radial:
                        raise ValueError("仅转盘支持角度和瓶位定位")
                    tolerance = self.peer.position_tolerance
                    if not self.config.ring_positions[-1] - tolerance <= peer_state["position"] <= tolerance:
                        raise RuntimeError("平台超出已标定工作范围")
                    rev = self.config.counts_per_revolution
                    lower, offset = divmod(state["position"], rev)
                    target = (lower + (1 if offset * 2 >= rev else 0)) * rev
                    motion = dict(action="move_absolute", position=target, speed=1000)
                else:
                    if radial:
                        raise ValueError("仅转盘支持角度和瓶位定位")
                    ring = self.peer._ring_index(peer_state["position"])
                    if ring < 0:
                        raise RuntimeError("平台不在已标定圈位")
                    first = 1 + sum(self.config.ring_counts[:ring])
                    count = self.config.ring_counts[ring]
                    if not first <= req.bottle < first + count:
                        raise ValueError("只能选择当前圈内瓶位，请先分步换圈")
                    rev = self.config.counts_per_revolution
                    offset = bottle_location(self.config, req.bottle)["rotation_offset"]
                    target = state["position"] // rev * rev + offset
                    if target < state["position"]:
                        target += rev
                    motion = dict(action="move_absolute", position=target, speed=1000)
            elif req.action == "home":
                if radial or req.direction != "negative" or req.speed != 1000:
                    raise ValueError("仅转盘支持以1000速度字段负向机械回零")
                motion = req
            elif req.action == "move_relative":
                if radial:
                    raise ValueError("平台请使用带当前坐标校验的高级移动指令")
                if req.speed != 1000 or not 0 < abs(req.steps) <= 500:
                    raise ValueError("微调须为±1–500计数，速度字段1000")
                motion = req
            else:
                raise ValueError("接样设备仅支持圈位、圈内选瓶、有限微调和转盘回零")
            if self.peer.stopping or self.peer.generation != peer_generation:
                raise RuntimeError("配对轴停止请求已取消待执行运动")
            result = super().command(motion, generation, owner)
            if req.action == "home":
                # Capture short homing near the sensor before the supervisor's
                # next tick. The synchronous protocol enforces query spacing.
                self.read(force=True)
                return dict(self.summary()["action"])
            return result
