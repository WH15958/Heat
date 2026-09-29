"""Per-device coordination; synchronous calls, no driver polling threads."""
import hashlib
import json
from pathlib import Path
import threading
import time
from datetime import datetime, timezone

from src.devices.syringe_commands import SyringeCommand
from src.devices.syringe_pump import SyringePumpDevice
from src.utils.serial_binding import resolve_connection


class SyringeController:
    def __init__(self, config, registry_dir=Path("data/syringe_programs"), device=None):
        self.device = device or SyringePumpDevice(config)
        self.config = config
        self.lock = threading.RLock()
        self.gate = threading.Lock()
        self.owner = None
        self.generation = 0
        self.stopping = 0
        self.binding = None
        self.registry_dir = Path(registry_dir)
        self.verified_slots = {}
        self.events = []

    def refresh_binding(self):
        with self.lock:
            if not self.device.is_connected():
                self.binding = resolve_connection(self.config.connection)
            return self.summary()

    def summary(self):
        with self.lock:
            d = self.device
            binding = vars(self.binding) if self.binding else {}
            return {"device_id": self.config.device_id, "name": self.config.name,
                    "connected": d.is_connected(), "configured": bool(self.config.connection.port or self.config.connection.binding.serial_number),
                    "connection_port": binding.get("resolved_port"), **binding,
                    "capacity_ml": self.config.capacity_ml, "valve_type": self.config.valve_type,
                    "address": self.config.connection.address, "protocol": self.config.protocol,
                    "microstep": d.mode, "orientation": d.orientation,
                    "owner": "experiment" if self.owner else None,
                    "action": {k: v for k, v in (d.action or {}).items() if k != "deadline"},
                    "stop_confirmed": d.stop_confirmed,
                    "events": list(self.events[-30:]), **d.snapshot}

    def connect(self):
        with self.lock:
            self.refresh_binding()
            if not self.binding or not self.binding.binding_resolved:
                raise ValueError("串口待配置或指纹未唯一匹配")
            if not self.device.is_connected():
                self.verified_slots.clear()
            return self.device.connect(self.binding.resolved_port)

    def disconnect(self):
        with self.lock:
            if self.owner:
                raise RuntimeError("实验占用中，不能断开")
            with self.gate:
                self.stopping += 1
        try:
            if self.device.is_connected() and not self.stop():
                raise RuntimeError("停机未确认，保留连接")
            with self.lock:
                self.verified_slots.clear()
                return self.device.disconnect()
        finally:
            with self.gate:
                self.stopping -= 1

    def claim(self, owner):
        with self.lock:
            if self.stopping:
                raise RuntimeError("停止/断开处理中")
            if self.owner not in (None, owner):
                raise RuntimeError("注射泵已被其他实验占用")
            if not self.device.is_connected():
                raise RuntimeError("注射泵未连接")
            if self.device.action and self.device.action.get("result") in ("accepted", "running", "paused", "unknown"):
                raise RuntimeError("注射泵有未完成的手动动作")
            self.owner = owner

    def release(self, owner):
        with self.lock:
            if self.owner == owner:
                self.owner = None

    def read(self, diagnostics=False):
        with self.lock:
            if not self.device.is_connected():
                return self.summary()
            try:
                status = self.device.diagnostics() if diagnostics else self.device.read_status()
            except Exception as exc:
                self.device.trusted = False
                if self.device.action and self.device.action.get("result") in ("accepted", "running"):
                    self.device.action["result"] = "unknown"
                self.device.snapshot = self.device.unknown(str(exc))
                return self.summary()
            result = {**self.summary(), **status}
        return result

    def enforce_timeout(self):
        """Application supervisor only; GET/WS reads never initiate writes."""
        with self.lock:
            action = self.device.action
            overdue = action and action.get("result") in ("accepted", "running", "paused", "unknown") and "deadline" in action and time.monotonic() > action["deadline"]
        if overdue:
            stopped = self.stop()
            with self.lock:
                if self.device.action is action:
                    action["result"] = "failed"
                    action["error"] = "动作超时；" + ("停止已确认" if stopped else "停止未确认")

    def _record(self, request, result):
        self.events.append({"at": datetime.now(timezone.utc).isoformat(),
                            "request": request.model_dump(exclude_unset=True), "result": result})
        self.events = self.events[-100:]

    def command(self, request, owner=None, expected_generation=None):
        req = request if isinstance(request, SyringeCommand) else SyringeCommand.model_validate(request)
        if req.action == "stop":
            return {"result": "stopped" if self.stop() else "stop_unconfirmed"}
        with self.gate:
            generation = self.generation if expected_generation is None else expected_generation
        def check_generation():
            with self.gate:
                if generation != self.generation or self.stopping:
                    raise RuntimeError("停止请求已取消待执行命令")
        with self.lock:
            with self.gate:
                if generation != self.generation:
                    raise RuntimeError("停止请求已取消待执行命令")
                if self.stopping:
                    raise RuntimeError("停止处理中")
            if self.owner is not None and self.owner != owner:
                raise RuntimeError("实验占用中，禁止手动控制")
            stored = None
            if req.action == "program_run" and req.slot is not None:
                if req.slot not in self.verified_slots:
                    raise ValueError("此连接尚未存储该槽位；禁止执行来源不明的EEPROM程序")
                stored = self.programs()[str(req.slot)]["program"]
                if hashlib.sha256(stored.encode()).hexdigest() != self.verified_slots[req.slot]:
                    raise ValueError("程序登记内容已变化，需重新存储")
            if req.action == "program_store":
                self.verified_slots.pop(req.slot, None)
            try:
                result = self.device.execute(req, stored, check_generation)
                if req.action == "program_store":
                    self._store(req)
                    self.verified_slots[req.slot] = hashlib.sha256(req.program.encode()).hexdigest()
                self._record(req, result)
                return result
            except Exception as exc:
                self._record(req, {"result": "failed_or_unknown", "error": str(exc)})
                raise

    def stop(self):
        # Invalidate calls queued before this stop, without holding the I/O lock.
        with self.gate:
            self.generation += 1
            self.stopping += 1
        try:
            result = self._stop()
            with self.lock:
                self._record(SyringeCommand(action="stop"),
                             {"result": "stop_confirmed" if result else "stop_unconfirmed"})
            return result
        finally:
            with self.gate:
                self.stopping -= 1

    def invalidate_pending(self):
        with self.gate:
            self.generation += 1

    def _stop(self):
        with self.lock:
            if not self.device.is_connected():
                return False
            try:
                self.device.execute({"action": "stop"})
            except Exception:
                return False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.lock:
                try:
                    q = self.device.exchange("Q", allow_fault=True)
                    if q.ready:
                        self.device.stop_confirmed = True
                        self.device.read_status()
                        return True
                except Exception:
                    return False
            time.sleep(0.1)
        return False  # T cannot interrupt a valve movement.

    def _path(self):
        # Hash configured IDs, not user paths.
        key = hashlib.sha256(self.config.device_id.encode()).hexdigest()
        return self.registry_dir / f"{key}.json"

    def programs(self):
        path = self._path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _store(self, req):
        records = self.programs()
        records[str(req.slot)] = {"name": req.name, "program": req.program,
                                  "sha256": hashlib.sha256(req.program.encode()).hexdigest(),
                                  "at": datetime.now(timezone.utc).isoformat(),
                                  "verification": "sent_unverified"}
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        path = self._path()
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(path)
        except Exception as exc:
            self.verified_slots.pop(req.slot, None)
            raise RuntimeError("EEPROM可能已写入，但程序登记持久化失败；禁止运行该槽位") from exc
