import math
import yaml
from pathlib import Path
from typing import List

from src.experiment.actions import (
    ExperimentStep,
    ActionType,
    WaitCondition,
    WaitType,
)

EXPERIMENTS_DIR = Path("experiments")


def _validate_nonnegative_finite_number(value, field_name: str, step_id: str):
    invalid = isinstance(value, bool) or not isinstance(value, (int, float))
    if not invalid:
        try:
            invalid = not math.isfinite(value) or value < 0
        except (TypeError, ValueError, OverflowError):
            invalid = True
    if invalid:
        raise ValueError(
            f"Invalid {field_name} for step {step_id}: expected a finite number >= 0"
        )
    return value


def _validate_filename(filename: str) -> Path:
    """验证文件名安全性，防止路径遍历

    Args:
        filename: 文件名

    Returns:
        Path: 安全的文件路径

    Raises:
        ValueError: 文件名包含非法字符
    """
    if not filename.endswith(".yaml") and not filename.endswith(".yml"):
        raise ValueError(f"Invalid experiment file type: {filename}")
    if ".." in filename or any(c in filename for c in '/\\:<>"|?*') or any(ord(c) < 32 for c in filename):
        raise ValueError(f"Invalid filename: {filename}")
    path = EXPERIMENTS_DIR / filename
    try:
        path.resolve().relative_to(EXPERIMENTS_DIR.resolve())
    except ValueError:
        raise ValueError(f"Path traversal detected: {filename}")
    return path

ACTION_MAP = {
    "heater.set_temperature": ActionType.HEATER_SET_TEMP,
    "heater.start": ActionType.HEATER_START,
    "heater.stop": ActionType.HEATER_STOP,
    "microwave.configure_manual": ActionType.MICROWAVE_CONFIGURE_MANUAL,
    "microwave.configure_auto_power": ActionType.MICROWAVE_CONFIGURE_AUTO_POWER,
    "microwave.configure_constant_rate": ActionType.MICROWAVE_CONFIGURE_CONSTANT_RATE,
    "microwave.start": ActionType.MICROWAVE_START,
    "microwave.stop": ActionType.MICROWAVE_STOP,
    "pump.start": ActionType.PUMP_START,
    "pump.stop": ActionType.PUMP_STOP,
    "pump.stop_channel": ActionType.PUMP_STOP_CHANNEL,
    "valve.switch": ActionType.VALVE_SWITCH,
    "wait": ActionType.WAIT,
    "emergency_stop": ActionType.EMERGENCY_STOP,
    "log": ActionType.LOG,
}

ACTION_MAP.update({a.value: a for a in ActionType if a.value.startswith("syringe_pump.")})
ACTION_MAP.update({a.value: a for a in (ActionType.SYRINGE_PAIR_DISPENSE,)})

WAIT_MAP = {
    "syringe_pump_complete": WaitType.SYRINGE_PUMP_COMPLETE,
    "none": WaitType.NONE,
    "duration": WaitType.DURATION,
    "temperature_reached": WaitType.TEMPERATURE_REACHED,
    "microwave_temperature_reached": WaitType.MICROWAVE_TEMPERATURE_REACHED,
    "microwave_temperature_below": WaitType.MICROWAVE_TEMPERATURE_BELOW,
    "microwave_complete": WaitType.MICROWAVE_COMPLETE,
    "pump_complete": WaitType.PUMP_COMPLETE,
}


def parse_experiment(filepath: str) -> dict:
    """解析实验YAML文件

    Args:
        filepath: YAML文件名或路径，会自动提取文件名部分

    Returns:
        dict: 包含name, description, steps的字典

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: YAML格式错误或文件名不安全
    """
    filename = Path(filepath).name
    path = _validate_filename(filename)
    if not path.exists():
        raise FileNotFoundError(f"Experiment file not found: {filepath}")

    return parse_experiment_content(path.read_text(encoding="utf-8"), filename)


def parse_experiment_content(content: str, filename: str = "untitled.yaml", *, validate_devices: bool = True) -> dict:
    """Parse an in-memory definition without creating a file or accessing hardware."""
    data = yaml.safe_load(content)
    return parse_experiment_data(data, filename, validate_devices=validate_devices)


def parse_experiment_data(data, filename: str = "untitled.yaml", *, validate_devices: bool = True) -> dict:
    """Shared structural/semantic validation for files and editor documents."""
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError("Invalid experiment file: missing 'steps'")
    if not isinstance(data["steps"], list):
        raise ValueError("Invalid experiment file: 'steps' must be a list")

    steps = []
    step_ids = set()
    pump_repeat_counts = {}
    syringe_ids = None
    for s in data.get("steps", []):
        if not isinstance(s, dict):
            raise ValueError("Invalid experiment step: expected object")
        step_label = s.get("id", "<unknown>")
        wait_data = s.get("wait", {})
        if not isinstance(wait_data, dict):
            raise ValueError(
                f"Invalid wait definition for step {step_label}: expected object"
            )
        wait_type_name = wait_data.get("type", "none")
        if wait_type_name not in WAIT_MAP:
            raise ValueError(f"Unknown wait type: {wait_type_name}")
        params = s.get("params", {})
        if not isinstance(params, dict):
            raise ValueError(f"Invalid params for step {step_label}: expected object")
        enabled = s.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Invalid enabled value for step {step_label}: expected bool")
        seconds = _validate_nonnegative_finite_number(
            wait_data.get("seconds", 0), "wait.seconds", step_label
        )
        timeout = _validate_nonnegative_finite_number(
            wait_data.get("timeout", 3600), "wait.timeout", step_label
        )
        tolerance = wait_data.get("tolerance", 1.0)
        target_temperature = wait_data.get(
            "target_temperature", wait_data.get("temperature")
        )
        if wait_type_name in {
            "temperature_reached",
            "microwave_temperature_reached",
        }:
            tolerance = _validate_nonnegative_finite_number(
                tolerance, "wait.tolerance", step_label
            )
        if wait_type_name in {"microwave_temperature_reached", "microwave_temperature_below"}:
            target_temperature = _validate_nonnegative_finite_number(
                target_temperature, "wait.target_temperature", step_label
            )
        wait = WaitCondition(
            type=WAIT_MAP[wait_type_name],
            seconds=seconds,
            device_id=wait_data.get("device_id", ""),
            tolerance=tolerance,
            timeout=timeout,
            channel=wait_data.get("channel", 0),
            target_temperature=target_temperature,
        )
        action_type = ACTION_MAP.get(s.get("type", ""))
        if action_type is None:
            raise ValueError(f"Unknown action type: {s.get('type')}")

        if action_type == ActionType.PUMP_START and wait.type == WaitType.PUMP_COMPLETE:
            repeat_count = params.get("repeat_count", 1)
            if isinstance(repeat_count, bool) or repeat_count != 1:
                raise ValueError(
                    f"Invalid repeat_count for step {step_label}: "
                    "pump_complete requires a single run (repeat_count=1)"
                )

        step_id = s.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Experiment step requires a non-empty string 'id'")
        if step_id in step_ids:
            raise ValueError(f"Duplicate step id: {step_id}")
        step_ids.add(step_id)

        on_error = s.get("on_error", "stop")
        if wait_type_name == "microwave_temperature_below":
            if on_error != "stop" or s.get("enabled", True) is not True:
                raise ValueError("Cooling wait must be enabled and requires on_error=stop")
            if not isinstance(wait.device_id, str) or not wait.device_id.strip():
                raise ValueError("Cooling wait requires wait.device_id")
            if timeout <= 0:
                raise ValueError("Cooling wait requires a positive timeout")
        if on_error not in {"stop", "skip"}:
            raise ValueError(f"Unknown on_error policy for step {step_id}: {on_error}")

        if action_type in (ActionType.SYRINGE_PAIR_DISPENSE,):
            if on_error != "stop" or enabled is not True:
                raise ValueError("Coordinated steps must be enabled and require on_error=stop")
        if action_type == ActionType.SYRINGE_PAIR_DISPENSE:
            from src.devices.syringe_commands import SyringeCommand
            feeds = params.get("feeds")
            if set(params) != {"feeds"} or not isinstance(feeds, list) or len(feeds) != 2:
                raise ValueError("syringe_pair.dispense requires two feeds")
            ids = []
            for feed in feeds:
                if not isinstance(feed, dict) or not isinstance(feed.get("device_id"), str) or not feed["device_id"].strip():
                    raise ValueError("Each feed requires device_id")
                if set(feed) - {"device_id", "volume", "unit", "speed", "timeout"}:
                    raise ValueError("Unsupported parallel feed parameter")
                SyringeCommand.model_validate({"action": "dispense", **{k: v for k, v in feed.items() if k != "device_id"}})
                ids.append(feed["device_id"])
            if len(set(ids)) != 2:
                raise ValueError("Parallel feeds require distinct syringe pumps")
            if validate_devices:
                from src.utils.config import ConfigManager
                configured = {c.device_id for c in ConfigManager().load().syringe_pumps if c.enabled}
                if any(did not in configured for did in ids):
                    raise ValueError("Device is not a configured syringe_pump type")

        if action_type == ActionType.VALVE_SWITCH:
            if set(params) != {"device_id", "position"}:
                raise ValueError("valve.switch requires only device_id and position")
            if not isinstance(params["device_id"], str) or not params["device_id"].strip():
                raise ValueError("valve.switch requires a non-empty device_id")
            if params["position"] not in ("NO", "NC"):
                raise ValueError("valve position must be NO or NC")
            if on_error != "stop":
                raise ValueError("valve.switch requires on_error=stop; unknown flow route cannot be skipped")
            if validate_devices:
                from src.utils.config import ConfigManager
                valve_ids = {c.device_id for c in ConfigManager().load().valves if c.enabled}
                if params["device_id"] not in valve_ids:
                    raise ValueError("Device is not a configured valve type")
        if action_type.value.startswith("syringe_pump."):
            from src.devices.syringe_commands import SyringeCommand
            if not isinstance(params.get("device_id"), str) or not params["device_id"]:
                raise ValueError("Syringe action requires device_id")
            values = {k: v for k, v in params.items() if k != "device_id"}
            values["action"] = action_type.value.split(".", 1)[1]
            command = SyringeCommand.model_validate(values)
            if command.action == "pause":
                raise ValueError("Hardware pause is manual only; experiment pause uses action boundaries")
            if command.program:
                from src.protocols.syringe_pump import check_program
                # Check feasible stroke intervals without assuming an initial position.
                # Upload/execution rechecks against live position and selected mode.
                check_program(command.program, None, 48000)
            if command.action in ("program_run", "program_load", "program_store", "repeat") and "timeout" not in values:
                raise ValueError("Programs require an explicit timeout")
        if wait_type_name == "syringe_pump_complete" and not wait.device_id:
            raise ValueError("syringe_pump_complete requires device_id")
        if wait_type_name == "syringe_pump_complete" and not 0 < timeout <= 3600:
            raise ValueError("Syringe wait timeout must be in (0, 3600]")
        if validate_devices and (action_type.value.startswith("syringe_pump.") or wait_type_name == "syringe_pump_complete"):
            if syringe_ids is None:
                from src.utils.config import ConfigManager
                syringe_ids = {c.device_id for c in ConfigManager().load().syringe_pumps if c.enabled}
            ids = ([params["device_id"]] if action_type.value.startswith("syringe_pump.") else [])
            if wait_type_name == "syringe_pump_complete":
                ids.append(wait.device_id)
            if any(did not in syringe_ids for did in ids):
                raise ValueError("Device is not a configured syringe_pump type")

        if enabled:
            if action_type == ActionType.PUMP_START:
                pump_key = (params.get("device_id"), params.get("channel"))
                if None not in pump_key:
                    pump_repeat_counts[pump_key] = params.get("repeat_count", 1)
            elif action_type == ActionType.PUMP_STOP:
                device_id = params.get("device_id")
                pump_repeat_counts = {
                    key: repeat_count
                    for key, repeat_count in pump_repeat_counts.items()
                    if key[0] != device_id
                }
            elif action_type == ActionType.PUMP_STOP_CHANNEL:
                pump_repeat_counts.pop(
                    (params.get("device_id"), params.get("channel")), None
                )
            elif action_type == ActionType.EMERGENCY_STOP:
                pump_repeat_counts.clear()

            if wait.type == WaitType.PUMP_COMPLETE:
                repeat_count = pump_repeat_counts.get(
                    (wait.device_id, wait.channel), 1
                )
                if isinstance(repeat_count, bool) or repeat_count != 1:
                    raise ValueError(
                        f"Invalid repeat_count for step {step_label}: "
                        "pump_complete requires a single run (repeat_count=1)"
                    )

        step = ExperimentStep(
            id=step_id,
            type=action_type,
            params=params,
            wait=wait,
            enabled=enabled,
            on_error=on_error,
        )
        steps.append(step)

    return {
        "name": data.get("name", Path(filename).stem),
        "description": data.get("description", ""),
        "steps": steps,
        "metadata": data.get("metadata") or {},
    }


def list_experiments(directory: str = "experiments") -> List[dict]:
    """列出所有可用的实验

    Args:
        directory: 实验YAML目录

    Returns:
        List[dict]: 实验摘要列表
    """
    exp_dir = Path(directory)
    if not exp_dir.exists():
        return []
    results = []
    experiment_files = (
        f for f in exp_dir.iterdir()
        if f.is_file() and f.suffix in {".yaml", ".yml"}
    )
    for f in sorted(experiment_files):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            results.append(
                {
                    "filename": f.name,
                    "name": data.get("name", f.stem),
                    "description": data.get("description", ""),
                    "steps_count": len(data.get("steps", [])),
                }
            )
        except Exception:
            pass
    return results
