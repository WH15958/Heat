import asyncio
import json

import pytest
import yaml

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.executor import StepExecutor
from src.utils.config import (
    ConfigManager,
    DeviceConnectionConfig,
    HeaterDeviceConfig,
    MicrowaveDeviceConfig,
    MonitorConfig,
    PumpChannelConfigYaml,
    PumpDeviceConfig,
)


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (DeviceConnectionConfig, "timeout"),
        (HeaterDeviceConfig, "min_temperature"),
        (HeaterDeviceConfig, "max_temperature"),
        (HeaterDeviceConfig, "safety_limit"),
        (HeaterDeviceConfig, "poll_interval"),
        (HeaterDeviceConfig, "retry_delay"),
        (PumpChannelConfigYaml, "max_flow_rate"),
        (PumpDeviceConfig, "timeout"),
        (PumpDeviceConfig, "poll_interval"),
        (PumpDeviceConfig, "retry_delay"),
        (MicrowaveDeviceConfig, "max_temperature"),
        (MicrowaveDeviceConfig, "poll_interval"),
        (MicrowaveDeviceConfig, "retry_delay"),
        (MonitorConfig, "log_interval"),
        (MonitorConfig, "alarm_check_interval"),
    ],
    ids=[
        "connection-timeout",
        "heater-min-temperature",
        "heater-max-temperature",
        "heater-safety-limit",
        "heater-poll-interval",
        "heater-retry-delay",
        "pump-channel-max-flow",
        "pump-timeout",
        "pump-poll-interval",
        "pump-retry-delay",
        "microwave-max-temperature",
        "microwave-poll-interval",
        "microwave-retry-delay",
        "monitor-log-interval",
        "monitor-alarm-interval",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [True, "1.0", float("nan"), float("inf"), float("-inf")],
    ids=["bool", "non-numeric", "nan", "positive-inf", "negative-inf"],
)
def test_safety_critical_float_config_rejects_non_finite_or_non_numeric(
    factory, field_name, invalid_value
):
    config = factory()
    setattr(config, field_name, invalid_value)

    assert len(config.validate()) > 0


def test_safety_critical_float_config_keeps_integer_values_compatible():
    configs = [
        DeviceConnectionConfig(timeout=1),
        HeaterDeviceConfig(
            min_temperature=0,
            max_temperature=400,
            safety_limit=450,
            poll_interval=1,
            retry_delay=0,
        ),
        PumpChannelConfigYaml(max_flow_rate=1),
        PumpDeviceConfig(timeout=1, poll_interval=1, retry_delay=0),
        MicrowaveDeviceConfig(max_temperature=300, poll_interval=1, retry_delay=0),
        MonitorConfig(log_interval=1, alarm_check_interval=1),
    ]

    assert all(config.validate() == [] for config in configs)


def test_config_manager_fails_fast_for_non_finite_safety_value(tmp_path):
    config_path = tmp_path / "system.yaml"
    config_path.write_text(
        """
name: numeric guard
version: '1'
heaters:
  - device_id: heater1
    max_temperature: .nan
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="配置验证失败"):
        ConfigManager(str(config_path)).load()


def _parse_experiment(tmp_path, monkeypatch, *, wait, params=None, action="wait"):
    import src.experiment.parser as parser_module

    monkeypatch.setattr(parser_module, "EXPERIMENTS_DIR", tmp_path)
    path = tmp_path / "numeric_wait.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "numeric wait guard",
                "steps": [
                    {
                        "id": "step_1",
                        "type": action,
                        "params": params or {},
                        "wait": wait,
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return parser_module.parse_experiment(path.name)


@pytest.mark.parametrize(
    "invalid_value",
    [True, "1.0", -1, float("nan"), float("inf"), float("-inf")],
    ids=["bool", "non-numeric", "negative", "nan", "positive-inf", "negative-inf"],
)
def test_parser_rejects_invalid_duration_seconds(tmp_path, monkeypatch, invalid_value):
    with pytest.raises(ValueError, match=r"wait\.seconds"):
        _parse_experiment(
            tmp_path,
            monkeypatch,
            wait={"type": "duration", "seconds": invalid_value},
        )


@pytest.mark.parametrize(
    "invalid_value",
    [True, "1.0", -1, float("nan"), float("inf"), float("-inf")],
    ids=["bool", "non-numeric", "negative", "nan", "positive-inf", "negative-inf"],
)
def test_parser_rejects_invalid_wait_timeout(tmp_path, monkeypatch, invalid_value):
    with pytest.raises(ValueError, match=r"wait\.timeout"):
        _parse_experiment(
            tmp_path,
            monkeypatch,
            wait={
                "type": "temperature_reached",
                "device_id": "heater1",
                "timeout": invalid_value,
            },
        )


@pytest.mark.parametrize(
    "invalid_value",
    [True, "1.0", -1, float("nan"), float("inf"), float("-inf")],
    ids=["bool", "non-numeric", "negative", "nan", "positive-inf", "negative-inf"],
)
@pytest.mark.parametrize(
    "wait_type", ["temperature_reached", "microwave_temperature_reached"]
)
def test_parser_rejects_invalid_temperature_wait_tolerance(
    tmp_path, monkeypatch, wait_type, invalid_value
):
    wait = {
        "type": wait_type,
        "device_id": "heater1" if wait_type == "temperature_reached" else "microwave1",
        "tolerance": invalid_value,
    }
    if wait_type == "microwave_temperature_reached":
        wait["target_temperature"] = 25

    with pytest.raises(ValueError, match=r"wait\.tolerance"):
        _parse_experiment(tmp_path, monkeypatch, wait=wait)


@pytest.mark.parametrize(
    "invalid_value",
    [None, True, "25", -1, float("nan"), float("inf"), float("-inf")],
    ids=["missing", "bool", "non-numeric", "negative", "nan", "positive-inf", "negative-inf"],
)
def test_parser_rejects_invalid_microwave_wait_target(
    tmp_path, monkeypatch, invalid_value
):
    with pytest.raises(ValueError, match=r"wait\.target_temperature"):
        _parse_experiment(
            tmp_path,
            monkeypatch,
            wait={
                "type": "microwave_temperature_reached",
                "device_id": "microwave1",
                "target_temperature": invalid_value,
            },
        )


def test_parser_preserves_none_wait_and_valid_timing(tmp_path, monkeypatch):
    parsed = _parse_experiment(
        tmp_path,
        monkeypatch,
        wait={"type": "none"},
    )
    assert parsed["steps"][0].wait.type == WaitType.NONE

    parsed = _parse_experiment(
        tmp_path,
        monkeypatch,
        wait={"type": "duration", "seconds": 0, "timeout": 1.5},
    )
    assert parsed["steps"][0].wait.seconds == 0
    assert parsed["steps"][0].wait.timeout == 1.5


@pytest.mark.parametrize("repeat_count", [0, 2, 3, True, None])
def test_parser_rejects_repeating_pump_with_pump_complete(
    tmp_path, monkeypatch, repeat_count
):
    with pytest.raises(ValueError, match="pump_complete requires a single run"):
        _parse_experiment(
            tmp_path,
            monkeypatch,
            action="pump.start",
            params={"repeat_count": repeat_count},
            wait={"type": "pump_complete", "device_id": "pump1", "channel": 1},
        )


def test_parser_allows_single_or_default_pump_run_with_pump_complete(
    tmp_path, monkeypatch
):
    for params in ({"repeat_count": 1}, {}):
        parsed = _parse_experiment(
            tmp_path,
            monkeypatch,
            action="pump.start",
            params=params,
            wait={"type": "pump_complete", "device_id": "pump1", "channel": 1},
        )
        assert parsed["steps"][0].wait.type == WaitType.PUMP_COMPLETE


def test_parser_rejects_separate_pump_complete_after_repeating_start(
    tmp_path, monkeypatch
):
    import src.experiment.parser as parser_module

    monkeypatch.setattr(parser_module, "EXPERIMENTS_DIR", tmp_path)
    path = tmp_path / "repeating_then_wait.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "repeating pump guard",
                "steps": [
                    {
                        "id": "start_repeat",
                        "type": "pump.start",
                        "params": {
                            "device_id": "pump1",
                            "channel": 1,
                            "repeat_count": 3,
                            "interval_time": 1,
                        },
                    },
                    {
                        "id": "wait_repeat",
                        "type": "wait",
                        "wait": {
                            "type": "pump_complete",
                            "device_id": "pump1",
                            "channel": 1,
                        },
                    },
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pump_complete requires a single run"):
        parser_module.parse_experiment(path.name)


class _NoDeviceReads:
    def __getattr__(self, name):
        raise AssertionError(f"unexpected device access: {name}")


class _RepeatingPump:
    def __init__(self):
        self.status_reads = 0

    def start_pump_channel(self, *_args):
        return True

    def read_pump_status(self, _device_id):
        self.status_reads += 1
        raise AssertionError("repeating pump status must not be treated as completion")


def test_executor_rejects_separate_pump_complete_for_known_repeating_start():
    dm = _RepeatingPump()
    executor = StepExecutor(dm)
    start = ExperimentStep(
        id="start_repeat",
        type=ActionType.PUMP_START,
        params={
            "device_id": "pump1",
            "channel": 1,
            "mode": "TIME_SPEED",
            "run_time": 1,
            "repeat_count": 3,
            "interval_time": 1,
        },
    )
    wait = ExperimentStep(
        id="wait_repeat",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.PUMP_COMPLETE,
            device_id="pump1",
            channel=1,
            timeout=1,
        ),
    )

    assert asyncio.run(executor.execute(start)) is True
    assert asyncio.run(executor.execute(wait)) is False
    assert dm.status_reads == 0


@pytest.mark.parametrize(
    "invalid_value", [-1, float("nan"), float("inf"), float("-inf")]
)
def test_executor_rejects_invalid_duration_without_treating_it_as_complete(
    invalid_value,
):
    executor = StepExecutor(_NoDeviceReads())
    condition = WaitCondition(type=WaitType.DURATION, seconds=invalid_value)

    assert asyncio.run(executor._wait_condition(condition)) is False


@pytest.mark.parametrize(
    "wait_type",
    [
        WaitType.TEMPERATURE_REACHED,
        WaitType.MICROWAVE_TEMPERATURE_REACHED,
        WaitType.MICROWAVE_COMPLETE,
        WaitType.PUMP_COMPLETE,
    ],
)
@pytest.mark.parametrize(
    "invalid_value", [-1, float("nan"), float("inf"), float("-inf")]
)
def test_executor_rejects_invalid_timeout_before_device_access(
    wait_type, invalid_value
):
    executor = StepExecutor(_NoDeviceReads())
    condition = WaitCondition(
        type=wait_type,
        timeout=invalid_value,
        target_temperature=25,
    )

    assert asyncio.run(executor._wait_condition(condition)) is False


@pytest.mark.parametrize(
    "wait_type", [WaitType.TEMPERATURE_REACHED, WaitType.MICROWAVE_TEMPERATURE_REACHED]
)
@pytest.mark.parametrize(
    "invalid_value", [True, -1, float("nan"), float("inf"), float("-inf")]
)
def test_executor_rejects_invalid_temperature_tolerance_before_device_access(
    wait_type, invalid_value
):
    executor = StepExecutor(_NoDeviceReads())
    condition = WaitCondition(
        type=wait_type,
        tolerance=invalid_value,
        target_temperature=25,
    )

    assert asyncio.run(executor._wait_condition(condition)) is False


@pytest.mark.parametrize(
    "invalid_value", [None, True, -1, float("nan"), float("inf"), float("-inf")]
)
def test_executor_rejects_invalid_microwave_target_before_device_access(
    invalid_value,
):
    executor = StepExecutor(_NoDeviceReads())
    condition = WaitCondition(
        type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
        target_temperature=invalid_value,
    )

    assert asyncio.run(executor._wait_condition(condition)) is False


def test_executor_preserves_none_and_zero_duration_waits():
    executor = StepExecutor(_NoDeviceReads())

    assert asyncio.run(executor._wait_condition(WaitCondition())) is True
    assert asyncio.run(
        executor._wait_condition(WaitCondition(type=WaitType.DURATION, seconds=0))
    ) is True


def test_delete_experiment_run_requires_exact_run_id_boundary(tmp_path, monkeypatch):
    import src.experiment.experiment_logger as logger_module

    exact_run_id = "20260716_010203_abc123"
    similar_run_id = "20260716_010203_abc124"
    exact_path = tmp_path / f"{exact_run_id}_experiment.json"
    similar_path = tmp_path / f"{similar_run_id}_experiment.json"
    exact_path.write_text(json.dumps({"run_id": exact_run_id}), encoding="utf-8")
    similar_path.write_text(json.dumps({"run_id": similar_run_id}), encoding="utf-8")

    removed_sample_ids = []
    monkeypatch.setattr(logger_module, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(
        logger_module,
        "remove_sample_records_for_run_ids",
        lambda run_ids: removed_sample_ids.append(run_ids),
    )

    assert logger_module.delete_experiment_run("20260716_010203") is False
    assert exact_path.exists()
    assert similar_path.exists()
    assert removed_sample_ids == []

    assert logger_module.get_experiment_run("20260716_010203") is None
    assert logger_module.get_experiment_run(exact_run_id) == {"run_id": exact_run_id}

    assert logger_module.delete_experiment_run(exact_run_id) is True
    assert not exact_path.exists()
    assert similar_path.exists()
    assert removed_sample_ids == [[exact_run_id]]
