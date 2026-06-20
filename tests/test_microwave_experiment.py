"""
Microwave experiment YAML parser and executor tests.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.executor import StepExecutor
from src.experiment.parser import parse_experiment
import src.experiment.parser as parser_mod


def run(coro):
    return asyncio.run(coro)


class FakeMicrowaveExperimentManager:
    def __init__(self, allow=True):
        self.allow = allow
        self.calls = []
        self.configure_result = True
        self.start_result = True
        self.stop_result = True
        self.emergency_stop_result = True
        self.read_payloads = []
        self.configured_segments = None
        self.start_mode = None
        self.read_count = 0

    def is_microwave_experiment_control_allowed(self, device_id):
        self.calls.append(("is_microwave_experiment_control_allowed", device_id))
        return self.allow

    def configure_microwave_manual(self, device_id, segments):
        self.calls.append(("configure_microwave_manual", device_id))
        self.configured_segments = segments
        return self.configure_result

    def configure_microwave_auto_power(self, device_id, segments):
        self.calls.append(("configure_microwave_auto_power", device_id))
        self.configured_segments = segments
        return self.configure_result

    def configure_microwave_constant_rate(self, device_id, segments):
        self.calls.append(("configure_microwave_constant_rate", device_id))
        self.configured_segments = segments
        return self.configure_result

    def start_microwave(self, device_id, mode):
        self.calls.append(("start_microwave", device_id))
        self.start_mode = mode
        return self.start_result

    def stop_microwave(self, device_id):
        self.calls.append(("stop_microwave", device_id))
        return self.stop_result

    def emergency_stop_all(self):
        self.calls.append(("emergency_stop_all",))
        return self.emergency_stop_result

    def read_microwave_data(self, device_id):
        self.calls.append(("read_microwave_data", device_id))
        self.read_count += 1
        if not self.read_payloads:
            return {"material_temperature": 25.0, "running": False}
        if len(self.read_payloads) == 1:
            payload = self.read_payloads[0]
        else:
            payload = self.read_payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def test_parser_recognizes_microwave_actions_and_waits():
    tmp_dir = Path(tempfile.mkdtemp())
    original_dir = parser_mod.EXPERIMENTS_DIR
    parser_mod.EXPERIMENTS_DIR = tmp_dir
    try:
        yaml_path = tmp_dir / "microwave_flow.yaml"
        yaml_path.write_text(
            """name: microwave_flow
steps:
  - id: configure
    type: microwave.configure_manual
    params:
      device_id: microwave1
      segments:
        - segment: 1
          heat_temperature: 80
          heat_power: 20
          hold_temperature: 80
          hold_power: 20
          hold_deviation: 2
          hold_hours: 0
          hold_minutes: 5
          hold_seconds: 0
  - id: start
    type: microwave.start
    params:
      device_id: microwave1
      mode: manual_power
    wait:
      type: microwave_temperature_reached
      device_id: microwave1
      target_temperature: 80
      tolerance: 1
      timeout: 60
  - id: complete
    type: wait
    wait:
      type: microwave_complete
      device_id: microwave1
      timeout: 120
  - id: stop
    type: microwave.stop
    params:
      device_id: microwave1
""",
            encoding="utf-8",
        )

        parsed = parse_experiment(str(yaml_path))

        assert parsed["steps"][0].type == ActionType.MICROWAVE_CONFIGURE_MANUAL
        assert parsed["steps"][1].type == ActionType.MICROWAVE_START
        assert parsed["steps"][1].wait.type == WaitType.MICROWAVE_TEMPERATURE_REACHED
        assert parsed["steps"][1].wait.target_temperature == 80
        assert parsed["steps"][2].wait.type == WaitType.MICROWAVE_COMPLETE
        assert parsed["steps"][3].type == ActionType.MICROWAVE_STOP
    finally:
        parser_mod.EXPERIMENTS_DIR = original_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_microwave_configure_manual_success_maps_yaml_aliases():
    dm = FakeMicrowaveExperimentManager(allow=True)
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="configure_manual",
        type=ActionType.MICROWAVE_CONFIGURE_MANUAL,
        params={
            "device_id": "microwave1",
            "segments": [
                {
                    "segment": 1,
                    "heat_temperature": 80,
                    "heat_power": 20,
                    "hold_temperature": 81,
                    "hold_power": 21,
                    "hold_deviation": 2,
                    "hold_hours": 0,
                    "hold_minutes": 5,
                    "hold_seconds": 3,
                }
            ],
        },
    )

    result = run(executor.execute(step))

    assert result is True
    assert ("configure_microwave_manual", "microwave1") in dm.calls
    segment = dm.configured_segments[0]
    assert segment.heating_temperature == 80
    assert segment.heating_power_percent == 20
    assert segment.holding_temperature == 81
    assert segment.holding_power_percent == 21
    assert segment.holding_deviation == 2
    assert segment.minutes == 5
    assert segment.seconds == 3


def test_microwave_start_success_calls_manager():
    dm = FakeMicrowaveExperimentManager(allow=True)
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="start",
        type=ActionType.MICROWAVE_START,
        params={"device_id": "microwave1", "mode": "manual_power"},
    )

    result = run(executor.execute(step))

    assert result is True
    assert dm.start_mode == "manual_power"
    assert ("start_microwave", "microwave1") in dm.calls


def test_legacy_experiment_control_flag_does_not_block_configure_and_start():
    dm = FakeMicrowaveExperimentManager(allow=False)
    executor = StepExecutor(dm)
    configure_step = ExperimentStep(
        id="configure_allowed",
        type=ActionType.MICROWAVE_CONFIGURE_MANUAL,
        params={"device_id": "microwave1", "segments": [{"segment": 1}]},
    )
    start_step = ExperimentStep(
        id="start_allowed",
        type=ActionType.MICROWAVE_START,
        params={"device_id": "microwave1", "mode": "manual_power"},
    )

    assert run(executor.execute(configure_step)) is True
    assert run(executor.execute(start_step)) is True
    assert ("is_microwave_experiment_control_allowed", "microwave1") not in dm.calls
    assert ("configure_microwave_manual", "microwave1") in dm.calls
    assert ("start_microwave", "microwave1") in dm.calls


def test_microwave_stop_calls_manager_with_legacy_flag_false():
    dm = FakeMicrowaveExperimentManager(allow=False)
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="stop",
        type=ActionType.MICROWAVE_STOP,
        params={"device_id": "microwave1"},
    )

    result = run(executor.execute(step))

    assert result is True
    assert ("stop_microwave", "microwave1") in dm.calls


def test_microwave_device_false_result_fails_step():
    dm = FakeMicrowaveExperimentManager(allow=True)
    dm.configure_result = False
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="configure_failed",
        type=ActionType.MICROWAVE_CONFIGURE_AUTO_POWER,
        params={"device_id": "microwave1", "segments": [{"segment": 1}]},
    )

    result = run(executor.execute(step))

    assert result is False
    assert ("configure_microwave_auto_power", "microwave1") in dm.calls


def test_emergency_stop_false_result_fails_step():
    dm = FakeMicrowaveExperimentManager()
    dm.emergency_stop_result = False
    executor = StepExecutor(dm)
    step = ExperimentStep(id="emergency", type=ActionType.EMERGENCY_STOP)

    result = run(executor.execute(step))

    assert result is False
    assert dm.calls == [("emergency_stop_all",)]


def test_microwave_temperature_reached_success():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [{"material_temperature": 79.8, "running": True}]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_temp",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
            device_id="microwave1",
            target_temperature=80,
            tolerance=0.5,
            timeout=1,
        ),
    )

    result = run(executor.execute(step))

    assert result is True
    assert dm.read_count == 1


def test_microwave_temperature_reached_timeout_fails():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [{"material_temperature": 25.0, "running": True}]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_temp_timeout",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
            device_id="microwave1",
            target_temperature=80,
            tolerance=0.5,
            timeout=0.05,
        ),
    )

    result = run(executor.execute(step))

    assert result is False
    assert dm.read_count >= 1


def test_microwave_temperature_reached_stop_interrupts():
    dm = FakeMicrowaveExperimentManager()
    executor = StepExecutor(dm)
    executor.set_stop_checker(lambda: True)
    step = ExperimentStep(
        id="wait_temp_stop",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_TEMPERATURE_REACHED,
            device_id="microwave1",
            target_temperature=80,
            timeout=10,
        ),
    )

    result = run(executor.execute(step))

    assert result is False
    assert dm.read_count == 0


def test_microwave_complete_success():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [
        {"running": True, "power_percent": 20, "current": 1.2, "material_temperature": 80},
        {"running": False, "power_percent": 0, "current": 0, "material_temperature": 80},
    ]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_complete",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_COMPLETE,
            device_id="microwave1",
            timeout=1,
        ),
    )

    result = run(executor.execute(step))

    assert result is True
    assert dm.read_count >= 2


def test_microwave_complete_explicit_signal_still_succeeds():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [{"completed": True, "material_temperature": 80}]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_complete_explicit_signal",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_COMPLETE,
            device_id="microwave1",
            timeout=1,
        ),
    )

    result = run(executor.execute(step))

    assert result is True
    assert dm.read_count == 1


def test_microwave_complete_ignores_display_running_without_completion_signal():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [{"running": False, "material_temperature": 80}]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_complete_without_signal",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_COMPLETE,
            device_id="microwave1",
            timeout=0.05,
        ),
    )

    result = run(executor.execute(step))

    assert result is False
    assert dm.read_count >= 1


def test_microwave_complete_timeout_fails():
    dm = FakeMicrowaveExperimentManager()
    dm.read_payloads = [{"running": True, "material_temperature": 80}]
    executor = StepExecutor(dm)
    step = ExperimentStep(
        id="wait_complete_timeout",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_COMPLETE,
            device_id="microwave1",
            timeout=0.05,
        ),
    )

    result = run(executor.execute(step))

    assert result is False
    assert dm.read_count >= 1


def test_microwave_complete_stop_interrupts():
    dm = FakeMicrowaveExperimentManager()
    executor = StepExecutor(dm)
    executor.set_stop_checker(lambda: True)
    step = ExperimentStep(
        id="wait_complete_stop",
        type=ActionType.WAIT,
        wait=WaitCondition(
            type=WaitType.MICROWAVE_COMPLETE,
            device_id="microwave1",
            timeout=10,
        ),
    )

    result = run(executor.execute(step))

    assert result is False
    assert dm.read_count == 0


def run_all():
    tests = [
        test_parser_recognizes_microwave_actions_and_waits,
        test_microwave_configure_manual_success_maps_yaml_aliases,
        test_microwave_start_success_calls_manager,
        test_legacy_experiment_control_flag_does_not_block_configure_and_start,
        test_microwave_stop_calls_manager_with_legacy_flag_false,
        test_microwave_device_false_result_fails_step,
        test_emergency_stop_false_result_fails_step,
        test_microwave_temperature_reached_success,
        test_microwave_temperature_reached_timeout_fails,
        test_microwave_temperature_reached_stop_interrupts,
        test_microwave_complete_success,
        test_microwave_complete_explicit_signal_still_succeeds,
        test_microwave_complete_ignores_display_running_without_completion_signal,
        test_microwave_complete_timeout_fails,
        test_microwave_complete_stop_interrupts,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
    passed = len(tests) - failed
    print(f"microwave experiment tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
