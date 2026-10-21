"""Terminal storage retries preserve execution history and never replay hardware."""
import asyncio
import copy
import csv
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.experiment import experiment_logger as logging_module
from src.experiment.experiment_logger import ExperimentLogger
from src.science import sample_record


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No physical serial access')))
    monkeypatch.setattr(logging_module, 'LOGS_DIR', tmp_path / 'logs')
    monkeypatch.setattr(sample_record, 'SAMPLES_DIR', tmp_path / 'samples')
    monkeypatch.setattr(sample_record, 'SAMPLES_CSV', tmp_path / 'samples' / 'samples.csv')


def started_logger(save_log=True):
    logger = ExperimentLogger(save_log=save_log)
    logger.start_run('重试实验', 'retry.yaml', 1, {'operator': 'test'})
    logger.start_step(0, 'log', 'log', {'message': 'completed'})
    logger.finish_step(0, True)
    return logger


def execution_facts(run):
    snapshot = copy.deepcopy(run.to_dict())
    for key in ('persistence_status', 'persistence_errors', 'log_saved', 'sample_record_saved'):
        snapshot.pop(key)
    return snapshot


def rows():
    with sample_record.SAMPLES_CSV.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize('status', ['completed', 'failed', 'stopped'])
def test_sample_retry_preserves_terminal_execution_facts_and_repairs_saved_log(monkeypatch, status):
    logger = started_logger()
    callback = Mock()
    logger.on_log(callback)
    writer = logging_module.write_sample_record
    monkeypatch.setattr(logging_module, 'write_sample_record', Mock(side_effect=PermissionError('CSV locked')))
    assert logger.finish_run(status) is False
    run = logger.active_run
    frozen = execution_facts(run)
    assert run.log_saved is True and run.sample_record_saved is False
    monkeypatch.setattr(logging_module, 'write_sample_record', writer)
    assert logger.retry_persistence() is True
    assert execution_facts(run) == frozen
    assert run.persistence_errors == []
    assert run.persistence_status == 'ok' and run.sample_record_saved is True
    stored = json.loads(logger._log_filepath(run).read_text(encoding='utf-8'))
    assert stored == run.to_dict()
    assert len(rows()) == 1 and rows()[0]['finished_at'] == run.finished_at
    assert rows()[0]['status'] == status
    callback.assert_called_once()  # The original finish event is not emitted again.


def test_log_retry_does_not_rewrite_successful_sample_or_change_history(monkeypatch):
    logger = started_logger()
    save_log = logger._save_to_file
    writer = Mock(wraps=logging_module.write_sample_record)
    monkeypatch.setattr(logging_module, 'write_sample_record', writer)
    monkeypatch.setattr(logger, '_save_to_file', Mock(return_value=False))
    assert logger.finish_run('stopped') is False
    run = logger.active_run
    frozen = execution_facts(run)
    original_csv = sample_record.SAMPLES_CSV.read_bytes()
    assert run.sample_record_saved is True and run.log_saved is False
    monkeypatch.setattr(logger, '_save_to_file', save_log)
    assert logger.retry_persistence() is True
    assert execution_facts(run) == frozen
    assert sample_record.SAMPLES_CSV.read_bytes() == original_csv
    writer.assert_called_once()
    assert json.loads(logger._log_filepath(run).read_text(encoding='utf-8')) == run.to_dict()
    assert logger.retry_persistence() is True
    writer.assert_called_once()


def test_repeated_sample_failure_remains_error_then_recovers_without_log_enabled(monkeypatch):
    logger = started_logger(save_log=False)
    write_sample = logging_module.write_sample_record
    writer = Mock(side_effect=[False, False, True])

    def write(*args, **kwargs):
        return write_sample(*args, **kwargs) if writer() else False

    monkeypatch.setattr(logging_module, 'write_sample_record', write)
    assert logger.finish_run('completed') is False
    frozen = execution_facts(logger.active_run)
    assert logger.retry_persistence() is False
    assert logger.active_run.persistence_status == 'error'
    assert logger.active_run.persistence_errors == ['sample_record_not_saved']
    assert logger.retry_persistence() is True
    assert logger.active_run.log_saved is None
    assert logger.active_run.persistence_errors == []
    assert execution_facts(logger.active_run) == frozen
    assert len(rows()) == 1
    assert writer.call_count == 3


def test_repaired_sample_is_not_repeated_when_log_retry_still_fails(monkeypatch):
    logger = started_logger()
    writer = logging_module.write_sample_record
    save_log = logger._save_to_file
    monkeypatch.setattr(logging_module, 'write_sample_record', Mock(return_value=False))
    monkeypatch.setattr(logger, '_save_to_file', Mock(return_value=False))
    assert logger.finish_run('failed') is False
    repaired_writer = Mock(wraps=writer)
    monkeypatch.setattr(logging_module, 'write_sample_record', repaired_writer)
    assert logger.retry_persistence() is False
    assert logger.active_run.sample_record_saved is True
    assert logger.active_run.persistence_status == 'error'
    assert logger.active_run.persistence_errors == ['experiment_log_not_saved']
    assert logger.retry_persistence() is False
    repaired_writer.assert_called_once()
    monkeypatch.setattr(logger, '_save_to_file', save_log)
    assert logger.retry_persistence() is True
    repaired_writer.assert_called_once()
    assert len(rows()) == 1


@pytest.mark.parametrize('status,finished_at', [('running', None), ('paused', None),
    ('running', '2026-10-20T12:00:00'), ('completed', None)])
def test_retry_requires_a_finished_terminal_run(monkeypatch, status, finished_at):
    logger = started_logger()
    logger.active_run.status = status
    logger.active_run.finished_at = finished_at
    writer = Mock(side_effect=AssertionError('must not save an active run'))
    monkeypatch.setattr(logger, '_write_sample_record', writer)
    before = logger.active_run.to_dict()
    assert logger.retry_persistence() is False
    assert logger.active_run.to_dict() == before
    writer.assert_not_called()


def test_retry_without_run_is_not_success():
    assert ExperimentLogger(save_log=False).retry_persistence() is False


@pytest.mark.parametrize('phase', ['priming', 'group'])
def test_guided_exit_retries_failed_run_storage_without_replaying_steps(tmp_path, monkeypatch, phase):
    from test_guided import FakeManager, spec, fast_timed_flow, fast_microwave_stability
    from src.desktop.lifecycle import DesktopShutdown
    from src.experiment import guided
    from src.web.api import experiments, guided as api

    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr(guided.StepExecutor, '_run_timed_flow', fast_timed_flow)
    monkeypatch.setattr(guided.StepExecutor, '_wait_condition', fast_microwave_stability)
    monkeypatch.setattr(guided.StepExecutor, '_wait_heater_pair_stable', AsyncMock(return_value=True))
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(api, '_batches', {})

    async def scenario():
        dm = FakeManager()
        dm._begin_global_stop = Mock()
        dm.cleanup = Mock(return_value=True)
        batch = guided.GuidedBatch(dm, spec())
        experiments._engines[batch.batch_id] = batch
        api._batches[batch.batch_id] = batch
        write_sample = logging_module.write_sample_record

        def fail_selected_sample(*args, **kwargs):
            if phase == 'group' and kwargs['metadata'].get('run_kind') == 'priming':
                return write_sample(*args, **kwargs)
            return False

        monkeypatch.setattr(logging_module, 'write_sample_record', fail_selected_sample)
        await batch.start(prime_only=phase == 'priming')
        await batch.task
        run = batch.exp_logger.active_run
        assert batch.state.value == 'failed' and run.persistence_status == 'error'
        frozen = execution_facts(run)
        recovery_required = batch.record['recovery_required']
        hardware_steps = [call for call in dm.calls if call[0] not in {
            'heater_stop', 'pump_stop', 'syringe_stop', 'microwave_stop'}]
        coordinator = DesktopShutdown(SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        assert (await coordinator.shutdown())['success'] is False
        monkeypatch.setattr(logging_module, 'write_sample_record', write_sample)
        result = await coordinator.shutdown()
        assert result['success'], result
        assert execution_facts(run) == frozen
        assert batch.state.value == 'failed'
        assert batch.record['recovery_required'] is recovery_required
        assert [call for call in dm.calls if call[0] not in {
            'heater_stop', 'pump_stop', 'syringe_stop', 'microwave_stop'}] == hardware_steps
        assert len(rows()) == (1 if phase == 'priming' else 2)
        checkpoint = json.loads((guided.BATCH_DIR / (batch.batch_id + '.json')).read_text(encoding='utf-8'))
        entry = checkpoint['priming'] if phase == 'priming' else checkpoint['groups'][0]
        assert entry['persistence_status'] == 'ok'
        assert entry['run_id'] == run.run_id
        if phase == 'group':
            assert entry['state'] == 'completed' and entry['persistence_errors'] == []
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['ordinary', 'microwave'])
def test_real_runner_exit_retries_persistence_without_replaying_execution(tmp_path, monkeypatch, kind):
    from src.desktop.lifecycle import DesktopShutdown
    from src.experiment import yaml_recovery, microwave_program
    from src.experiment.actions import ActionType, ExperimentStep
    from src.web.api import experiments

    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(yaml_recovery, 'RECOVERY_DIR', tmp_path / 'recovery')
    monkeypatch.setattr(microwave_program, 'PROGRAM_DIR', tmp_path / 'microwave')

    async def scenario():
        if kind == 'ordinary':
            dm = SimpleNamespace(_begin_global_stop=Mock(), cleanup=Mock(return_value=True))
            executor = Mock()
            executor.activity_snapshot = None
            executor.last_device_result = None
            executor.execute = AsyncMock(return_value=True)
            executor.stop_active_devices = AsyncMock(return_value=True)
            runner = yaml_recovery.PersistentExperimentEngine(executor, exp_logger=ExperimentLogger())
            runner.record = yaml_recovery.new_record('retry.yaml', 'source')
            runner.load_steps([ExperimentStep(id='once', type=ActionType.LOG,
                params={'message': 'execute once'})], filename='retry.yaml')
        else:
            from test_guided import fast_microwave_stability
            from test_microwave_program import Manager, spec
            monkeypatch.setattr(microwave_program.StepExecutor, '_wait_condition', fast_microwave_stability)
            dm = Manager()
            dm._begin_global_stop = Mock()
            dm.cleanup = Mock(return_value=True)
            runner = microwave_program.MicrowaveProgramRun(dm, 'microwave1', spec())
        experiments._engines['retry-runner'] = runner
        write_sample = logging_module.write_sample_record
        monkeypatch.setattr(logging_module, 'write_sample_record', Mock(return_value=False))
        await runner.start()
        if kind == 'ordinary':
            await runner.wait_finished()
        else:
            await runner.task
        run = runner.exp_logger.active_run
        assert run.persistence_status == 'error'
        frozen = execution_facts(run)
        state = runner.state
        recovery_required = runner.record['recovery_required']
        if kind == 'ordinary':
            executor.execute.assert_awaited_once()
        else:
            calls = list(dm.calls)
        coordinator = DesktopShutdown(SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        assert (await coordinator.shutdown())['success'] is False
        assert run.persistence_status == 'error'
        monkeypatch.setattr(logging_module, 'write_sample_record', write_sample)
        result = await coordinator.shutdown()
        assert result['success'], result
        assert execution_facts(run) == frozen
        assert runner.state == state
        assert runner.record['recovery_required'] is recovery_required
        assert run.persistence_status == 'ok'
        assert len(rows()) == 1
        if kind == 'ordinary':
            executor.execute.assert_awaited_once()
        else:
            assert dm.calls == calls
    asyncio.run(scenario())


def test_guided_checkpoint_save_failure_keeps_exit_failed_until_explicit_retry(tmp_path, monkeypatch):
    from test_guided import FakeManager, spec
    from src.desktop.lifecycle import DesktopShutdown
    from src.experiment import guided
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.web.api import experiments

    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)

    async def scenario():
        dm = FakeManager()
        dm._begin_global_stop = Mock()
        dm.cleanup = Mock(return_value=True)
        batch = guided.GuidedBatch(dm, spec())
        logger = started_logger()
        write_sample = logging_module.write_sample_record
        monkeypatch.setattr(logging_module, 'write_sample_record', Mock(return_value=False))
        assert logger.finish_run('failed') is False
        batch.engine = ExperimentEngine(batch.executor, exp_logger=logger)
        batch.engine._state = ExperimentState.FAILED
        batch.engine._cleanup_result = True
        batch.engine._stop_result = True
        batch.state = ExperimentState.FAILED
        batch.record.update(phase='experiments', recovery_required=True,
            groups=[{'run_id': logger.active_run.run_id, 'persistence_status': 'error',
                     'persistence_errors': ['sample_record_not_saved'], 'state': 'failed'}])
        batch.save()
        experiments._engines[batch.batch_id] = batch
        frozen = execution_facts(logger.active_run)
        coordinator = DesktopShutdown(SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        assert not (await coordinator.shutdown())['success']
        monkeypatch.setattr(logging_module, 'write_sample_record', write_sample)
        save_record = guided.atomic_record
        monkeypatch.setattr(guided, 'atomic_record', Mock(side_effect=PermissionError('checkpoint locked')))
        result = await coordinator.shutdown()
        assert result['success'] is False and result['errors']
        assert logger.active_run.persistence_status == 'ok'
        assert batch.record['persistence_status'] == 'error'
        assert coordinator.exiting and not coordinator.succeeded
        assert execution_facts(logger.active_run) == frozen
        monkeypatch.setattr(guided, 'atomic_record', save_record)
        assert (await coordinator.shutdown())['success'] is True
        assert batch.state == ExperimentState.FAILED and batch.record['recovery_required'] is True
        checkpoint = json.loads((guided.BATCH_DIR / (batch.batch_id + '.json')).read_text(encoding='utf-8'))
        assert checkpoint['groups'][0]['persistence_status'] == 'ok'
        assert checkpoint['groups'][0]['state'] == 'failed'
        assert checkpoint['recovery_required'] is True
        assert execution_facts(logger.active_run) == frozen
        assert len(rows()) == 1
    asyncio.run(scenario())
