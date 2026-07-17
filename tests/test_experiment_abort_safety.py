import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock


_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))


def _step(action_type, step_id, params=None, wait=None, on_error="stop"):
    from src.experiment.actions import ExperimentStep

    return ExperimentStep(
        id=step_id,
        type=action_type,
        params=params or {},
        wait=wait,
        on_error=on_error,
    )


def test_pump_start_rejects_invalid_direction_and_mode():
    from src.experiment.actions import ActionType, WaitCondition
    from src.experiment.executor import StepExecutor

    dm = Mock()
    executor = StepExecutor(dm)
    invalid_params = [
        {"device_id": "pump1", "channel": 1, "direction": "TYPO"},
        {"device_id": "pump1", "channel": 1, "direction": "CW", "mode": "TYPO"},
    ]

    for index, params in enumerate(invalid_params):
        step = _step(
            ActionType.PUMP_START,
            f"invalid_pump_{index}",
            params=params,
            wait=WaitCondition(),
        )
        assert asyncio.run(executor.execute(step)) is False

    dm.start_pump_channel.assert_not_called()
    assert executor._active_pumps == set()


def test_on_error_stop_cleans_every_device_started_by_experiment():
    from src.experiment.actions import ActionType, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor

    class DeviceManager:
        def __init__(self):
            self.stopped = []

        def start_heater(self, _device_id):
            return True

        def start_pump_channel(self, *_args):
            return True

        def start_microwave(self, _device_id, _mode):
            return True

        def stop_heater(self, device_id):
            self.stopped.append(("heater", device_id))
            return True

        def stop_pump_channel(self, device_id, channel):
            self.stopped.append(("pump", device_id, channel))
            return True

        def stop_microwave(self, device_id):
            self.stopped.append(("microwave", device_id))
            return True

    async def fail_wait(_condition):
        return False

    dm = DeviceManager()
    executor = StepExecutor(dm)
    executor._wait_condition = fail_wait
    exp_logger = Mock()
    engine = ExperimentEngine(executor, exp_logger=exp_logger)
    engine.load_steps(
        [
            _step(
                ActionType.HEATER_START,
                "heater_start",
                {"device_id": "heater1"},
                WaitCondition(),
            ),
            _step(
                ActionType.PUMP_START,
                "pump_start",
                {"device_id": "pump1", "channel": 2},
                WaitCondition(),
            ),
            _step(
                ActionType.MICROWAVE_START,
                "microwave_start",
                {"device_id": "microwave1", "mode": "manual_power"},
                WaitCondition(),
            ),
            _step(
                ActionType.WAIT,
                "failed_wait",
                wait=SimpleNamespace(type=SimpleNamespace(value="duration")),
            ),
        ],
        name="cleanup",
        filename="cleanup.yaml",
    )

    async def scenario():
        await engine.start()
        await engine._task

    asyncio.run(scenario())

    assert engine.state == ExperimentState.FAILED
    assert set(dm.stopped) == {
        ("heater", "heater1"),
        ("pump", "pump1", 2),
        ("microwave", "microwave1"),
    }
    exp_logger.finish_run.assert_called_once_with("failed")


def test_failed_start_command_is_still_cleaned_up():
    from src.experiment.actions import ActionType, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor

    dm = Mock()
    dm.start_heater.return_value = False
    dm.stop_heater.return_value = True
    exp_logger = Mock()
    engine = ExperimentEngine(StepExecutor(dm), exp_logger=exp_logger)
    engine.load_steps(
        [
            _step(
                ActionType.HEATER_START,
                "uncertain_heater_start",
                {"device_id": "heater1"},
                WaitCondition(),
            )
        ]
    )

    async def scenario():
        await engine.start()
        await engine._task

    asyncio.run(scenario())

    assert engine.state == ExperimentState.FAILED
    dm.stop_heater.assert_called_once_with("heater1")


def test_stop_api_reports_device_cleanup_failure():
    from src.experiment.actions import ActionType, WaitCondition, WaitType
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor
    from src.web.api.experiments import _cleanup_engine, _engines, stop_experiment

    class DeviceManager:
        def __init__(self):
            self.stop_calls = 0

        def start_pump_channel(self, *_args):
            return True

        def stop_pump_channel(self, _device_id, _channel):
            self.stop_calls += 1
            return False

    dm = DeviceManager()
    exp_logger = Mock()
    engine = ExperimentEngine(StepExecutor(dm), exp_logger=exp_logger)
    engine.load_steps(
        [
            _step(
                ActionType.PUMP_START,
                "running_pump",
                {"device_id": "pump1", "channel": 1},
                WaitCondition(type=WaitType.DURATION, seconds=5),
            )
        ],
        name="stop failure",
        filename="stop_failure.yaml",
    )

    async def scenario():
        _cleanup_engine("stop_failure.yaml")
        _engines["stop_failure.yaml"] = engine
        try:
            await engine.start()
            await asyncio.sleep(0.08)
            response = await stop_experiment("stop_failure.yaml")
            assert response == {"success": False}
        finally:
            _cleanup_engine("stop_failure.yaml")

    asyncio.run(scenario())

    assert engine.state == ExperimentState.FAILED
    assert dm.stop_calls == 1
    exp_logger.finish_run.assert_called_once_with("failed")


def test_skip_records_only_one_final_skipped_entry():
    from src.experiment.actions import ActionType, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState

    class FailingExecutor:
        def set_stop_checker(self, _checker):
            pass

        def set_pause_checker(self, _checker):
            pass

        async def execute(self, _step):
            return False

        async def stop_active_devices(self):
            return True

    exp_logger = Mock()
    engine = ExperimentEngine(FailingExecutor(), exp_logger=exp_logger)
    engine.load_steps(
        [
            _step(
                ActionType.LOG,
                "skip_me",
                {"message": "fail"},
                WaitCondition(),
                on_error="skip",
            )
        ]
    )

    async def scenario():
        await engine.start()
        await engine._task

    asyncio.run(scenario())

    assert engine.state == ExperimentState.COMPLETED
    exp_logger.skip_step.assert_called_once_with(0, reason="Skipped due to error")
    exp_logger.finish_step.assert_not_called()


def test_paused_experiment_still_records_sensor_data():
    from src.utils import serial_manager as serial_mod
    from src.web.api import experiments as experiments_mod
    from src.web.api import ws as ws_mod

    exp_logger = Mock()
    exp_logger.active_run = object()
    engine = SimpleNamespace(
        state=SimpleNamespace(value="paused"),
        exp_logger=exp_logger,
    )
    original_engines = dict(experiments_mod._engines)
    original_payload_builder = ws_mod.build_realtime_payload
    original_sleep = ws_mod.asyncio.sleep
    original_get_serial_manager = serial_mod.get_serial_manager

    async def payload_builder(_dm):
        return {"type": "device_data", "heaters": {}, "pumps": {}, "microwaves": {}}

    async def stop_after_iteration(_seconds):
        raise asyncio.CancelledError

    async def scenario():
        experiments_mod._engines.clear()
        experiments_mod._engines["paused.yaml"] = engine
        ws_mod.build_realtime_payload = payload_builder
        ws_mod.asyncio.sleep = stop_after_iteration
        serial_mod.get_serial_manager = lambda: SimpleNamespace(feed_watchdog=lambda: None)
        try:
            await ws_mod.data_push_loop(
                SimpleNamespace(state=SimpleNamespace(device_manager=Mock()))
            )
        except asyncio.CancelledError:
            pass
        finally:
            experiments_mod._engines.clear()
            experiments_mod._engines.update(original_engines)
            ws_mod.build_realtime_payload = original_payload_builder
            ws_mod.asyncio.sleep = original_sleep
            serial_mod.get_serial_manager = original_get_serial_manager

    asyncio.run(scenario())
    exp_logger.record_sensor_data.assert_called_once()


TESTS = [
    test_pump_start_rejects_invalid_direction_and_mode,
    test_on_error_stop_cleans_every_device_started_by_experiment,
    test_failed_start_command_is_still_cleaned_up,
    test_stop_api_reports_device_cleanup_failure,
    test_skip_records_only_one_final_skipped_entry,
    test_paused_experiment_still_records_sensor_data,
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f"[OK] {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
    print(f"\nResult: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
