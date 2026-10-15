"""Read-only execution observations. No hardware calls or completion decisions."""
import copy
import math
import time


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ActivityProgress:
    def __init__(self, wait_clock):
        self.clock = wait_clock
        self.reset()

    def reset(self, step=None):
        self.step_id = step.id if step else ""
        self.state = "executing"
        self.wait_type = None
        self.started = None
        self.duration = None
        self.reference = False
        self.stable_seconds = 0.0
        self.stable_required = None
        self.readings = []
        self.devices = {}
        self.frozen = None

    def wait(self, condition):
        self.wait_type = condition.type.value
        self.state = "waiting"
        if not self.reference:
            self.started = self.clock()
            self.duration = condition.seconds if self.wait_type in ("duration", "microwave_monitored_hold") else None
        if self.wait_type == "heater_pair_stable":
            self.stable_required = condition.seconds

    def pump_started(self, seconds):
        if valid_number(seconds) and seconds >= 0:
            self.reference = True
            self.started = time.monotonic()
            self.duration = seconds

    def temperatures(self, targets, values, tolerance=None):
        self.readings = [dict(device_id=target["device_id"], target=target["target_temperature"],
            value=values.get(target["device_id"]) if valid_number(values.get(target["device_id"])) and values[target["device_id"]] >= 0 else None,
            read_ok=valid_number(values.get(target["device_id"])) and values[target["device_id"]] >= 0, tolerance=tolerance,
            sampled_at=time.time()) for target in targets]

    def device(self, device_id, data):
        self.devices[device_id] = {key: data.get(key) for key in ("read_ok", "busy", "running", "fault_code", "control_active", "relay_energized")}
        self.devices[device_id]["result"] = (data.get("action") or {}).get("result")

    def snapshot(self):
        if self.frozen is not None:
            return copy.deepcopy(self.frozen)
        now = time.monotonic() if self.reference else self.clock()
        elapsed = max(0, now - self.started) if self.started is not None else None
        return dict(step_id=self.step_id, state=self.state, wait_type=self.wait_type,
            elapsed_seconds=elapsed, duration_seconds=self.duration,
            remaining_seconds=max(0, self.duration - elapsed) if self.duration is not None and elapsed is not None else None,
            reference=self.reference, stable_seconds=self.stable_seconds,
            stable_required_seconds=self.stable_required, readings=copy.deepcopy(self.readings),
            devices=copy.deepcopy(self.devices))

    def finish(self, success):
        self.state = "completed" if success else "failed"
        self.frozen = self.snapshot()


def guided_activity(step, observation):
    """Describe the compiled step, not an inferred or prospective device action."""
    sid, params = step.id, step.params
    activity = dict(observation, title="正在执行设备操作", description="等待设备确认本次动作。", stage=None)
    device_id = params.get("device_id") or step.wait.device_id
    activity["device_ids"] = [device_id] if device_id else []
    activity["parameters"] = {key: params[key] for key in ("volume", "unit", "flow_rate", "channel", "position", "temperature") if key in params}
    if sid.startswith("prime_"):
        activity["stage"] = "preparation"
        if sid.startswith("prime_initialize_"):
            activity.update(title="初始化注射泵 " + ("A" if sid.endswith("1") else "B"), description="正在移动活塞并切换泵阀，等待初始化完成。")
        elif sid == "prime_heat_duration":
            activity.update(title="前驱体加热脱气", description="保持第一组目标温度；设定加热时间结束后检查双路稳定到温。")
        elif sid == "prime_heat_both_stable":
            activity.update(title="等待前驱体稳定到温", description="加热时间已到；两路同时在目标 ±3℃ 内连续 30 秒后开始预充。")
        elif sid.startswith("prime_heat_"):
            activity.update(title="启动前驱体加热" if sid.endswith("start") else "设置前驱体目标温度", description="按第一组条件准备两路加热，随后计时脱气。")
        elif sid in ("prime_temperature", "prime_recheck_temperature"):
            activity.update(title="检查反应液温度", description="等待反应液降至 45℃及以下，满足后继续本批准备。")
        elif sid == "prime_waste_route":
            activity.update(title="切换至废液出口", description="三通阀切向 NC，等待继电器读回确认。")
        elif sid.startswith("prime_drain"):
            activity.update(title="停止预充排液" if sid.endswith("stop") else "正在排出预充液", description="通道四经 NC 排废；设定时长结束后仍需设备确认完成。")
        else:
            parts = sid.split("_")
            if len(parts) == 4 and parts[1] in ("1", "2"):
                activity.update(title=f"注射泵 {'A' if parts[1]=='1' else 'B'} · 第 {parts[2]} 次预充", description="正在吸取前驱体，等待泵完成。" if parts[3] == "aspirate" else "正在排出前驱体，等待泵完成。")
    elif sid.startswith("heat_"):
        activity.update(stage="stabilizing", title="等待前驱体稳定到温" if sid == "heat_both_stable" else "调整前驱体加热", description="按本组目标温度检查 A/B；两路同时在目标 ±3℃ 内连续 30 秒后允许吸液与进料。")
    elif sid.startswith("aspirate_") or sid == "feed_both":
        activity.update(stage="feeding", title="两路前驱体正在进料" if sid == "feed_both" else "注射泵正在吸液", description="两泵同时开始、各自完成；两路均完成后才启动微波。" if sid == "feed_both" else "按本组设定剂量吸液，等待注射泵完成。")
        if sid == "feed_both":
            activity["device_ids"] = [feed["device_id"] for feed in params["feeds"]]
            activity["feeds"] = [{key: feed[key] for key in ("device_id", "volume", "unit")} for feed in params["feeds"]]
    elif sid.startswith("microwave_") or sid == "hold":
        activity.update(stage="reaction", title={"hold": "微波反应保温", "microwave_start": "等待微波反应液升温", "microwave_stop": "正在停止微波", "microwave_config": "设置微波反应条件"}.get(sid, "微波反应"), description="物料到温后计时保温，结束后确认停止微波。前驱体加热器持续保温。")
    elif sid.startswith("clean_"):
        parts = sid.split("_")
        cycle = int(parts[1]) + 1
        action = parts[2]
        activity.update(stage="cleaning", title=f"第 {cycle} 次清洗 · " + {"route": "切向废液", "in": "注入清洗液", "dwell": "停留", "out": "排出清洗液"}.get(action, "清洗"), description={"route": "先切 NC 废液端，等待继电器读回。", "in": "通道三按设定流量与液量进液。", "dwell": "清洗液停留，计时结束后排液。", "out": "通道四经 NC 排废；设定时长结束后仍需设备确认完成。"}.get(action, "等待当前动作完成。"))
        if sid.endswith("_stop"):
            activity["title"] = f"第 {cycle} 次清洗 · 停止{'进液' if action=='in' else '排液'}"
    elif sid in ("cool_before_collection", "recheck_temperature", "product_route") or sid.startswith("collect_"):
        activity.update(stage="collection", title="等待反应液降温", description="反应液降至 45℃及以下后，经 NO 出口收集产物。")
        if sid == "product_route":
            activity.update(title="切换至产物出口", description="三通阀切向 NO，等待继电器读回确认。")
        elif sid.startswith("collect_"):
            activity.update(title="停止产物抽取" if sid.endswith("stop") else "正在收集产物", description="通道四经 NO 收集产物；设定时长结束后仍需设备确认完成。")
    if sid.startswith("prime_drain") or sid.startswith("clean_"):
        activity["parameters"]["position"] = "NC"
    elif sid.startswith("collect_"):
        activity["parameters"]["position"] = "NO"
    if step.wait.target_temperature is not None:
        activity["parameters"]["target_temperature"] = step.wait.target_temperature
    if step.wait.targets:
        activity["device_ids"] = [target["device_id"] for target in step.wait.targets]
    return activity
