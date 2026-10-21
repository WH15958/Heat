"""Packaging boundaries prevent real experiment data entering a release."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_desktop_bundle", ROOT / "packaging/desktop/verify_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def make_bundle(root):
    for relative in ("Heat.exe", "HeatBackend.exe", *["_internal/" + name for name in bundle.REQUIRED_RESOURCES]):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")


def test_distribution_requires_backend_and_resources(tmp_path):
    make_bundle(tmp_path)
    bundle.verify_bundle(tmp_path)
    (tmp_path / "HeatBackend.exe").unlink()
    with pytest.raises(ValueError, match="Missing desktop executable"):
        bundle.verify_bundle(tmp_path)


@pytest.mark.parametrize("base", ["", "_internal"])
@pytest.mark.parametrize("private", bundle.PRIVATE_ROOTS)
def test_distribution_rejects_lab_data(tmp_path, base, private):
    make_bundle(tmp_path)
    (tmp_path / base / private).mkdir(parents=True)
    with pytest.raises(ValueError, match="Workspace data must not be distributed"):
        bundle.verify_bundle(tmp_path)


@pytest.mark.parametrize("resource", bundle.REQUIRED_RESOURCES)
def test_distribution_requires_runtime_resources(tmp_path, resource):
    make_bundle(tmp_path)
    (tmp_path / "_internal" / resource).unlink()
    with pytest.raises(ValueError, match="Missing packaged resource"):
        bundle.verify_bundle(tmp_path)
