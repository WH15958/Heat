"""Opt-in persistent storage root for the desktop launcher."""
import os
from pathlib import Path


def data_path(relative, legacy=None) -> Path:
    """Use desktop storage when configured, preserving existing Web defaults."""
    directory = os.environ.get("HEAT_DATA_DIR")
    if not directory:
        return Path(relative if legacy is None else legacy)
    root = Path(directory).expanduser()
    if not root.is_absolute():
        raise ValueError("HEAT_DATA_DIR must be an absolute path")
    root = root.resolve()
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Runtime data paths must be relative to HEAT_DATA_DIR")
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Runtime data path escapes HEAT_DATA_DIR")
    return target
