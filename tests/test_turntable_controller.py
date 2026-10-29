"""Real turntable coordination over fake devices; no hardware or long waits."""
from collections import deque
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from src.devices.turntable import TurntableDevice
from src.devices.turntable_commands import TurntableCommand
from src.utils.config import TurntableConfig
from src.web.turntable_control import TurntableController


class FakeDevice:
    unknown = staticmethod(TurntableDevice.unknown)

    def __init__(self, *, connected=True):
        self.connected = connected
        self.position = 0
        self.work_state = 0x20
        self.snapshot = self.unknown()
        self.commands = []
        self.reads = deque()
        self.read_count = 0
        self.stop_ok = True
        self.write_error = None
        self.last_command_error = None
        self.disconnect_calls = 0

    def is_connected(self):
        return self.connected

    def read_status(self):
        self.read_count += 1
        if self.reads:
            result = self.reads.popleft()
            if isinstance(result, Exception):
                self.snapshot = self.unknown(str(result))
                raise result
            self.position, self.work_state = result
        self.snapshot = dict(read_ok=True, read_at=datetime.now(timezone.utc).isoformat(),
            position=self.position, speed_raw=0, input_raw=0x3C,
            inputs=dict(positive_limit=False, home=False, negative_limit=False, input4=False),
            work_state=self.work_state,
            state_name={0: 'reset', 1: 'positioning', 4: 'manual', 8: 'homing', 0x20: 'stopped'}[self.work_state],
            busy=self.work_state in (1, 4, 8), read_error=None)
        return dict(self.snapshot)

    def send_command(self, request):
        req = request if isinstance(request, TurntableCommand) else TurntableCommand.model_validate(request)
        self.commands.append(req.model_dump(exclude_unset=True))
        self.snapshot = self.unknown()
        if self.write_error:
            raise self.write_error
        if req.action == 'stop':
            if self.stop_ok:
                self.work_state = 0x20
        elif req.action.startswith('move_'):
            self.work_state = 1
        elif req.action == 'run':
            self.work_state = 4
        else:
            self.work_state = 8

    def connect(self, port):
        self.connected = True
        self.read_status()
        return True

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False
        self.snapshot = self.unknown()
        return True


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('No physical serial access')
    monkeypatch.setattr('serial.Serial.open', forbidden)


@pytest.fixture
def clock(monkeypatch):
    from src.web import turntable_control

    current = SimpleNamespace(now=10.0)
    def advance(seconds):
        current.now += seconds
    monkeypatch.setattr(turntable_control, 'time', SimpleNamespace(
        monotonic=lambda: current.now, sleep=advance))
    current.advance = advance
    return current


@pytest.fixture
def controller(clock):
    device = FakeDevice()
    control = TurntableController(TurntableConfig(position_encoding_verified=True), device=device)
    control.read()
    return control


@pytest.fixture
def api_app(controller, monkeypatch, tmp_path):
    from src.desktop.lifecycle import DesktopShutdownMiddleware
    from src.web.api import experiments, turntables
    from src.web.device_manager import DeviceManager

    monkeypatch.setattr(experiments, '_engines', {})
    monkeypatch.setattr(experiments, '_source_lock', asyncio.Lock())
    monkeypatch.setattr(experiments, '_stopping', 0)
    monkeypatch.setattr(experiments, '_stop_generation', 0)
    monkeypatch.setattr(experiments, '_desktop_exiting', False)
    monkeypatch.setattr('src.experiment.yaml_recovery.RECOVERY_DIR', tmp_path / 'recovery')
    monkeypatch.setattr('src.experiment.guided.BATCH_DIR', tmp_path / 'batches')
    monkeypatch.setattr('src.experiment.microwave_program.PROGRAM_DIR', tmp_path / 'programs')
    app = FastAPI()
    app.add_middleware(DesktopShutdownMiddleware)
    app.include_router(turntables.router, prefix='/api')
    app.state.device_manager = DeviceManager()
    app.state.device_manager.turntables['turntable1'] = controller
    return app


def move(control, steps=100):
    return control.command(dict(action='move_relative', steps=steps, speed=400))


@pytest.mark.parametrize('cancel_during_read', [False, True])
def test_guided_reset_preparation_respects_stop_generation(controller, monkeypatch, cancel_during_read):
    controller.device.work_state = 0
    controller.read()
    owner = object()
    controller.claim(owner)
    generation = controller.generation
    if cancel_during_read:
        read = controller.device.read_status
        def read_and_cancel():
            result = read()
            controller.invalidate_pending()
            return result
        monkeypatch.setattr(controller.device, 'read_status', read_and_cancel)
    else:
        controller.invalidate_pending()
    with pytest.raises(RuntimeError, match='取消'):
        controller.prepare_guided_start(owner, generation)
    assert not controller.device.commands


def test_status_reads_never_turn_reset_into_stop_command(controller):
    controller.device.work_state = 0
    for _ in range(3):
        state = controller.read()
        assert state['work_state'] == 0 and not state['stop_confirmed']
    assert not controller.device.commands


def stable_read(control, clock, position):
    control.device.position, control.device.work_state = position, 0x20
    control.read()
    clock.advance(.1)
    return control.read()


def test_never_connected_controller_does_not_block_unrelated_experiments(clock):
    control = TurntableController(TurntableConfig(), device=FakeDevice(connected=False))
    control.require_idle()
    assert not control.summary()['connected']
    assert not control.device.commands and control.device.read_count == 0


def test_pending_motion_blocks_duplicate_and_experiment_guard_before_send(controller, monkeypatch):
    send = controller.device.send_command
    def pending(request):
        with pytest.raises(RuntimeError):
            controller.require_idle()
        send(request)
    monkeypatch.setattr(controller.device, 'send_command', pending)
    assert move(controller)['result'] == 'accepted'
    with pytest.raises(RuntimeError):
        move(controller)
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['move_relative']


def test_completion_requires_target_and_two_distinct_stable_samples(controller, clock):
    move(controller)
    controller.device.position, controller.device.work_state = 100, 0x20
    controller.read()
    assert controller.action['result'] == 'accepted'
    controller.read()
    assert controller.action['result'] == 'accepted'  # Same instant is not a second sample.
    clock.advance(.1)
    assert controller.read()['action']['result'] == 'completed'
    assert controller.stop_confirmed
    controller.require_idle()
    assert len(controller.device.commands) == 1


def test_wrong_final_position_remains_unknown_until_supervisor_stops(controller, clock):
    move(controller)
    assert stable_read(controller, clock, 90)['action']['result'] == 'unknown'
    assert not controller.stop_confirmed
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert len(controller.device.commands) == 1
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert '目标' in controller.action['error']
    assert controller.stop_confirmed
    assert [r['action'] for r in controller.device.commands] == ['move_relative', 'stop']
    controller.require_idle()


@pytest.mark.parametrize('moving', [False, True])
def test_read_failure_invalidates_state_without_sending_stop(controller, moving):
    if moving:
        move(controller)
    before = list(controller.device.commands)
    controller.device.reads.append(TimeoutError('injected read timeout'))
    result = controller.read()
    assert not result['read_ok'] and result['position'] is None and result['busy'] is None
    assert not result['stop_confirmed']
    assert controller.device.commands == before
    with pytest.raises(RuntimeError):
        controller.require_idle()
    if moving:
        assert result['action']['result'] == 'unknown'
        controller.device.work_state = 0x20
        controller.read()
        with pytest.raises(RuntimeError):
            move(controller)  # A later idle read cannot erase an ambiguous motion.


def test_motion_write_failure_does_not_retry_and_requires_explicit_stop(controller):
    controller.device.write_error = OSError('injected partial write')
    with pytest.raises(OSError, match='partial write'):
        move(controller)
    assert controller.action['result'] == 'unknown'
    with pytest.raises(RuntimeError):
        move(controller)
    assert len(controller.device.commands) == 1
    controller.device.write_error = None
    assert controller.stop()
    controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['move_relative', 'stop']


def test_lost_connection_discards_last_successful_status(controller):
    move(controller)
    assert controller.read()['read_ok']
    controller.device.connected = False
    result = controller.read()
    assert not result['connected'] and not result['read_ok']
    assert result['position'] is None and result['busy'] is None
    assert result['action']['result'] == 'unknown'
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['move_relative']


def test_intentional_confirmed_disconnect_remains_idle_after_status_read(controller):
    assert controller.disconnect()['connected'] is False
    assert controller.read()['read_ok'] is False
    controller.require_idle()


def test_idle_guard_detects_cable_loss_before_next_read(controller):
    controller.require_idle()
    controller.device.connected = False
    before = controller.device.read_count
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert controller.device.read_count == before
    assert not controller.device.commands


def test_stop_after_cable_loss_invalidates_prior_confirmed_stop_immediately(controller):
    assert controller.stop()
    assert controller.summary()['stop_confirmed'] and controller.summary()['read_ok']
    controller.device.connected = False
    assert controller.stop() is False
    result = controller.summary()
    assert not result['stop_confirmed'] and not result['read_ok']
    assert result['motion_blocked']
    assert result['position'] is None and result['busy'] is None
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['stop']


def test_disconnect_cannot_erase_motion_after_cable_loss_before_next_read(controller):
    move(controller)
    controller.device.connected = False
    with pytest.raises((RuntimeError, OSError)):
        controller.disconnect()
    assert not controller.device.disconnect_calls
    assert controller.action['result'] in ('accepted', 'unknown')
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['move_relative']


def test_reconnect_does_not_complete_or_resume_previous_pending_motion(controller, clock, monkeypatch):
    from src.web import turntable_control

    move(controller)
    controller.device.connected = False
    controller.device.position, controller.device.work_state = 100, 0x20
    monkeypatch.setattr(turntable_control, 'resolve_connection', lambda _config: SimpleNamespace(
        binding_resolved=True, resolved_port='TEST'))
    connected = controller.connect()
    assert connected['connected'] and connected['action']['result'] == 'unknown'
    clock.advance(.1)
    observed = controller.read()
    assert observed['action']['result'] == 'unknown' and not observed['homed']
    with pytest.raises(RuntimeError):
        controller.require_idle()
    with pytest.raises(RuntimeError):
        move(controller)
    assert [r['action'] for r in controller.device.commands] == ['move_relative']
    assert controller.stop()
    controller.require_idle()
    assert controller.action['result'] == 'stopped'
    assert [r['action'] for r in controller.device.commands] == ['move_relative', 'stop']


def test_stopped_state_still_changing_coordinates_is_not_confirmed(controller):
    controller.device.reads.extend([(1, 0x20), (2, 0x20), (3, 0x20), (3, 0x20)])
    before = controller.device.read_count
    assert controller.stop()
    assert controller.device.read_count - before == 4
    assert controller.stop_confirmed


@pytest.mark.parametrize('confirmation', ['stop', 'completed_move'])
def test_coordinate_drift_revokes_stop_until_two_new_stable_reads(controller, clock, confirmation):
    if confirmation == 'stop':
        assert controller.stop()
    else:
        move(controller)
        stable_read(controller, clock, 100)
    assert controller.stop_confirmed
    commands = list(controller.device.commands)
    for _ in range(2):
        controller.device.position += 10
        clock.advance(.1)
        state = controller.read()
        assert not state['stop_confirmed'] and state['motion_blocked']
        with pytest.raises(RuntimeError):
            controller.require_idle()
        with pytest.raises(RuntimeError):
            move(controller)
    clock.advance(.1)
    state = controller.read()
    assert state['stop_confirmed'] and not state['motion_blocked']
    controller.require_idle()
    assert controller.device.commands == commands


def test_motion_preflight_rejects_newly_observed_coordinate_drift(controller, clock):
    assert controller.stop()
    controller.device.position += 1
    clock.advance(.1)
    with pytest.raises(RuntimeError):
        move(controller)
    assert [r['action'] for r in controller.device.commands] == ['stop']
    assert not controller.stop_confirmed and controller.summary()['motion_blocked']


def test_successful_stop_seeds_stability_at_the_final_position(controller, clock):
    move(controller)
    controller.device.position = 50
    assert controller.stop()
    clock.advance(.1)
    state = controller.read()
    assert state['stop_confirmed'] and not state['motion_blocked']
    controller.require_idle()


def test_stability_recovery_does_not_clear_a_failed_explicit_stop(controller, clock):
    assert controller.stop()
    controller.device.position += 1
    clock.advance(.1)
    assert controller.read()['motion_blocked']
    controller.device.reads.extend(OSError('stop response lost') for _ in range(40))
    assert not controller.stop()
    controller.device.reads.clear()
    stable_read(controller, clock, controller.device.position)
    assert not controller.stop_confirmed and controller.summary()['motion_blocked']
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert controller.stop()
    controller.require_idle()


def test_snapshot_order_covers_commands_and_errors_without_read_timestamps(controller):
    before = controller.summary()
    move(controller)
    accepted = controller.summary()
    assert accepted['action']['result'] == 'accepted' and accepted['read_at'] is None
    controller.device.reads.append(OSError('injected read failure'))
    failed = controller.read()
    assert not failed['read_ok'] and failed['read_at'] is None
    assert before['state_session'] == accepted['state_session'] == failed['state_session']
    assert before['state_revision'] < accepted['state_revision'] < failed['state_revision']
    assert datetime.fromisoformat(before['state_session']).utcoffset().total_seconds() == 0


@pytest.mark.parametrize('release_fails_once', [False, True])
def test_desktop_exit_releases_never_connected_turntable_after_open_failure(
        api_app, monkeypatch, release_fails_once):
    from src.desktop.lifecycle import DesktopShutdown
    from src.web import turntable_control

    device = FakeDevice(connected=False)
    control = TurntableController(TurntableConfig(), device=device)
    api_app.state.device_manager.turntables['turntable1'] = control
    monkeypatch.setattr(turntable_control, 'resolve_connection', lambda _: SimpleNamespace(
        binding_resolved=True, resolved_port='TEST'))
    monkeypatch.setattr(device, 'connect', Mock(side_effect=OSError('injected Windows error 31')))
    with pytest.raises(OSError):
        control.connect()
    disconnect = device.disconnect
    outcomes = [False, True] if release_fails_once else [True]
    def release():
        return disconnect() if outcomes.pop(0) else False
    monkeypatch.setattr(device, 'disconnect', Mock(side_effect=release))

    async def scenario():
        shutdown = api_app.state.desktop_shutdown = DesktopShutdown(api_app)
        result = await shutdown.shutdown()
        if release_fails_once:
            assert not result['success'] and shutdown.exiting
            result = await shutdown.shutdown()
        assert result['success'], result
        assert shutdown.succeeded
    asyncio.run(scenario())
    assert device.disconnect_calls == 1 and not device.commands
    assert not control.summary()['connected']
    control.require_idle()


def test_failed_stop_retains_connection_blocks_motion_and_allows_retry(controller):
    move(controller)
    controller.device.stop_ok = False
    assert controller.stop() is False
    assert controller.device.is_connected() and not controller.stop_confirmed
    with pytest.raises(RuntimeError):
        controller.require_idle()
    with pytest.raises(RuntimeError):
        move(controller)
    with pytest.raises(OSError, match='保留连接'):
        controller.disconnect()
    assert not controller.device.disconnect_calls
    controller.device.stop_ok = True
    assert controller.stop()
    controller.require_idle()
    assert controller.disconnect()['connected'] is False
    assert controller.device.disconnect_calls == 1


@pytest.mark.parametrize('error', [OSError('Undefined CL-01A work state: 0x10'),
                                  TimeoutError('short status frame')])
def test_stop_rechecks_after_bad_read_without_resending(controller, error):
    device = controller.device
    device.reads.extend([(17, 0x20), error, (17, 0x20), (17, 0x20)])
    before = device.read_count
    assert controller.stop()
    assert device.read_count - before == 4
    assert [r['action'] for r in device.commands] == ['stop']
    assert controller.stop_confirmed


def test_stop_persistent_read_errors_remain_blocked_at_deadline(controller, clock, monkeypatch):
    def unreadable():
        raise OSError('Undefined CL-01A work state: 0x10')
    monkeypatch.setattr(controller.device, 'read_status', unreadable)
    started = clock.now
    assert not controller.stop()
    assert 3 <= clock.now - started < 3.2
    assert not controller.stop_confirmed
    assert controller.device.is_connected()
    with pytest.raises(RuntimeError):
        controller.require_idle()
    assert [r['action'] for r in controller.device.commands] == ['stop']


def test_stop_does_not_accept_a_read_finishing_after_deadline(controller, clock, monkeypatch):
    read = controller.device.read_status
    def delayed_read():
        clock.advance(1.6)
        return read()
    monkeypatch.setattr(controller.device, 'read_status', delayed_read)
    assert not controller.stop()
    assert not controller.stop_confirmed


def test_stop_write_failure_is_not_retried(controller):
    controller.device.write_error = OSError('stop write failed')
    before = controller.device.read_count
    assert not controller.stop()
    assert controller.device.read_count == before
    assert [r['action'] for r in controller.device.commands] == ['stop']
    assert not controller.stop_confirmed


def test_run_stop_transient_unknown_state_can_complete(controller, clock):
    controller.command(dict(action='run', direction='negative', speed=400, duration_seconds=1))
    controller.read()
    clock.advance(1)
    controller.device.reads.extend([
        OSError('Undefined CL-01A work state: 0x10'), (17, 0x20), (17, 0x20)])
    controller.enforce_timeout()
    assert controller.action['result'] == 'completed'
    assert controller.stop_confirmed
    assert [r['action'] for r in controller.device.commands] == ['run', 'stop']


def test_observed_run_stop_failure_does_not_claim_running_was_unobserved(controller, clock, monkeypatch):
    controller.command(dict(action='run', direction='positive', speed=400, duration_seconds=1))
    controller.read()
    clock.advance(1)
    def unreadable():
        raise OSError('Undefined CL-01A work state: 0x10')
    monkeypatch.setattr(controller.device, 'read_status', unreadable)
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert '未确认连续运行' not in controller.action['error']
    assert '停止未确认' in controller.action['error']
    assert not controller.stop_confirmed


def test_run_stops_at_backend_deadline_and_is_not_replayed(controller, clock):
    controller.command(dict(action='run', direction='positive', speed=400, duration_seconds=10))
    clock.advance(9.9)
    controller.enforce_timeout()
    assert controller.action['result'] == 'running' and len(controller.device.commands) == 1
    clock.advance(.1)
    controller.enforce_timeout()
    assert controller.action['result'] == 'completed' and controller.stop_confirmed
    assert [r['action'] for r in controller.device.commands] == ['run', 'stop']
    controller.enforce_timeout()
    assert len(controller.device.commands) == 2


def test_run_ending_early_is_failed_not_success(controller, clock):
    controller.command(dict(action='run', direction='negative', speed=400, duration_seconds=10))
    stable_read(controller, clock, -25)
    assert controller.action['result'] == 'unknown'
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert '提前停止' in controller.action['error']
    assert controller.stop_confirmed


def test_run_without_observed_running_never_completes_at_deadline(controller, clock):
    controller.command(dict(action='run', direction='positive', speed=400, duration_seconds=10))
    controller.device.work_state = 0x20  # Simulate firmware ignoring the request.
    clock.advance(10)
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert '未确认连续运行' in controller.action['error']
    assert controller.stop_confirmed
    assert [r['action'] for r in controller.device.commands] == ['run', 'stop']


def test_target_report_after_deadline_cannot_complete_finite_motion(controller, clock, monkeypatch):
    move(controller)
    clock.advance(controller.config.action_timeout - .05)
    controller.device.position, controller.device.work_state = 100, 0x20
    controller.read()  # One good but insufficient observation before timeout.
    original_read = controller.device.read_status
    def delayed_read():
        clock.advance(.1)
        return original_read()
    monkeypatch.setattr(controller.device, 'read_status', delayed_read)
    result = controller.read()
    assert result['action']['result'] == 'unknown'
    assert '超时' in result['action']['error']
    assert not result['stop_confirmed']
    assert [r['action'] for r in controller.device.commands] == ['move_relative']
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed' and controller.stop_confirmed


def test_finite_action_timeout_stops_once_and_preserves_failure(controller, clock):
    move(controller)
    clock.advance(controller.config.action_timeout)
    controller.enforce_timeout()
    assert controller.action['result'] == 'failed'
    assert '超时' in controller.action['error'] and controller.stop_confirmed
    assert [r['action'] for r in controller.device.commands] == ['move_relative', 'stop']
    controller.enforce_timeout()
    assert len(controller.device.commands) == 2


@pytest.mark.parametrize('action,config', [
    (dict(action='move_absolute', position=100, speed=400), dict(position_encoding_verified=False)),
    (dict(action='home', direction='positive', speed=400), dict(home_enabled=False)),
])
def test_unverified_position_and_home_are_disabled_before_io(action, config, clock):
    device = FakeDevice()
    control = TurntableController(TurntableConfig(**config), device=device)
    with pytest.raises(RuntimeError):
        control.command(action)
    assert not device.commands and device.read_count == 0


def test_reset_zero_does_not_complete_motion_or_restore_home(controller):
    move(controller)
    controller.homed = True
    controller.device.position, controller.device.work_state = 0, 0
    result = controller.read()
    assert result['action']['result'] == 'unknown'
    assert not result['homed'] and not result['stop_confirmed']
    assert len(controller.device.commands) == 1


@pytest.mark.parametrize('observe_homing', [False, True])
def test_home_completion_requires_actual_homing_state(controller, clock, observe_homing):
    controller.config.home_enabled = True
    controller.command(dict(action='home', direction='negative', speed=400))
    if observe_homing:
        controller.read()
    result = stable_read(controller, clock, 0)
    assert result['action']['result'] == ('completed' if observe_homing else 'unknown')
    assert result['homed'] is observe_homing


def test_guard_never_waits_on_serial_lock_and_stale_status_blocks(controller, clock):
    entered, release = threading.Event(), threading.Event()
    def occupy_serial():
        with controller.lock:
            entered.set()
            assert release.wait(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        occupied = workers.submit(occupy_serial)
        assert entered.wait(2)
        try:
            workers.submit(controller.require_idle).result(timeout=.5)
            clock.advance(7)
            with pytest.raises(RuntimeError, match='过期'):
                workers.submit(controller.require_idle).result(timeout=.5)
        finally:
            release.set()
        occupied.result(timeout=2)


def test_stop_invalidates_queued_motion_before_acquiring_serial_lock(controller):
    stop_intent = threading.Event()
    original = controller.begin_stop
    def begin_stop():
        original()
        stop_intent.set()
    controller.begin_stop = begin_stop
    generation = controller.generation
    with ThreadPoolExecutor(max_workers=2) as workers:
        with controller.lock:
            queued = workers.submit(controller.command,
                dict(action='move_relative', steps=100, speed=400), expected_generation=generation)
            stopping = workers.submit(controller.stop)
            assert stop_intent.wait(2), 'STOP intent must not wait on serial lock'
        with pytest.raises(RuntimeError, match='取消'):
            queued.result(timeout=2)
        assert stopping.result(timeout=2)
    assert [r['action'] for r in controller.device.commands] == ['stop']


def test_real_manager_guard_checks_controller_and_allows_empty_manager(controller):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    dm.require_turntables_idle()
    dm.turntables['turntable1'] = controller
    dm.require_turntables_idle()
    move(controller)
    with pytest.raises(RuntimeError):
        dm.require_turntables_idle()
    controller.device.reads.append(OSError('read failed'))
    controller.read()
    with pytest.raises(RuntimeError):
        dm.require_turntables_idle()
    controller.device.stop_ok = False
    assert not controller.stop()
    with pytest.raises(RuntimeError):
        dm.require_turntables_idle()
    controller.device.stop_ok = True
    assert controller.stop()
    dm.require_turntables_idle()


@pytest.mark.parametrize('operation', ['cleanup', 'emergency_stop_all'])
def test_manager_failed_stop_preserves_connection_and_reports_failure(controller, operation):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    dm.turntables['turntable1'] = controller
    move(controller)
    controller.device.stop_ok = False
    assert getattr(dm, operation)() is False
    assert controller.device.is_connected() and not controller.device.disconnect_calls
    assert not controller.stop_confirmed and dm._global_stop_depth == 0
    if operation == 'emergency_stop_all':
        report = dm.get_last_emergency_stop_report()[0]
        assert report['device_id'] == 'turntable1'
        assert report['physical_stop_confirmed'] is False
    controller.device.stop_ok = True
    assert getattr(dm, operation)() is True
    assert controller.device.is_connected() is (operation == 'emergency_stop_all')
    assert dm._global_stop_depth == 0


def test_manager_stop_only_cleanup_retains_connected_turntable(controller):
    from src.web.device_manager import DeviceManager

    dm = DeviceManager()
    assert dm.cleanup() is True
    dm.turntables['turntable1'] = controller
    move(controller)
    assert dm.cleanup(disconnect=False) is True
    assert controller.stop_confirmed and controller.device.is_connected()
    assert not controller.device.disconnect_calls


def test_real_api_stop_survives_desktop_exit_and_global_stop_gate(api_app, controller, monkeypatch):
    from src.web.api import experiments

    move(controller)
    api_app.state.desktop_shutdown = SimpleNamespace(exiting=True)
    api_app.state.device_manager._begin_global_stop()
    monkeypatch.setattr(experiments, '_desktop_exiting', True)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            before = list(controller.device.commands)
            response = await client.post('/api/turntable/turntable1/command',
                json=dict(action='run', direction='positive', speed=400))
            assert response.status_code == 409
            assert controller.device.commands == before
            response = await client.post('/api/turntable/turntable1/command', json={'action': 'stop'})
            assert response.status_code == 200, response.text
            assert response.json()['state']['stop_confirmed']
            assert [r['action'] for r in controller.device.commands] == ['move_relative', 'stop']
    asyncio.run(scenario())


def test_http_stop_intent_cancels_motion_queued_on_shared_registration_lock(api_app, controller):
    from src.web.api import experiments

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            await experiments._source_lock.acquire()
            try:
                moving = asyncio.create_task(client.post('/api/turntable/turntable1/command',
                    json=dict(action='move_relative', steps=100, speed=400)))
                await asyncio.sleep(0)
                stopping = asyncio.create_task(client.post('/api/turntable/turntable1/command', json={'action': 'stop'}))
                await asyncio.sleep(0)
                assert controller.stopping == 1
                newer = asyncio.create_task(client.post('/api/turntable/turntable1/command',
                    json=dict(action='move_relative', steps=200, speed=400)))
                await asyncio.sleep(0)
                assert not controller.device.commands
            finally:
                experiments._source_lock.release()
            moved, stopped, moved_newer = await asyncio.wait_for(asyncio.gather(moving, stopping, newer), 2)
            assert moved.status_code == 409
            assert moved_newer.status_code == 409
            assert stopped.status_code == 200, stopped.text
            assert not controller.stopping
            assert [r['action'] for r in controller.device.commands] == ['stop']
    asyncio.run(scenario())


def test_cancelled_http_stop_releases_stop_intent_and_preserves_read_access(api_app, controller):
    from src.web.api import experiments

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            before_generation = controller.generation
            await experiments._source_lock.acquire()
            try:
                stopping = asyncio.create_task(client.post('/api/turntable/turntable1/command', json={'action': 'stop'}))
                await asyncio.sleep(0)
                assert controller.stopping == 1
                stopping.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await stopping
                assert controller.stopping == 0
                assert controller.generation > before_generation
                response = await client.get('/api/turntable/turntable1/status')
                assert response.status_code == 200
                assert not controller.device.commands
            finally:
                experiments._source_lock.release()
            response = await client.post('/api/turntable/turntable1/command', json={'action': 'stop'})
            assert response.status_code == 200
            assert not controller.stopping
    asyncio.run(scenario())


def test_cancelled_http_motion_holds_registration_until_worker_finishes(api_app, controller, monkeypatch):
    from src.web.api import experiments

    api_app.include_router(experiments.router, prefix='/api')
    entered, release = threading.Event(), threading.Event()
    original_read = controller.device.read_status

    def blocked_read():
        entered.set()
        assert release.wait(3), 'Test must release synchronous preflight'
        return original_read()
    monkeypatch.setattr(controller.device, 'read_status', blocked_read)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            moving = asyncio.create_task(client.post('/api/turntable/turntable1/command',
                json=dict(action='move_relative', steps=100, speed=400)))
            experiment = None
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                assert experiments._source_lock.locked()
                moving.cancel()
                await asyncio.sleep(0)
                assert experiments._source_lock.locked()
                assert not moving.done()
                experiment = asyncio.create_task(client.post('/api/experiments/demo.yaml/start', json={}))
                await asyncio.sleep(0)
                assert not experiment.done()
                assert not controller.device.commands
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(moving, 2)
            assert not experiments._source_lock.locked()
            assert controller.action['result'] == 'accepted'
            assert [r['action'] for r in controller.device.commands] == ['move_relative']
            with pytest.raises(RuntimeError):
                controller.require_idle()
            assert experiment is not None
            response = await asyncio.wait_for(experiment, 2)
            assert response.status_code == 409
            assert '转盘' in response.json()['detail']
    asyncio.run(scenario())


@pytest.mark.parametrize('state,cleanup', [('running', False), ('paused', False), ('failed', True)])
def test_real_api_motion_rejected_during_experiment_and_stop_requests_runner_stop(
        api_app, controller, state, cleanup):
    from src.web.api import experiments

    runner = SimpleNamespace(state=SimpleNamespace(value=state), cleanup_pending=cleanup, request_stop=Mock())
    experiments._engines['experiment.yaml'] = runner

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url='http://heat.test') as client:
            response = await client.post('/api/turntable/turntable1/command',
                json=dict(action='run', direction='positive', speed=400))
            assert response.status_code == 409
            assert not controller.device.commands
            response = await client.get('/api/turntable/turntable1/status')
            assert response.status_code == 200 and not controller.device.commands
            response = await client.post('/api/turntable/turntable1/command', json={'action': 'stop'})
            assert response.status_code == 200, response.text
            runner.request_stop.assert_called_once()
            assert [r['action'] for r in controller.device.commands] == ['stop']
    asyncio.run(scenario())
