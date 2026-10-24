"""Tray callbacks leave the native message loop free; no native UI or hardware."""
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.desktop import main as host
from src.desktop.common import URL, VERSION


pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows desktop host')


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No physical serial access')))
    monkeypatch.setattr(host, 'message_box', Mock(return_value=True))


def desktop(tmp_path):
    app = host.Desktop(tmp_path / 'Heat')
    app.window = Mock()
    app.window.get_current_url.return_value = None
    return app


def identity(home, **changes):
    result = dict(pid=12345, version=VERSION, workspace=str((Path(home) / 'workspace').resolve()),
                  url=URL, instance_id='a' * 32, state='ready', errors=[])
    return dict(result, **changes)


def call_from_tray(callback):
    """Model pystray's synchronous callback on its native message-loop thread."""
    returned = threading.Event()
    errors = []

    def invoke():
        try:
            callback(None, None)
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    return thread, returned, errors


def test_show_returns_to_tray_while_window_activation_is_blocked(tmp_path):
    app = desktop(tmp_path)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    show_threads = []

    def show():
        show_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5), 'test did not release window activation'
        completed.set()

    app.window.show.side_effect = show
    tray, returned, errors = call_from_tray(app.show_from_tray)
    try:
        assert entered.wait(2), 'window activation was not dispatched'
        assert returned.wait(1), 'window activation blocked the tray message loop'
        assert len(show_threads) == 1
        assert show_threads[0] != tray.ident
        app.window.restore.assert_not_called()
    finally:
        release.set()
        tray.join(timeout=2)
        assert completed.wait(2)
    assert not errors


def test_boot_binds_only_nonblocking_callbacks_to_native_tray(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.setup_visible = True
    app.navigation_ready.set()
    watch_finished = threading.Event()
    monkeypatch.setattr(app, '_watch', watch_finished.set)
    monkeypatch.setattr('PIL.Image.open', Mock(return_value=Mock()))
    icon = Mock()
    icon.run.side_effect = lambda *, setup: setup(icon)
    icon_factory = Mock(return_value=icon)
    pystray = SimpleNamespace(
        Icon=icon_factory,
        Menu=lambda *items: items,
        MenuItem=lambda text, action, **options: SimpleNamespace(text=text, action=action),
    )
    monkeypatch.setitem(sys.modules, 'pystray', pystray)
    backend = Mock(side_effect=AssertionError('uninitialized workspace must not start backend'))
    monkeypatch.setattr(host, 'request', backend)
    app._boot()
    assert watch_finished.wait(2)
    icon_factory.assert_called_once()
    items = icon_factory.call_args.kwargs['menu']
    assert [(item.text, item.action) for item in items] == [
        ('显示窗口', app.show_from_tray), ('退出 Heat', app.exit_from_tray),
    ]
    assert app.tray_ready.is_set()
    backend.assert_not_called()
    host.message_box.assert_not_called()


def test_exit_returns_to_tray_while_confirmation_is_open(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    confirming_threads = []
    backend = Mock(side_effect=AssertionError('declined confirmation must not contact backend'))
    monkeypatch.setattr(host, 'request', backend)

    def confirm(*args, **kwargs):
        confirming_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5), 'test did not release exit confirmation'
        return False

    monkeypatch.setattr(host, 'message_box', confirm)
    original = app.request_exit

    def exit_attempt():
        try:
            return original()
        finally:
            completed.set()

    monkeypatch.setattr(app, 'request_exit', exit_attempt)
    tray, returned, errors = call_from_tray(app.exit_from_tray)
    try:
        assert entered.wait(2), 'exit confirmation was not dispatched'
        assert returned.wait(1), 'exit confirmation blocked the tray message loop'
        assert confirming_threads[0] != tray.ident
        backend.assert_not_called()
        app.window.destroy.assert_not_called()
    finally:
        release.set()
        tray.join(timeout=2)
        assert completed.wait(2)
    assert not errors
    backend.assert_not_called()
    assert not app.operation.locked()
    assert not app.finished.is_set()


def test_concurrent_tray_exit_only_sends_one_confirmed_shutdown(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    entered, release = threading.Event(), threading.Event()
    done = [threading.Event(), threading.Event()]
    attempt_lock = threading.Lock()
    attempts = []
    commands = []

    def confirm(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'test did not release exit confirmation'
        return True

    confirmation = Mock(side_effect=confirm)
    monkeypatch.setattr(host, 'message_box', confirmation)

    def control(home, role, command, **kwargs):
        commands.append(command)
        if command == 'status':
            return identity(home, state='ready' if len(commands) == 1 else 'stopped')
        assert kwargs['instance_id'] == 'a' * 32
        return identity(home, state='stopping' if command == 'shutdown' else 'stopped')

    monkeypatch.setattr(host, 'request', control)
    handle = Mock()
    handle.wait.return_value = True
    monkeypatch.setattr(host, 'ProcessHandle', Mock(return_value=handle))
    original = app.request_exit

    def exit_attempt():
        with attempt_lock:
            index = len(attempts)
            attempts.append(threading.get_ident())
        try:
            return original()
        finally:
            done[index].set()

    monkeypatch.setattr(app, 'request_exit', exit_attempt)
    first, first_returned, first_errors = call_from_tray(app.exit_from_tray)
    second = None
    try:
        assert entered.wait(2)
        assert first_returned.wait(1)
        second, second_returned, second_errors = call_from_tray(app.exit_from_tray)
        assert second_returned.wait(1)
        assert done[1].wait(2), 'concurrent exit did not promptly observe operation lock'
        assert not done[0].is_set()
        confirmation.assert_called_once()
        assert commands == []
    finally:
        release.set()
        first.join(timeout=2)
        if second is not None:
            second.join(timeout=2)
        assert done[0].wait(2)
    assert not first_errors
    assert not second_errors
    assert commands == ['status', 'shutdown', 'status', 'commit_exit']
    app.window.destroy.assert_called_once()
    handle.close.assert_called_once()
    assert not app.operation.locked()


def test_exit_logs_confirmation_shutdown_cleanup_and_process_completion(tmp_path, monkeypatch, caplog):
    app = desktop(tmp_path)
    commands = []

    def control(home, role, command, **kwargs):
        commands.append(command)
        if command == 'status':
            return identity(home, state='ready' if len(commands) == 1 else 'stopped')
        return identity(home, state='stopping' if command == 'shutdown' else 'stopped')

    monkeypatch.setattr(host, 'request', control)
    handle = Mock()
    handle.wait.return_value = True
    monkeypatch.setattr(host, 'ProcessHandle', Mock(return_value=handle))
    with caplog.at_level(logging.INFO, logger=host.__name__):
        assert app.request_exit() == {}
    messages = '\n'.join(record.getMessage().lower() for record in caplog.records)
    for stage in ('exit requested', 'shutdown requested', 'cleanup confirmed',
                  'backend process exited', 'desktop exit complete'):
        assert stage in messages, f'missing diagnostic stage: {stage}'


def test_declined_exit_is_logged_without_contacting_backend(tmp_path, monkeypatch, caplog):
    app = desktop(tmp_path)
    monkeypatch.setattr(host, 'message_box', Mock(return_value=False))
    backend = Mock(side_effect=AssertionError('declined exit must not contact backend'))
    monkeypatch.setattr(host, 'request', backend)
    with caplog.at_level(logging.INFO, logger=host.__name__):
        assert app.request_exit() == {}
    assert any('exit cancelled' in record.getMessage().lower() for record in caplog.records)
    backend.assert_not_called()
    app.window.destroy.assert_not_called()
    assert not app.operation.locked()
