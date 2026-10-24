"""Cancelled HTTP/orchestration waiters must never cancel owned hardware cleanup."""
import asyncio
import json
import threading

import pytest

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine, ExperimentState
from src.experiment.executor import StepExecutor
from src.experiment.experiment_logger import ExperimentLogger
from src.experiment.yaml_recovery import PersistentExperimentEngine, new_record, records


class Manager:
    def __init__(self):
        self.stopping = threading.Event()
        self.release = threading.Event()
        self.heater_running = self.pump_running = False
        self.heater_stops = self.pump_stops = 0
        self.stop_ok = True

    def start_heater(self, _did):
        self.heater_running = True
        return True

    def start_pump_channel(self, *args):
        self.pump_running = True
        return True

    def stop_heater(self, _did):
        self.heater_stops += 1
        self.heater_running = False
        return True

    def stop_pump_channel(self, *_args):
        self.pump_stops += 1
        self.stopping.set()
        if not self.release.wait(3):
            raise TimeoutError("Test failed to release fake stop")
        if self.stop_ok:
            self.pump_running = False
        return self.stop_ok


async def running_engine(persistent):
    manager = Manager()
    cls = PersistentExperimentEngine if persistent else ExperimentEngine
    engine = cls(StepExecutor(manager), ExperimentLogger(save_log=True))
    if persistent:
        engine.record = new_record("cancel.yaml", "test source")
    engine.load_steps([
        ExperimentStep("heater", ActionType.HEATER_START, {"device_id": "heater1"}),
        ExperimentStep("pump", ActionType.PUMP_START, {"device_id": "pump1", "channel": 1,
                                                     "flow_rate": 1, "direction": "CW"}),
        ExperimentStep("wait", ActionType.WAIT, wait=WaitCondition(WaitType.DURATION, seconds=600)),
    ], filename="cancel.yaml")
    await engine.start()
    async def started():
        while engine.progress.step_id != "wait":
            await asyncio.sleep(0)
    await asyncio.wait_for(started(), 2)
    return engine, manager


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("cancel_wait", ["stop", "wait_finished"])
def test_cancelled_waiter_does_not_interrupt_terminal_cleanup(persistent, cancel_wait):
    async def scenario():
        engine, dm = await running_engine(persistent)
        waiter = asyncio.create_task(getattr(engine, cancel_wait)())
        if cancel_wait == "wait_finished":
            engine.request_stop()
        try:
            assert await asyncio.to_thread(dm.stopping.wait, 2)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        finally:
            dm.release.set()
        await asyncio.wait_for(engine.wait_finished(), 2)
        assert await engine.stop() is True
        assert not engine._task.cancelled()
        assert engine.state == ExperimentState.STOPPED
        assert dm.pump_stops == dm.heater_stops == 1
        assert not dm.pump_running and not dm.heater_running
        assert not engine.cleanup_pending
        assert engine.exp_logger.active_run.status == "stopped"
        if persistent:
            stored = records({})[0]
            assert stored["state"] == "stopped"
            assert not stored["cleanup_required"] and not stored["recovery_required"]
    asyncio.run(scenario())


def test_concurrent_stop_waiters_share_failed_attempt_then_explicit_retry():
    async def scenario():
        engine, dm = await running_engine(True)
        dm.stop_ok = False
        first = asyncio.create_task(engine.stop())
        assert await asyncio.to_thread(dm.stopping.wait, 2)
        second = asyncio.create_task(engine.stop())
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        dm.release.set()
        assert await asyncio.wait_for(second, 2) is False
        assert dm.pump_stops == dm.heater_stops == 1
        assert engine.cleanup_pending and engine.record["recovery_required"]
        dm.stop_ok = True
        assert await engine.stop() is True
        assert dm.pump_stops == 2 and dm.heater_stops == 1
        # A failed run keeps its recovery acknowledgement even after cleanup.
        assert engine.record["recovery_required"] and not engine.record["cleanup_required"]
    asyncio.run(scenario())


def test_cancelled_direct_cleanup_waiter_cannot_start_duplicate_cleanup():
    async def scenario():
        dm = Manager()
        executor = StepExecutor(dm)
        executor._active_pumps.add(("pump1", 1))
        executor._active_heaters.add("heater1")
        engine = ExperimentEngine(executor)
        first = asyncio.create_task(engine._cleanup_active_devices())
        assert await asyncio.to_thread(dm.stopping.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(engine._cleanup_active_devices())
        await asyncio.sleep(0)
        dm.release.set()
        assert await asyncio.wait_for(second, 2) is True
        assert dm.pump_stops == dm.heater_stops == 1
    asyncio.run(scenario())


def test_restart_cannot_displace_an_owned_stop_still_in_progress():
    async def scenario():
        dm = Manager()
        executor = StepExecutor(dm)
        executor._active_pumps.add(("pump1", 1))
        engine = ExperimentEngine(executor)
        stop = asyncio.create_task(engine.stop())
        try:
            assert await asyncio.to_thread(dm.stopping.wait, 2)
            with pytest.raises(RuntimeError, match="stop is still pending"):
                await engine.start()
        finally:
            dm.release.set()
        assert await asyncio.wait_for(stop, 2)
        assert engine._task is None and dm.pump_stops == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["guided", "microwave"])
def test_orchestration_stop_owns_finalization_after_waiter_cancellation(kind, tmp_path):
    from test_guided import FakeManager, spec
    from src.experiment import guided, microwave_program

    class FakeHardware(FakeManager):
        def __init__(self):
            super().__init__()
            self.stopping = threading.Event()
            self.release = threading.Event()
            self.stop_calls = 0
            self.heater_running = False

        def gate(self):
            self.stop_calls += 1
            self.stopping.set()
            if not self.release.wait(3):
                raise TimeoutError("Test failed to release orchestration stop")

        def stop_heater(self, did):
            self.gate()
            self.heater_running = False
            return super().stop_heater(did)

        def start_heater(self, did):
            self.heater_running = True
            return super().start_heater(did)

        def stop_microwave(self, did, **kwargs):
            self.gate()
            return super().stop_microwave(did, **kwargs)

    async def scenario():
        dm = FakeHardware()
        if kind == "guided":
            run = guided.GuidedBatch(dm, spec(), directory=tmp_path / "batch")
            # A short synthetic recipe still uses the real batch/engine/executor
            # and persistence; no laboratory recipe or device is executed.
            run.priming["steps"] = [
                {"id": "route", "type": "valve.switch", "params": {"device_id": "valve1", "position": "NC"}},
                {"id": "heater", "type": "heater.start", "params": {"device_id": "heater1"}},
                {"id": "wait", "type": "wait", "wait": {"type": "duration", "seconds": 600}},
            ]
            run.recipes = []
            active = lambda: dm.heater_running
        else:
            body = microwave_program.ProgramRequest(request_id="c" * 32, mode="auto_power",
                stages=[dict(temperature=30, hold_seconds=600)], hardware_confirmed=True)
            run = microwave_program.MicrowaveProgramRun(dm, "microwave1", body)
            active = lambda: dm.microwave_on
        await run.start()
        async def started():
            while not active():
                await asyncio.sleep(0)
        await asyncio.wait_for(started(), 2)
        first = asyncio.create_task(run.stop())
        try:
            assert await asyncio.to_thread(dm.stopping.wait, 2)
            second = asyncio.create_task(run.stop())
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        finally:
            dm.release.set()
        assert await asyncio.wait_for(second, 2) is True
        await asyncio.wait_for(run.task, 2)
        assert not run.task.cancelled() and not active()
        assert dm.stop_calls == 1
        if kind == "guided":
            path = tmp_path / "batch" / (run.batch_id + ".json")
        else:
            path = microwave_program.PROGRAM_DIR / (run.record["program_id"] + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["state"] in ("stopped", "failed")
        assert not saved["cleanup_required"]
    asyncio.run(scenario())
