"""Workspace import preserves traceability and never overwrites existing user data."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from src.desktop import migration


@pytest.fixture
def original(tmp_path):
    source = tmp_path / "原项目"
    path = source / "config/system_config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: imported\nheaters: []\npumps: []\nmicrowaves: []\n", encoding="utf-8")
    return source


def write(source, relative, content="saved"):
    path = source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


def test_import_copies_allowlist_and_hashes_without_changing_source(original, tmp_path):
    included = [
        "experiments/custom.yaml", "data/datasets/samples.csv", "data/campaigns/trials.json",
        "data/campaigns/recommendation.pending.json", "data/syringe_programs/program.json",
        "output/experiment_logs/run.json", "output/yaml_runs/yaml_record.json",
        "output/guided_batches/batch.json", "output/guided_batches/plans/batch.json",
        "output/microwave_programs/program.json", "logs/system.log", "reports/report.html",
    ]
    for relative in included:
        write(original, relative, f"original:{relative}")
    for relative in ("src/private.py", ".venv/token", "output/heat-launcher.lock",
                     "output/experiment_logs/write.tmp", "logs/process.lock"):
        write(original, relative)
    before = snapshot(original)
    workspace = tmp_path / "应用数据"
    manifest = migration.import_workspace(original, workspace, check_running=False)
    assert migration.is_initialized(workspace)
    assert manifest["version"] == 1
    assert {item["path"] for item in manifest["files"]} == set(included) | {"config/system_config.yaml"}
    for item in manifest["files"]:
        content = (workspace / item["path"]).read_bytes()
        assert item["size"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()
    assert snapshot(original) == before
    assert not (workspace / "src").exists()
    assert not (workspace / "output/heat-launcher.lock").exists()


def test_readonly_source_files_import_as_writable_without_changing_source(original, tmp_path, monkeypatch):
    from src.experiment import yaml_recovery
    from src.science import sample_record

    recovery = yaml_recovery.new_record("test.yaml", "steps: []")
    recovery_path = "output/yaml_runs/" + recovery["recovery_id"] + ".json"
    paths = [
        original / "config/system_config.yaml",
        write(original, "data/datasets/samples.csv", "sample_id,run_id\nS1,old-run\n"),
        write(original, "data/campaigns/trials.json", "[]"),
        write(original, recovery_path, json.dumps(recovery)),
    ]
    workspace = tmp_path / "workspace"
    for path in paths:
        path.chmod(stat.S_IREAD)
    before = {path: (path.read_bytes(), path.stat().st_mode) for path in paths}
    try:
        migration.import_workspace(original, workspace, check_running=False)
        assert migration.is_initialized(workspace)
        for path in paths:
            copied = workspace / path.relative_to(original)
            assert copied.stat().st_mode & stat.S_IWRITE
            assert (path.read_bytes(), path.stat().st_mode) == before[path]
            assert copied.read_bytes() == before[path][0]

        monkeypatch.setattr(sample_record, "SAMPLES_DIR", workspace / "data/datasets")
        monkeypatch.setattr(sample_record, "SAMPLES_CSV", workspace / "data/datasets/samples.csv")
        assert sample_record.write_sample_record("new-run", {"sample_id": "S2"})
        monkeypatch.setattr(yaml_recovery, "RECOVERY_DIR", workspace / "output/yaml_runs")
        recovery["recovery_required"] = True
        yaml_recovery.write_record(recovery)
        assert json.loads((workspace / recovery_path).read_text("utf-8"))["recovery_required"] is True
        assert {path: (path.read_bytes(), path.stat().st_mode) for path in paths} == before
    finally:
        for path in paths:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
            copied = workspace / path.relative_to(original)
            if copied.exists():
                copied.chmod(copied.stat().st_mode | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="Windows readonly removal behavior")
def test_failed_import_removes_readonly_staging_and_can_retry(original, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    real_copy = migration.shutil.copy2

    def fail_after_readonly_copy(source, target):
        real_copy(source, target)
        Path(target).chmod(stat.S_IREAD)
        raise OSError("copy interrupted after metadata")

    with monkeypatch.context() as scoped:
        scoped.setattr(migration.shutil, "copy2", fail_after_readonly_copy)
        with pytest.raises(OSError, match="copy interrupted"):
            migration.import_workspace(original, workspace, check_running=False)
    assert not workspace.exists()
    assert not list(tmp_path.glob(".workspace-import-*"))
    migration.import_workspace(original, workspace, check_running=False)
    assert migration.is_initialized(workspace)


def test_existing_empty_destination_can_be_imported(original, tmp_path):
    workspace = tmp_path / "empty"
    workspace.mkdir()
    migration.import_workspace(original, workspace, check_running=False)
    assert migration.is_initialized(workspace)


def test_existing_data_is_never_overwritten(original, tmp_path):
    workspace = tmp_path / "existing"
    write(workspace, "keep.txt", "user data")
    with pytest.raises(ValueError, match="不能覆盖"):
        migration.import_workspace(original, workspace, check_running=False)
    assert snapshot(workspace) == {"keep.txt": b"user data"}


@pytest.mark.parametrize("target", ["same", "child", "parent"])
def test_source_and_destination_cannot_overlap(original, target):
    workspace = {"same": original, "child": original / "child", "parent": original.parent}[target]
    with pytest.raises(ValueError, match="互相包含"):
        migration.import_workspace(original, workspace, check_running=False)


def test_missing_or_invalid_configuration_does_not_initialize(original, tmp_path):
    config = original / "config/system_config.yaml"
    config.unlink()
    workspace = tmp_path / "workspace"
    with pytest.raises(ValueError, match="缺少"):
        migration.import_workspace(original, workspace, check_running=False)
    assert not config.exists()
    config.write_text("heaters: invalid\n", encoding="utf-8")
    with pytest.raises(ValueError):
        migration.import_workspace(original, workspace, check_running=False)
    assert not workspace.exists()


def test_configuration_disappearing_after_check_is_not_recreated(original, tmp_path, monkeypatch):
    config = original / "config/system_config.yaml"
    workspace = tmp_path / "workspace"
    original_check = migration._check_path
    removed = False
    def remove_checked_file(path, source):
        nonlocal removed
        original_check(path, source)
        if path == config and not removed:
            config.unlink()
            removed = True
    monkeypatch.setattr(migration, "_check_path", remove_checked_file)
    with pytest.raises(FileNotFoundError):
        migration.import_workspace(original, workspace, check_running=False)
    assert not config.exists()
    assert not workspace.exists()
    assert not migration.is_initialized(workspace)
    assert not list(tmp_path.glob(".workspace-import-*"))


@pytest.mark.parametrize("remove", [True, False])
def test_configuration_changed_after_validation_cannot_initialize(original, tmp_path, monkeypatch, remove):
    config = original / "config/system_config.yaml"
    workspace = tmp_path / "workspace"
    original_inventory = migration._inventory
    def change_before_snapshot(source):
        if remove:
            config.unlink()
        else:
            config.write_text("heaters: invalid\n", encoding="utf-8")
        return original_inventory(source)
    monkeypatch.setattr(migration, "_inventory", change_before_snapshot)
    with pytest.raises(ValueError, match="源配置发生变化"):
        migration.import_workspace(original, workspace, check_running=False)
    assert not workspace.exists()
    assert not migration.is_initialized(workspace)
    assert not list(tmp_path.glob(".workspace-import-*"))
    if remove:
        assert not config.exists()
    else:
        assert config.read_text(encoding="utf-8") == "heaters: invalid\n"


@pytest.mark.parametrize("directory", ["../outside", "custom-logs"])
def test_nonstandard_output_configuration_is_rejected(original, tmp_path, directory):
    with (original / "config/system_config.yaml").open("a", encoding="utf-8") as stream:
        stream.write(f"logging:\n  log_dir: {directory}\n")
    with pytest.raises(ValueError):
        migration.import_workspace(original, tmp_path / "workspace", check_running=False)


def test_running_backend_blocks_import(original, tmp_path, monkeypatch):
    class Connected:
        def close(self):
            pass
    monkeypatch.setattr(migration.socket, "create_connection", lambda *a, **kw: Connected())
    with pytest.raises(ValueError, match="8000"):
        migration.import_workspace(original, tmp_path / "workspace")
    assert not (tmp_path / "workspace").exists()


def test_failed_copy_cleans_only_staging_and_can_retry(original, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    def fail(*args, **kwargs):
        raise OSError("disk full")
    with monkeypatch.context() as scoped:
        scoped.setattr(migration.shutil, "copy2", fail)
        with pytest.raises(OSError, match="disk full"):
            migration.import_workspace(original, workspace, check_running=False)
    assert not workspace.exists()
    assert not list(tmp_path.glob(".workspace-import-*"))
    assert (original / "config/system_config.yaml").exists()
    migration.import_workspace(original, workspace, check_running=False)
    assert migration.is_initialized(workspace)


def test_source_change_during_copy_is_detected(original, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    real_copy = migration.shutil.copy2
    def change(source, target):
        result = real_copy(source, target)
        Path(source).write_text("changed during copy", encoding="utf-8")
        return result
    monkeypatch.setattr(migration.shutil, "copy2", change)
    with pytest.raises(ValueError, match="源文件发生变化"):
        migration.import_workspace(original, workspace, check_running=False)
    assert not workspace.exists()
    assert not list(tmp_path.glob(".workspace-import-*"))


def test_hash_mismatch_prevents_publishing(original, tmp_path, monkeypatch):
    real_copy = migration.shutil.copy2
    def corrupt(source, target):
        real_copy(source, target)
        Path(target).write_bytes(b"corrupt")
    monkeypatch.setattr(migration.shutil, "copy2", corrupt)
    with pytest.raises(ValueError, match="校验失败"):
        migration.import_workspace(original, tmp_path / "workspace", check_running=False)
    assert not (tmp_path / "workspace").exists()


def test_destination_created_during_import_is_not_overwritten(original, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    real_copy = migration.shutil.copy2
    def create_destination(source, target):
        result = real_copy(source, target)
        write(workspace, "keep.txt", "concurrent user data")
        return result
    monkeypatch.setattr(migration.shutil, "copy2", create_destination)
    with pytest.raises(OSError):
        migration.import_workspace(original, workspace, check_running=False)
    assert snapshot(workspace) == {"keep.txt": b"concurrent user data"}
    assert not list(tmp_path.glob(".workspace-import-*"))


def test_symlink_escape_is_rejected(original, tmp_path):
    outside = write(tmp_path, "outside/private.json")
    link = original / "data/campaigns/escape.json"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(ValueError, match="符号链接"):
        migration.import_workspace(original, tmp_path / "workspace", check_running=False)
    assert outside.read_text(encoding="utf-8") == "saved"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_escape_is_rejected(original, tmp_path):
    outside = tmp_path / "outside"
    write(outside, "private.json")
    (original / "data").mkdir()
    link = original / "data/campaigns"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError, match="重解析点"):
        migration.import_workspace(original, tmp_path / "workspace", check_running=False)
    assert (outside / "private.json").read_text(encoding="utf-8") == "saved"


def test_unreadable_or_invalid_marker_is_not_initialized(tmp_path):
    assert not migration.is_initialized(tmp_path)
    write(tmp_path, migration.MARKER, "not json")
    assert not migration.is_initialized(tmp_path)
    write(tmp_path, migration.MARKER, json.dumps({"version": 2, "files": []}))
    assert not migration.is_initialized(tmp_path)
    write(tmp_path, migration.MARKER, json.dumps({"version": 1, "files": []}))
    assert not migration.is_initialized(tmp_path)
