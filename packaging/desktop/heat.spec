# Run through scripts/build_desktop.ps1. Never bundle the developer's workspace.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parents[1]
icon = Path(os.environ["HEAT_BUILD_ICON"]).resolve()
static = root / "src/web/static"
if not (static / "index.html").is_file():
    raise SystemExit("Build the production frontend before freezing Heat")

# Deliberate source resource allowlist: no config, data, logs, experiments or output.
datas = [(str(static), "src/web/static"), (str(icon), "desktop")]
binaries = []
hidden = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "webview.platforms.winforms", "webview.platforms.edgechromium", "pystray._win32",
    "serial.tools.list_ports_windows", "psutil", "win32api", "win32con", "win32file",
    "win32security", "ntsecuritycon", "matplotlib.backends.backend_agg",
] + collect_submodules("src")
for package in ("webview", "pythonnet", "clr_loader"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hidden += package_hidden

analyses = []
executables = []
for module, name in (("main", "Heat"), ("backend", "HeatBackend")):
    analysis = Analysis(
        [str(root / f"src/desktop/{module}.py")], pathex=[str(root)],
        binaries=binaries, datas=datas, hiddenimports=hidden,
        excludes=["pytest", "resvg_py", "IPython", "notebook", "matplotlib.backends.backend_qtagg"],
        hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    )
    analyses.append(analysis)
    executable = EXE(
        PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True,
        name=name, console=False, icon=str(icon), upx=False,
    )
    executables.append(executable)

collection = COLLECT(
    *executables, *[toc for analysis in analyses for toc in (analysis.binaries, analysis.datas)],
    name="Heat", upx=False,
)
