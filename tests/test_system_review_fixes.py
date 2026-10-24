"""Cross-layer review regressions: fake devices and isolated files only."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from fastapi import HTTPException

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.web.api import experiments


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No real serial')))
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)


def test_emergency_dispatches_before_manual_lock_and_cancels_queued_start(monkeypatch):
    from src.web.api import devices
    monkeypatch.setattr('src.web.api.microwave_program.require_recovered', lambda: None)

    async def scenario():
        loop = asyncio.get_running_loop()
        dispatched = asyncio.Event()
        dm = SimpleNamespace(emergency_stop_all=lambda: loop.call_soon_threadsafe(dispatched.set) or True)
        request = SimpleNamespace(method='POST', scope={}, url=SimpleNamespace(path='/api/heater/h/start'),
                                  app=SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        dependency = devices.protect_guided_devices(request)
        await anext(dependency)
        queued = asyncio.create_task(experiments.start_experiment('queued.yaml', experiments.StartExperimentRequest(), request))
        await asyncio.sleep(0)
        emergency = asyncio.create_task(devices.emergency_stop(request))
        try:
            await asyncio.wait_for(dispatched.wait(), 2)
            assert not emergency.done()  # Still serializes final registration/cleanup.
        finally:
            await dependency.aclose()
        with pytest.raises(HTTPException) as error:
            await queued
        assert error.value.status_code == 409
        assert (await emergency)['success'] is True
        assert experiments._stopping == 0
    asyncio.run(scenario())


def test_cleanup_pending_is_reported_and_retry_clears_it(monkeypatch):
    from src.web.api.ws import manager
    broadcast = AsyncMock()
    monkeypatch.setattr(manager, 'broadcast', broadcast)

    async def scenario():
        dm = SimpleNamespace(start_pump_channel=Mock(return_value=True),
                             stop_pump_channel=Mock(side_effect=[False, True]))
        engine = ExperimentEngine(StepExecutor(dm), Mock())
        engine.load_steps([ExperimentStep(id='pump', type=ActionType.PUMP_START,
                                         params={'device_id': 'pump1', 'channel': 1})])
        experiments._engines['review.yaml'] = engine
        await engine.start()
        await engine.wait_finished()
        assert (await experiments.get_progress('review.yaml'))['cleanup_pending'] is True
        await experiments._broadcast_progress('review.yaml', engine.progress)
        assert broadcast.call_args.args[0]['cleanup_pending'] is True
        assert (await experiments.stop_experiment('review.yaml'))['success'] is True
        assert (await experiments.get_progress('review.yaml'))['cleanup_pending'] is False
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['guided', 'microwave'])
def test_emergency_cancels_start_still_in_preflight(monkeypatch, kind):
    from src.web.api import devices, guided, microwave_program
    from test_guided import spec as guided_spec
    from test_microwave_program import spec as microwave_spec

    async def scenario():
        entered, release, dispatched = asyncio.Event(), asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        async def preflight(*args, **kwargs):
            entered.set()
            await release.wait()
        dm = SimpleNamespace(emergency_stop_all=lambda: loop.call_soon_threadsafe(dispatched.set) or True)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        runner = SimpleNamespace(dm=dm, batch_id='review', start=AsyncMock())
        for module in (guided, microwave_program):
            monkeypatch.setattr(module, '_source_lock', experiments._source_lock)
            monkeypatch.setattr(module, '_engines', experiments._engines)
            monkeypatch.setattr(module, 'records', lambda: [])
        monkeypatch.setattr(microwave_program, 'require_recovered', lambda: None)
        if kind == 'guided':
            monkeypatch.setattr(guided.guided, 'GuidedBatch', Mock(return_value=runner))
            monkeypatch.setattr(guided.guided, 'preflight', preflight)
            starting = asyncio.create_task(guided.start(guided_spec(), request))
        else:
            monkeypatch.setattr(microwave_program.program, 'MicrowaveProgramRun', Mock(return_value=runner))
            monkeypatch.setattr(microwave_program.program, 'preflight', preflight)
            starting = asyncio.create_task(microwave_program.start('microwave1', microwave_spec(), request))
        await entered.wait()
        stopping = asyncio.create_task(devices.emergency_stop(request))
        await asyncio.wait_for(dispatched.wait(), 2)
        release.set()
        with pytest.raises(HTTPException) as error:
            await starting
        assert error.value.status_code == 409
        await stopping
        runner.start.assert_not_awaited()
        assert not experiments._engines
    asyncio.run(scenario())


def test_lifespan_finishes_runs_before_device_cleanup(monkeypatch):
    from src.web import app as web
    async def background(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(web, 'setup_logging', Mock())
    monkeypatch.setattr(web, 'data_push_loop', background)
    monkeypatch.setattr(web, 'syringe_supervisor', background)
    monkeypatch.setattr(web, 'turntable_supervisor', background)

    async def scenario():
        engine = ExperimentEngine(StepExecutor(SimpleNamespace()), Mock())
        engine.load_steps([ExperimentStep(id='wait', type=ActionType.WAIT,
                                         wait=WaitCondition(type=WaitType.DURATION, seconds=600))])
        # All registry runner types share this contract, including failed stops.
        guided = SimpleNamespace(request_stop=Mock(), stop=AsyncMock(return_value=False))
        microwave = SimpleNamespace(request_stop=Mock(), stop=AsyncMock(side_effect=OSError('stop failed')))
        experiments._engines.update(ordinary=engine, guided=guided, microwave=microwave)
        def cleanup():
            assert engine._task.done() and engine.state.value == 'stopped'
            engine.exp_logger.finish_run.assert_called_once_with('stopped')
            guided.stop.assert_awaited_once()
            microwave.stop.assert_awaited_once()
            return True
        dm = SimpleNamespace(cleanup=Mock(side_effect=cleanup))
        monkeypatch.setattr(web, 'create_device_manager', lambda: dm)
        async with web.lifespan(SimpleNamespace(state=SimpleNamespace())):
            await engine.start()
            await asyncio.sleep(0)
        dm.cleanup.assert_called_once()
    asyncio.run(scenario())


def test_invalid_later_step_is_rejected_before_registration(tmp_path, monkeypatch):
    from src.experiment import parser
    monkeypatch.setattr(parser, 'EXPERIMENTS_DIR', tmp_path)
    monkeypatch.setattr('src.web.api.guided.records', lambda: [])
    monkeypatch.setattr('src.web.api.microwave_program.require_recovered', lambda: None)
    (tmp_path / 'invalid.yaml').write_text('''steps:
  - id: heat
    type: heater.start
    params: {device_id: heater1}
  - id: broken
    type: heater.set_temperature
    params: {device_id: heater1}
''', encoding='utf-8')
    dm = Mock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
    with pytest.raises(HTTPException) as error:
        asyncio.run(experiments.start_experiment('invalid.yaml', experiments.StartExperimentRequest(), request))
    assert error.value.status_code == 400
    assert experiments._engines == {}
    assert dm.mock_calls == [call.require_turntables_idle()]  # Memory guard only; no hardware actions.


@pytest.mark.parametrize('interruption', [OSError, KeyboardInterrupt])
def test_characterization_pair_recovers_and_retry_is_single(tmp_path, monkeypatch, interruption):
    from src.campaigns import store as module
    monkeypatch.setattr(module, 'CAMPAIGNS_DIR', tmp_path)
    for name in ('CAMPAIGNS', 'TRIALS', 'RECOMMENDATIONS', 'CHARACTERIZATIONS'):
        monkeypatch.setattr(module, name + '_JSON', tmp_path / (name.lower() + '.json'))
    store = module.CampaignStore()
    trial = store.create_trials(campaign_id='c', recommendation_id='', parameters_batch=[{}])[0]
    kwargs = dict(campaign_id='c', trial_id=trial['trial_id'], characterization_type='PL', metrics={'score': 1})
    write = module._write_json
    failed = False
    def interrupted(path, value):
        nonlocal failed
        if path == module.TRIALS_JSON and not failed:
            failed = True
            raise interruption('second file failure')
        write(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_write_json', interrupted)
        with pytest.raises(interruption):
            store.create_characterization(**kwargs)
    assert store.list_characterizations('c') == []
    assert store.list_trials('c') == [trial]
    store.create_characterization(**kwargs)
    assert len(store.list_characterizations('c')) == 1
    assert store.get_trial('c', trial['trial_id'])['status'] == 'characterized'


@pytest.mark.parametrize('bulk', [False, True])
def test_delete_failure_keeps_retry_anchor_and_returns_503(tmp_path, monkeypatch, bulk):
    from src.experiment import experiment_logger as logs
    from src.science import sample_record as samples
    monkeypatch.setattr(logs, 'LOGS_DIR', tmp_path)
    monkeypatch.setattr(samples, 'SAMPLES_DIR', tmp_path)
    monkeypatch.setattr(samples, 'SAMPLES_CSV', tmp_path / 'samples.csv')
    rid = '20261012_000000_abcdef'
    path = tmp_path / (rid + '_review.json')
    path.write_text(json.dumps({'run_id': rid}), encoding='utf-8')
    assert samples.write_sample_record(rid, {'sample_id': 'review'})
    call = experiments.delete_all_history_runs if bulk else lambda: experiments.delete_history_run(rid)
    with monkeypatch.context() as patch:
        patch.setattr(samples.os, 'replace', Mock(side_effect=PermissionError('locked CSV')))
        with pytest.raises(HTTPException) as error:
            asyncio.run(call())
        assert error.value.status_code == 503
    assert path.exists() and rid in samples.SAMPLES_CSV.read_text(encoding='utf-8')
    assert asyncio.run(call())['success'] is True
    assert not path.exists() and rid not in samples.SAMPLES_CSV.read_text(encoding='utf-8')


def test_delete_repairs_orphan_sample_without_log(tmp_path, monkeypatch):
    from src.experiment import experiment_logger as logs
    from src.science import sample_record as samples
    monkeypatch.setattr(logs, 'LOGS_DIR', tmp_path / 'missing_logs')
    monkeypatch.setattr(samples, 'SAMPLES_DIR', tmp_path)
    monkeypatch.setattr(samples, 'SAMPLES_CSV', tmp_path / 'samples.csv')
    rid = '20261012_000000_abcdef'
    assert samples.write_sample_record(rid, {'sample_id': 'review'})
    assert logs.delete_experiment_run(rid)
    assert rid not in samples.SAMPLES_CSV.read_text(encoding='utf-8')
