"""Guided collection ordering and durable bottle records, with no physical I/O."""
import asyncio
import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.experiment import executor as execution, guided
from src.science import sample_record
from src.utils.config import ConfigManager
from src.web.api import experiments, guided as api
from test_guided import (FakeManager, spec, until, fast_timed_flow,
                         fast_microwave_stability, _real_timed_flow)


@pytest.fixture(autouse=True)
def rig(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('No real hardware')))
    monkeypatch.setattr(execution.StepExecutor, '_run_timed_flow', fast_timed_flow)
    monkeypatch.setattr(execution.StepExecutor, '_wait_condition', fast_microwave_stability)
    monkeypatch.setattr(execution.StepExecutor, '_wait_heater_pair_stable', AsyncMock(return_value=True))
    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(api, '_engines', experiments._engines)
    monkeypatch.setattr(api, '_batches', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())


def app_for(dm):
    app = FastAPI()
    app.state.device_manager = dm
    app.include_router(api.router, prefix='/api')
    return app


def test_home_before_consumption_then_collect_clean_move_and_final_home():
    class RecordingManager(FakeManager):
        def start_pump_channel(self, did, channel, *args):
            if channel == 4 and self.valve_energized is False:
                bottle = self.turntable('turntable1').summary()['current_bottle']
                self.calls.append(('collect_bottle', bottle))
            return super().start_pump_channel(did, channel, *args)

    async def run():
        dm = RecordingManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await batch.task
        assert batch.state.value == 'completed', batch.record.get('error')
        assert batch.record['preparation']['status'] == 'completed'
        assert batch.record['finalization']['status'] == 'completed'
        calls = dm.calls
        first_home = calls.index(('turntable_home', 1))
        first_init = calls.index(('initialize', 'syringe_pump1'))
        assert calls.index(('valve', True)) < first_home < first_init
        assert [c for c in calls if c[0] == 'collect_bottle'] == [('collect_bottle', 1), ('collect_bottle', 2)]
        assert [c for c in calls if c[0].startswith('turntable_')] == [
            ('turntable_home', 1), ('turntable_next', 2), ('turntable_home', 1)]
        next_bottle = calls.index(('turntable_next', 2))
        first_collect = calls.index(('collect_bottle', 1))
        first_clean = calls.index(('pump_start', 3), first_collect)
        assert first_collect < first_clean < next_bottle < calls.index(('collect_bottle', 2))
        assert calls[next_bottle - 1] == ('pump_stop', 4)
        second_feed = calls.index(('aspirate', 'syringe_pump1'), next_bottle)
        assert next_bottle < second_feed
        last_home = len(calls) - 1 - calls[::-1].index(('turntable_home', 1))
        assert calls.index(('heater_stop', 'heater1')) < last_home
        assert calls.index(('heater_stop', 'heater2')) < last_home
        assert ('valve', True) in calls[next_bottle:last_home]
        assert not batch.cleanup_pending
        assert dm.turntable('turntable1').summary()['current_bottle'] == 1
        assert [g['bottle_number'] for g in batch.record['groups']] == [1, 2]
        assert [g['collection_status'] for g in batch.record['groups']] == ['collected', 'collected']
        assert [r['metadata']['bottle_number'] for r in batch.recipes] == [1, 2]
        saved = api.read_record(batch.batch_id)
        assert saved['groups'] == batch.record['groups']
        assert saved['cleanup_required'] is False
        assert dm.turntable('turntable1').owner is None
        rows = list(csv.DictReader(sample_record.SAMPLES_CSV.open(encoding='utf-8-sig')))
        formal = [r for r in rows if r['run_id'] in {g['run_id'] for g in batch.record['groups']}]
        assert len(formal) == 2
        logs = [json.loads(Path(r['raw_log_path']).read_text(encoding='utf-8')) for r in formal]
        assert [log['metadata']['bottle_number'] for log in logs] == [1, 2]
        assert [log['metadata']['collection_status'] for log in logs] == ['collected', 'collected']
    asyncio.run(run())


@pytest.mark.parametrize('fail_feed', [False, True])
def test_batch_elapsed_includes_pause_and_cleanup_then_freezes(fail_feed):
    async def run():
        dm = FakeManager()
        dm.fail_feed = fail_feed
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        clock = SimpleNamespace(now=100.0)
        batch.elapsed_clock = lambda: clock.now
        stop_devices = batch.executor.stop_active_devices

        async def timed_cleanup(*args, **kwargs):
            if batch.executor.release_resources_on_cleanup:
                clock.now += 5
                assert batch.snapshot()['elapsed_seconds'] == 25
                result = await stop_devices(*args, **kwargs)
                clock.now += 5
                return result
            return await stop_devices(*args, **kwargs)

        batch.executor.stop_active_devices = timed_cleanup
        assert batch.snapshot()['elapsed_seconds'] == 0
        await batch.start()
        await batch.pause()
        clock.now = 112
        assert batch.snapshot()['elapsed_seconds'] == 12
        await batch.resume()
        clock.now = 120
        await batch.task
        assert batch.state.value == ('failed' if fail_feed else 'completed'), batch.record['error']
        assert batch.snapshot()['elapsed_seconds'] == 30
        if not fail_feed:
            assert batch.snapshot()['progress']['step_id'] == 'turntable_home_finish'
            assert batch.snapshot()['progress']['elapsed'] == 0
            assert len(batch.record['groups']) == 2
        assert api.read_record(batch.batch_id)['elapsed_seconds'] == 30
        clock.now = 10000
        batch.save()
        assert batch.snapshot()['elapsed_seconds'] == 30
        assert api.read_record(batch.batch_id)['elapsed_seconds'] == 30
    asyncio.run(run())


@pytest.mark.parametrize('stop_when_ready', [False, True])
def test_batch_elapsed_continues_between_priming_and_formal_start(stop_when_ready):
    async def run():
        batch = guided.GuidedBatch(FakeManager(), spec())
        clock = SimpleNamespace(now=100.0)
        batch.elapsed_clock = lambda: clock.now
        await batch.start(prime_only=True)
        await batch.task
        assert batch.record['phase'] == 'ready'
        clock.now = 130
        assert batch.snapshot()['elapsed_seconds'] == 30
        if stop_when_ready:
            await batch.stop()
            assert batch.state.value == 'stopped'
        else:
            await batch.begin_experiments(batch.spec)
            clock.now = 145
            await batch.task
            assert batch.state.value == 'completed', batch.record['error']
        expected = 30 if stop_when_ready else 45
        assert api.read_record(batch.batch_id)['elapsed_seconds'] == expected
        clock.now = 10000
        assert batch.snapshot()['elapsed_seconds'] == expected
    asyncio.run(run())


@pytest.mark.parametrize('field,value', [
    ('turntable_drip_seconds', None), ('turntable_drip_seconds', -1),
    ('turntable_drip_seconds', 3601), ('turntable_drip_seconds', True),
])
def test_invalid_drip_rejected_before_writes(field, value):
    dm = FakeManager()
    body = spec().model_dump()
    if value is None:
        body.pop(field)
    else:
        body[field] = value
    with TestClient(app_for(dm)) as client:
        for endpoint in ('preview', 'prime', 'start'):
            assert client.post('/api/guided/' + endpoint, json=body).status_code == 422
    assert not dm.calls


def test_empty_bottle_confirmation_is_once_per_batch_and_not_needed_for_preview():
    dm = FakeManager()
    with TestClient(app_for(dm)) as client:
        body = spec(bottles_confirmed=False).model_dump()
        assert client.post('/api/guided/preview', json=body).status_code == 200
        for endpoint in ('prime', 'start'):
            response = client.post('/api/guided/' + endpoint, json=body)
            assert response.status_code == 409, response.text
            assert '瓶' in response.text
    assert not dm.calls


@pytest.mark.parametrize('change', ['missing', 'disabled', 'no_home', 'unverified', 'over_capacity'])
def test_turntable_configuration_and_group_capacity_rejected_without_writes(monkeypatch, change):
    config = copy.deepcopy(ConfigManager().load())
    turntable = next(t for t in config.turntables if t.device_id == 'turntable1')
    if change == 'missing':
        config.turntables = []
    elif change == 'disabled':
        turntable.enabled = False
    elif change == 'no_home':
        turntable.home_enabled = False
    elif change == 'unverified':
        turntable.position_encoding_verified = False
    else:
        turntable.bottle_count = 1
    monkeypatch.setattr(ConfigManager, 'load', lambda *_: config)
    dm = FakeManager()
    with TestClient(app_for(dm)) as client:
        for endpoint in ('preview', 'prime', 'start'):
            response = client.post('/api/guided/' + endpoint, json=spec(repeats=2).model_dump())
            assert response.status_code in (409, 422), response.text
            assert '转盘' in response.text
    assert not dm.calls


def test_twelve_groups_allowed_but_thirteenth_never_wraps():
    assert len(guided.compile_plan(spec(repeats=12))) == 12
    with pytest.raises(ValueError, match='12'):
        guided.compile_plan(spec(repeats=13))


def test_final_home_failure_keeps_completed_samples_and_requires_recovery():
    async def run():
        dm = FakeManager()
        device = dm.turntable('turntable1').device
        original = device.send_command
        homes = 0
        def send(command):
            nonlocal homes
            if command.action == 'home':
                homes += 1
                if homes == 2:
                    raise OSError('final home unavailable')
            return original(command)
        device.send_command = send
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['finalization']['status'] == 'failed'
        assert batch.record['recovery_required']
        assert [g['state'] for g in batch.record['groups']] == ['completed', 'completed']
        assert [g['collection_status'] for g in batch.record['groups']] == ['collected', 'collected']
        assert len({g['sample_id'] for g in batch.record['groups']}) == 2
        assert homes == 2  # No retry or failure-path homing.
        assert ('turntable_stop', None) in dm.calls
        assert not batch.executor._active_heaters
        restored = api.read_record(batch.batch_id)
        assert restored['recovery_required']
        assert restored['groups'] == batch.record['groups']
    asyncio.run(run())


def test_position_lost_before_product_route_prevents_collection_and_next_group():
    async def run():
        dm = FakeManager()
        microwave_stop = dm.stop_microwave
        def stop(*args, **kwargs):
            result = microwave_stop(*args, **kwargs)
            dm.turntable('turntable1')._invalidate_bottle()
            return result
        dm.stop_microwave = stop
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert not any(c == ('valve', False) for c in dm.calls)
        assert sum(c == ('pump_start', 4) for c in dm.calls) == 1  # Priming only.
        assert sum(c[0] == 'turntable_home' for c in dm.calls) == 1
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        assert len(batch.record['groups']) == 1
        assert batch.record['groups'][0]['collection_status'] == 'pending'
    asyncio.run(run())


def test_stop_during_collection_keeps_partial_bottle_and_never_moves(monkeypatch):
    async def timed(self, did, channel, seconds):
        seconds = .5 if self._activity_step.id == 'collect_product' else .01
        return await _real_timed_flow(self, did, channel, seconds)
    monkeypatch.setattr(execution.StepExecutor, '_run_timed_flow', timed)
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await until(lambda: sum(c == ('pump_start', 4) for c in dm.calls) == 2)
        assert batch.record['groups'][0]['collection_status'] == 'collecting'
        assert await batch.stop()
        assert batch.state.value == 'stopped'
        assert batch.record['groups'][0]['collection_status'] == 'possibly_partial'
        assert batch.record['groups'][0]['bottle_number'] == 1
        assert sum(c[0] == 'turntable_home' for c in dm.calls) == 1
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        assert len(batch.record['groups']) == 1
        assert ('turntable_stop', None) in dm.calls
    asyncio.run(run())


def test_pause_during_indexing_finishes_motion_then_waits_without_replay():
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await until(lambda: ('turntable_next', 2) in dm.calls)
        await batch.pause()
        await until(lambda: dm.turntable('turntable1').summary()['current_bottle'] == 2)
        assert batch.state.value == 'paused'
        assert len(batch.record['groups']) == 1
        writes = list(dm.calls)
        await asyncio.sleep(.1)
        assert dm.calls == writes
        await batch.resume()
        await batch.task
        assert batch.state.value == 'completed', batch.record.get('error')
        assert dm.calls.count(('turntable_next', 2)) == 1
        assert dm.calls.count(('turntable_home', 1)) == 2
        assert len(batch.record['groups']) == 2
    asyncio.run(run())


def test_collection_intent_write_failure_does_not_start_pump(monkeypatch):
    original = guided.atomic_record
    def save(record, directory=None):
        if any(g.get('collection_status') == 'collecting' for g in record.get('groups', [])):
            raise OSError('cannot persist collection intent')
        return original(record, directory)
    monkeypatch.setattr(guided, 'atomic_record', save)
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert sum(c == ('pump_start', 4) for c in dm.calls) == 1
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        assert batch.persistence_failure == 'cannot persist collection intent'
        assert 'cannot persist collection intent' in batch.record['error']
    asyncio.run(run())


def test_restart_marks_inflight_collection_partial_without_reestablishing_position():
    batch = guided.GuidedBatch(FakeManager(), spec())
    batch.state = guided.ExperimentState.RUNNING
    batch.record['phase'] = 'experiments'
    batch.record['groups'] = [dict(index=1, bottle_number=1, sample_id='S001',
                                  state='running', collection_status='collecting')]
    batch.save()
    record = api.read_record(batch.batch_id)
    assert record['state'] == 'interrupted' and record['recovery_required']
    assert record['groups'][0]['collection_status'] == 'possibly_partial'
    assert record['groups'][0]['bottle_number'] == 1
    assert record['turntable']['current_bottle'] is None


@pytest.mark.parametrize('stage', ['preparing', 'indexing', 'finishing'])
def test_stop_during_motion_never_adds_a_recovery_home(stage):
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        def moving():
            if stage == 'preparing':
                return dm.calls.count(('turntable_home', 1)) == 1
            if stage == 'indexing':
                return ('turntable_next', 2) in dm.calls
            return dm.calls.count(('turntable_home', 1)) == 2
        await until(moving)
        homes = dm.calls.count(('turntable_home', 1))
        assert await batch.stop()
        assert batch.state.value == 'stopped', batch.record.get('error')
        assert dm.calls.count(('turntable_home', 1)) == homes
        assert ('turntable_stop', None) in dm.calls
        assert not batch.turntable.claimed
        assert batch.record['recovery_required']
        if stage == 'preparing':
            assert not any(c[0] in ('initialize', 'aspirate', 'dispense', 'pump_start') for c in dm.calls)
            assert batch.record['groups'] == []
        elif stage == 'indexing':
            assert len(batch.record['groups']) == 1
            assert batch.record['groups'][0]['collection_status'] == 'collected'
        else:
            assert [g['state'] for g in batch.record['groups']] == ['completed', 'completed']
            assert [g['collection_status'] for g in batch.record['groups']] == ['collected', 'collected']
            assert batch.record['finalization']['status'] == 'failed'
    asyncio.run(run())


def test_position_loss_during_collection_stops_before_cleaning_or_next_group(monkeypatch):
    async def timed(self, did, channel, seconds):
        seconds = .3 if self._activity_step.id == 'collect_product' else .01
        return await _real_timed_flow(self, did, channel, seconds)
    monkeypatch.setattr(execution.StepExecutor, '_run_timed_flow', timed)
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        await batch.start()
        await until(lambda: sum(c == ('pump_start', 4) for c in dm.calls) == 2)
        dm.turntable('turntable1')._invalidate_bottle()
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['groups'][0]['collection_status'] == 'possibly_partial'
        assert not any(c[0] == 'turntable_next' or c == ('pump_start', 3) for c in dm.calls)
        assert not dm.flow_channels
        assert dm.calls.count(('turntable_home', 1)) == 1
    asyncio.run(run())


def test_preparation_valve_failure_does_not_home_or_consume_precursors(monkeypatch):
    async def run():
        dm = FakeManager()
        original = dm.valve_operation
        def switch(did, action, *args):
            if action == 'switch':
                raise OSError('NC relay readback unavailable')
            return original(did, action, *args)
        monkeypatch.setattr(dm, 'valve_operation', switch)
        batch = guided.GuidedBatch(dm, spec())
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['preparation']['status'] == 'failed'
        assert batch.record['priming']['status'] == 'pending'
        assert not any(c[0] in ('turntable_home', 'initialize', 'aspirate', 'dispense', 'pump_start') for c in dm.calls)
    asyncio.run(run())


def test_drip_wait_excludes_pause_and_consumes_scheduler_delay(monkeypatch):
    async def run():
        batch = guided.GuidedBatch(FakeManager(), spec(turntable_drip_seconds=.2))
        batch.state = guided.ExperimentState.RUNNING
        batch.record['phase'] = 'indexing'
        clock = SimpleNamespace(now=0.0, sleeps=0)
        monkeypatch.setattr(guided, 'time', SimpleNamespace(monotonic=lambda: clock.now))
        async def sleep(seconds):
            clock.now += seconds
            clock.sleeps += 1
            if clock.sleeps == 1:
                await batch.pause()
                clock.now += 50
                await batch.resume()
            else:
                clock.now += 5  # A scheduling stall consumes the remaining wait.
        monkeypatch.setattr(guided, 'asyncio', SimpleNamespace(sleep=sleep))
        await batch.settle()
        assert clock.sleeps == 2
        assert clock.now == pytest.approx(55.1)
        assert not batch.dm.calls
    asyncio.run(run())


def test_drip_wait_stop_interrupts_before_movement(monkeypatch):
    async def run():
        batch = guided.GuidedBatch(FakeManager(), spec(turntable_drip_seconds=100))
        batch.state = guided.ExperimentState.RUNNING
        clock = SimpleNamespace(now=0.0)
        monkeypatch.setattr(guided, 'time', SimpleNamespace(monotonic=lambda: clock.now))
        async def sleep(seconds):
            clock.now += seconds
            batch.request_stop()
        monkeypatch.setattr(guided, 'asyncio', SimpleNamespace(sleep=sleep))
        with pytest.raises(RuntimeError, match='停止'):
            await batch.settle()
        assert clock.now < 1
        assert not batch.dm.calls
    asyncio.run(run())


@pytest.mark.parametrize('channel', ['3', '4'])
def test_hardware_paused_pump_is_not_stopped_at_start(channel):
    dm = FakeManager()
    read = dm.read_pump_status
    def paused(did):
        status = read(did)
        status['channels'][channel].update(run_status='PAUSE', running=False)
        return status
    dm.read_pump_status = paused
    with TestClient(app_for(dm)) as client:
        for endpoint in ('prime', 'start'):
            response = client.post('/api/guided/' + endpoint, json=spec().model_dump())
            assert response.status_code == 409, response.text
            assert '未确认停止' in response.text
    assert not dm.calls


def test_hardware_paused_pump_blocks_intergroup_motion():
    async def run():
        dm = FakeManager()
        read = dm.read_pump_status
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        def paused_before_next(did):
            status = read(did)
            if batch.record['phase'] == 'indexing':
                status['channels']['4'].update(run_status='PAUSE', running=False)
            return status
        dm.read_pump_status = paused_before_next
        await batch.start()
        await batch.task
        assert batch.state.value == 'failed'
        assert '未确认停止' in batch.record['error']
        assert len(batch.record['groups']) == 1
        assert batch.record['groups'][0]['collection_status'] == 'collected'
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        assert dm.calls.count(('turntable_home', 1)) == 1
    asyncio.run(run())


def test_ready_second_read_failure_invalidates_priming_and_stops_retained_heat():
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec())
        await batch.start(prime_only=True)
        await batch.task
        assert batch.record['phase'] == 'ready'
        control = dm.turntable('turntable1')
        read = control.read
        reads = 0
        def fail_verification_read():
            nonlocal reads
            reads += 1
            if reads == 2:  # Preflight passed, then bottle verification fails.
                control.device.reads.append(OSError('lost during ready verification'))
            return read()
        control.read = fail_verification_read
        with pytest.raises(OSError, match='lost during ready verification'):
            await batch.begin_experiments(spec())
        assert batch.state.value == 'failed'
        assert batch.record['priming']['status'] == 'invalidated'
        assert batch.record['recovery_required']
        assert not batch.executor._active_heaters
        assert not batch.turntable.claimed
        assert ('turntable_stop', None) in dm.calls
        assert dm.calls.count(('turntable_home', 1)) == 1
        assert not any(c[0] == 'microwave_start' for c in dm.calls)
        assert batch.record['groups'] == []
        with pytest.raises(ValueError):
            await batch.begin_experiments(spec())
    asyncio.run(run())


@pytest.mark.parametrize('changed_device', ['pump', 'valve'])
def test_resume_rechecks_liquid_interlocks_before_moving(changed_device):
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec(repeats=2))
        paused = asyncio.Event()
        verify = batch.verify_waste_route
        poisoned = False
        async def pause_after_read():
            await verify()
            if (not paused.is_set() and batch.record['phase'] == 'indexing'
                    and batch._orchestration_step and batch._orchestration_step[0] == 'turntable_settle'):
                # All pre-move reads succeeded, but their evidence ages while paused.
                await batch.pause()
                paused.set()
        batch.verify_waste_route = pause_after_read
        read_pump = dm.read_pump_status
        def current_pump_state(did):
            status = read_pump(did)
            if poisoned and changed_device == 'pump':
                status['channels']['4'].update(run_status='PAUSE', running=False)
            return status
        dm.read_pump_status = current_pump_state
        await batch.start()
        await asyncio.wait_for(paused.wait(), 5)
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        poisoned = True
        if changed_device == 'valve':
            dm.valve_energized = False
        await batch.resume()
        await batch.task
        assert batch.state.value == 'failed'
        assert batch.record['recovery_required']
        assert not any(c[0] == 'turntable_next' for c in dm.calls)
        assert len(batch.record['groups']) == 1
        assert batch.record['groups'][0]['collection_status'] == 'collected'
    asyncio.run(run())


def test_stop_arriving_during_final_cleanup_cannot_be_reported_completed():
    async def run():
        dm = FakeManager()
        batch = guided.GuidedBatch(dm, spec())
        cleaning = asyncio.Event()
        release = asyncio.Event()
        original = batch.executor.stop_active_devices
        async def block_final_cleanup(*args, **kwargs):
            if (batch.executor.release_resources_on_cleanup
                    and batch.record['finalization']['status'] == 'completed'):
                cleaning.set()
                await release.wait()
            return await original(*args, **kwargs)
        batch.executor.stop_active_devices = block_final_cleanup
        await batch.start()
        await asyncio.wait_for(cleaning.wait(), 5)
        assert batch.state.value == 'running'
        assert batch.snapshot()['cleanup_pending']
        batch.request_stop()
        release.set()
        await batch.task
        assert batch.state.value == 'stopped'
        assert batch.record['recovery_required']
        assert batch.record['groups'][0]['state'] == 'completed'
        assert batch.record['groups'][0]['collection_status'] == 'collected'
        assert dm.calls.count(('turntable_home', 1)) == 2
        assert ('turntable_stop', None) in dm.calls
        assert not batch.turntable.claimed
    asyncio.run(run())
