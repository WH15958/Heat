"""Synchronous MSP1-CX driver. Scheduling/ownership live in the Web layer."""
from datetime import datetime, timezone
import math
import time
import serial
from src.protocols.syringe_pump import SyringeProtocol, ERRORS, FULL_STEPS, SETTINGS, QUERIES, check_program
from src.utils.serial_manager import get_serial_manager


class SyringePumpDevice:
    def __init__(self, config, serial_factory=serial.Serial):
        self.config = config
        self.serial_factory = serial_factory
        self.handle = self.protocol = None
        self.mode = None  # No query for N: do not assume a prior application's mode.
        self.orientation = None
        self.trusted = False
        self.last_command_error = None
        self.action = None
        self.loaded = None
        self.last_program = None
        self.stop_confirmed = False
        self.snapshot = self.unknown()

    def is_connected(self):
        return self.handle is not None and self.handle.is_open

    def unknown(self, error=None):
        return {"read_ok": False, "busy": None, "initialized": None, "position": None,
                "target_position": None, "valve_position": None, "fault_code": None,
                "fault_description": None, "position_trusted": False,
                "theoretical_volume_ul": None, "read_error": error, "read_at": None}

    def connect(self, port):
        if self.is_connected():
            return True
        if not port:
            raise ValueError("串口待配置")
        mgr = get_serial_manager()
        if not mgr.acquire_port(port, force=False):
            raise RuntimeError("串口被占用")
        try:
            self.handle = self.serial_factory(port=None, baudrate=self.config.connection.baudrate,
                                              bytesize=8, parity="N", stopbits=1,
                                              timeout=0.1, write_timeout=1,
                                              xonxoff=False, rtscts=False, dsrdtr=False)
            self.handle.rts = self.handle.dtr = False
            self.handle.port = port
            mgr.register_handle(port, self.handle)
            self.handle.open()
            self.protocol = SyringeProtocol(self.handle, self.config.connection.address,
                                            self.config.protocol, self.config.connection.timeout)
            self.trusted = False
            self.mode = self.orientation = None
            self.loaded = None
            self.action = self.last_program = None
            self.stop_confirmed = False
            self.read_status()
            return True
        except Exception:
            mgr.release_port(port)
            self.handle = self.protocol = None
            raise

    def disconnect(self):
        if self.handle:
            if not get_serial_manager().release_port(self.handle.port):
                return False
        self.handle = self.protocol = None
        self.trusted = False
        self.mode = self.orientation = None
        self.loaded = None
        self.snapshot = self.unknown()
        return True

    def exchange(self, command, allow_fault=False):
        if not self.is_connected():
            raise RuntimeError("设备未连接")
        try:
            reply = self.protocol.exchange(command)
            if reply.error in (1, 7, 9, 10):
                self.trusted = False
            if reply.error and not allow_fault:
                raise RuntimeError(f"{reply.error}: {ERRORS.get(reply.error, '未知错误')}")
            return reply
        except Exception as exc:
            self.last_command_error = str(exc)
            self.trusted = False
            if self.action:
                self.action["result"] = "unknown"
            self.snapshot = self.unknown(str(exc))
            raise

    def read_status(self):
        q = self.exchange("Q", allow_fault=True)
        result = self.unknown()
        result.update(read_ok=True, read_at=datetime.now(timezone.utc).isoformat(),
                      busy=not q.ready, initialized=q.error not in (1, 7),
                      fault_code=q.error, fault_description=ERRORS.get(q.error, "未知错误"))
        if q.ready:
            for key in ("position", "target", "valve"):
                r = self.exchange(QUERIES[key], allow_fault=True)
                if r.error != q.error:
                    raise IOError("Status changed during snapshot")
                result[{"target": "target_position", "valve": "valve_position"}.get(key, key)] = int(r.data)
        if self.action and q.error:
            self.action["result"] = "failed"
        elif self.action and q.ready and self.action["result"] in ("accepted", "running"):
            buffer_ready = self.exchange("?10").data == "96"
            target = self.action.get("target")
            valve = self.action.get("valve")
            if not buffer_ready:
                self.action["result"] = "running"
            elif (target is not None and result["position"] != target) or (valve is not None and result["valve_position"] != valve):
                self.action["result"] = "failed"
                self.trusted = False
                self.last_command_error = "目标位置/阀位读回不一致"
                self.action["error"] = self.last_command_error
            else:
                self.action["result"] = "completed"
                if self.action["action"] == "configure":
                    verified, unverified = {}, []
                    for key, value in self.action["settings"].items():
                        if key in QUERIES:
                            actual = int(self.exchange(QUERIES[key]).data)
                            if actual != value:
                                self.trusted = False
                                self.action["result"] = "failed"
                                raise RuntimeError(f"参数读回不一致: {key}={actual}, expected={value}")
                            verified[key] = actual
                        else:
                            unverified.append(key)
                    if "microstep" in self.action["settings"]:
                        self.mode = self.action["settings"]["microstep"]
                    self.action.update(verified=verified, unverified=unverified,
                                       result="sent_unverified" if unverified else "completed")
                if self.action["action"] == "initialize":
                    self.mode = 0
                    self.orientation = self.action["direction"]
                    self.trusted = True
        elif self.action and not q.ready and self.action["result"] == "accepted":
            self.action["result"] = "running"
        result["position_trusted"] = self.trusted and q.ready and q.error == 0
        if q.ready and self.mode is not None and not 0 <= result["position"] <= FULL_STEPS[self.mode]:
            self.trusted = False
            raise IOError("Position outside configured stroke")
        if result["position_trusted"] and self.mode is not None:
            result["theoretical_volume_ul"] = result["position"] / FULL_STEPS[self.mode] * self.config.capacity_ml * 1000
        self.snapshot = result
        return dict(result)

    def diagnostics(self):
        data = self.read_status()
        if data["busy"]:
            return data
        values = {}
        for name, cmd in QUERIES.items():
            values[name] = self.exchange(cmd, allow_fault=True).data
        return {**data, "diagnostics": values}

    def _ready(self, initialize=False):
        data = self.read_status()
        if data["busy"] or (self.action and self.action["result"] in ("accepted", "running", "paused")):
            raise RuntimeError("泵忙，禁止叠加命令")
        if not initialize and (data["fault_code"] or not self.trusted or self.mode is None or self.orientation is None):
            raise RuntimeError("故障或位置/模式未经本连接确认；检查安装后显式初始化")
        if self.action and self.action["result"] in ("unknown", "failed") and not initialize:
            raise RuntimeError("前一动作结果未确认，禁止重放或继续运动")
        return data

    def valve_code(self, logical):
        if logical == "B":
            return 8
        return (4 if logical == "I" else 0) if self.orientation == "Z" else (0 if logical == "I" else 4)

    def checked(self, text):
        data = self._ready()
        port = "B" if data["valve_position"] == 8 else ("I" if data["valve_position"] == self.valve_code("I") else "O")
        return check_program(text, data["position"], FULL_STEPS[self.mode], port)

    def execute(self, request, stored=None, before_write=None):
        from src.devices.syringe_commands import SyringeCommand
        req = request if isinstance(request, SyringeCommand) else SyringeCommand.model_validate(request)
        def send(command, allow_fault=False):
            if before_write:
                try:
                    before_write()
                except RuntimeError:
                    if self.action:
                        self.action["result"] = "failed"
                    raise
            return self.exchange(command, allow_fault)
        op = req.action
        if op == "stop":
            send("T", allow_fault=True)
            self.trusted = False
            self.loaded = None
            if self.action:
                self.action["result"] = "stopped"
            self.stop_confirmed = False
            return {"result": "stop_requested"}
        if op in ("pause", "resume"):
            state = self.read_status()
            if state["fault_code"] or not self.trusted:
                raise RuntimeError("故障或位置未经确认，禁止暂停/继续")
            if (op == "resume" and self.action and self.action.get("waits_input")
                    and self.action["result"] in ("accepted", "running")):
                send("R")  # Manual p.28: release H wait, never use X (repeat).
                return dict(self.action)
            if not self.action or self.action["result"] not in (("accepted", "running") if op == "pause" else ("paused",)):
                raise ValueError("没有可暂停/继续的已知动作")
            send("h" if op == "pause" else "r")
            self.action["result"] = "paused" if op == "pause" else "running"
            return dict(self.action)
        data = self._ready(initialize=op == "initialize")
        if op == "program_validate":
            return vars(self.checked(req.program))
        if self.loaded is not None and op not in ("program_run", "program_load", "program_store", "initialize"):
            raise RuntimeError("存在待执行缓冲程序，先执行或停止清理")
        if op == "initialize":
            self.trusted = False
            if req.initialization_code in (0, *range(10, 41)) and self.config.capacity_ml < 2.5:
                raise ValueError("小注射器须使用手册对应的低驱动力初始化代码")
            if req.initialization_code == 1 and self.config.capacity_ml < 0.5:
                raise ValueError("此注射器应使用初始化代码2")
            command, target, valve = f"{req.direction}{req.initialization_code}R", 0, 0 if req.direction == "Z" else 4
            self.loaded = None
        elif op == "configure":
            if "microstep" in req.settings and data["position"] != 0:
                raise ValueError("仅在零位切换步进模式")
            command = "".join(SETTINGS[k][0] + str(v) for k, v in req.settings.items()) + "R"
            self.action = {"action": op, "result": "accepted", "settings": req.settings,
                           "timeout": req.timeout, "deadline": time.monotonic() + req.timeout}
            send(command)
            return dict(self.action)
        elif op == "io":
            send(f"J{req.output}R")
            self.action = {"action": op, "result": "sent_unverified", "output": req.output}
            return dict(self.action)
        elif op in ("program_load", "program_store"):
            checked = self.checked(req.program)
            send((f"s{req.slot}" + checked.text + "R") if op == "program_store" else checked.text)
            if op == "program_load":
                self.loaded = req.program
            else:
                self.loaded = None
            self.action = {"action": op, "result": "sent_unverified", **vars(checked)}
            return dict(self.action)
        elif op in ("program_run", "repeat"):
            text = self.last_program if op == "repeat" else (stored if req.slot is not None else self.loaded)
            if not text:
                raise ValueError("没有经过本应用登记的可执行程序")
            checked = self.checked(text)
            # Re-upload validated text for repeat; do not blindly replay device X.
            command = (checked.text + "R" if op == "repeat" else
                       f"e{req.slot}R" if req.slot is not None else "R")
            target, valve = checked.target, self.valve_code(checked.valve)
            self.last_program, self.loaded = text, None
        else:
            target, valve = None, None
            if op == "valve":
                logical = {"input": "I", "output": "O", "bypass": "B"}[req.valve]
                command, valve = logical + "R", self.valve_code(logical)
            else:
                if op == "move":
                    target = req.position
                    logical = "I" if target > data["position"] else "O"
                else:
                    amount = req.volume if req.unit == "steps" else req.volume * (1000 if req.unit == "mL" else 1) / (self.config.capacity_ml * 1000) * FULL_STEPS[self.mode]
                    if not math.isfinite(amount) or amount > FULL_STEPS[self.mode]:
                        raise ValueError("超出注射器额定容量")
                    steps = math.floor(amount + 0.5)
                    if steps < 1:
                        raise ValueError("体积小于一步的分辨率")
                    target = data["position"] + (steps if op == "aspirate" else -steps)
                    logical = "I" if op == "aspirate" else "O"
                if not 0 <= target <= FULL_STEPS[self.mode]:
                    raise ValueError("超出注射器行程")
                command = f"v50c50V{req.speed}{logical}A{target}R"
                valve = self.valve_code(logical)
        self.action = {"action": op, "result": "accepted", "target": target, "valve": valve,
                       "direction": req.direction if op == "initialize" else self.orientation,
                       "timeout": req.timeout, "started_at": datetime.now(timezone.utc).isoformat(),
                       "deadline": time.monotonic() + req.timeout}
        if op in ("move", "aspirate", "dispense"):
            self.action["theoretical_delta_ul"] = (target - data["position"]) / FULL_STEPS[self.mode] * self.config.capacity_ml * 1000
        if op in ("program_run", "repeat"):
            self.action["waits_input"] = checked.waits_input
        send(command)
        self.stop_confirmed = False
        return dict(self.action)
