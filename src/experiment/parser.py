import yaml
from pathlib import Path
from typing import List

from src.experiment.actions import (
    ExperimentStep,
    ActionType,
    WaitCondition,
    WaitType,
)

ACTION_MAP = {
    "heater.set_temperature": ActionType.HEATER_SET_TEMP,
    "heater.start": ActionType.HEATER_START,
    "heater.stop": ActionType.HEATER_STOP,
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
    "pump_complete": WaitType.PUMP_COMPLETE,
}


def parse_experiment(filepath: str) -> dict:
    """解析实验YAML文件

    Args:
        filepath: YAML文件路径

    Returns:
        dict: 包含name, description, steps的字典

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: YAML格式错误
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Experiment file not found: {filepath}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "steps" not in data:
        raise ValueError("Invalid experiment file: missing 'steps'")

    steps = []
    for s in data.get("steps", []):
        wait_data = s.get("wait", {})
        wait = WaitCondition(
            type=WAIT_MAP.get(wait_data.get("type", "none"), WaitType.NONE),
            seconds=wait_data.get("seconds", 0),
            device_id=wait_data.get("device_id", ""),
            tolerance=wait_data.get("tolerance", 1.0),
            timeout=wait_data.get("timeout", 3600),
            channel=wait_data.get("channel", 0),
        )
        action_type = ACTION_MAP.get(s.get("type", ""))
        if action_type is None:
            raise ValueError(f"Unknown action type: {s.get('type')}")

        step = ExperimentStep(
            id=s["id"],
            type=action_type,
            params=s.get("params", {}),
            wait=wait,
            enabled=s.get("enabled", True),
            on_error=s.get("on_error", "stop"),
        )
        steps.append(step)

    return {
        "name": data.get("name", path.stem),
        "description": data.get("description", ""),
        "steps": steps,
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
