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
    if ".." in filename or "/" in filename or "\\" in filename:
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
    "wait": ActionType.WAIT,
    "emergency_stop": ActionType.EMERGENCY_STOP,
    "log": ActionType.LOG,
}

WAIT_MAP = {
    "none": WaitType.NONE,
    "duration": WaitType.DURATION,
    "temperature_reached": WaitType.TEMPERATURE_REACHED,
    "microwave_temperature_reached": WaitType.MICROWAVE_TEMPERATURE_REACHED,
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

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError("Invalid experiment file: missing 'steps'")
    if not isinstance(data["steps"], list):
        raise ValueError("Invalid experiment file: 'steps' must be a list")

    steps = []
    step_ids = set()
    for s in data.get("steps", []):
        if not isinstance(s, dict):
            raise ValueError("Invalid experiment step: expected object")
        wait_data = s.get("wait", {})
        if not isinstance(wait_data, dict):
            raise ValueError(
                f"Invalid wait definition for step {s.get('id', '<unknown>')}: expected object"
            )
        wait_type_name = wait_data.get("type", "none")
        if wait_type_name not in WAIT_MAP:
            raise ValueError(f"Unknown wait type: {wait_type_name}")
        params = s.get("params", {})
        if not isinstance(params, dict):
            raise ValueError(f"Invalid params for step {s.get('id', '<unknown>')}: expected object")
        enabled = s.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Invalid enabled value for step {s.get('id', '<unknown>')}: expected bool")
        wait = WaitCondition(
            type=WAIT_MAP[wait_type_name],
            seconds=wait_data.get("seconds", 0),
            device_id=wait_data.get("device_id", ""),
            tolerance=wait_data.get("tolerance", 1.0),
            timeout=wait_data.get("timeout", 3600),
            channel=wait_data.get("channel", 0),
            target_temperature=wait_data.get(
                "target_temperature", wait_data.get("temperature")
            ),
        )
        action_type = ACTION_MAP.get(s.get("type", ""))
        if action_type is None:
            raise ValueError(f"Unknown action type: {s.get('type')}")

        step_id = s.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Experiment step requires a non-empty string 'id'")
        if step_id in step_ids:
            raise ValueError(f"Duplicate step id: {step_id}")
        step_ids.add(step_id)

        on_error = s.get("on_error", "stop")
        if on_error not in {"stop", "skip"}:
            raise ValueError(f"Unknown on_error policy for step {step_id}: {on_error}")

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
        "name": data.get("name", path.stem),
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
    for f in sorted(exp_dir.glob("*.yaml")):
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
