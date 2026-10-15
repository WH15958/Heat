"""Keep mandatory YAML recovery records isolated from real runtime records."""
import pytest


@pytest.fixture(autouse=True)
def isolated_yaml_recovery(tmp_path, monkeypatch):
    from src.experiment import yaml_recovery
    monkeypatch.setattr(yaml_recovery, 'RECOVERY_DIR', tmp_path / 'yaml_runs')
