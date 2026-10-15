"""Shared runtime storage isolation for pytest and standalone software tests."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch


@contextmanager
def isolated_runtime(directory=None):
    # Keep real persistence enabled: save_log=False still writes samples.csv.
    from src.campaigns import store
    from src.experiment import experiment_logger, guided, microwave_program, parser, yaml_recovery
    from src.science import sample_record

    with ExitStack() as stack:
        root = Path(directory or stack.enter_context(
            tempfile.TemporaryDirectory(prefix="heat-software-test-"))).resolve()
        experiments = root / "experiments"
        # Parser/editor tests may read the shipped recipes, but must edit copies.
        shutil.copytree(Path(__file__).resolve().parents[1] / "experiments",
                        experiments, dirs_exist_ok=True)
        paths = [
            (experiment_logger, "LOGS_DIR", root / "experiment_logs"),
            (sample_record, "SAMPLES_DIR", root / "datasets"),
            (sample_record, "SAMPLES_CSV", root / "datasets" / "samples.csv"),
            (guided, "BATCH_DIR", root / "guided_batches"),
            (microwave_program, "PROGRAM_DIR", root / "microwave_programs"),
            (yaml_recovery, "RECOVERY_DIR", root / "yaml_runs"),
            (parser, "EXPERIMENTS_DIR", experiments),
            (store, "CAMPAIGNS_DIR", root / "campaigns"),
        ]
        for name in ("CAMPAIGNS_JSON", "TRIALS_JSON", "RECOMMENDATIONS_JSON", "CHARACTERIZATIONS_JSON"):
            paths.append((store, name, root / "campaigns" / getattr(store, name).name))
        for module, name, value in paths:
            stack.enter_context(patch.object(module, name, value))
        yield root
