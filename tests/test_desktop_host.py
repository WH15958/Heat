"""Windows host/pipe tests; native windows and hardware are never opened."""
import json
import asyncio
from multiprocessing.connection import Client, Listener
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.desktop.common import InstanceLock, URL, VERSION, ipc_token, pipe_address
from src.desktop.ipc import MAX_MESSAGE, PipeServer, request
from src.desktop import main as host


pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows desktop host')


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No physical serial access')))
    monkeypatch.setattr(host, 'message_box', Mock(return_value=True))


def desktop(tmp_path):
    result = host.Desktop(tmp_path / 'Heat')
    result.window = Mock()
    result.window.get_current_url.return_value = None
    return result


def identity(home, **changes):
    status = dict(pid=12345, version=VERSION, workspace=str((Path(home) / 'workspace').resolve()),
                  url=URL, instance_id='a' * 32, state='ready', errors=[])
    return dict(status, **changes)


def test_named_pipe_authenticates_and_rejects_wrong_key_without_stopping_server(tmp_path, monkeypatch):
    import src.desktop.ipc as ipc
    handler = Mock(return_value={'state': 'ready'})
    server = PipeServer(tmp_path, 'auth-test', handler)
    server.start()
    try:
        assert request(tmp_path, 'auth-test', 'status') == {'state': 'ready'}
        with monkeypatch.context() as patch:
            patch.setattr(ipc, 'ipc_token', lambda home: 'ff' * 32)
            with pytest.raises((RuntimeError, OSError, EOFError, ValueError)):
                request(tmp_path, 'auth-test', 'shutdown', timeout=0.5)
        assert request(tmp_path, 'auth-test', 'status') == {'state': 'ready'}
        assert [call.args[0] for call in handler.call_args_list] == ['status', 'status']
    finally:
        server.close()


@pytest.mark.parametrize('payload', [b'{invalid json', b'[]', b'x' * (MAX_MESSAGE + 1)],
                         ids=['invalid-json', 'wrong-shape', 'oversize'])
def test_named_pipe_rejects_malformed_or_oversize_messages_and_keeps_serving(tmp_path, payload):
    handler = Mock(return_value={'alive': True})
    server = PipeServer(tmp_path, 'bounds-test', handler)
    server.start()
    try:
        with Client(pipe_address(tmp_path, 'bounds-test'), family='AF_PIPE') as connection:
            # An invalid peer may send immediately or after the server challenge;
            # neither form can reach the command handler.
            try:
                connection.send_bytes(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Windows may close an oversized message before its write completes.
        assert request(tmp_path, 'bounds-test', 'status') == {'alive': True}
        handler.assert_called_once()
        assert handler.call_args.args[0] == 'status'
    finally:
        server.close()


def test_named_pipe_rejects_invalid_command_type_and_handler_errors(tmp_path):
    def handle(command, *args):
        if command != 'status':
            raise ValueError('unsupported command')
        return {'ready': True}

    server = PipeServer(tmp_path, 'commands-test', handle)
    server.start()
    try:
        with pytest.raises((RuntimeError, ValueError, EOFError, OSError)):
            request(tmp_path, 'commands-test', 123, timeout=0.5)
        with pytest.raises(RuntimeError, match='unsupported command'):
            request(tmp_path, 'commands-test', 'start-device')
        assert request(tmp_path, 'commands-test', 'status') == {'ready': True}
    finally:
        server.close()


def test_unknown_pipe_cannot_claim_authenticated_identity_or_receive_secret(tmp_path):
    token = ipc_token(tmp_path)
    observed = []
    listener = Listener(pipe_address(tmp_path, 'imposter-test'), family='AF_PIPE')

    def pretend():
        with listener.accept() as connection:
            connection.send_bytes(json.dumps({'authenticated': True, 'result': {'state': 'ready'}}).encode())
            if connection.poll(1):
                try:
                    observed.append(connection.recv_bytes(MAX_MESSAGE))
                except (OSError, EOFError):
                    pass

    thread = threading.Thread(target=pretend, daemon=True)
    thread.start()
    try:
        with pytest.raises((RuntimeError, ValueError, OSError, EOFError, TimeoutError)):
            request(tmp_path, 'imposter-test', 'status', timeout=0.5)
    finally:
        thread.join(timeout=2)
        listener.close()
    assert not thread.is_alive()
    assert all(token.encode() not in message for message in observed)


def test_instance_lock_blocks_same_role_across_processes_and_releases(tmp_path):
    first, other_role = InstanceLock(tmp_path, 'shell'), InstanceLock(tmp_path, 'backend')
    assert first.acquire()
    assert other_role.acquire()
    try:
        command = ('from src.desktop.common import InstanceLock; '
                   f'lock=InstanceLock({str(tmp_path)!r}, "shell"); '
                   'ok=lock.acquire(); print(int(ok)); lock.close()')
        result = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == '0'
    finally:
        first.close()
        other_role.close()
    replacement = InstanceLock(tmp_path, 'shell')
    assert replacement.acquire()
    replacement.close()


def test_window_close_only_hides_to_tray_and_never_uses_backend(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    backend = Mock(side_effect=AssertionError('window close must not control backend'))
    monkeypatch.setattr(host, 'request', backend)
    app.tray_ready.set()
    assert app.closing() is False
    app.window.hide.assert_called_once()
    app.window.destroy.assert_not_called()
    app.allow_close = True
    assert app.closing() is True
    backend.assert_not_called()


def test_window_remains_visible_until_tray_is_ready(tmp_path):
    app = desktop(tmp_path)
    assert app.closing() is False
    app.window.hide.assert_not_called()
    app.window.destroy.assert_not_called()


def test_shell_pipe_only_activates_window(tmp_path):
    app = desktop(tmp_path)
    server = PipeServer(app.home, 'shell', app._activate)
    server.start()
    try:
        assert request(app.home, 'shell', 'show')['version'] == VERSION
        app.window.show.assert_called_once()
        with pytest.raises(RuntimeError):
            request(app.home, 'shell', 'shutdown')
        app.window.destroy.assert_not_called()
    finally:
        server.close()


@pytest.mark.parametrize('field,value', [
    ('version', 'unknown'), ('url', 'http://127.0.0.1:9000'),
    ('workspace', 'C:/unknown-workspace'), ('pid', '12345'), ('pid', True), ('pid', 0),
    ('instance_id', ''), ('instance_id', {'valid': True}), ('state', 'unknown'),
])
def test_backend_identity_mismatch_is_rejected_before_connecting(tmp_path, field, value):
    status = identity(tmp_path)
    status[field] = value
    with pytest.raises(RuntimeError):
        host.validate_backend(status, tmp_path)


def test_unknown_backend_is_not_replaced_or_adopted(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    status = identity(app.home)
    status['version'] = 'incompatible'
    monkeypatch.setattr(host, 'request', Mock(return_value=status))
    launch = Mock(side_effect=AssertionError('must not replace unknown service'))
    monkeypatch.setattr(host.subprocess, 'Popen', launch)
    with pytest.raises(RuntimeError):
        app._start_backend()
    launch.assert_not_called()
    app.window.load_url.assert_not_called()


def test_port_conflict_does_not_start_or_replace_a_service(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    monkeypatch.setattr(host, 'request', Mock(side_effect=FileNotFoundError()))
    occupied = Mock()
    occupied.__enter__ = Mock(return_value=occupied)
    occupied.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(host.socket, 'create_connection', Mock(return_value=occupied))
    launch = Mock(side_effect=AssertionError('must not launch on occupied port'))
    monkeypatch.setattr(host.subprocess, 'Popen', launch)
    with pytest.raises(RuntimeError, match='8000'):
        app._start_backend()
    launch.assert_not_called()


def test_shell_reattaches_to_known_backend_without_starting_process(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    monkeypatch.setattr(host, 'request', Mock(return_value=identity(app.home)))
    launch = Mock(side_effect=AssertionError('must reuse existing backend'))
    monkeypatch.setattr(host.subprocess, 'Popen', launch)
    app._start_backend()
    assert app.backend_id == 'a' * 32
    app.window.load_url.assert_called_once_with(URL)
    launch.assert_not_called()


def test_import_bridge_returns_navigation_after_callback_without_replacing_document(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    source = tmp_path / 'original'
    app.window.create_file_dialog.return_value = [str(source)]
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=1)))
    imported = Mock()
    monkeypatch.setattr(host, 'import_workspace', imported)
    monkeypatch.setattr(host, 'request', Mock(return_value=identity(app.home)))
    assert host.Bridge(app).choose_source() == {'url': URL}
    imported.assert_called_once_with(source, app.home / 'workspace')
    assert not app.setup_visible
    app.window.load_html.assert_not_called()
    app.window.load_url.assert_not_called()


def test_successful_import_with_backend_failure_returns_retry_action_in_same_document(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.window.create_file_dialog.return_value = [str(tmp_path / 'original')]
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=1)))
    monkeypatch.setattr(host, 'import_workspace', Mock())
    monkeypatch.setattr(host, 'is_initialized', Mock(return_value=True))
    monkeypatch.setattr(host, 'request', Mock(side_effect=RuntimeError('后台不可用')))
    bridge = host.Bridge(app)
    result = bridge.choose_source()
    assert result['error'] == '后台不可用'
    assert result['page']['action'] == 'start_backend'
    assert not app.setup_visible
    app.window.load_html.assert_not_called()
    app.window.load_url.assert_not_called()
    monkeypatch.setattr(host, 'request', Mock(return_value=identity(app.home)))
    assert bridge.start_backend() == {'url': URL}
    app.window.load_html.assert_not_called()
    app.window.load_url.assert_not_called()


def test_failed_import_keeps_import_action_without_replacing_document(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.window.create_file_dialog.return_value = [str(tmp_path / 'original')]
    monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=1)))
    monkeypatch.setattr(host, 'import_workspace', Mock(side_effect=ValueError('复制失败')))
    monkeypatch.setattr(host, 'is_initialized', Mock(return_value=False))
    assert host.Bridge(app).choose_source() == {'error': '复制失败'}
    assert app.setup_visible
    app.window.load_html.assert_not_called()
    app.window.load_url.assert_not_called()


def test_stopped_backend_bridge_returns_exit_action_without_replacing_document(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.setup_visible = False
    monkeypatch.setattr(host, 'request', Mock(return_value=identity(app.home, state='stopped')))
    result = host.Bridge(app).start_backend()
    assert result['page']['action'] == 'request_exit'
    assert 'url' not in result
    app.window.load_html.assert_not_called()
    app.window.load_url.assert_not_called()


def test_backend_disconnect_shows_explicit_reconnect_without_restarting(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.backend_id = 'a' * 32
    app.finished = Mock()
    app.finished.wait.side_effect = [False, True]
    monkeypatch.setattr(host, 'request', Mock(side_effect=FileNotFoundError()))
    launch = Mock(side_effect=AssertionError('disconnect must not auto restart'))
    monkeypatch.setattr(host.subprocess, 'Popen', launch)
    app._watch()
    assert app.backend_id is None
    assert 'start_backend' in app.window.load_html.call_args.args[0]
    app.window.show.assert_called_once()
    app.window.destroy.assert_not_called()
    launch.assert_not_called()


def test_user_declining_exit_does_not_contact_backend_or_close_window(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    monkeypatch.setattr(host, 'message_box', Mock(return_value=False))
    backend = Mock(side_effect=AssertionError('user declined exit'))
    monkeypatch.setattr(host, 'request', backend)
    assert app.request_exit() == {}
    backend.assert_not_called()
    app.window.destroy.assert_not_called()


@pytest.mark.parametrize('failure', [None, 'stop-failed', 'process-still-running'])
def test_shell_exit_commits_only_confirmed_cleanup_and_waits_for_process(tmp_path, monkeypatch, failure):
    app = desktop(tmp_path)
    app.backend_id = 'a' * 32
    commands = []

    def control(home, role, command, **kwargs):
        commands.append((command, kwargs))
        if command == 'status':
            if len(commands) == 1:
                return identity(home)
            return identity(home, state='exit_failed' if failure == 'stop-failed' else 'stopped',
                            errors=['device stop failed'] if failure == 'stop-failed' else [])
        assert kwargs['instance_id'] == app.backend_id
        return identity(home, state='stopping' if command == 'shutdown' else 'stopped')

    handle = Mock()

    def wait(timeout):
        app.window.destroy.assert_not_called()
        return failure != 'process-still-running'

    handle.wait.side_effect = wait
    monkeypatch.setattr(host, 'request', control)
    monkeypatch.setattr(host, 'ProcessHandle', Mock(return_value=handle))
    result = app.request_exit()
    if failure is None:
        assert result == {}
        assert [command for command, _ in commands] == ['status', 'shutdown', 'status', 'commit_exit']
        handle.wait.assert_called_once()
        app.window.destroy.assert_called_once()
    else:
        assert result['error']
        app.window.destroy.assert_not_called()
        assert not app.finished.is_set()
        if failure == 'stop-failed':
            assert all(command != 'commit_exit' for command, _ in commands)
            handle.wait.assert_not_called()
    handle.close.assert_called_once()


def test_shell_cannot_exit_while_backend_lock_exists_but_pipe_is_missing(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    lock = InstanceLock(app.home, 'backend')
    assert lock.acquire()
    monkeypatch.setattr(host, 'request', Mock(side_effect=FileNotFoundError()))
    try:
        assert app.request_exit()['error']
        app.window.destroy.assert_not_called()
    finally:
        lock.close()


def test_exit_rejects_changed_backend_before_sending_control(tmp_path, monkeypatch):
    app = desktop(tmp_path)
    app.backend_id = 'b' * 32
    backend = Mock(return_value=identity(app.home))
    monkeypatch.setattr(host, 'request', backend)
    assert app.request_exit()['error']
    backend.assert_called_once_with(app.home, 'backend', 'status')
    app.window.destroy.assert_not_called()


def test_bridge_exposes_only_three_actions_and_rejects_web_page_exit(tmp_path):
    app = desktop(tmp_path)
    bridge = host.Bridge(app)
    public = {name for name in dir(bridge) if not name.startswith('_') and callable(getattr(bridge, name))}
    assert public == {'choose_source', 'start_backend', 'request_exit'}
    app.window.get_current_url.return_value = URL
    assert bridge.request_exit()['error']
    app.window.destroy.assert_not_called()


@pytest.mark.parametrize('stage', ['before-bind', 'after-bind'])
@pytest.mark.parametrize('address', ['127.0.0.1', '::1'])
def test_backend_refuses_existing_listener_without_starting_lifespan(tmp_path, monkeypatch, stage, address):
    import uvicorn
    from src.desktop import backend
    from src.web import app as web

    connection = Mock()
    probes = [OSError('not listening')] * (2 if stage == 'after-bind' else 0)
    if address == '::1':
        probes.append(OSError('not listening on IPv4'))
    probes.append(connection)
    sock = Mock()
    fake_socket = SimpleNamespace(
        create_connection=Mock(side_effect=probes), socket=Mock(return_value=sock),
        AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM,
        SOL_SOCKET=socket.SOL_SOCKET, SO_EXCLUSIVEADDRUSE=socket.SO_EXCLUSIVEADDRUSE,
    )
    monkeypatch.setattr(backend, 'socket', fake_socket)
    manager = Mock(side_effect=AssertionError('Conflict must not start device lifespan'))
    monkeypatch.setattr(web, 'create_device_manager', manager)
    server = SimpleNamespace(serve=AsyncMock())
    server_factory = Mock(return_value=server)
    monkeypatch.setattr(uvicorn, 'Server', server_factory)
    control = Mock()
    control_factory = Mock(return_value=control)
    monkeypatch.setattr(backend, 'PipeServer', control_factory)
    with pytest.raises(RuntimeError, match='8000'):
        asyncio.run(backend.serve(tmp_path))
    connection.close.assert_called_once()
    manager.assert_not_called()
    server.serve.assert_not_awaited()
    control.start.assert_not_called()
    sock.listen.assert_not_called()
    if stage == 'before-bind':
        fake_socket.socket.assert_not_called()
        server_factory.assert_not_called()
        control_factory.assert_not_called()
    else:
        sock.bind.assert_called_once_with(('127.0.0.1', 8000))
        sock.close.assert_called_once()
        control.close.assert_called_once()


def test_empty_device_backend_lives_independently_and_commits_confirmed_exit(tmp_path):
    """A real backend child owns only an empty, explicitly isolated workspace."""
    from src.desktop.migration import MARKER

    # A wildcard listener may coexist with a Windows exclusive loopback bind.
    # Check actual listeners before considering the port available for this test.
    for address in ('127.0.0.1', '::1'):
        try:
            connection = socket.create_connection((address, 8000), timeout=0.25)
        except OSError:
            continue
        connection.close()
        pytest.skip('Port 8000 already belongs to another service; it is left untouched')
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 8000))
    except OSError:
        pytest.skip('Port 8000 already belongs to another service; it is left untouched')
    finally:
        probe.close()
    home = tmp_path / 'Heat'
    workspace = home / 'workspace'
    (workspace / 'config').mkdir(parents=True)
    (workspace / 'config/system_config.yaml').write_text(
        'name: isolated desktop host test\nheaters: []\npumps: []\nmicrowaves: []\n'
        'syringe_pumps: []\nvalves: []\n', encoding='utf-8')
    (workspace / MARKER).write_text(json.dumps({'version': 1, 'files': []}), encoding='utf-8')
    environment = dict(os.environ, LOCALAPPDATA=str(tmp_path), HEAT_DATA_DIR=str(workspace),
                       PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    code = ('import serial; '
            'serial.Serial.open=lambda *a,**k: (_ for _ in ()).throw(AssertionError("No real serial")); '
            'from src.desktop.backend import main; raise SystemExit(main())')
    process = subprocess.Popen([sys.executable, '-c', code], cwd=tmp_path, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    status = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert process.poll() is None, 'Isolated backend exited before readiness'
            try:
                status = request(home, 'backend', 'status', timeout=0.5)
                if status['state'] == 'ready':
                    break
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            time.sleep(0.05)
        assert status and status['state'] == 'ready'
        assert status['pid'] == process.pid
        assert host.validate_backend(status, home) == status
        assert process.poll() is None  # No desktop shell exists to keep this child alive.
        for command in ('shutdown', 'commit_exit'):
            with pytest.raises(RuntimeError, match='身份'):
                request(home, 'backend', command, instance_id='0' * 32)
        with pytest.raises(RuntimeError):
            request(home, 'backend', 'commit_exit', instance_id=status['instance_id'])
        with pytest.raises(RuntimeError):
            request(home, 'backend', 'start_device', instance_id=status['instance_id'])
        request(home, 'backend', 'shutdown', instance_id=status['instance_id'])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = request(home, 'backend', 'status')
            if result['state'] == 'stopped':
                break
            time.sleep(0.05)
        assert result['state'] == 'stopped' and not result['errors']
        assert process.poll() is None  # Success remains observable until acknowledged.
        request(home, 'backend', 'commit_exit', instance_id=status['instance_id'])
        assert process.wait(timeout=10) == 0
        log = (home / 'desktop/backend.log').read_text(encoding='utf-8')
        assert 'Registered heater:' not in log and 'Registered pump:' not in log
    finally:
        if process.poll() is None:
            # Only the authenticated, isolated child is requested to exit; no kill.
            try:
                current = request(home, 'backend', 'status')
                request(home, 'backend', 'shutdown', instance_id=current['instance_id'])
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    current = request(home, 'backend', 'status')
                    if current['state'] == 'stopped':
                        request(home, 'backend', 'commit_exit', instance_id=current['instance_id'])
                        break
                    time.sleep(0.05)
            finally:
                process.wait(timeout=10)
        process.communicate(timeout=2)


def test_offline_page_escapes_imported_text_and_rejects_unknown_actions():
    from src.desktop.ui import page
    result = page('<script>bad()</script>', '<img src=x onerror=bad()>',
                  action='choose_source', label='<import>')
    assert '<script>bad()</script>' not in result
    assert '<img src=x onerror=bad()>' not in result
    assert '&lt;import&gt;' in result
    with pytest.raises(ValueError):
        page('x', 'y', action='start_device')


def test_offline_javascript_waits_for_bridge_result_before_navigation_and_switches_retry_action():
    from src.desktop.ui import page
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for the offline page interaction test')
    script = re.search(r'<script>(.*?)</script>', page('导入', '原项目', action='choose_source'), re.S).group(1)
    harness = r'''
const assert=require('node:assert/strict');
const vm=require('node:vm');
let callback, complete;
const navigation=[], calls=[];
const elements=Object.fromEntries(['action','page-title','page-message','detail'].map(
  id=>[id,{textContent:'',disabled:true}]));
const context={document:{getElementById:id=>elements[id]},window:{
  addEventListener:(name,fn)=>{callback=fn},
  location:{assign:url=>navigation.push(url)}},pywebview:{api:{
    choose_source:()=>{calls.push('choose_source');return new Promise(resolve=>{complete=resolve})},
    start_backend:async()=>{calls.push('start_backend');return {url:'http://127.0.0.1:8000'}}}}};
vm.runInNewContext(require('node:fs').readFileSync(0,'utf8'),context);
callback();
(async()=>{
 const first=elements.action.onclick();
 assert.equal(elements.action.disabled,true);
 assert.deepEqual(navigation,[]);
 complete({error:'启动失败',page:{title:'后台未就绪',message:'请重试',
   action:'start_backend',label:'重新连接／启动后台'}});
 await first;
 assert.deepEqual(calls,['choose_source']);
 assert.deepEqual(navigation,[]);
 assert.equal(elements['page-title'].textContent,'后台未就绪');
 assert.equal(elements['page-message'].textContent,'请重试');
 assert.equal(elements.action.textContent,'重新连接／启动后台');
 assert.equal(elements.detail.textContent,'启动失败');
 assert.equal(elements.action.disabled,false);
 await elements.action.onclick();
 assert.deepEqual(calls,['choose_source','start_backend']);
 assert.deepEqual(navigation,['http://127.0.0.1:8000']);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    result = subprocess.run([node, '-e', harness], input=script, capture_output=True,
                            text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr


def test_error_page_data_navigation_is_trusted_only_for_current_host_document(tmp_path):
    import base64
    app = desktop(tmp_path)
    app._show_error('端口 8000 已占用')
    content = app.window.load_html.call_args.args[0]
    uri = 'data:text/html;charset=utf-8;base64,' + base64.b64encode(content.encode()).decode()
    assert app._navigation_allowed(uri)
    app.window.get_current_url.return_value = uri
    assert app._trusted_page()
    app._show_error('连接已断开')
    assert not app._navigation_allowed(uri)
    assert not app._trusted_page()
    for untrusted in ('data:text/html,<script>bad()</script>',
                      'https://example.com', 'file:///C:/private.html',
                      'http://127.0.0.1:8001', 'blob:https://example.com/x'):
        assert not app._navigation_allowed(untrusted)
    assert app._navigation_allowed('about:blank')
    assert app._navigation_allowed(URL + '/experiments')
    assert app._navigation_allowed('blob:' + URL + '/export')
