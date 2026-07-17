import asyncio
import os
import sys
import threading
from unittest.mock import Mock


_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))


def _heater(start_result=True, stop_result=True):
    heater = Mock()
    heater.set_temperature.return_value = True
    heater.start.return_value = start_result
    heater.stop.return_value = stop_result
    return heater


def _pump(start_result=True, stop_result=True):
    pump = Mock()
    pump.set_flow_rate.return_value = True
    pump.set_direction.return_value = True
    pump.start_channel.return_value = start_result
    pump.stop_channel.return_value = stop_result
    pump.stop_all.return_value = True
    return pump


def test_step_failure_cleans_only_devices_started_by_controller():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    heater = _heater()
    pump = _pump(start_result=False)
    controller = ProgramController(heater=heater, pump=pump)
    controller.load_program(
        ProgramConfig(
            name="failure cleanup",
            steps=[
                ProgramStep(step_id=1, step_type=StepType.HEAT, temperature=50),
                ProgramStep(
                    step_id=2,
                    step_type=StepType.PUMP_START,
                    pump_channel=2,
                    pump_flow_rate=1,
                ),
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        task = controller._task
        await task

    asyncio.run(scenario())

    assert controller.status.completed is False
    assert controller.status.error == "Step failed: 2"
    heater.stop.assert_called_once_with()
    pump.stop_channel.assert_called_once_with(2)
    pump.stop_all.assert_not_called()


def test_natural_end_stops_tracked_channel_before_completing():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    pump = _pump()
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="natural end",
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=3,
                    pump_flow_rate=1,
                )
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        task = controller._task
        await task

    asyncio.run(scenario())

    assert controller.status.completed is True
    assert controller.status.error is None
    pump.stop_channel.assert_called_once_with(3)
    pump.stop_all.assert_not_called()


def test_end_step_cleans_once_and_terminates_program():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    pump = _pump()
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="explicit end",
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=1,
                    pump_flow_rate=1,
                ),
                ProgramStep(step_id=2, step_type=StepType.END),
                ProgramStep(
                    step_id=3,
                    step_type=StepType.PUMP_START,
                    pump_channel=4,
                    pump_flow_rate=1,
                ),
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        task = controller._task
        await task

    asyncio.run(scenario())

    assert controller.status.completed is True
    pump.start_channel.assert_called_once_with(1)
    pump.stop_channel.assert_called_once_with(1)


def test_max_duration_timeout_cleans_started_devices():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    pump = _pump()
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="timeout cleanup",
            max_duration=0.05,
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=2,
                    pump_flow_rate=1,
                ),
                ProgramStep(step_id=2, step_type=StepType.WAIT, wait_time=10),
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        task = controller._task
        await task

    asyncio.run(scenario())

    assert controller.status.completed is False
    assert "max_duration" in controller.status.error
    pump.stop_channel.assert_called_once_with(2)


def test_hold_and_wait_exclude_paused_time():
    from src.control.program_controller import ProgramController, ProgramStep, StepType

    async def exercise(step, method_name):
        controller = ProgramController()
        method = getattr(controller, method_name)
        task = asyncio.create_task(method(step))
        await asyncio.sleep(0.02)
        await controller.pause()
        await asyncio.sleep(0.65)
        await controller.resume()
        await asyncio.sleep(0.05)
        assert task.done() is False
        assert await asyncio.wait_for(task, timeout=1.0) is True

    async def scenario():
        await exercise(
            ProgramStep(step_id=1, step_type=StepType.HOLD, hold_time=0.15),
            "_execute_hold",
        )
        await exercise(
            ProgramStep(step_id=2, step_type=StepType.WAIT, wait_time=0.15),
            "_execute_wait",
        )

    asyncio.run(scenario())


def test_cleanup_failure_prevents_false_completed_status():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    pump = _pump(stop_result=False)
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="cleanup failure",
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=1,
                    pump_flow_rate=1,
                )
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        task = controller._task
        await task

    asyncio.run(scenario())

    assert controller.status.completed is False
    assert "Failed to stop" in controller.status.error
    pump.stop_channel.assert_called_once_with(1)


def test_start_retries_failed_automatic_cleanup_before_starting_hardware():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    pump = _pump()
    pump.stop_channel.side_effect = [False, False, True, True]
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="cleanup retry gate",
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=1,
                    pump_flow_rate=1,
                )
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        await controller._task
        assert controller.status.completed is False

        assert await controller.start() is False
        assert pump.start_channel.call_count == 1

        assert await controller.start() is True
        await controller._task

    asyncio.run(scenario())

    assert controller.status.completed is True
    assert controller.status.error is None
    assert pump.start_channel.call_count == 2
    assert pump.stop_channel.call_count == 4


def test_explicit_stop_failure_gates_restart_until_cleanup_succeeds():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    for stop_failure in (False, RuntimeError("stop_all failed")):
        pump = _pump()
        if isinstance(stop_failure, Exception):
            pump.stop_all.side_effect = stop_failure
        else:
            pump.stop_all.return_value = stop_failure
        pump.stop_channel.side_effect = [False, True, True]
        controller = ProgramController(pump=pump)
        controller.load_program(
            ProgramConfig(
                name="explicit stop failure",
                steps=[
                    ProgramStep(
                        step_id=1,
                        step_type=StepType.PUMP_START,
                        pump_channel=1,
                        pump_flow_rate=1,
                    ),
                    ProgramStep(step_id=2, step_type=StepType.WAIT, wait_time=10),
                ],
            )
        )

        async def scenario():
            assert await controller.start() is True
            while pump.start_channel.call_count == 0:
                await asyncio.sleep(0.01)

            assert await controller.stop() is False
            assert controller._automatic_cleanup_result is False
            assert controller._pump_channels_started == {1}

            controller.load_program(
                ProgramConfig(
                    name="restart after cleanup",
                    steps=[
                        ProgramStep(
                            step_id=1,
                            step_type=StepType.PUMP_START,
                            pump_channel=1,
                            pump_flow_rate=1,
                        )
                    ],
                )
            )
            assert await controller.start() is False
            assert pump.start_channel.call_count == 1
            assert controller._automatic_cleanup_result is False

            assert await controller.start() is True
            await controller._task

            assert controller.status.completed is True
            assert pump.start_channel.call_count == 2
            assert pump.stop_channel.call_count == 3

            pump.stop_all.side_effect = None
            pump.stop_all.return_value = True
            assert await controller.stop() is True
            assert controller._automatic_cleanup_result is None

        asyncio.run(scenario())


def test_start_is_blocked_until_explicit_stop_cleanup_finishes():
    from src.control.program_controller import (
        ProgramConfig,
        ProgramController,
        ProgramStep,
        StepType,
    )

    start_entered = threading.Event()
    stop_entered = threading.Event()
    stop_release = threading.Event()
    pump = _pump()

    def signal_start(_channel):
        start_entered.set()
        return True

    def blocking_stop_all():
        stop_entered.set()
        if not stop_release.wait(timeout=2):
            raise TimeoutError("test did not release stop_all")
        return True

    pump.start_channel.side_effect = signal_start
    pump.stop_all.side_effect = blocking_stop_all
    controller = ProgramController(pump=pump)
    controller.load_program(
        ProgramConfig(
            name="concurrent stop/start gate",
            steps=[
                ProgramStep(
                    step_id=1,
                    step_type=StepType.PUMP_START,
                    pump_channel=1,
                    pump_flow_rate=1,
                ),
                ProgramStep(step_id=2, step_type=StepType.WAIT, wait_time=10),
            ],
        )
    )

    async def scenario():
        assert await controller.start() is True
        assert await asyncio.to_thread(start_entered.wait, 1)

        stop_task = asyncio.create_task(controller.stop())
        assert await asyncio.to_thread(stop_entered.wait, 1)

        restart_result = None
        try:
            restart_result = await controller.start()
        finally:
            stop_release.set()
            assert await stop_task is True
            if restart_result:
                await controller.stop()

        assert restart_result is False
        assert pump.start_channel.call_count == 1

        controller.load_program(ProgramConfig(name="restart after stop", steps=[]))
        assert await controller.start() is True
        await controller._task
        assert controller.status.completed is True

    asyncio.run(scenario())


def test_cancelled_stop_keeps_start_blocked_until_device_stop_finishes():
    from src.control.program_controller import ProgramConfig, ProgramController

    stop_entered = threading.Event()
    stop_release = threading.Event()
    stop_finished = threading.Event()
    pump = _pump()

    def blocking_stop_all():
        stop_entered.set()
        try:
            if not stop_release.wait(timeout=2):
                raise TimeoutError("test did not release stop_all")
            return True
        finally:
            stop_finished.set()

    pump.stop_all.side_effect = blocking_stop_all
    controller = ProgramController(pump=pump)
    controller.load_program(ProgramConfig(name="cancelled stop gate", steps=[]))

    async def scenario():
        cancelled_waiter = asyncio.create_task(controller.stop())
        normal_waiter = asyncio.create_task(controller.stop())
        assert await asyncio.to_thread(stop_entered.wait, 1)
        device_stop_task = controller._device_stop_task
        assert device_stop_task is not None

        cancelled_waiter.cancel()
        try:
            await cancelled_waiter
        except asyncio.CancelledError:
            pass

        try:
            assert device_stop_task.done() is False
            assert normal_waiter.done() is False
            assert await controller.start() is False
        finally:
            stop_release.set()

        assert await normal_waiter is True
        assert await device_stop_task is True
        assert stop_finished.is_set()
        assert pump.stop_all.call_count == 1

        assert await controller.start() is True
        await controller._task
        assert controller.status.completed is True

    asyncio.run(scenario())


def test_concurrent_stop_waiters_share_one_device_cleanup():
    from src.control.program_controller import ProgramConfig, ProgramController

    stop_entered = threading.Event()
    stop_release = threading.Event()
    pump = _pump()

    def blocking_stop_all():
        stop_entered.set()
        if not stop_release.wait(timeout=2):
            raise TimeoutError("test did not release stop_all")
        return True

    pump.stop_all.side_effect = blocking_stop_all
    controller = ProgramController(pump=pump)
    controller.load_program(ProgramConfig(name="shared stop cleanup", steps=[]))

    async def scenario():
        stop_waiters = asyncio.gather(controller.stop(), controller.stop())
        assert await asyncio.to_thread(stop_entered.wait, 1)
        first_device_stop_task = controller._device_stop_task
        assert first_device_stop_task is not None

        try:
            assert await controller.start() is False
        finally:
            stop_release.set()

        assert await stop_waiters == [True, True]
        assert pump.stop_all.call_count == 1

        assert await controller.stop() is True
        assert controller._device_stop_task is not first_device_stop_task
        assert pump.stop_all.call_count == 2

        assert await controller.start() is True
        await controller._task
        assert controller.status.completed is True

    asyncio.run(scenario())


TESTS = [
    test_step_failure_cleans_only_devices_started_by_controller,
    test_natural_end_stops_tracked_channel_before_completing,
    test_end_step_cleans_once_and_terminates_program,
    test_max_duration_timeout_cleans_started_devices,
    test_hold_and_wait_exclude_paused_time,
    test_cleanup_failure_prevents_false_completed_status,
    test_start_retries_failed_automatic_cleanup_before_starting_hardware,
    test_explicit_stop_failure_gates_restart_until_cleanup_succeeds,
    test_start_is_blocked_until_explicit_stop_cleanup_finishes,
    test_cancelled_stop_keeps_start_blocked_until_device_stop_finishes,
    test_concurrent_stop_waiters_share_one_device_cleanup,
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
