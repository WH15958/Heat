"""Reject accidental workspace data and record the exact release contents."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


PRIVATE_ROOTS = ("config", "data", "output", "logs", "reports", "experiments")
REQUIRED_RESOURCES = (
    "src/web/static/index.html", "desktop/heat.ico", "python310.dll",
    "pythonnet/runtime/Python.Runtime.dll", "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
    "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    "win32/win32api.pyd", "win32/win32file.pyd", "win32/win32security.pyd",
    "psutil/_psutil_windows.pyd",
)


def verify_bundle(distribution: Path):
    for executable in ("Heat.exe", "HeatBackend.exe"):
        if not (distribution / executable).is_file():
            raise ValueError(f"Missing desktop executable: {executable}")
    for base in (distribution, distribution / "_internal"):
        for name in PRIVATE_ROOTS:
            if (base / name).exists():
                raise ValueError(f"Workspace data must not be distributed: {base / name}")
    for resource in REQUIRED_RESOURCES:
        if not (distribution / "_internal" / resource).is_file():
            raise ValueError(f"Missing packaged resource: {resource}")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("build_root", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--iscc", required=True, type=Path)
    args = parser.parse_args()
    distribution = args.build_root / "dist/Heat"
    verify_bundle(distribution)
    installers = list((args.build_root / "release").glob(f"Heat-Setup-{args.version}-x64.exe"))
    if len(installers) != 1:
        raise ValueError("Exactly one versioned Heat installer must exist")
    files = sorted(path for path in distribution.rglob("*") if path.is_file()) + installers
    manifest = {
        "version": args.version,
        "python": sys.version,
        "platform": "windows-x64",
        "webview2_sha256": sha256(args.runtime),
        "iscc_sha256": sha256(args.iscc),
        "dependencies": json.loads(subprocess.check_output([sys.executable, "-m", "pip", "list", "--format=json"], text=True)),
        "files": [{"path": path.relative_to(args.build_root).as_posix(), "bytes": path.stat().st_size,
                   "sha256": sha256(path)} for path in files],
    }
    (args.build_root / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(files)} release files; release-manifest.json written")


if __name__ == "__main__":
    main()
