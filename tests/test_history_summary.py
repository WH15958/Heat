import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.experiment import experiment_logger as logs, guided
from src.web.api import guided as api


def write_run(directory, run_id, batch_id):
    path = directory / (run_id + '_test.json')
    path.write_text(json.dumps(dict(run_id=run_id, experiment_name='test', status='completed',
        metadata={'batch_id': batch_id}, steps=[{'data': 'x' * 10000}],
        sensor_data={'large': list(range(1000))})), encoding='utf-8')
    return path


def test_summary_cache_filter_and_invalidation(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, 'LOGS_DIR', tmp_path)
    path = write_run(tmp_path, '20261112_100000_aaaaaa', 'one')
    write_run(tmp_path, '20261112_100001_bbbbbb', 'two')
    result = logs.list_experiment_runs(summary=True, batch_id='one')
    assert len(result) == 1 and 'steps' not in result[0] and 'sensor_data' not in result[0]
    original = Path.read_text
    def guarded(self, *args, **kwargs):
        assert self.parent != tmp_path, 'cached list must not reread full logs'
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    assert logs.list_experiment_runs(summary=True, batch_id='one') == result
    monkeypatch.setattr(Path, 'read_text', original)
    data = json.loads(path.read_text(encoding='utf-8'))
    data['status'] = 'failed'
    path.write_text(json.dumps(data), encoding='utf-8')
    assert logs.list_experiment_runs(summary=True, batch_id='one')[0]['status'] == 'failed'


@pytest.fixture
def batch_files(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, 'LOGS_DIR', tmp_path / 'logs')
    logs.LOGS_DIR.mkdir()
    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path / 'batches')
    guided.BATCH_DIR.mkdir()
    monkeypatch.setattr(api, '_batches', {})
    batch_id = 'guided_' + 'a' * 32
    ids = ['20261112_100000_aaaaaa', '20261112_100001_bbbbbb']
    for run_id in ids:
        write_run(logs.LOGS_DIR, run_id, batch_id)
    record = dict(batch_id=batch_id, state='completed', created_at='2026-11-12',
                  groups=[dict(run_id=ids[1])], priming=dict(run_id=ids[0]))
    path = guided.BATCH_DIR / (batch_id + '.json')
    path.write_text(json.dumps(record), encoding='utf-8')
    for folder in ('charts', 'plans'):
        (guided.BATCH_DIR / folder).mkdir()
        (guided.BATCH_DIR / folder / path.name).write_text('{}', encoding='utf-8')
    return batch_id, path, record


def test_delete_batch_removes_both_histories(batch_files):
    batch_id, path, _ = batch_files
    asyncio.run(api.delete_batch(batch_id))
    assert not logs.list_experiment_runs()
    assert not api.records()
    assert not list(guided.BATCH_DIR.rglob('*.json'))


def test_delete_failure_keeps_retry_anchor(batch_files, monkeypatch):
    batch_id, path, _ = batch_files
    original = logs.remove_sample_records_for_run_ids
    def fail(ids):
        raise OSError('locked CSV')
    monkeypatch.setattr(logs, 'remove_sample_records_for_run_ids', fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.delete_batch(batch_id))
    assert error.value.status_code == 503 and path.exists()
    assert len(logs.list_experiment_runs()) == 2
    monkeypatch.setattr(logs, 'remove_sample_records_for_run_ids', original)
    asyncio.run(api.delete_batch(batch_id))
    assert not path.exists()


def test_recovery_batch_cannot_be_deleted(batch_files):
    batch_id, path, record = batch_files
    record['cleanup_required'] = True
    path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.delete_batch(batch_id))
    assert error.value.status_code == 409 and path.exists()


def test_clear_all_also_removes_batch_archives(batch_files, monkeypatch):
    from src.web.api import experiments
    monkeypatch.setattr(experiments, '_engines', {})
    result = asyncio.run(experiments.delete_all_history_runs())
    assert result['deleted_count'] == 2
    assert not api.records() and not logs.list_experiment_runs()


def test_api_batch_filter_includes_legacy_linked_runs(batch_files):
    from src.web.api import experiments
    batch_id, _, _ = batch_files
    path = next(logs.LOGS_DIR.glob('*.json'))
    data = json.loads(path.read_text(encoding='utf-8'))
    data['metadata'] = {}
    path.write_text(json.dumps(data), encoding='utf-8')
    result = asyncio.run(experiments.get_history_runs(batch_id))
    assert len(result) == 2 and all('sensor_data' not in run for run in result)
