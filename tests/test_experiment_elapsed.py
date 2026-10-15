"""Elapsed time follows the run lifecycle, without hardware or wall-clock sleeps."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.engine import ExperimentEngine, ExperimentState


def test_elapsed_freezes_for_all_terminal_paths_and_resets_on_restart():
    async def scenario(outcome):
        clock = SimpleNamespace(monotonic=lambda: now[0])
        executor = Mock()
        executor.activity_snapshot = None
        executor.execute = AsyncMock(return_value=outcome != "failed")
        executor.stop_active_devices = AsyncMock(return_value=True)
        if outcome == "exception":
            executor.execute.side_effect = RuntimeError("device failed")
        engine = ExperimentEngine(executor, exp_logger=Mock())
        engine.load_steps([ExperimentStep(id="step", type=ActionType.LOG)])
        now = [0.0]
        with patch("src.experiment.engine.time", clock):
            await engine.start()
            now[0] = 5.0
            assert engine.progress.elapsed == 5.0
            await engine.pause()
            now[0] = 9.0
            assert engine.progress.elapsed == 9.0  # Includes paused time.
            if outcome == "stopped":
                await engine.stop()
            else:
                await engine.resume()
                try:
                    await engine.wait_finished()
                except RuntimeError:
                    assert outcome == "exception"
            expected = "failed" if outcome == "exception" else outcome
            assert engine.state.value == expected
            elapsed = engine.progress.elapsed
            now[0] = 100.0
            assert engine.progress.elapsed == elapsed == 9.0
            await engine.stop()
            assert engine.progress.elapsed == elapsed
            executor.execute.side_effect = None
            executor.execute.return_value = True
            engine.load_steps([ExperimentStep(id="next", type=ActionType.LOG)])
            await engine.start()
            assert engine.progress.elapsed == 0.0
            now[0] = 103.0
            await engine.wait_finished()
            assert engine.state == ExperimentState.COMPLETED
            assert engine.progress.elapsed == 3.0

    for outcome in ("completed", "failed", "stopped", "exception"):
        asyncio.run(scenario(outcome))
