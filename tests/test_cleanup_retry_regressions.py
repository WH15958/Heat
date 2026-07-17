import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException


@pytest.mark.parametrize(
    ("pump_stop", "heater_stop"),
    [
        (RuntimeError("pump stop failed"), True),
        (True, RuntimeError("heater stop failed")),
    ],
)
def test_program_stop_attempts_every_device_when_one_stop_raises(
    pump_stop, heater_stop
):
    from src.control.program_controller import ProgramController

    pump = Mock()
    heater = Mock()
    if isinstance(pump_stop, Exception):
        pump.stop_all.side_effect = pump_stop
    else:
        pump.stop_all.return_value = pump_stop
    if isinstance(heater_stop, Exception):
        heater.stop.side_effect = heater_stop
    else:
        heater.stop.return_value = heater_stop

    controller = ProgramController(heater=heater, pump=pump)

    assert asyncio.run(controller.stop()) is False
    pump.stop_all.assert_called_once_with()
    heater.stop.assert_called_once_with()


@pytest.mark.parametrize("current_unit", [None, [], [1]])
def test_float_write_is_aborted_when_required_unit_write_fails(current_unit):
    from src.devices.peristaltic_pump import LabSmartPumpDevice

    protocol = Mock()
    protocol.read_holding_registers.return_value = current_unit
    protocol.write_single_register.return_value = False
    protocol.write_multiple_registers.return_value = True

    pump = object.__new__(LabSmartPumpDevice)
    pump._lock = threading.RLock()
    pump._closed = False
    pump._protocol = protocol
    pump.config = SimpleNamespace(slave_address=7)

    assert pump._write_float_with_unit(100, 1.25, 200, 2) is False
    protocol.write_single_register.assert_called_once_with(7, 200, 2)
    protocol.write_multiple_registers.assert_not_called()


def test_failed_experiment_cleanup_is_retained_and_retry_is_deduplicated(
    monkeypatch,
):
    from src.experiment.actions import (
        ActionType,
        ExperimentStep,
        WaitCondition,
        WaitType,
    )
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor
    from src.web.api import experiments as exp_api

    class DeviceManager:
        def __init__(self):
            self.stop_calls = 0

        def start_pump_channel(self, *_args):
            return True

        def stop_pump_channel(self, _device_id, _channel):
            self.stop_calls += 1
            return self.stop_calls > 1

    class Request:
        app = SimpleNamespace(state=SimpleNamespace(device_manager=Mock()))

    async def scenario():
        filename = "cleanup_retry.yaml"
        exp_api._engines.clear()
        dm = DeviceManager()
        executor = StepExecutor(dm)
        exp_logger = Mock()
        engine = ExperimentEngine(executor, exp_logger=exp_logger)
        engine.load_steps(
            [
                ExperimentStep(
                    id="running_pump",
                    type=ActionType.PUMP_START,
                    params={"device_id": "pump1", "channel": 1},
                    wait=WaitCondition(type=WaitType.DURATION, seconds=5),
                )
            ],
            name="cleanup retry",
            filename=filename,
        )
        completion_calls = []

        def on_complete():
            completion_calls.append(True)
            exp_api._cleanup_engine(filename, engine)

        engine.on_complete(on_complete)
        exp_api._engines[filename] = engine

        try:
            await engine.start()
            await asyncio.sleep(0.08)

            first_response = await exp_api.stop_experiment(filename)
            assert first_response == {"success": False}
            assert engine.state == ExperimentState.FAILED
            assert engine.cleanup_pending is True
            assert executor._active_pumps == {("pump1", 1)}
            assert exp_api._engines.get(filename) is engine
            assert exp_api._get_active_engine() == (filename, engine)
            assert completion_calls == []

            monkeypatch.setattr(exp_api, "_validate_filename", lambda _name: None)
            monkeypatch.setattr(
                exp_api,
                "parse_experiment",
                lambda _path: {
                    "name": "blocked",
                    "description": "",
                    "metadata": {},
                    "steps": [],
                },
            )
            with pytest.raises(HTTPException) as exc_info:
                await exp_api.start_experiment(
                    "blocked.yaml",
                    exp_api.StartExperimentRequest(save_log=False),
                    Request(),
                )
            assert exc_info.value.status_code == 409
            assert exp_api._engines.get(filename) is engine

            retry_responses = await asyncio.gather(
                exp_api.stop_experiment(filename),
                exp_api.stop_experiment(filename),
            )
            assert retry_responses == [{"success": True}, {"success": True}]
            assert dm.stop_calls == 2
            assert executor._active_pumps == set()
            assert engine.cleanup_pending is False
            assert completion_calls == [True]
            assert filename not in exp_api._engines
            exp_logger.finish_run.assert_called_once_with("failed")
        finally:
            exp_api._engines.clear()

    asyncio.run(scenario())


def test_natural_completion_cleanup_failure_is_failed_and_retryable():
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor

    class DeviceManager:
        def __init__(self):
            self.stop_calls = 0

        def start_pump_channel(self, *_args):
            return True

        def stop_pump_channel(self, _device_id, _channel):
            self.stop_calls += 1
            return self.stop_calls > 1

    async def scenario():
        dm = DeviceManager()
        executor = StepExecutor(dm)
        exp_logger = Mock()
        engine = ExperimentEngine(executor, exp_logger=exp_logger)
        engine.load_steps(
            [
                ExperimentStep(
                    id="start_pump",
                    type=ActionType.PUMP_START,
                    params={"device_id": "pump1", "channel": 1},
                    wait=WaitCondition(),
                )
            ]
        )
        completion_calls = []
        engine.on_complete(lambda: completion_calls.append(True))

        await engine.start()
        await engine._task

        assert engine.state == ExperimentState.FAILED
        assert engine.cleanup_pending is True
        assert executor._active_pumps == {("pump1", 1)}
        assert completion_calls == []
        exp_logger.finish_run.assert_called_once_with("failed")

        assert await engine.stop() is True
        assert engine.cleanup_pending is False
        assert executor._active_pumps == set()
        assert completion_calls == [True]
        assert dm.stop_calls == 2
        exp_logger.finish_run.assert_called_once_with("failed")

    asyncio.run(scenario())


def test_direct_restart_retries_pending_cleanup_before_new_run():
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState

    class Executor:
        def __init__(self):
            self.execute_calls = 0
            self.cleanup_calls = 0
            self.cleanup_results = iter([False, False, True, True])

        def set_stop_checker(self, _checker):
            pass

        def set_pause_checker(self, _checker):
            pass

        async def execute(self, _step):
            self.execute_calls += 1
            return True

        async def stop_active_devices(self):
            self.cleanup_calls += 1
            return next(self.cleanup_results)

    async def scenario():
        step = ExperimentStep(
            id="run_once",
            type=ActionType.LOG,
            params={"message": "run"},
            wait=WaitCondition(),
        )
        executor = Executor()
        exp_logger = Mock()
        engine = ExperimentEngine(executor, exp_logger=exp_logger)
        engine.load_steps([step])

        await engine.start()
        await engine._task
        assert engine.state == ExperimentState.FAILED
        assert engine.cleanup_pending is True
        assert executor.execute_calls == 1

        engine.load_steps([step])
        with pytest.raises(RuntimeError, match="prior device cleanup"):
            await engine.start()
        assert engine.state == ExperimentState.FAILED
        assert engine.cleanup_pending is True
        assert executor.execute_calls == 1
        assert executor.cleanup_calls == 2
        assert exp_logger.start_run.call_count == 1

        await engine.start()
        await engine._task
        assert engine.state == ExperimentState.COMPLETED
        assert engine.cleanup_pending is False
        assert executor.execute_calls == 2
        assert executor.cleanup_calls == 4
        assert exp_logger.start_run.call_count == 2

    asyncio.run(scenario())


def test_start_while_paused_does_not_create_a_second_task():
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition
    from src.experiment.engine import ExperimentEngine, ExperimentState

    class Executor:
        def __init__(self):
            self.execute_calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        def set_stop_checker(self, _checker):
            pass

        def set_pause_checker(self, _checker):
            pass

        async def execute(self, _step):
            self.execute_calls += 1
            self.started.set()
            await self.release.wait()
            return True

        async def stop_active_devices(self):
            return True

    async def scenario():
        executor = Executor()
        exp_logger = Mock()
        engine = ExperimentEngine(executor, exp_logger=exp_logger)
        engine.load_steps(
            [
                ExperimentStep(
                    id="pause_gate",
                    type=ActionType.LOG,
                    params={"message": "run"},
                    wait=WaitCondition(),
                )
            ]
        )

        await engine.start()
        original_task = engine._task
        await executor.started.wait()
        await engine.pause()
        assert engine.state == ExperimentState.PAUSED

        assert await engine.start() is None
        assert engine._task is original_task
        assert executor.execute_calls == 1
        assert exp_logger.start_run.call_count == 1

        await engine.resume()
        executor.release.set()
        await original_task

    asyncio.run(scenario())
