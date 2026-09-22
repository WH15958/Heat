"""Launcher regressions using fake HTTP services; never access real devices."""

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import venv

from scripts import launch_heat as launcher


@contextlib.contextmanager
def fake_http(schema, page=b'<html><div id="app"></div></html>', page_status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/openapi.json":
                self.send_response(200)
                body = json.dumps(schema).encode()
            else:
                self.send_response(page_status)
                body = page
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.schema = {
            "info": {"title": "Heat - 温控与流体输送控制系统"},
            "paths": {"/api/devices": {}},
        }

    def test_ready_requires_heat_schema_and_frontend(self):
        for schema, page, status, expected in [
            (self.schema, b'<div id="app"></div>', 200, True),
            ({"info": {"title": "Another app"}}, b'<div id="app">', 200, False),
            (self.schema, b"Not built", 200, False),
            (self.schema, b'<div id="app">', 500, False),
            ({"info": None}, b'<div id="app">', 200, False),
        ]:
            with self.subTest(expected=expected, schema=schema, status=status):
                with fake_http(schema, page, status) as url:
                    self.assertEqual(launcher.heat_is_ready(url), expected)

    def test_preflight_reports_missing_frontend_and_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run_server.py").touch()
            with self.assertRaisesRegex(RuntimeError, "Frontend build is missing"):
                launcher.check_environment(root)
            static = root / "src/web/static"
            static.mkdir(parents=True)
            (static / "index.html").touch()
            with patch.object(launcher.importlib, "import_module", side_effect=ImportError("missing")):
                with self.assertRaisesRegex(RuntimeError, "pip install -r requirements.txt"):
                    launcher.check_environment(root)
            with patch.object(launcher.sys, "version_info", (3, 9)):
                with self.assertRaisesRegex(RuntimeError, "Python 3.10"):
                    launcher.check_environment(root)

    def test_timeout_does_not_open_browser_or_stop_server(self):
        stopped = threading.Event()
        with patch.object(launcher, "open_browser") as browser, contextlib.redirect_stdout(io.StringIO()) as output:
            launcher.wait_for_ready(stopped, timeout=0)
        browser.assert_not_called()
        self.assertFalse(stopped.is_set())
        self.assertIn("server remains", output.getvalue())

    def test_cancelled_startup_does_not_open_browser(self):
        stopped = threading.Event()
        stopped.set()
        with patch.object(launcher, "open_browser") as browser:
            launcher.wait_for_ready(stopped)
        browser.assert_not_called()

    def test_browser_opens_once_after_ready(self):
        with patch.object(launcher, "heat_is_ready", return_value=True), \
                patch.object(launcher, "open_browser") as browser:
            launcher.wait_for_ready(threading.Event())
        browser.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows launcher lock")
    def test_lock_blocks_second_process_and_releases_after_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = launcher.acquire_lock(root)
            self.assertIsNotNone(lock)
            try:
                result = subprocess.run(
                    [sys.executable, "-c",
                     "from pathlib import Path; import sys; "
                     "from scripts.launch_heat import acquire_lock; "
                     "sys.exit(0 if acquire_lock(Path(sys.argv[1])) is None else 1)", directory],
                    cwd=launcher.PROJECT_DIR, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                lock.close()
            with launcher.acquire_lock(root):
                pass

    def test_occupied_non_heat_port_never_starts_server(self):
        with patch.object(launcher, "acquire_lock", return_value=io.BytesIO()), \
                patch.object(launcher.socket, "create_connection", return_value=io.BytesIO()), \
                patch.object(launcher, "heat_is_ready", return_value=False), \
                patch.object(launcher.runpy, "run_path") as run:
            with self.assertRaisesRegex(RuntimeError, "Port 8000 is occupied"):
                launcher.launch(Path("unused"))
        run.assert_not_called()

    def test_existing_heat_opens_browser_without_starting_again(self):
        with patch.object(launcher, "acquire_lock", return_value=io.BytesIO()), \
                patch.object(launcher.socket, "create_connection", return_value=io.BytesIO()), \
                patch.object(launcher, "heat_is_ready", return_value=True), \
                patch.object(launcher, "open_browser") as browser, \
                patch.object(launcher.runpy, "run_path") as run:
            self.assertEqual(launcher.launch(Path("unused")), 0)
        browser.assert_called_once()
        run.assert_not_called()

    def test_duplicate_during_startup_never_starts_second_server(self):
        with patch.object(launcher, "acquire_lock", return_value=None), \
                patch.object(launcher, "heat_is_ready", return_value=False), \
                patch.object(launcher.runpy, "run_path") as run:
            self.assertEqual(launcher.launch(Path("unused")), 0)
        run.assert_not_called()

    def test_server_failure_cancels_watcher_immediately(self):
        events = []

        def watch(stopped):
            events.append(stopped)
            stopped.wait(5)

        with patch.object(launcher, "acquire_lock", return_value=io.BytesIO()), \
                patch.object(launcher.socket, "create_connection", side_effect=ConnectionRefusedError), \
                patch.object(launcher, "check_environment"), \
                patch.object(launcher, "wait_for_ready", side_effect=watch), \
                patch.object(launcher.runpy, "run_path", side_effect=ImportError("startup failed")):
            with self.assertRaisesRegex(ImportError, "startup failed"):
                launcher.launch(Path("unused"))
        self.assertTrue(events[0].is_set())

    def test_early_error_is_saved_in_launcher_log(self):
        original_cwd = Path.cwd()
        original_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(launcher, "PROJECT_DIR", Path(directory)), \
                        patch.object(launcher, "launch", side_effect=ImportError("early error")), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(launcher.main(), 1)
                self.assertIn("early error", (Path(directory) / "logs/launcher.log").read_text(encoding="utf-8"))
                os.chdir(original_cwd)
        finally:
            os.chdir(original_cwd)
            sys.path[:] = original_path

    @unittest.skipUnless(os.name == "nt", "Windows batch entry point")
    def test_batch_selects_conda_and_project_venv_in_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Heat launcher (test) ") as directory:
            root = Path(directory)
            shutil.copy2(launcher.PROJECT_DIR / "start_heat.bat", root)
            (root / "scripts").mkdir()
            # A stub entry point guarantees this test cannot start Heat or devices.
            (root / "scripts/launch_heat.py").write_text(
                "import sys; from pathlib import Path; "
                "Path('selected.txt').write_text(sys.executable, encoding='utf-8')\n",
                encoding="utf-8",
            )
            conda = root / "fake conda"
            (conda / "condabin").mkdir(parents=True)
            (conda / "Scripts").mkdir()
            (conda / "condabin/conda.bat").write_text(
                f'@echo off\nset "CONDA_PREFIX={sys.prefix}"\nexit /b 0\n',
                encoding="utf-8",
            )
            env = dict(os.environ, CONDA_EXE=str(conda / "Scripts/conda.exe"))
            for use_venv in (False, True):
                with self.subTest(use_venv=use_venv):
                    expected = Path(sys.executable)
                    if use_venv:
                        venv.EnvBuilder(with_pip=False).create(root / ".venv")
                        expected = root / ".venv/Scripts/python.exe"
                    result = subprocess.run(
                        [os.environ["COMSPEC"], "/d", "/c", str(root / "start_heat.bat")],
                        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
                    selected = (root / "selected.txt").read_text(encoding="utf-8")
                    self.assertEqual(Path(selected), expected)


if __name__ == "__main__":
    unittest.main()
