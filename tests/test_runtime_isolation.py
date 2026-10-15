"""Regressions for default persistence, including standalone test entry points."""
import asyncio
import csv
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from runtime_isolation import isolated_runtime
from src.experiment import experiment_logger, guided, microwave_program, parser, yaml_recovery
from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.science import sample_record


@pytest.mark.parametrize("save_log", [True, False])
def test_real_persistence_is_kept_inside_test_directory(isolated_test_runtime, save_log):
    logger = None if save_log else experiment_logger.ExperimentLogger(save_log=False)
    engine = ExperimentEngine(StepExecutor(Mock()), logger)
    logger = engine.exp_logger
    engine.load_steps([ExperimentStep("message", ActionType.LOG, {"message": "software test"})],
                      name="test", filename="isolation.yaml")

    async def run():
        await engine.start()
        await engine.wait_finished()

    asyncio.run(run())
    assert logger.active_run.persistence_status == "ok"
    assert sample_record.SAMPLES_CSV.is_relative_to(isolated_test_runtime)
    with sample_record.SAMPLES_CSV.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["run_id"] for row in rows] == [logger.active_run.run_id]
    assert len(list(experiment_logger.LOGS_DIR.glob("*.json"))) == int(save_log)
    guided.atomic_record({"batch_id": "test_batch"})
    yaml_recovery.write_record(yaml_recovery.new_record("isolation.yaml", "test"))
    assert (isolated_test_runtime / "guided_batches" / "test_batch.json").is_file()
    assert list((isolated_test_runtime / "yaml_runs").glob("*.json"))


def test_nested_isolation_restores_paths_after_failure(tmp_path):
    targets = [(experiment_logger, "LOGS_DIR"), (sample_record, "SAMPLES_CSV"),
               (guided, "BATCH_DIR"), (microwave_program, "PROGRAM_DIR"),
               (yaml_recovery, "RECOVERY_DIR"), (parser, "EXPERIMENTS_DIR")]
    original = [getattr(module, name) for module, name in targets]
    with pytest.raises(RuntimeError, match="simulated failure"):
        with isolated_runtime(tmp_path / "nested") as root:
            assert all(getattr(module, name).is_relative_to(root) for module, name in targets)
            raise RuntimeError("simulated failure")
    assert [getattr(module, name) for module, name in targets] == original


@pytest.mark.parametrize("filename", ["test_metadata.py", "test_code_review_fixes.py"])
def test_standalone_entry_point_does_not_write_outer_history(tmp_path, filename):
    # An outer sandbox stands in for the user's existing history. The script
    # must establish its own isolation without relying on pytest fixtures.
    script = '''
import runpy, sys
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from runtime_isolation import isolated_runtime
from src.science import sample_record
with isolated_runtime(sys.argv[1]) as outer:
    sample_record.SAMPLES_DIR.mkdir()
    original = b'sample_id,run_id\\nLAB_S001,lab_run\\n'
    sample_record.SAMPLES_CSV.write_bytes(original)
    try:
        runpy.run_path(str(Path('tests') / sys.argv[2]), run_name='__main__')
    except SystemExit as exc:
        assert exc.code in (None, 0), exc.code
    assert sample_record.SAMPLES_CSV.read_bytes() == original
    assert not list((outer / 'experiment_logs').glob('*.json'))
    assert not list((outer / 'yaml_runs').glob('*.json'))
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "outer"), filename],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")
