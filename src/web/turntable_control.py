"""Manual motion coordination. Only the application supervisor initiates timed stops."""
import copy
from datetime import datetime, timezone
import logging
import threading
import time
from uuid import uuid4

from src.devices.turntable import TurntableDevice
from src.devices.turntable_commands import MAX_POSITION, MIN_POSITION, TurntableCommand
from src.utils.serial_binding import resolve_connection
from src.web.turntable_commands import BottleCommand, parse_turntable_command

logger = logging.getLogger(__name__)
PENDING = {"accepted", "running", "unknown"}


class TurntableController:
    def __init__(self, config, device=None):
        self.config = config
        self.device = device or TurntableDevice(config)
        self.lock = threading.RLock()
        self.gate = threading.Lock()
        self.generation = 0
        self.stopping = 0
        self.binding = None
        self.action = None
        self.stop_confirmed = False
        self.homed = False
        self._bottle_position = None
        self._bottle_token = None
        self._blocked = None
        self._requires_stop = False
        self._stable_position = None
        self._stable_count = 0
        self._stable_at = None
        self._read_at = None
        self._stability_pending = False
        self._state_session = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        self._state_revision = 0

    def _block(self, reason):
        with self.gate:
            self._blocked = reason

    def require_idle(self):
        # Called under experiment registration lock: never wait for serial I/O.
        with self.gate:
            reason = self._blocked
            if self._requires_stop or (self.action and self.action["result"] in PENDING):
                reason = reason or "运动或停止结果待确认"
            if self._stability_pending:
                reason = reason or "停止坐标变化，等待稳定确认"
            if self.stopping:
                reason = "停止处理中"
            if not self.device.is_connected() and self._read_at is not None:
                reason = reason or "连接丢失，状态待确认"
            if (self.device.is_connected() and
                    (self._read_at is None or time.monotonic() - self._read_at > 6)):
                reason = reason or "状态未知或已过期"
            if reason:
                raise RuntimeError(f"转盘 {self.config.device_id}: {reason}")

    def refresh_binding(self):
        with self.lock:
            if not self.device.is_connected():
                self.binding = resolve_connection(self.config.connection)
            return self.summary()

    def snapshot_version(self):
        # Also usable for a timeout response while the serial lock is occupied.
        with self.gate:
            self._state_revision += 1
            return {"state_session": self._state_session, "state_revision": self._state_revision}

    def _invalidate_bottle(self):
        self._bottle_position = self._bottle_token = None

    def _bottle_state(self):
        status = self.device.snapshot
        current = None
        reason = None
        if not self.config.bottle_count:
            reason = "此设备尚未配置瓶位"
        elif not self.config.home_enabled or not self.config.position_encoding_verified:
            reason = "原点或定位协议尚未启用"
        elif not self.device.is_connected():
            reason = "请先连接设备并回到1号瓶"
        elif (not status.get("read_ok") or self._read_at is None
              or time.monotonic() - self._read_at > 6):
            reason = "状态未知或已过期，请刷新"
        elif (self.stopping or self._requires_stop or self._stability_pending
              or (self.action and self.action["result"] in PENDING) or status.get("busy") is not False):
            reason = "动作或停止结果待确认"
        elif (self._bottle_position is None or self._bottle_token is None
              or not self.stop_confirmed or status.get("position") != self._bottle_position):
            reason = "请先回到1号瓶建立瓶位基准"
        else:
            current = (self._bottle_position // self.config.pulses_per_bottle) % self.config.bottle_count + 1
        return {"bottle_count": self.config.bottle_count,
                "pulses_per_bottle": self.config.pulses_per_bottle,
                "current_bottle": current,
                "next_bottle": current % self.config.bottle_count + 1 if current is not None else None,
                "bottle_ready": current is not None, "bottle_error": reason,
                "bottle_token": self._bottle_token if current is not None else None}

    def summary(self):
        with self.lock:
            binding = vars(self.binding) if self.binding else {}
            return {"device_id": self.config.device_id, "name": self.config.name,
                    "configured": bool(self.config.connection.port or self.config.connection.binding.mode == "fingerprint"),
                    "connected": self.device.is_connected(),
                    "connection_error": getattr(self.device, "connection_error", None),
                    "connection_port": binding.get("resolved_port"), **binding,
                    **copy.deepcopy(self.device.snapshot),
                    "home_enabled": self.config.home_enabled,
                    "position_encoding_verified": self.config.position_encoding_verified,
                    "homed": self.homed, "stop_confirmed": self.stop_confirmed,
                    "motion_blocked": self._requires_stop or self._stability_pending or bool(self.stopping),
                    **self._bottle_state(),
                    "action": {k: v for k, v in (self.action or {}).items()
                               if k not in ("deadline", "saw_homing", "saw_running", "stop_attempted", "motion_action")} or None,
                    **self.snapshot_version()}

    def connect(self):
        with self.lock:
            if self.device.is_connected():
                return self.summary()
            if self.action and self.action["result"] in PENDING:
                self._fail("重新连接前的运动结果未知")
            self._reset_stability()
            self.refresh_binding()
            if not self.binding or not self.binding.binding_resolved:
                raise ValueError("串口待配置或指纹未唯一匹配")
            self.homed = self.stop_confirmed = False
            self._invalidate_bottle()
            self._block("连接状态待确认")
            try:
                if not self.device.connect(self.binding.resolved_port):
                    raise OSError("转盘连接失败")
                self._observe(self.device.snapshot)
            except Exception:
                self._block("连接失败，状态待确认")
                raise
            return self.summary()

    def _reset_stability(self):
        self._stable_position = self._stable_at = None
        self._stable_count = 0

    def _fail(self, reason):
        self.homed = self.stop_confirmed = False
        self._invalidate_bottle()
        self._requires_stop = True
        self._block(reason)
        if self.action and self.action["result"] in PENDING:
            self.action.update(result="unknown", error=reason)
            logger.warning("Turntable %s action uncertain: %s", self.config.device_id, self.action)

    def _observe(self, status):
        now = time.monotonic()
        if not status.get("read_ok"):
            raise OSError(status.get("read_error") or "转盘状态读取失败")
        with self.gate:
            self._read_at = now
        state, position = status["work_state"], status["position"]
        if self._bottle_position is not None and (state != 0x20 or position != self._bottle_position):
            self._invalidate_bottle()
        if state == 0:
            self.homed = False
        if state == 0x20:
            if position != self._stable_position:
                if self.stop_confirmed:
                    self._stability_pending = True
                    self.stop_confirmed = self.homed = False
                self._stable_position, self._stable_count, self._stable_at = position, 1, now
            elif self._stable_at is not None and now - self._stable_at >= 0.08:
                self._stable_count += 1
                self._stable_at = now
        else:
            self._reset_stability()
            self.stop_confirmed = False
        action = self.action
        if action and action["result"] in ("accepted", "running"):
            motion_action = action.get("motion_action", action["action"])
            if now >= action["deadline"] and motion_action != "run":
                self._fail("动作超时")
            elif state == 0:
                self._fail("控制器复位，运动结果未知")
            elif status["busy"]:
                action["result"] = "running"
                if state == 0x04:
                    action["saw_running"] = True
                if state == 0x08:
                    action["saw_homing"] = True
            elif state == 0x20 and self._stable_count >= 2:
                if motion_action == "run":
                    self._fail("连续运行提前停止")
                elif position != action["target"]:
                    self._fail("停止坐标与目标不一致")
                elif motion_action == "home" and not action.get("saw_homing"):
                    self._fail("未观察到回零过程，不能确认机械原点")
                else:
                    action["result"] = "completed"
                    self.stop_confirmed = True
                    self.homed = self.homed or motion_action == "home"
                    if action["action"] in ("home_bottle", "next_bottle"):
                        self._bottle_position = position
                        self._bottle_token = str(uuid4())
                    logger.info("Turntable %s completed: %s", self.config.device_id, action)
        pending = action and action["result"] in PENDING
        if (self._stability_pending and state == 0x20 and self._stable_count >= 2
                and not self._requires_stop and not pending):
            self._stability_pending = False
            self.stop_confirmed = True
        if self._requires_stop:
            self._block("运动或停止结果待确认")
        elif self._stability_pending:
            self._block("停止坐标变化，等待稳定确认")
        elif pending or status["busy"]:
            self._block("存在未完成运动")
        else:
            self._block(None)

    def read(self):
        with self.lock:
            if not self.device.is_connected():
                self._invalidate_bottle()
                self.device.snapshot = self.device.unknown(
                    getattr(self.device, "connection_error", None) or "转盘未连接")
                self.homed = self.stop_confirmed = False
                self._reset_stability()
                if self._read_at is not None:
                    self._block("连接丢失，状态待确认")
                if self.action and self.action["result"] in PENDING:
                    self._fail("运动中连接丢失")
                return self.summary()
            try:
                self._observe(self.device.read_status())
            except Exception as exc:
                self._invalidate_bottle()
                self.device.snapshot = self.device.unknown(str(exc))
                self._reset_stability()
                self.homed = self.stop_confirmed = False
                self._block("状态读取失败")
                if self.action and self.action["result"] in PENDING:
                    self._fail(str(exc))
            return self.summary()

    def command(self, request, expected_generation=None):
        req = parse_turntable_command(request)
        if req.action == "stop":
            if not self.stop():
                raise OSError("转盘停止未确认，连接已保留")
            return {"action": "stop", "result": "stopped"}
        with self.gate:
            generation = self.generation if expected_generation is None else expected_generation

        def check_generation():
            with self.gate:
                if generation != self.generation or self.stopping:
                    raise RuntimeError("停止请求已取消待执行运动")

        with self.lock:
            check_generation()
            if self._requires_stop or self._stability_pending or (self.action and self.action["result"] in PENDING):
                raise RuntimeError("已有运动或停止结果未确认")
            if req.action in ("move_relative", "move_absolute", "next_bottle") and not self.config.position_encoding_verified:
                raise RuntimeError("请先核验厂家工具的位移编码，再启用定位")
            if req.action in ("home", "home_bottle") and not self.config.home_enabled:
                raise RuntimeError("原点传感器及回零条件尚未确认")
            status = self.read()
            if not status["read_ok"] or status["busy"] is not False or status["motion_blocked"]:
                raise RuntimeError("转盘状态未知或正在运动")
            motion = req
            bottle_fields = {}
            if isinstance(req, BottleCommand):
                if not self.config.bottle_count:
                    raise RuntimeError("此设备尚未配置瓶位")
                if not self.config.position_encoding_verified:
                    raise RuntimeError("请先核验厂家工具的位移编码，再启用瓶位定位")
                if req.action == "home_bottle":
                    motion = TurntableCommand(action="home", direction="negative", speed=self.config.bottle_home_speed)
                    bottle_fields = {"target_bottle": 1}
                else:
                    if not status["bottle_ready"]:
                        raise RuntimeError(status["bottle_error"])
                    if (req.expected_position != status["position"]
                            or req.expected_bottle_token != status["bottle_token"]):
                        raise RuntimeError("瓶位已变化，请刷新后重新操作")
                    next_position = status["position"] + self.config.pulses_per_bottle
                    if next_position > MAX_POSITION:
                        raise ValueError("累计坐标达到上限，请先回到1号瓶")
                    motion = TurntableCommand(action="move_absolute",
                                              position=next_position,
                                              speed=self.config.bottle_speed)
                    bottle_fields = {"from_bottle": status["current_bottle"], "target_bottle": status["next_bottle"]}
            target = None
            if motion.action == "move_relative":
                target = status["position"] + motion.steps
            elif motion.action == "move_absolute":
                target = motion.position
            elif motion.action == "home":
                target = 0
            if target is not None and not MIN_POSITION <= target <= MAX_POSITION:
                raise ValueError("目标坐标超出控制器范围")
            check_generation()
            duration = motion.duration_seconds if motion.action == "run" else self.config.action_timeout
            if req.action == "home_bottle":
                duration = self.config.bottle_home_timeout
            self.action = {"action": req.action, "result": "accepted", "target": target,
                           "motion_action": motion.action, **bottle_fields,
                           "requested_speed": motion.speed, "duration_seconds": duration,
                           "deadline": time.monotonic() + duration}
            self._invalidate_bottle()
            self.stop_confirmed = False
            if motion.action == "home":
                self.homed = False
            self._reset_stability()
            self._block("存在未完成运动")
            try:
                check_generation()
                self.device.send_command(motion)
            except Exception as exc:
                self._fail(str(exc))
                raise
            logger.info("Turntable %s request=%s result=%s", self.config.device_id,
                        req.model_dump(exclude_unset=True), self.action)
            return dict(self.summary()["action"])

    def begin_stop(self):
        with self.gate:
            self.generation += 1
            self.stopping += 1

    def end_stop(self):
        with self.gate:
            self.stopping -= 1

    def invalidate_pending(self):
        with self.gate:
            self.generation += 1

    def stop(self):
        self.begin_stop()
        try:
            with self.lock:
                self._invalidate_bottle()
                if not self.device.is_connected():
                    self.device.snapshot = self.device.unknown("转盘未连接，无法确认停止")
                    self._fail("转盘未连接，停止未确认")
                    return False
                self._requires_stop = True
                self.stop_confirmed = self.homed = False
                self._block("停止待确认")
                try:
                    self.device.send_command(TurntableCommand(action="stop"))
                    deadline = time.monotonic() + 3
                    previous = None
                    while time.monotonic() < deadline:
                        try:
                            status = self.device.read_status()
                        except OSError as exc:
                            # Retry only observation, never the STOP write. Invalid
                            # reads break the consecutive stable-position evidence.
                            previous = None
                            self.device.snapshot = self.device.unknown(str(exc))
                            logger.warning("Turntable %s stop confirmation read failed: %s",
                                           self.config.device_id, exc)
                            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                            continue
                        if time.monotonic() >= deadline:
                            break
                        if status["work_state"] == 0x20 and previous == status["position"]:
                            self.stop_confirmed = True
                            self._requires_stop = False
                            self._stability_pending = False
                            self._stable_position = status["position"]
                            self._stable_count, self._stable_at = 2, time.monotonic()
                            with self.gate:
                                self._read_at = time.monotonic()
                            if self.action and self.action["result"] in PENDING:
                                self.action["result"] = "stopped"
                            self._block(None)
                            logger.info("Turntable %s stop confirmed at %s", self.config.device_id, status["position"])
                            return True
                        previous = status["position"] if status["work_state"] == 0x20 else None
                        time.sleep(0.1)
                except Exception as exc:
                    self.device.snapshot = self.device.unknown(str(exc))
                    logger.warning("Turntable %s stop failed: %s", self.config.device_id, exc)
                self._fail("停止未确认")
                return False
        finally:
            self.end_stop()

    def enforce_timeout(self):
        with self.lock:
            action = self.action
            if not action or action["result"] not in PENDING or action.get("stop_attempted"):
                return
            # The deadline is checked before a potentially blocking status read.
            due = time.monotonic() >= action["deadline"]
            if not due and not self._requires_stop:
                self.read()
                if action["result"] == "completed":
                    return
                due = time.monotonic() >= action["deadline"]
            if due or self._requires_stop:
                normal_end = (due and action["action"] == "run" and not self._requires_stop
                              and action.get("saw_running", False))
                error = action.get("error") or (
                    "连续运行到时停止" if normal_end else
                    "未确认连续运行" if action["action"] == "run" else "动作超时")
                action["stop_attempted"] = True
                stopped = self.stop()
                action["result"] = "completed" if normal_end and stopped else "failed"
                if action["result"] == "failed":
                    action["error"] = error + ("；停止已确认" if stopped else "；停止未确认")
                logger.info("Turntable %s supervised result: %s", self.config.device_id, action)

    def disconnect(self):
        self.begin_stop()
        try:
            with self.lock:
                if not self.device.is_connected() and (
                        self._read_at is not None or
                        (self.action and self.action["result"] in PENDING)):
                    self._fail("连接丢失，停止结果未确认")
                if self.device.is_connected() and not self.stop():
                    raise OSError("停止未确认，保留连接")
                if self._requires_stop:
                    raise RuntimeError("停止结果未确认，不能清除连接状态")
                if not self.device.disconnect():
                    raise OSError("串口释放失败，保留状态供重试")
                self.homed = self.stop_confirmed = False
                self._stability_pending = False
                self._invalidate_bottle()
                with self.gate:
                    self._read_at = None
                self._reset_stability()
                self._block(None)
                return self.summary()
        finally:
            self.end_stop()
