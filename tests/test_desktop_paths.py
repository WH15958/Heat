"""Desktop data roots are explicit; existing Web paths remain usable."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.utils.runtime_paths import data_path


def test_legacy_paths_are_unchanged_without_desktop_environment(monkeypatch):
    monkeypatch.delenv("HEAT_DATA_DIR", raising=False)
    assert data_path("output/logs") == Path("output/logs")
    assert data_path("config", legacy="old/config") == Path("old/config")


def test_desktop_paths_use_absolute_root_from_any_working_directory(tmp_path, monkeypatch):
    root = tmp_path / "实验 workspace"
    monkeypatch.setenv("HEAT_DATA_DIR", str(root))
    monkeypatch.chdir(tmp_path)
    assert data_path("output/yaml_runs", legacy="old") == root / "output/yaml_runs"
    assert not root.exists()  # Resolving a path does not initialize storage.


@pytest.mark.parametrize("relative", ["../outside", "config/../../outside"])
def test_desktop_paths_reject_parent_escape(tmp_path, monkeypatch, relative):
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "workspace"))
    with pytest.raises(ValueError):
        data_path(relative)


def test_desktop_paths_reject_absolute_argument_or_relative_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "workspace"))
    with pytest.raises(ValueError):
        data_path(tmp_path / "outside")
    monkeypatch.setenv("HEAT_DATA_DIR", "relative/workspace")
    with pytest.raises(ValueError):
        data_path("config")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_desktop_paths_reject_junction_escape(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "output"), str(outside)],
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    monkeypatch.setenv("HEAT_DATA_DIR", str(root))
    with pytest.raises(ValueError, match="escapes"):
        data_path("output/experiment_logs")


def test_all_business_paths_follow_desktop_root_before_import(tmp_path):
    root = tmp_path / "用户 workspace"
    env = dict(os.environ, HEAT_DATA_DIR=str(root),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    code = """
import json
from pathlib import Path
from src.utils.config import ConfigManager
from src.campaigns import store
from src.science import sample_record
from src.experiment import parser, experiment_logger, guided, microwave_program, yaml_recovery
from src.web.syringe_control import SyringeController
from src.utils.csv_logger import CSVDataLogger
from src.reports.report_generator import ReportGenerator
root = Path(__import__('os').environ['HEAT_DATA_DIR'])
paths = [ConfigManager().config_path, store.CAMPAIGNS_DIR, sample_record.SAMPLES_CSV,
         parser.EXPERIMENTS_DIR, experiment_logger.LOGS_DIR, guided.BATCH_DIR,
         microwave_program.PROGRAM_DIR, yaml_recovery.RECOVERY_DIR,
         SyringeController(object(), device=object()).registry_dir,
         CSVDataLogger(root / 'reports').output_dir, ReportGenerator().output_dir]
assert all(p.is_relative_to(root) for p in paths), paths
parser.EXPERIMENTS_DIR.mkdir(parents=True)
(parser.EXPERIMENTS_DIR / 'local.yaml').write_text('name: local\\nsteps: []\\n', encoding='utf-8')
assert [item['filename'] for item in parser.list_experiments()] == ['local.yaml']
print(json.dumps([str(p.relative_to(root)) for p in paths]))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(paths) == 11


def test_explicit_syringe_program_directory_still_overrides_default(tmp_path, monkeypatch):
    from src.web.syringe_control import SyringeController
    monkeypatch.setenv("HEAT_DATA_DIR", str(tmp_path / "desktop"))
    explicit = tmp_path / "isolated-programs"
    controller = SyringeController(SimpleNamespace(), explicit, object())
    assert controller.registry_dir == explicit


@pytest.mark.parametrize("location", ["workspace", "external", "relative"])
def test_explicit_report_csv_and_logging_directories_keep_caller_choice(tmp_path, monkeypatch, location):
    from src.reports.report_generator import ReportGenerator
    from src.utils.csv_logger import CSVDataLogger
    from src.utils.logger import DeviceLogger, setup_logging

    root = tmp_path / "workspace"
    monkeypatch.setenv("HEAT_DATA_DIR", str(root))
    monkeypatch.chdir(tmp_path)
    explicit = {"workspace": root / "exports", "external": tmp_path / "exports",
                "relative": Path("explicit-exports")}[location]
    root_logger = logging.getLogger()
    handlers, level = root_logger.handlers[:], root_logger.level
    device_logger = logging.getLogger("device.desktop-explicit-path-test")
    try:
        report = ReportGenerator(explicit)
        assert report.output_dir == explicit
        csv_logger = CSVDataLogger(explicit)
        assert csv_logger.output_dir == explicit
        with csv_logger:
            csv_logger.record("heater", 25, 30)
        assert csv_logger.filepath.is_file()
        configured = setup_logging(log_dir=str(explicit), console_output=False)
        configured.info("explicit output directory")
        assert all(Path(handler.baseFilename).parent == explicit.resolve()
                   for handler in configured.handlers)
        DeviceLogger("desktop-explicit-path-test", str(explicit)).info("device export")
        assert Path(device_logger.handlers[0].baseFilename).parent == (explicit / "devices").resolve()
        assert not (root / "logs").exists()
        assert not (root / "reports").exists()
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if handler not in handlers:
                handler.close()
        for handler in handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(level)
        for handler in device_logger.handlers[:]:
            device_logger.removeHandler(handler)
            handler.close()


def test_default_reports_and_logging_stay_in_desktop_workspace(tmp_path, monkeypatch):
    from src.reports.report_generator import ReportGenerator
    from src.utils.logger import DeviceLogger, setup_logging

    root = tmp_path / "workspace"
    monkeypatch.setenv("HEAT_DATA_DIR", str(root))
    monkeypatch.chdir(tmp_path)
    root_logger = logging.getLogger()
    handlers, level = root_logger.handlers[:], root_logger.level
    device_logger = logging.getLogger("device.desktop-default-path-test")
    try:
        assert ReportGenerator().output_dir == root / "reports"
        configured = setup_logging(console_output=False)
        assert Path(configured.handlers[0].baseFilename).parent == root / "logs"
        DeviceLogger("desktop-default-path-test")
        assert Path(device_logger.handlers[0].baseFilename).parent == root / "logs/devices"
        assert not (tmp_path / "logs").exists()
        assert not (tmp_path / "reports").exists()
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if handler not in handlers:
                handler.close()
        for handler in handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(level)
        for handler in device_logger.handlers[:]:
            device_logger.removeHandler(handler)
            handler.close()
