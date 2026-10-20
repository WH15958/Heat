"""Finite startup verification and diagnostic persistence, without hardware."""
import asyncio
import json
import threading
from copy import deepcopy

import pytest

from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.protocols.microwave_params import CONTROL_WORD, auto_power_segment_start
from src.web.device_manager import DeviceManager
from test_microwave_atomic_config import make_device


def configured():
    device, protocol = make_device()
    assert device.configure_auto_power([dict(segment=n, target_temperature=60,
        holding_temperature=60, minutes=31) for n in range(1, 6)])
    return device, protocol


@pytest.mark.parametrize('failure', ['reload', 'read_failure'])
def test_post_start_change_or_unreadable_parameters_rejects_start(failure):
    device, protocol = configured()
    original_read = protocol.read_holding_registers
    reads = []
    def read(slave, address, count):
        if protocol.single_writes and address == auto_power_segment_start(1):
            reads.append(address)
            if failure == 'read_failure':
                return None
            protocol.registers[address+3] = 5
        return original_read(slave, address, count)
    protocol.read_holding_registers = read
    assert not device.start('auto_power')
    assert 'post-start configuration mismatch' in device.last_command_error
    assert reads == [auto_power_segment_start(1)]
    assert device.last_command_result['configuration_verified'] is False
    assert len(protocol.single_writes) == 1


def test_success_reads_each_written_block_once_and_preserves_expected_actual():
    device, protocol = configured()
    read = protocol.read_holding_registers
    addresses = []
    def observe(slave, address, count):
        if auto_power_segment_start(1) <= address <= auto_power_segment_start(5):
            addresses.append(address)
        return read(slave, address, count)
    protocol.read_holding_registers = observe
    assert device.start('auto_power')
    assert addresses == [auto_power_segment_start(n) for n in range(1, 6)]
    result = device.last_command_result
    assert result['configuration_verified'] and result['success']
    assert all(block['expected'] == block['actual'] for block in result['blocks'])
    assert result['after_verification']['control_active'] is True


def test_stop_intent_cancels_remaining_configuration_reads():
    device, protocol = configured()
    read = protocol.read_holding_registers
    checks = []
    cancelled = False
    def observe(slave, address, count):
        nonlocal cancelled
        if address == auto_power_segment_start(1):
            checks.append(address)
            cancelled = True
        return read(slave, address, count)
    protocol.read_holding_registers = observe
    assert not device.start('auto_power', should_stop=lambda: cancelled)
    assert checks == [auto_power_segment_start(1)]
    assert 'stop request' in device.last_command_error
    assert len(device.last_command_result['blocks']) == 1


def test_manager_stop_generation_is_checked_between_verification_reads():
    device, protocol = configured()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    read = protocol.read_holding_registers
    def observe(slave, address, count):
        if address == auto_power_segment_start(1):
            dm._request_microwave_stop('mw1')
        return read(slave, address, count)
    protocol.read_holding_registers = observe
    assert not dm.start_microwave('mw1', 'auto_power')
    assert len(device.last_command_result['blocks']) == 1
    assert dm.stop_microwave('mw1', source='user_stop')
    assert dm.get_microwave_events('mw1', 0)[1][-1]['source'] == 'user_stop'


def test_engine_stop_request_preempts_remaining_startup_verification_reads():
    device, protocol = configured()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    engine = ExperimentEngine(StepExecutor(dm))
    engine.load_steps([ExperimentStep('start', ActionType.MICROWAVE_START,
                                      dict(device_id='mw1', mode='auto_power'))])
    read = protocol.read_holding_registers
    addresses = []
    stopped = threading.Event()
    async def scenario():
        loop = asyncio.get_running_loop()
        def stop():
            engine.request_stop()
            stopped.set()
        def observe(slave, address, count):
            if auto_power_segment_start(1) <= address <= auto_power_segment_start(5):
                addresses.append(address)
                loop.call_soon_threadsafe(stop)
                assert stopped.wait(timeout=2)
            return read(slave, address, count)
        protocol.read_holding_registers = observe
        await engine.start()
        await engine.wait_finished()
    asyncio.run(scenario())
    assert addresses == [auto_power_segment_start(1)]
    assert engine.state.value == 'stopped'
    events = engine.exp_logger.active_run.microwave_events
    assert events[0]['action'] == 'start' and events[0]['success'] is False
    assert events[-1]['action'] == 'stop' and events[-1]['source'] == 'user_stop'


@pytest.mark.parametrize('failure', ['block_exception', 'final_status'])
def test_post_start_verification_exceptions_return_failure_with_evidence(failure):
    device, protocol = configured()
    read = protocol.read_holding_registers
    def observe(slave, address, count):
        if protocol.single_writes:
            if failure == 'block_exception' and address == auto_power_segment_start(1):
                raise IOError('verification connection lost')
            if failure == 'final_status' and len(device.last_command_result['blocks']) == 5:
                raise IOError('final status lost')
        return read(slave, address, count)
    protocol.read_holding_registers = observe
    assert device.start('auto_power') is False
    assert 'failed' in device.last_command_error
    assert device.last_command_result['success'] is False
    if failure == 'block_exception':
        assert device.last_command_result['blocks'][0]['error'] == 'verification connection lost'
        assert device._expected_configuration is None


@pytest.mark.parametrize('mode', ['manual_power', 'auto_power', 'constant_rate'])
def test_each_mode_verifies_only_its_written_blocks(mode):
    device, protocol = make_device()
    method = 'configure_manual' if mode == 'manual_power' else 'configure_' + mode
    assert getattr(device, method)([dict(segment=2, target_temperature=60)])
    expected = deepcopy(device.last_command_result['blocks'])
    assert device.start(mode)
    assert [block['address'] for block in device.last_command_result['blocks']] == [
        block['address'] for block in expected]


@pytest.mark.parametrize('source', ['manual_stop', 'user_stop', 'normal_cleanup', 'emergency_stop'])
def test_stop_sources_and_written_control_words_are_preserved(source):
    device, protocol = make_device()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    assert dm.stop_microwave('mw1', source=source)
    event = dm.get_microwave_events('mw1', 0)[1][-1]
    assert event['source'] == source and event['success']
    assert event['result']['written_control_word'] == 0
    assert event['result']['after_stop']['stop_confirmed'] is True


def test_incomplete_diagnostic_buffer_has_an_explicit_gap_marker():
    dm = DeviceManager()
    for index in range(201):
        dm._record_microwave_event('mw1', 'state_change', 'observation', value=index)
    _, events = dm.get_microwave_events('mw1', 0)
    assert events[0]['action'] == 'diagnostic_gap'
    assert len(events) == 201


def test_failed_reconfiguration_invalidates_previous_qualification():
    device, protocol = configured()
    assert not device.configure_auto_power([dict(segment=1, target_temperature=60.9)])
    assert not device.start('auto_power')
    assert protocol.single_writes == []


def test_disconnect_clears_configuration_for_new_session():
    device, protocol = configured()
    device.disconnect()
    assert device._expected_configuration is None
    assert device._configuration_attempted is False


@pytest.mark.parametrize('cleanup_ok', [True, False])
def test_failed_start_saves_diagnostics_and_keeps_original_error(cleanup_ok):
    device, protocol = make_device()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    write = protocol.write_single_register
    def reload(slave, address, value):
        result = write(slave, address, value)
        if address == CONTROL_WORD and value:
            protocol.registers[auto_power_segment_start(1)+3] = 5
        return result if value or cleanup_ok else False
    protocol.write_single_register = reload
    engine = ExperimentEngine(StepExecutor(dm))
    engine.load_steps([
        ExperimentStep('configure', ActionType.MICROWAVE_CONFIGURE_AUTO_POWER,
            dict(device_id='mw1', segments=[dict(segment=1, target_temperature=60, minutes=31)])),
        ExperimentStep('start', ActionType.MICROWAVE_START, dict(device_id='mw1', mode='auto_power'))])
    async def scenario():
        await engine.start()
        await engine.wait_finished()
    asyncio.run(scenario())
    run = engine.exp_logger.active_run
    assert engine.state.value == 'failed'
    assert 'post-start configuration mismatch' in run.steps[1]['error']
    events = run.microwave_events
    assert [e['action'] for e in events] == ['configure_auto_power', 'start', 'stop']
    assert events[-1]['source'] == 'failure_cleanup'
    assert events[-1]['success'] is cleanup_ok
    saved = json.loads(json.dumps(run.to_dict()))
    assert saved['steps'][0]['device_result']['microwave_events'][0]['result']['blocks']
    on_disk = json.loads(engine.exp_logger._log_filepath(run).read_text(encoding='utf-8'))
    assert on_disk['microwave_events'] == saved['microwave_events']
    frozen = deepcopy(events[1])
    dm.stop_microwave('mw1', source='manual_stop')
    assert events[1] == frozen


def test_recovery_cleanup_persists_late_evidence_without_refinalizing_run(monkeypatch):
    device, protocol = make_device()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    write = protocol.write_single_register
    protocol.write_single_register = lambda *args: False
    engine = ExperimentEngine(StepExecutor(dm))
    engine.load_steps([ExperimentStep('start', ActionType.MICROWAVE_START,
                                      dict(device_id='mw1', mode='auto_power'))])
    async def scenario():
        await engine.start()
        await engine.wait_finished()
        assert engine.cleanup_pending
        run = engine.exp_logger.active_run
        original = (run.status, run.finished_at, run.total_duration, deepcopy(run.steps))
        monkeypatch.setattr(engine.exp_logger, '_write_sample_record',
                            lambda *args: pytest.fail('recovery must not rewrite sample records'))
        protocol.write_single_register = write
        assert await engine.stop()
        assert (run.status, run.finished_at, run.total_duration, run.steps) == original
        return run
    run = asyncio.run(scenario())
    saved = json.loads(engine.exp_logger._log_filepath(run).read_text(encoding='utf-8'))
    stops = [event for event in saved['microwave_events'] if event['action'] == 'stop']
    assert [event['success'] for event in stops] == [False, True]
    assert [event['source'] for event in stops] == ['failure_cleanup', 'user_stop']


def test_late_diagnostic_save_failure_is_exposed_without_changing_run_status(monkeypatch):
    from src.experiment.experiment_logger import ExperimentLogger
    log = ExperimentLogger()
    log.start_run('diagnostics', '', 0)
    log.finish_run('failed')
    run = log.active_run
    monkeypatch.setattr(log, '_save_to_file', lambda: False)
    log.record_microwave_events([dict(action='stop', source='user_stop', success=True)])
    assert run.status == 'failed'
    assert run.log_saved is False and run.persistence_status == 'error'
    assert 'microwave_diagnostics_not_saved' in run.persistence_errors


def test_existing_reads_record_transitions_and_temperature_source_without_extra_calls():
    device, protocol = make_device()
    dm = DeviceManager()
    dm._microwaves['mw1'] = device
    calls = []
    original = protocol.read_holding_registers
    protocol.read_holding_registers = lambda *args: (calls.append(args), original(*args))[1]
    dm.read_microwave_data('mw1')
    dm.read_microwave_data('mw1')
    assert len(calls) == 4  # Fake float reader returns None without a Modbus call.
    sequence, events = dm.get_microwave_events('mw1', 0)
    assert len(events) == 1
    assert events[0]['state']['temperature_source'] == 'raw'
    assert dm.get_microwave_events('mw1', sequence)[1] == []
