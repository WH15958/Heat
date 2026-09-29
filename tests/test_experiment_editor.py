"""Authoring endpoints must never reach a device; exercise real file/HTTP boundaries."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi import FastAPI

from src.experiment import editor, parser
from src.web.api import experiments as api

CONTENT = '# keep me\nname: demo\nmetadata: {custom: yes}\nsteps:\n  - id: note\n    type: log\n    params: {message: hello}\n    enabled: false\n    on_error: skip\n    wait: {type: duration, seconds: 2, timeout: 8}\n'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path)
    monkeypatch.setattr(api, '_engines', {})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    app = FastAPI()
    app.include_router(api.router, prefix='/api')
    app.state.device_manager = Mock(side_effect=AssertionError('No hardware access'))
    return tmp_path, app


async def request(app, method, url, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        return await client.request(method, '/api/experiments' + url, **kwargs)


def test_source_roundtrip_and_no_device_calls(setup):
    root, app = setup
    result = asyncio.run(request(app, 'PUT', '/demo.yaml/source', json={'content': CONTENT}))
    assert result.status_code == 200
    assert (root / 'demo.yaml').read_text('utf-8') == CONTENT
    result = asyncio.run(request(app, 'GET', '/demo.yaml/source'))
    assert result.json()['content'] == CONTENT
    parsed = parser.parse_experiment('demo.yaml')
    assert parsed['steps'][0].enabled is False
    assert parsed['steps'][0].on_error == 'skip'
    assert parsed['steps'][0].wait.timeout == 8
    assert not app.state.device_manager.mock_calls


def test_create_update_external_change_and_missing_file_conflicts(setup):
    root, app = setup
    first = editor.write_source('demo.yaml', CONTENT, None)
    with pytest.raises(editor.SourceConflict):
        editor.write_source('demo.yaml', CONTENT, None)
    editor.write_source('demo.yaml', CONTENT + '\n', first['revision'])
    result = asyncio.run(request(app, 'PUT', '/demo.yaml/source', json={'content': CONTENT, 'revision': first['revision']}))
    assert result.status_code == 409
    (root / 'demo.yaml').unlink()
    with pytest.raises(editor.SourceConflict):
        editor.write_source('demo.yaml', CONTENT, first['revision'])


@pytest.mark.parametrize('name', ['../escape.yaml', 'sub/a.yaml', 'sub\\a.yaml', 'x.txt', 'C:bad.yaml', 'CON.yaml'])
def test_filename_rejected(setup, name):
    with pytest.raises(ValueError):
        editor.write_source(name, CONTENT, None)


def test_atomic_failure_preserves_original_and_cleans_temp(setup, monkeypatch):
    root, _ = setup
    first = editor.write_source('demo.yaml', CONTENT, None)
    def fail(*args):
        raise OSError('simulated replace error')
    monkeypatch.setattr(editor.os, 'replace', fail)
    with pytest.raises(OSError):
        editor.write_source('demo.yaml', CONTENT + '\n', first['revision'])
    assert (root / 'demo.yaml').read_text('utf-8') == CONTENT
    assert list(root.glob('*.tmp')) == []


@pytest.mark.parametrize('state,pending', [('running', False), ('paused', False), ('failed', True)])
def test_active_source_cannot_be_replaced_but_other_file_can(setup, state, pending):
    _, app = setup
    original = editor.write_source('demo.yaml', CONTENT, None)
    api._engines['demo.yaml'] = SimpleNamespace(state=SimpleNamespace(value=state), cleanup_pending=pending)
    result = asyncio.run(request(app, 'PUT', '/demo.yaml/source', json={'content': CONTENT, 'revision': original['revision']}))
    assert result.status_code == 409
    assert asyncio.run(request(app, 'PUT', '/other.yaml/source', json={'content': CONTENT})).status_code == 200


def test_validation_locations_and_bad_documents(setup):
    _, app = setup
    invalids = ['steps: [', 'steps: []\nsteps: []', 'steps: []\n---\nsteps: []', 'steps: [{id: a, type: imaginary}]', 'metadata: 5\nsteps: []']
    for content in invalids:
        result = asyncio.run(request(app, 'POST', '/validate', json={'content': content})).json()
        assert result['valid'] is False
        assert result['errors'][0]['line'] >= 1
    invalid = 'steps:\n  - id: start\n    type: pump.start\n    params: {device_id: pump1, channel: 1, mode: TIME_SPEED}\n'
    result = editor.validate_source(invalid)
    assert not result['valid']
    assert result['errors'][0]['step_id'] == 'start'
    assert result['errors'][0]['line'] == 4
    assert not app.state.device_manager.mock_calls


def test_invalid_save_never_creates_file(setup):
    root, app = setup
    result = asyncio.run(request(app, 'PUT', '/bad.yaml/source', json={'content': 'steps: ['}))
    assert result.status_code == 422
    assert not (root / 'bad.yaml').exists()


def test_authoring_unknown_syringe_warns_without_relaxing_run_or_timeout_checks():
    content = 'steps:\n- id: offline\n  type: syringe_pump.stop\n  params: {device_id: unregistered_syringe}\n'
    result = editor.validate_source(content)
    assert result['valid']
    assert result['warnings'][0]['path'] == ['steps', 0, 'params', 'device_id']
    with pytest.raises(ValueError, match='configured syringe_pump'):
        parser.parse_experiment_content(content)
    invalid = content + '  wait: {type: syringe_pump_complete, device_id: unregistered_syringe, timeout: 0}\n'
    assert not editor.validate_source(invalid)['valid']


def test_save_and_start_share_lock(setup, monkeypatch):
    _, app = setup
    original = editor.write_source('demo.yaml', CONTENT, None)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def fake_start(filename, body, req):
            entered.set()
            await release.wait()
            api._engines[filename] = SimpleNamespace(state=SimpleNamespace(value='running'), cleanup_pending=False)
            return {'success': True}
        monkeypatch.setattr(api, '_start_experiment_locked', fake_start)
        start = asyncio.create_task(request(app, 'POST', '/demo.yaml/start', json={}))
        await entered.wait()
        save = asyncio.create_task(request(app, 'PUT', '/demo.yaml/source', json={'content': CONTENT, 'revision': original['revision']}))
        await asyncio.sleep(0)
        assert not save.done()
        release.set()
        assert (await start).status_code == 200
        assert (await save).status_code == 409
    asyncio.run(scenario())


def test_concurrent_creates_have_single_winner(setup):
    _, app = setup
    async def scenario():
        results = await asyncio.gather(*(request(app, 'PUT', '/demo.yaml/source', json={'content': CONTENT}) for _ in range(2)))
        assert sorted(r.status_code for r in results) == [200, 409]
    asyncio.run(scenario())


def test_all_existing_samples_parse_equally_from_file_and_memory(monkeypatch):
    for path in Path('experiments').glob('*.yaml'):
        content = path.read_text('utf-8')
        try:
            direct = parser.parse_experiment(str(path))
        except (ValueError, yaml.YAMLError):
            continue  # Repository can contain drafts; they must remain readable as source.
        assert direct == parser.parse_experiment_content(content, path.name)
