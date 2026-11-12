"""Four-ring coordination through real controllers, with serial access forbidden."""
import asyncio
import copy
from unittest.mock import AsyncMock

import pytest

from src.experiment import guided
from src.experiment.collection_layout import bottle_location, collection_plan
from src.experiment.guided_collection import GuidedCollection
from src.experiment.engine import ExperimentState
from src.utils.config import ConfigManager
from src.web.collection_control import CollectionAxisController
from test_guided import FakeManager, spec
from test_turntable_controller import FakeDevice, clock, no_hardware


class MovingDevice(FakeDevice):
    def __init__(self, clock, writes, did):
        super().__init__()
        self.clock, self.writes, self.did = clock, writes, did
        self.failure = None
        self.error = 0

    def read_status(self):
        self.clock.advance(.1)
        return super().read_status()

    def send_command(self, request):
        super().send_command(request)
        self.writes.append((self.did, request.action, request.position))
        self.reads.clear()
        if request.action == 'stop':
            return
        target = 0 if request.action == 'home' else request.position
        self.reads.extend([(self.position, 8 if request.action == 'home' else 1)])
        if self.failure:
            self.reads.extend([self.failure, self.failure])
        else:
            self.reads.extend([(target + self.error, 32)] * 3)


@pytest.fixture
def rig(monkeypatch, clock, tmp_path):
    from src.web import collection_control, turntable_control
    monkeypatch.setattr(collection_control, 'time', turntable_control.time)
    config = ConfigManager().load()
    monkeypatch.setattr(ConfigManager, 'load', lambda *_: copy.deepcopy(config))
    dm = FakeManager()
    writes = []
    dm.turntables = {c.device_id: CollectionAxisController(c, MovingDevice(clock, writes, c.device_id))
                     for c in config.turntables}
    r, p = dm.turntables.values()
    r.peer, p.peer, p.lock = p, r, r.lock
    for _ in range(3):
        r.read(force=True); p.read(force=True)
    monkeypatch.setattr(GuidedCollection, 'poll_seconds', .001)
    monkeypatch.setattr(guided, 'BATCH_DIR', tmp_path)
    stages = []

    async def stage(phase, label, target, did, execute):
        stages.append((phase, target))
        return await execute()

    coordinator = GuidedCollection(dm, lambda: False, lambda _: None, stage)
    return dm, r, p, coordinator, writes, stages, config


def position(r, p, bottle):
    location = bottle_location(r.config, bottle)
    r.device.position = location['rotation_offset']
    p.device.position = location['platform_position']
    for _ in range(3):
        r.read(force=True); p.read(force=True)


async def established(rig, bottle):
    _, r, p, c, *_ = rig
    position(r, p, bottle)
    await c.claim()
    c.current_bottle = bottle
    c.expected_positions = [r.device.position, p.device.position]
    await c.verify(bottle)


def test_mapping_and_capacity(rig):
    _, r, _, _, _, _, config = rig
    plan = collection_plan(config, 72)
    assert plan['capacity'] == 72 and len(plan['devices']) == 2
    for first, count, ring in [(1, 28, 1), (29, 20, 2), (49, 16, 3), (65, 8, 4)]:
        for local in range(1, count + 1):
            location = bottle_location(r.config, first + local - 1)
            assert location['collection_ring'] == ring
            assert location['ring_bottle_number'] == local
            assert location['rotation_offset'] == round((local - 1) * 144000 / count)
    with pytest.raises(ValueError):
        collection_plan(config, 73)
    with pytest.raises(ValueError):
        bottle_location(r.config, 0)
    recipes = guided.compile_plan(spec(repeats=72))
    assert recipes[28]['metadata']['collection_ring'] == 2
    assert recipes[28]['metadata']['ring_bottle_number'] == 1
    assert recipes[-1]['metadata']['bottle_number'] == 72
    with pytest.raises(ValueError):
        guided.compile_plan(spec(repeats=73))


@pytest.mark.parametrize('source,target,phase', [(1, 2, 'rotation_bottle'), (28, 29, 'platform_ring'),
                                               (48, 49, 'platform_ring'), (64, 65, 'platform_ring')])
def test_order_and_verified_destination(rig, source, target, phase):
    async def run():
        _, r, p, c, writes, stages, _ = rig
        await established(rig, source)
        result = await c.next(target)
        assert result['current_bottle'] == target
        assert stages[-1] == (phase, target)
        if phase == 'platform_ring':
            assert [w[0] for w in writes] == [r.config.device_id, p.config.device_id]
            assert writes[0][2] == 144000
            assert writes[1][2] == bottle_location(r.config, target)['platform_position']
        else:
            assert len(writes) == 1
        assert await c.release()
        assert r.owner is None and p.owner is None
    asyncio.run(run())


@pytest.mark.parametrize('bottle', [1, 34, 57, 72])
def test_home_from_any_ring_returns_outer_one(rig, bottle):
    async def run():
        _, r, p, c, writes, _, _ = rig
        await established(rig, bottle)
        await c.prepare_start()
        result = await c.home()
        assert result['current_bottle'] == 1
        assert writes == [(r.config.device_id, 'home', None), (p.config.device_id, 'move_absolute', 0)]
        assert r.device.position == p.device.position == 0
    asyncio.run(run())


def test_claim_rollback_and_no_manual_or_unowned_bypass(rig):
    async def run():
        _, r, p, c, writes, _, _ = rig
        other = object()
        p.owner = other
        with pytest.raises(RuntimeError):
            await c.claim()
        assert r.owner is None and p.owner is other
        p.owner = None
        await c.claim()
        with pytest.raises(RuntimeError):
            p.command(dict(action='select_ring', ring=2, expected_position=0))
        with pytest.raises(RuntimeError):
            p.command(dict(action='select_ring', ring=2, expected_position=0), owner=object())
        with pytest.raises(RuntimeError):
            p.disconnect()
        assert not writes
    asyncio.run(run())


@pytest.mark.parametrize('axis_index', [1, 2])
def test_motion_failure_stops_both_without_replay(rig, axis_index):
    async def run():
        _, r, p, c, writes, _, _ = rig
        await established(rig, 28)
        (r if axis_index == 1 else p).device.failure = TimeoutError('0/8')
        with pytest.raises(OSError):
            await c.next(29)
        assert [w[1] for w in writes].count('move_absolute') == axis_index
        assert writes[-2:] == [(r.config.device_id, 'stop', None), (p.config.device_id, 'stop', None)]
        assert c.current_bottle is None
    asyncio.run(run())


def test_stop_failure_retains_both_owners(rig):
    async def run():
        _, r, p, c, *_ = rig
        await established(rig, 28)
        p.device.stop_ok = False
        p.device.work_state = 1
        assert not await c.stop()
        assert not await c.release()
        assert r.owner is c.owner and p.owner is c.owner
    asyncio.run(run())


def test_no_wrap_and_dual_axis_verification(rig):
    async def run():
        _, r, p, c, writes, *_ = rig
        await established(rig, 72)
        with pytest.raises(ValueError):
            await c.next(73)
        p.device.position += 100
        with pytest.raises(RuntimeError):
            await c.verify(72)
        assert not writes
    asyncio.run(run())


@pytest.mark.parametrize("pause_axis", ["rotation", "platform"])
def test_pause_at_axis_boundary_then_continue_once(rig, pause_axis):
    async def run():
        dm, r, p, _, writes, _, _ = rig
        batch = guided.GuidedBatch(dm, spec())
        batch.state = ExperimentState.RUNNING
        batch.record['phase'] = 'indexing'
        batch.pumps_stopped = AsyncMock()
        batch.verify_waste_route = AsyncMock()
        c = batch.turntable
        position(r, p, 28)
        await c.claim()
        c.current_bottle = 28
        c.expected_positions = [r.device.position, p.device.position]
        paused_device = r.device if pause_axis == "rotation" else p.device
        original = paused_device.send_command

        def request_pause(command):
            original(command)
            batch._motion_pause_pending = True
        paused_device.send_command = request_pause
        task = asyncio.create_task(c.next(29))
        for _ in range(1000):
            if batch.state == ExperimentState.PAUSED:
                break
            await asyncio.sleep(.001)
        assert batch.state == ExperimentState.PAUSED
        assert batch.snapshot()['progress']['device_id'] == (r.config.device_id if pause_axis == 'rotation' else p.config.device_id)
        assert len(writes) == (1 if pause_axis == "rotation" else 2)
        assert p.device.position == (0 if pause_axis == "rotation" else -147246)
        assert batch.record['turntable']['current_bottle'] is None
        await batch.resume()
        result = await asyncio.wait_for(task, 3)
        assert result['current_bottle'] == 29
        assert len(writes) == 2
        assert batch.pumps_stopped.await_count == batch.verify_waste_route.await_count == 2
    asyncio.run(run())


def test_stage_intent_persistence_failure_prevents_motion(rig):
    async def run():
        dm, r, p, _, writes, *_ = rig
        batch = guided.GuidedBatch(dm, spec())
        batch.state = ExperimentState.RUNNING
        batch.pumps_stopped = AsyncMock()
        batch.verify_waste_route = AsyncMock()
        position(r, p, 28)
        c = batch.turntable
        await c.claim()
        c.current_bottle = 28
        c.expected_positions = [r.device.position, p.device.position]
        def fail():
            raise OSError('disk full')
        batch.save = fail
        with pytest.raises(OSError):
            await c.next(29)
        assert all(w[1] == 'stop' for w in writes)
    asyncio.run(run())


def test_signature_includes_platform_calibration(rig):
    *_, config = rig
    original = guided.priming_signature(spec())
    config.turntables[1].ring_positions[1] -= 1
    assert guided.priming_signature(spec()) != original


def test_full_batch_crosses_ring_and_persists_samples(rig, monkeypatch):
    from src.experiment import executor
    from src.science import sample_record
    from test_guided import fast_timed_flow, fast_microwave_stability
    import csv
    monkeypatch.setattr(executor.StepExecutor, '_run_timed_flow', fast_timed_flow)
    monkeypatch.setattr(executor.StepExecutor, '_wait_condition', fast_microwave_stability)
    monkeypatch.setattr(executor.StepExecutor, '_wait_heater_pair_stable', AsyncMock(return_value=True))

    async def run():
        dm, r, p, _, writes, *_ = rig
        batch = guided.GuidedBatch(dm, spec(repeats=29))
        collected = []
        original = dm.start_pump_channel
        def collect(did, channel, *args):
            if channel == 4 and dm.valve_energized is False:
                collected.append((batch.turntable.current_bottle, r.device.position, p.device.position))
            return original(did, channel, *args)
        dm.start_pump_channel = collect
        await batch.start()
        await batch.task
        assert batch.state.value == 'completed', batch.record['error']
        assert [b for b, _, _ in collected] == list(range(1, 30))
        assert collected[-1][1:] == (144000, -147246)
        assert writes[-2:] == [(r.config.device_id, 'home', None), (p.config.device_id, 'move_absolute', 0)]
        assert all(g['collection_status'] == 'collected' for g in batch.record['groups'])
        assert batch.record['groups'][-1]['collection_ring'] == 2
        assert batch.record['groups'][-1]['collection_device_id'] == r.config.device_id
        assert r.owner is None and p.owner is None
        with sample_record.SAMPLES_CSV.open(encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
        row = next(row for row in rows if row['bottle_number'] == '29')
        assert row['collection_ring'] == '2' and row['ring_bottle_number'] == '1'
        assert row['collection_platform_id'] == p.config.device_id
    asyncio.run(run())


def test_stop_between_stages_prevents_platform_command(rig):
    async def run():
        _, r, p, c, writes, *_ = rig
        await established(rig, 28)
        async def stage(phase, label, target, did, execute):
            result = await execute()
            if phase == 'rotation_start':
                r.stop()
            return result
        c.stage = stage
        with pytest.raises(RuntimeError):
            await c.next(29)
        assert not any(w[0] == p.config.device_id and w[1] == 'move_absolute' for w in writes)
    asyncio.run(run())


@pytest.mark.parametrize('error,accepted', [(-10, True), (10, True), (11, False)])
def test_platform_tolerance_in_automatic_crossing(rig, error, accepted):
    async def run():
        _, _, p, c, *_ = rig
        await established(rig, 28)
        p.device.error = error
        if accepted:
            result = await c.next(29)
            assert result['current_bottle'] == 29
            assert result['axes'][p.config.device_id]['action']['position_error'] == error
        else:
            with pytest.raises(RuntimeError):
                await c.next(29)
            assert c.current_bottle is None
    asyncio.run(run())


@pytest.mark.parametrize('fault', ['disconnected', 'wrong_position', 'out_of_range'])
def test_invalid_platform_prevents_collection(rig, fault):
    async def run():
        _, _, p, c, writes, *_ = rig
        await established(rig, 29)
        if fault == 'disconnected':
            p.device.connected = False
        else:
            p.device.position = -999999 if fault == 'out_of_range' else -123456
        with pytest.raises((RuntimeError, OSError)):
            await c.verify(29)
        assert not writes
    asyncio.run(run())


def test_restart_clears_both_axis_confirmation_and_keeps_partial_sample(rig):
    import json
    from src.web.api import guided as api
    dm, *_ = rig
    batch = guided.GuidedBatch(dm, spec())
    batch.state = ExperimentState.RUNNING
    batch.record['state'] = 'running'
    batch.record['turntable'].update(current_bottle=29, collection_ring=2, ring_bottle_number=1,
                                     axes={'saved': 'untrusted'})
    batch.record['groups'] = [dict(index=1, bottle_number=29, collection_ring=2,
                                   ring_bottle_number=1, collection_status='collecting')]
    guided.BATCH_DIR.mkdir(parents=True, exist_ok=True)
    (guided.BATCH_DIR / (batch.batch_id + '.json')).write_text(json.dumps(batch.record), encoding='utf-8')
    loaded = api.read_record(batch.batch_id)
    assert loaded['state'] == 'interrupted'
    assert loaded['turntable']['axes'] is None and loaded['turntable']['collection_ring'] is None
    assert loaded['groups'][0]['collection_status'] == 'possibly_partial'
    assert loaded['groups'][0]['bottle_number'] == 29


def test_csv_adds_columns_without_inventing_old_ring_data(rig):
    import csv
    from src.science import sample_record
    sample_record.SAMPLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    sample_record.SAMPLES_CSV.write_text('sample_id,run_id,custom\nold,old_run,preserve\n', encoding='utf-8')
    assert sample_record.write_sample_record('new_run', dict(sample_id='new', bottle_number=29,
        collection_ring=2, ring_bottle_number=1, collection_device_id='turntable1'), status='completed')
    with sample_record.SAMPLES_CSV.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]['custom'] == 'preserve' and rows[0]['collection_ring'] == ''
    assert rows[1]['bottle_number'] == '29' and rows[1]['collection_ring'] == '2'


def test_startup_reset_rotates_home_before_platform(rig):
    async def run():
        _, r, p, c, writes, *_ = rig
        r.device.work_state = 0
        r.read(force=True)
        await c.claim()
        await c.prepare_start()
        assert not writes
        await c.home()
        assert writes[0][1] == 'home'
        assert writes[1] == (p.config.device_id, 'move_absolute', 0)
    asyncio.run(run())


@pytest.mark.parametrize('queried_axis', ['rotation', 'platform'])
def test_stationary_peer_timeout_during_motion_recovers_once(rig, queried_axis):
    async def run():
        _, r, p, c, writes, *_ = rig
        await established(rig, 28)
        original = r.device.send_command
        def send(request):
            original(request)
            if request.action == 'move_absolute':
                failed = p if queried_axis == 'platform' else r
                failed.device.reads.appendleft(TimeoutError('transient timeout'))
        r.device.send_command = send
        await c.next(29)
        assert r.action['status_retry']['result'] == 'received'
        assert r.action['status_retry']['device_id'] == (p if queried_axis == 'platform' else r).config.device_id
        assert c.current_bottle == 29
        assert [w[1] for w in writes] == ['move_absolute', 'move_absolute']
    asyncio.run(run())
