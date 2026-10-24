"""Guided collection uses real ownership/motion logic and fake serial devices."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
from types import SimpleNamespace

import pytest

from src.experiment.guided_turntable import GuidedTurntable
from src.utils.config import TurntableConfig
from src.web.device_manager import DeviceManager
from src.web.turntable_control import TurntableController
from test_turntable_controller import FakeDevice, clock, no_hardware


class MovingDevice(FakeDevice):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.motion_samples = deque()
        self.complete = True
        self.observe_home = True
        self.offset = 0

    def read_status(self):
        self.clock.advance(.1)
        if self.motion_samples and not self.reads:
            self.position, self.work_state = self.motion_samples.popleft()
        return super().read_status()

    def send_command(self, request):
        super().send_command(request)
        if request.action == 'stop':
            self.motion_samples.clear()
        elif self.complete:
            target = (0 if request.action == 'home' else request.position) + self.offset
            moving = 8 if request.action == 'home' else 1
            if request.action != 'home' or self.observe_home:
                self.motion_samples.append((self.position, moving))
            self.motion_samples.extend([(target, 0x20), (target, 0x20)])


@pytest.fixture
def rig(clock, monkeypatch):
    monkeypatch.setattr('src.experiment.guided_turntable.POLL_SECONDS', 0)
    device = MovingDevice(clock)
    config = TurntableConfig(home_enabled=True, position_encoding_verified=True,
        bottle_count=12, pulses_per_bottle=12000, bottle_speed=1000,
        bottle_home_timeout=180)
    control = TurntableController(config, device=device)
    assert control.stop()
    device.commands.clear()
    dm = DeviceManager()
    dm.turntables['turntable1'] = control
    state = SimpleNamespace(stopping=False, changes=[])
    helper = GuidedTurntable(dm, lambda: state.stopping, state.changes.append)
    return SimpleNamespace(helper=helper, dm=dm, control=control, device=device,
                           state=state, clock=clock)


def test_claim_is_read_only_and_owned_connect_disconnect_and_motion_are_rejected(rig):
    async def run():
        reads = rig.device.read_count
        await rig.helper.claim()
        assert rig.device.read_count == reads and rig.device.commands == []
        assert rig.control.summary()['experiment_owned']
        generation = rig.control.generation
        for action in (rig.control.connect, rig.control.disconnect,
                       lambda: rig.control.command({'action': 'home_bottle'}),
                       lambda: rig.control.claim(object())):
            with pytest.raises(RuntimeError, match='占用'):
                action()
        assert rig.control.generation == generation
        assert not rig.device.commands
        assert rig.control.release(object()) is False
        assert await rig.helper.release()
        assert rig.control.owner is None
    asyncio.run(run())


@pytest.mark.parametrize('field', ['enabled', 'home_enabled', 'position_encoding_verified', 'bottle_count'])
def test_claim_rejects_unavailable_bottle_configuration_without_hardware_io(rig, field):
    setattr(rig.control.config, field, False if field != 'bottle_count' else 0)
    async def run():
        reads = rig.device.read_count
        with pytest.raises(RuntimeError, match='启用并核验'):
            await rig.helper.claim()
        assert rig.device.read_count == reads and not rig.device.commands
        assert rig.control.owner is None
    asyncio.run(run())


def test_owned_stop_is_still_allowed_and_invalidates_bottle(rig):
    async def run():
        await rig.helper.claim()
        await rig.helper.home()
        result = rig.dm.turntable_command('turntable1', {'action': 'stop'})
        assert result['result'] == 'stopped'
        assert rig.control.summary()['current_bottle'] is None
        assert rig.control.owner is rig.helper.owner
        assert await rig.helper.release()
    asyncio.run(run())


def test_disconnect_fences_queued_motion_before_acquiring_serial_lock(rig, monkeypatch):
    checked = threading.Event()
    original = rig.control._check_owner
    def check_owner(owner):
        original(owner)
        checked.set()
    monkeypatch.setattr(rig.control, '_check_owner', check_owner)
    generation = rig.control.generation
    with ThreadPoolExecutor(max_workers=2) as pool:
        with rig.control.lock:
            moving = pool.submit(rig.control.command, {'action': 'home_bottle'}, generation)
            disconnecting = pool.submit(rig.control.disconnect)
            assert checked.wait(2)
            with rig.control.gate:
                assert rig.control.stopping == 1
        with pytest.raises(RuntimeError, match='停止请求'):
            moving.result(timeout=2)
        assert disconnecting.result(timeout=2)['connected'] is False
    assert [item['action'] for item in rig.device.commands] == ['stop']


def test_home_next_verify_and_final_home_keep_single_owner_without_intermediate_stop(rig):
    async def run():
        await rig.helper.claim()
        first = await rig.helper.home()
        assert first['current_bottle'] == 1 and first['position'] == 0
        assert first['action']['action'] == 'home_bottle'
        assert rig.helper.claimed and not rig.helper.needs_stop
        assert (await rig.helper.verify(1))['bottle_token'] == first['bottle_token']
        second = await rig.helper.next(2)
        assert second['current_bottle'] == 2 and second['position'] == 12000
        assert second['bottle_token'] != first['bottle_token']
        assert second['action']['action_id'] != first['action']['action_id']
        final = await rig.helper.home()
        assert final['current_bottle'] == 1
        assert await rig.helper.release()
        assert [item['action'] for item in rig.device.commands] == ['home', 'move_absolute', 'home']
        assert any(s['action']['result'] == 'running' for s in rig.state.changes)
        assert rig.control.summary()['bottle_ready']
    asyncio.run(run())


def test_no_wrapping_or_reusing_bottle_after_capacity_is_reached(rig):
    async def run():
        await rig.helper.claim()
        await rig.helper.home()
        for bottle in range(2, 13):
            assert (await rig.helper.next(bottle))['current_bottle'] == bottle
        commands = list(rig.device.commands)
        for invalid in (13, 1, True, 0, 2.0):
            with pytest.raises(ValueError):
                await rig.helper.next(invalid)
        assert rig.device.commands == commands
        assert rig.control.summary()['current_bottle'] == 12
    asyncio.run(run())


def test_next_requires_exact_previous_bottle_and_never_skips(rig):
    async def run():
        await rig.helper.claim()
        await rig.helper.home()
        with pytest.raises(RuntimeError, match='2号瓶'):
            await rig.helper.next(3)
        assert [item['action'] for item in rig.device.commands] == ['home', 'stop']
        assert rig.control.summary()['current_bottle'] is None
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['unobserved_home', 'wrong_target', 'timeout'])
def test_failed_motion_stops_without_trusting_a_bottle_or_retrying(rig, mode):
    if mode == 'unobserved_home':
        rig.device.observe_home = False
    elif mode == 'wrong_target':
        rig.device.offset = 1
    else:
        rig.device.complete = False
        rig.control.config.bottle_home_timeout = .3
    async def run():
        await rig.helper.claim()
        with pytest.raises(RuntimeError):
            await rig.helper.home()
        assert [item['action'] for item in rig.device.commands] == ['home', 'stop']
        assert rig.control.summary()['current_bottle'] is None
        assert rig.control.stop_confirmed
        assert await rig.helper.release()
    asyncio.run(run())


def test_read_failure_during_motion_stops_and_preserves_original_error(rig, monkeypatch):
    send = rig.device.send_command
    def failed_read(request):
        send(request)
        if request.action == 'home':
            rig.device.reads.append(OSError('injected motion read failure'))
    monkeypatch.setattr(rig.device, 'send_command', failed_read)
    async def run():
        await rig.helper.claim()
        with pytest.raises(OSError, match='injected motion read failure'):
            await rig.helper.home()
        assert [item['action'] for item in rig.device.commands] == ['home', 'stop']
        assert rig.control.stop_confirmed
    asyncio.run(run())


def test_verify_failure_leaves_stop_to_caller_so_collection_pump_can_stop_first(rig):
    async def run():
        await rig.helper.claim()
        await rig.helper.home()
        rig.device.reads.append(OSError('collection position unknown'))
        with pytest.raises(OSError, match='collection position unknown'):
            await rig.helper.verify(1)
        assert rig.helper.needs_stop
        assert not await rig.helper.release()
        assert [item['action'] for item in rig.device.commands] == ['home']
        assert await rig.helper.stop()
        assert await rig.helper.release()
    asyncio.run(run())


def test_previous_completed_action_cannot_complete_new_home(rig, monkeypatch):
    async def run():
        await rig.helper.claim()
        first = await rig.helper.home()
        real_read = rig.control.read
        def stale():
            summary = real_read()
            if (summary.get('action') or {}).get('action_id') != first['action']['action_id']:
                summary = deepcopy(first)
            return summary
        monkeypatch.setattr(rig.control, 'read', stale)
        with pytest.raises(RuntimeError, match='动作已变化'):
            await rig.helper.home()
        assert [item['action'] for item in rig.device.commands] == ['home', 'home', 'stop']
    asyncio.run(run())


@pytest.mark.parametrize('cancel_task', [False, True])
def test_stop_fences_queued_motion_before_worker_can_write(rig, monkeypatch, cancel_task):
    reached, proceed = threading.Event(), threading.Event()
    original = rig.dm.turntable_command
    def delayed(*args, **kwargs):
        reached.set()
        assert proceed.wait(2)
        return original(*args, **kwargs)
    monkeypatch.setattr(rig.dm, 'turntable_command', delayed)
    async def run():
        await rig.helper.claim()
        task = asyncio.create_task(rig.helper.home())
        assert await asyncio.to_thread(reached.wait, 2)
        if cancel_task:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        else:
            rig.state.stopping = True
            rig.helper.invalidate_pending()
        proceed.set()
        with pytest.raises(asyncio.CancelledError if cancel_task else RuntimeError):
            await task
        assert [item['action'] for item in rig.device.commands] == ['stop']
        assert rig.control.stop_confirmed
        assert await rig.helper.release()
    asyncio.run(run())


def test_stopped_during_motion_does_not_home_again(rig):
    def stop_on_running(summary):
        rig.state.changes.append(summary)
        if (summary.get('action') or {}).get('result') == 'running':
            rig.state.stopping = True
    rig.helper._changed = stop_on_running
    async def run():
        await rig.helper.claim()
        with pytest.raises(RuntimeError, match='批次停止'):
            await rig.helper.home()
        assert [item['action'] for item in rig.device.commands] == ['home', 'stop']
        assert not rig.control.summary()['bottle_ready']
    asyncio.run(run())


def test_stop_failure_retains_owner_until_explicit_successful_cleanup(rig):
    rig.device.complete = False
    rig.device.stop_ok = False
    rig.control.config.bottle_home_timeout = .3
    async def run():
        await rig.helper.claim()
        with pytest.raises(RuntimeError, match='超时'):
            await rig.helper.home()
        assert rig.helper.needs_stop
        assert not await rig.helper.release()
        assert rig.control.owner is rig.helper.owner
        with pytest.raises(RuntimeError, match='占用'):
            rig.control.command({'action': 'home_bottle'})
        rig.device.stop_ok = True
        assert await rig.helper.stop()
        assert await rig.helper.release()
        assert rig.control.owner is None
        assert [item['action'] for item in rig.device.commands] == ['home', 'stop', 'stop']
    asyncio.run(run())


def test_stop_deduplicates_confirmed_cleanup_but_never_reuses_invalidated_status(rig):
    async def run():
        await rig.helper.claim()
        assert all(await asyncio.gather(rig.helper.stop(), rig.helper.stop()))
        assert [item['action'] for item in rig.device.commands] == ['stop']
        rig.device.reads.append(OSError('lost confirmation'))
        assert not rig.control.read()['read_ok']
        assert await rig.helper.stop()
        assert [item['action'] for item in rig.device.commands] == ['stop', 'stop']
        assert await rig.helper.release()
    asyncio.run(run())


def test_persistence_callback_failure_stops_and_keeps_ownership_for_recovery(rig):
    def failed(_summary):
        raise OSError('checkpoint disk full')
    rig.helper._changed = failed
    async def run():
        await rig.helper.claim()
        with pytest.raises(OSError, match='checkpoint disk full'):
            await rig.helper.home()
        assert rig.control.stop_confirmed
        assert not await rig.helper.release()
        assert rig.control.owner is rig.helper.owner
        rig.helper._changed = None
        assert await rig.helper.stop()
        assert await rig.helper.release()
    asyncio.run(run())


def test_release_pending_motion_or_stale_status_does_not_clear_controller_owner(rig):
    owner = object()
    rig.control.claim(owner)
    rig.control.command({'action': 'home_bottle'}, owner=owner)
    assert rig.control.release(owner) is False
    assert rig.control.stop()
    rig.clock.advance(7)
    assert rig.control.release(owner) is False
    rig.control.read()
    assert rig.control.release(owner) is True


def test_release_cannot_treat_controller_reset_as_confirmed_stop(rig):
    owner = object()
    rig.control.claim(owner)
    rig.device.work_state = 0
    rig.control.read()
    assert rig.control.release(owner) is False
    assert rig.control.owner is owner
    assert rig.control.stop()
    assert rig.control.release(owner) is True


def test_global_disconnect_stops_owned_turntable_but_preserves_batch_connection(rig):
    async def run():
        await rig.helper.claim()
        assert not rig.dm._cleanup_devices(disconnect=True)
        assert rig.control.owner is rig.helper.owner
        assert rig.device.connected and rig.device.disconnect_calls == 0
        assert [item['action'] for item in rig.device.commands] == ['stop']
        assert await rig.helper.release()
    asyncio.run(run())
