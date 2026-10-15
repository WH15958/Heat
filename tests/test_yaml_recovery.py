"""Persistent ordinary-YAML ownership, with no physical serial access."""
import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from src.experiment import parser
from src.web.api import experiments as api


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('Physical serial forbidden')))


def engine(monkeypatch, cleanup=True):
    from src.experiment import yaml_recovery as recovery
    from src.experiment.experiment_logger import ExperimentLogger
    from src.experiment.actions import ExperimentStep, ActionType
    executor = Mock()
    executor.activity_snapshot = None
    executor.last_device_result = None
    executor.execute = AsyncMock(return_value=True)
    executor.stop_active_devices = AsyncMock(return_value=cleanup)
    logger = ExperimentLogger(save_log=False)
    monkeypatch.setattr(logger, '_write_sample_record', lambda status: True)
    run = recovery.PersistentExperimentEngine(executor, exp_logger=logger)
    run.record = recovery.new_record('test.yaml', 'source')
    run.load_steps([ExperimentStep(id='one', type=ActionType.LOG, params={'message': 'test'})], filename='test.yaml')
    return run, executor


def test_intent_precedes_action_and_clean_finish_releases_record(monkeypatch):
    from src.experiment import yaml_recovery as recovery
    run, executor = engine(monkeypatch)
    async def execute(step):
        stored = recovery.records({})[0]
        assert stored['recovery_required'] is True
        assert stored['run_id'] == run.exp_logger.active_run.run_id
        assert stored['sample_id'] == run.exp_logger.active_run.metadata['sample_id']
        return True
    executor.execute.side_effect = execute
    async def scenario():
        await run.start()
        await run.wait_finished()
    asyncio.run(scenario())
    assert recovery.records({})[0]['cleanup_required'] is False
    assert recovery.records({})[0]['recovery_required'] is False


@pytest.mark.parametrize('failure', ['intent', 'checkpoint', 'final', 'stop', 'log'])
def test_failures_keep_recovery_lock_and_do_not_report_clean_completion(monkeypatch, failure):
    from src.experiment import yaml_recovery as recovery
    run, executor = engine(monkeypatch, cleanup=failure != 'stop')
    write = recovery.write_record
    writes = []
    def fail(record):
        writes.append(dict(record))
        if failure == 'intent' or (failure == 'checkpoint' and record['run_id']) or (
                failure == 'final' and not record['cleanup_required']):
            raise OSError('disk unavailable')
        write(record)
    monkeypatch.setattr(recovery, 'write_record', fail)
    if failure == 'log':
        monkeypatch.setattr(run.exp_logger, '_write_sample_record', lambda status: False)
    async def scenario():
        if failure == 'intent':
            with pytest.raises(OSError):
                await run.start()
        else:
            await run.start()
            await run.wait_finished()
    asyncio.run(scenario())
    assert run.cleanup_pending
    assert recovery.records({'test.yaml': run})[0]['recovery_required']
    if failure in {'intent', 'checkpoint'}:
        executor.execute.assert_not_called()
    if failure != 'intent':
        assert recovery.records({})[0]['recovery_required']


def test_pending_and_acknowledge_never_replay_or_clear_on_failed_write(tmp_path, monkeypatch):
    from src.experiment import yaml_recovery as recovery
    record = recovery.new_record('deleted.yaml', 'old source')
    recovery.write_record(record)
    monkeypatch.setattr(api, '_engines', {})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    app = FastAPI()
    app.include_router(api.router, prefix='/api')
    app.state.device_manager = Mock()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/api/experiments/recovery/' + record['recovery_id'] + '/acknowledge'
            assert (await client.get('/api/experiments/recovery/pending')).json()[0]['state'] == 'interrupted'
            assert (await client.post(url, json={'devices_stopped_confirmed': False})).status_code == 409
            assert (await client.post(url, json={'devices_stopped_confirmed': 'yes'})).status_code == 422
            with monkeypatch.context() as patch:
                patch.setattr(recovery, 'write_record', Mock(side_effect=OSError('readonly')))
                assert (await client.post(url, json={'devices_stopped_confirmed': True})).status_code == 503
            assert (await client.get('/api/experiments/recovery/pending')).json()
            assert (await client.post(url, json={'devices_stopped_confirmed': True})).json()['success']
            assert (await client.get('/api/experiments/recovery/pending')).json() == []
    asyncio.run(scenario())
    assert not app.state.device_manager.mock_calls


@pytest.mark.parametrize('contents', ['{', '{}', '[]'])
def test_corrupt_storage_fails_closed(monkeypatch, contents):
    from src.experiment import yaml_recovery as recovery
    recovery.RECOVERY_DIR.mkdir()
    (recovery.RECOVERY_DIR / ('yaml_' + '0' * 32 + '.json')).write_text(contents)
    monkeypatch.setattr(api, '_engines', {})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        api.require_yaml_recovered()
    assert caught.value.status_code == 503


def test_process_exit_leaves_durable_intent_and_restarted_service_sends_no_commands(monkeypatch):
    from src.experiment import yaml_recovery as recovery
    script = '''
import asyncio, os, sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from src.experiment import yaml_recovery as recovery
from src.experiment.actions import ExperimentStep, ActionType
from src.experiment.experiment_logger import ExperimentLogger
from src.science import sample_record
patch('serial.Serial.open', side_effect=AssertionError('No serial')).start()
recovery.RECOVERY_DIR = Path(sys.argv[1])
sample_record.SAMPLES_DIR = recovery.RECOVERY_DIR.parent / 'crash_samples'
sample_record.SAMPLES_CSV = sample_record.SAMPLES_DIR / 'samples.csv'
executor = Mock(activity_snapshot=None, last_device_result=None)
async def action(step):
    os._exit(23)
executor.execute = action
executor.stop_active_devices = AsyncMock(return_value=True)
logger = ExperimentLogger(save_log=False)
engine = recovery.PersistentExperimentEngine(executor, exp_logger=logger)
engine.record = recovery.new_record('crash.yaml', 'original source')
engine.load_steps([ExperimentStep(id='motion', type=ActionType.LOG, params={'message':'fake'})], filename='crash.yaml')
async def main():
    await engine.start()
    await engine.wait_finished()
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-c', script, str(recovery.RECOVERY_DIR)],
                            capture_output=True, timeout=15)
    assert result.returncode == 23, result.stderr.decode(errors='replace')
    monkeypatch.setattr(api, '_engines', {})
    records = asyncio.run(api.pending_recovery())
    assert len(records) == 1
    assert records[0]['state'] == 'interrupted'
    assert records[0]['run_id'] and records[0]['sample_id']
    from src.web.api.microwave_program import require_recovered
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        require_recovered()  # Used by ordinary, guided and hosted starts.
    assert caught.value.status_code == 409


def test_restart_lock_blocks_manual_writes_but_allows_reads_and_stop(monkeypatch):
    from src.experiment import yaml_recovery as recovery
    from src.web.api.devices import router
    recovery.write_record(recovery.new_record('old.yaml', 'source'))
    monkeypatch.setattr(api, '_engines', {})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    dm = Mock()
    dm.read_heater_data.return_value = {'pv': 25}
    dm.stop_heater.return_value = True
    app = FastAPI()
    app.state.device_manager = dm
    app.include_router(router, prefix='/api')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.post('/api/heater/heater1/set_temperature', json={'temperature': 50})).status_code == 409
            assert (await client.get('/api/heater/heater1/data')).status_code == 200
            assert (await client.post('/api/heater/heater1/stop')).json()['success']
    asyncio.run(scenario())
    dm.set_temperature.assert_not_called()


def test_live_failed_stop_cannot_be_acknowledged(monkeypatch):
    from fastapi import HTTPException
    run, executor = engine(monkeypatch, cleanup=False)
    monkeypatch.setattr(api, '_engines', {'test.yaml': run})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    async def scenario():
        await run.start()
        await run.wait_finished()
        with pytest.raises(HTTPException) as caught:
            await api.acknowledge_recovery(run.record['recovery_id'], api.YamlRecoveryConfirmation(devices_stopped_confirmed=True))
        assert caught.value.status_code == 409
        assert run.cleanup_pending
        executor.stop_active_devices.return_value = True
        assert (await api.acknowledge_recovery(run.record['recovery_id'], api.YamlRecoveryConfirmation(devices_stopped_confirmed=True)))['success']
    asyncio.run(scenario())
    assert not api._engines


def test_recovery_ack_write_failure_preserves_live_lock_after_successful_stop(monkeypatch):
    from src.experiment import yaml_recovery as recovery
    from fastapi import HTTPException
    run, executor = engine(monkeypatch, cleanup=False)
    monkeypatch.setattr(api, '_engines', {'test.yaml': run})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    async def scenario():
        await run.start()
        await run.wait_finished()
        executor.stop_active_devices.return_value = True
        with monkeypatch.context() as patch:
            patch.setattr(recovery, 'write_record', Mock(side_effect=OSError('disk full')))
            with pytest.raises(HTTPException) as caught:
                await api.acknowledge_recovery(run.record['recovery_id'], api.YamlRecoveryConfirmation(devices_stopped_confirmed=True))
            assert caught.value.status_code == 503
        assert run.cleanup_pending
        assert recovery.records({})[0]['recovery_required']
        assert (await api.acknowledge_recovery(run.record['recovery_id'], api.YamlRecoveryConfirmation(devices_stopped_confirmed=True)))['success']
    asyncio.run(scenario())
    assert not api._engines


def test_restart_must_block_an_unfinished_yaml_intent(tmp_path, monkeypatch):
    from src.experiment import yaml_recovery as recovery
    monkeypatch.setattr(recovery, 'RECOVERY_DIR', tmp_path / 'recovery')
    record = recovery.new_record('old.yaml', 'old source')
    recovery.write_record(record)
    monkeypatch.setattr(api, '_engines', {})
    monkeypatch.setattr(api, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path)
    (tmp_path / 'new.yaml').write_text('name: test\nsteps: []\n', encoding='utf-8')
    app = FastAPI()
    app.include_router(api.router, prefix='/api')
    app.state.device_manager = Mock()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/experiments/new.yaml/start', json={})
            assert response.status_code == 409
    asyncio.run(run())
    assert not app.state.device_manager.mock_calls


def test_persistent_pause_resume_keeps_ownership_without_replaying_action(monkeypatch):
    from src.experiment import yaml_recovery as recovery
    from src.experiment.actions import ExperimentStep, ActionType
    run, executor = engine(monkeypatch)
    run.load_steps([ExperimentStep(id=key, type=ActionType.LOG, params={'message': key})
                    for key in ('first', 'second')], filename='test.yaml')
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def execute(step):
            calls.append(step.id)
            if step.id == 'first':
                entered.set()
                await release.wait()
            return True
        executor.execute.side_effect = execute
        await run.start()
        await entered.wait()
        await run.pause()
        assert recovery.records({})[0]['recovery_required']
        release.set()
        await asyncio.sleep(0)
        assert calls == ['first']
        await run.resume()
        await run.wait_finished()
        assert calls == ['first', 'second']
        assert not recovery.records({})[0]['recovery_required']
    asyncio.run(scenario())
