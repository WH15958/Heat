"""Import an existing Heat workspace without changing its files or running hardware."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import tempfile
from datetime import datetime, timezone

import yaml

from src.utils.config import ConfigManager


MARKER = ".heat-workspace.json"
IMPORT_PATHS = (
    "config/system_config.yaml",
    "experiments",
    "data/campaigns",
    "data/datasets",
    "data/syringe_programs",
    "output/experiment_logs",
    "output/yaml_runs",
    "output/guided_batches",
    "output/microwave_programs",
    "logs",
    "reports",
)


def is_initialized(workspace: Path) -> bool:
    try:
        workspace = Path(workspace)
        marker = json.loads((workspace / MARKER).read_text(encoding="utf-8"))
        return (type(marker.get("version")) is int and marker["version"] == 1
                and isinstance(marker.get("files"), list)
                and (workspace / "config/system_config.yaml").is_file())
    except (OSError, ValueError, AttributeError):
        return False


def _check_stopped():
    for address in ("127.0.0.1", "::1"):
        try:
            connection = socket.create_connection((address, 8000), timeout=0.25)
        except OSError:
            continue
        connection.close()
        raise ValueError("端口 8000 正在使用，请先关闭原 Heat 后端再导入")


def _is_link(path: Path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _check_path(path: Path, source: Path):
    relative = path.relative_to(source)
    current = source
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise ValueError(f"不能导入符号链接或重解析点: {relative}")
    if not path.resolve().is_relative_to(source):
        raise ValueError(f"导入路径超出源目录: {relative}")


def _files(path: Path, source: Path):
    _check_path(path, source)
    if path.is_dir():
        for child in sorted(path.iterdir()):
            yield from _files(child, source)
    elif path.is_file():
        if path.suffix.lower() not in (".lock", ".tmp"):
            yield path
    else:
        raise ValueError(f"不能导入非常规文件: {path.relative_to(source)}")


def _digest(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"size": path.stat().st_size, "sha256": digest.hexdigest()}


def _inventory(source: Path):
    entries = {}
    for relative in IMPORT_PATHS:
        path = source / relative
        if path.exists() or path.is_symlink():
            for file in _files(path, source):
                entries[file.relative_to(source).as_posix()] = _digest(file)
    return entries


def _remove_readonly(function, path, exc_info):
    if not isinstance(exc_info[1], PermissionError):
        raise exc_info[1]
    os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    function(path)


def import_workspace(source: Path, workspace: Path, *, check_running=True) -> dict:
    """Copy an allowlisted, verified snapshot, publishing the whole workspace at once."""
    source = Path(source).absolute()
    workspace = Path(workspace).absolute()
    if _is_link(source) or ((workspace.exists() or workspace.is_symlink()) and _is_link(workspace)):
        raise ValueError("源目录和目标目录不能为符号链接或重解析点")
    source = source.resolve()
    workspace = workspace.resolve()
    if source.is_relative_to(workspace) or workspace.is_relative_to(source):
        raise ValueError("源目录和目标目录不能相同或互相包含")
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise ValueError("目标目录不是空目录，不能覆盖现有数据")
    config_path = source / "config/system_config.yaml"
    if not config_path.is_file():
        raise ValueError("源目录缺少 config/system_config.yaml")
    _check_path(config_path, source)
    # ConfigManager.load() may generate defaults; importing must never write the source.
    try:
        config_bytes = config_path.read_bytes()
        data = yaml.safe_load(config_bytes.decode("utf-8"))
        config = ConfigManager(str(config_path))._convert_dict_to_config(data)
        errors = config.validate()
    except (yaml.YAMLError, AttributeError, TypeError) as exc:
        raise ValueError("源配置格式无效") from exc
    if errors:
        raise ValueError("源配置验证失败: " + "; ".join(errors))
    for value in (config.logging.log_dir, config.report.output_dir):
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("源配置的日志或报告路径超出工作目录，不能完整导入")
        if path.as_posix() not in ("logs", "reports"):
            raise ValueError("导入仅支持默认 logs 和 reports 目录，请先整理自定义输出路径")
    if check_running:
        _check_stopped()
    inventory = _inventory(source)
    validated_config = dict(size=len(config_bytes), sha256=hashlib.sha256(config_bytes).hexdigest())
    if inventory.get("config/system_config.yaml") != validated_config:
        raise ValueError("校验后源配置发生变化，请关闭原程序后重试")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{workspace.name}-import-", dir=workspace.parent))
    try:
        for relative, expected in inventory.items():
            original = source / relative
            _check_path(original, source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            # Backups may be readonly; only the imported working copy must be writable.
            target.chmod(target.stat().st_mode | stat.S_IWRITE)
            if _digest(target) != expected:
                raise ValueError(f"导入文件校验失败: {relative}")
        if _inventory(source) != inventory:
            raise ValueError("导入期间源文件发生变化，请关闭原程序后重试")
        if check_running:
            _check_stopped()
        manifest = dict(version=1, imported_at=datetime.now(timezone.utc).isoformat(),
                        source=str(source), files=[dict(path=path, **entry) for path, entry in inventory.items()])
        with (staging / MARKER).open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if workspace.exists():
            workspace.rmdir()  # Only an empty destination may be replaced.
        staging.rename(workspace)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging, onerror=_remove_readonly)
