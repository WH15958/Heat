"""Stateful Modbus simulation for timed-speed setup; no physical serial I/O."""
import asyncio
import struct
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.devices.peristaltic_pump import LabSmartPumpDevice, PeristalticPumpConfig, PumpChannelConfig
from src.experiment.actions import ActionType, ExperimentStep
from src.experiment.executor import StepExecutor
from src.protocols.pump_params import PumpDirection, PumpRunMode
from src.web.api.devices import router
from test_pump_modbus_config_safety import _manager_with_pump


class RegisterPump:
    def __init__(self):
        self.registers = {4000: 1, 4001: 0, 4002: 1, 4004: 11, 4006: 0,
                          4100: 1, 4103: 0, 4106: 1, 4109: 1, 4112: 1}
        for address, value in ((4101, 1), (4104, 15), (4107, 1), (4110, 1.5)):
            self.put_float(address, value)
        self.calls = []
        self.after_write = lambda address: None
        self.fail_write = None
        self.fail_read = None
        self.fail_stop = False
        self.started = False

    def put_float(self, address, value):
        self.registers[address], self.registers[address+1] = struct.unpack('>HH', struct.pack('>f', value))

    def get_float(self, address):
        return struct.unpack('>f', struct.pack('>HH', self.registers[address], self.registers[address+1]))[0]

    def read_holding_registers(self, slave, address, count):
        self.calls.append(('read', address, count))
        if address == self.fail_read:
            return None
        return [self.registers.get(address+i, 0) for i in range(count)]

    def write_single_register(self, slave, address, value):
        return self.write(address, [int(value)])

    def read_float_register(self, slave, address):
        values = self.read_holding_registers(slave, address, 2)
        return None if values is None else struct.unpack('>f', struct.pack('>HH', *values))[0]

    def write_multiple_registers(self, slave, address, values):
        return self.write(address, values)

    def write(self, address, values):
        self.calls.append(('write', address, tuple(values)))
        if address == self.fail_write or (address == 4001 and values == [0] and self.started and self.fail_stop):
            return False
        self.registers.update({address+i: value for i, value in enumerate(values)})
        # Model mode/time coupling to expose order dependence, not a firmware claim.
        if address in (4006, 4107, 4109) and self.registers[4006] == 2:
            minutes = self.get_float(4107) * {0: 1/60, 1: 1, 2: 60}[self.registers[4109]]
            self.put_float(4110, self.get_float(4104) / minutes)
        if address == 4001 and values == [1]:
            self.started = True
        self.after_write(address)
        return True

    def disconnect(self):
        return True


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('Real hardware forbidden')))
    monkeypatch.setattr('src.devices.peristaltic_pump.time.sleep', lambda seconds: None)
    pump = LabSmartPumpDevice(PeristalticPumpConfig(device_id='pump1', channels=[
        PumpChannelConfig(channel=4, tube_model=11, max_flow_rate=18.75)]))
    wire = RegisterPump()
    pump._protocol = wire
    monkeypatch.setattr(pump, 'is_connected', lambda: True)
    return _manager_with_pump(pump), pump, wire


def start(dm, **changes):
    return dm.start_pump_channel(**{**dict(device_id='pump1', channel=4, flow_rate=15,
        direction=PumpDirection.COUNTER_CLOCKWISE, mode=PumpRunMode.TIME_SPEED,
        run_time=5, time_unit=1, flow_unit=1, tube_model=11, repeat_count=1), **changes})


def writes(wire, address):
    return [call[2] for call in wire.calls if call[:2] == ('write', address)]


def test_time_speed_sets_flow_in_target_mode_after_time(rig):
    dm, pump, wire = rig
    assert start(dm)
    assert wire.get_float(4110) == 15
    assert wire.get_float(4107) == 5
    assert writes(wire, 4006) == [(2,)]
    addresses = [c[1] for c in wire.calls if c[0] == 'write']
    assert addresses.index(4006) < addresses.index(4107) < addresses.index(4110) < addresses.index(4001, 1)
    assert not writes(wire, 4104) and not writes(wire, 4106)
    assert len(writes(wire, 4110)) == 1 and writes(wire, 4001) == [(0,), (1,)]


@pytest.mark.parametrize('address,value', [(4006, 1), (4110, 3), (4112, 0), (4107, 1),
                                          (4109, 0), (4100, 2), (4101, 3), (4103, 1)])
def test_final_configuration_mismatch_never_starts(rig, address, value):
    dm, pump, wire = rig
    def corrupt(written):
        if written == 4110:
            if address in (4110, 4107, 4101):
                wire.put_float(address, value)
            else:
                wire.registers[address] = value
    wire.after_write = corrupt
    assert not start(dm, interval_time=1, interval_time_unit=0)
    assert writes(wire, 4001) == [(0,)]
    assert 'expected=' in pump.last_command_error and 'readback=' in pump.last_command_error
    assert len(writes(wire, 4110)) == 1


def test_unreadable_final_flow_never_starts(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: setattr(wire, 'fail_read', 4110) if address == 4110 else None
    assert not start(dm)
    assert writes(wire, 4001) == [(0,)]
    assert 'readback=None' in pump.last_command_error
    assert sum(c[:2] == ('read', 4110) for c in wire.calls) == 3


@pytest.mark.parametrize('address', [4006, 4107, 4109, 4100, 4101, 4103, 4110, 4112])
def test_configuration_write_failure_is_not_retried(rig, address):
    dm, pump, wire = rig
    # Force a unit write even when the requested unit equals the initial unit.
    if address in (4109, 4103, 4112):
        wire.registers[address] = 2
    wire.fail_write = address
    assert not start(dm, interval_time=1)
    assert not wire.started
    assert len(writes(wire, address)) == 1
    assert pump.last_command_error


@pytest.mark.parametrize('stop_failure', [False, True, 'exception'])
def test_post_start_mismatch_stops_and_preserves_cause(rig, stop_failure):
    dm, pump, wire = rig
    def corrupt(address):
        if address == 4001 and wire.registers[4001] == 1:
            wire.put_float(4110, 3)
    wire.after_write = corrupt
    wire.fail_stop = stop_failure is True
    if stop_failure == 'exception':
        original = pump.stop_channel
        pump.stop_channel = lambda channel: (_ for _ in ()).throw(IOError('stop lost')) if wire.started else original(channel)
    assert not start(dm)
    assert writes(wire, 4001).count((1,)) == 1
    assert 'expected=15' in pump.last_command_error and 'readback=3' in pump.last_command_error
    assert ('停止未确认' if stop_failure else '停止已确认') in pump.last_command_error
    if not stop_failure:
        assert wire.registers[4001] == 0


def test_post_start_time_countdown_is_not_a_failure(rig):
    dm, pump, wire = rig
    def countdown(address):
        if address == 4001 and wire.registers[4001] == 1:
            wire.put_float(4107, 4.9)
    wire.after_write = countdown
    assert start(dm)


@pytest.mark.parametrize('failure', ['mode', 'unit', 'unreadable', 'exception', 'cancel', 'start_readback'])
def test_post_start_verification_failures_do_not_restart(rig, failure):
    dm, pump, wire = rig
    def corrupt(address):
        if address != 4001 or wire.registers[4001] != 1:
            return
        if failure == 'mode':
            wire.registers[4006] = 1
        elif failure == 'unit':
            wire.registers[4112] = 0
        elif failure == 'unreadable':
            wire.fail_read = 4110
        elif failure == 'exception':
            pump.read_float_value = Mock(side_effect=IOError('read lost'))
        elif failure == 'cancel':
            dm._request_pump_abort('pump1')
        else:
            wire.registers[4001] = 0
    wire.after_write = corrupt
    assert not start(dm)
    assert writes(wire, 4001) == [(0,), (1,), (0,)]
    assert '停止已确认' in pump.last_command_error


def test_stop_ack_without_stopped_readback_is_not_confirmed(rig):
    dm, pump, wire = rig
    def corrupt(address):
        if address == 4001 and wire.started:
            wire.put_float(4110, 3)
            wire.registers[4001] = 1
    wire.after_write = corrupt
    assert not start(dm)
    assert 'readback=3' in pump.last_command_error
    assert '停止未确认' in pump.last_command_error
    assert writes(wire, 4001) == [(0,), (1,), (0,)]


def test_mode_must_be_confirmed_before_setting_time(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: wire.registers.update({4006: 0}) if address == 4006 else None
    assert not start(dm)
    assert not writes(wire, 4107) and not wire.started


def test_configuration_read_exception_never_starts(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: setattr(pump, 'read_float_value', Mock(
        side_effect=IOError('read lost'))) if address == 4110 else None
    assert not start(dm)
    assert not wire.started
    assert 'read lost' in pump.last_command_error and '未启动' in pump.last_command_error


def test_stop_during_configuration_cancels_start(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: dm._request_pump_abort('pump1') if address == 4110 else None
    assert not start(dm)
    assert not wire.started


@pytest.mark.parametrize('mode', [PumpRunMode.FLOW_MODE, PumpRunMode.TIME_QUANTITY, PumpRunMode.QUANTITY_SPEED])
def test_other_modes_keep_existing_setup(rig, mode):
    dm, pump, wire = rig
    assert start(dm, mode=mode, dispense_volume=75)
    assert writes(wire, 4006) == ([(0,)] if mode == PumpRunMode.FLOW_MODE else [(0,), (int(mode),)])
    assert bool(writes(wire, 4104)) == (mode != PumpRunMode.FLOW_MODE)


def test_api_reports_specific_configuration_failure(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: wire.put_float(4110, 3) if address == 4110 else None
    app = FastAPI(); app.include_router(router, prefix='/api'); app.state.device_manager = dm
    with TestClient(app) as client:
        response = client.post('/api/pump/pump1/start', json=dict(channel=4, flow_rate=15,
            mode='TIME_SPEED', run_time=5, time_unit=1, flow_unit=1))
    assert response.status_code == 200
    data = response.json()
    assert data['success'] is False and data['flow_rate'] == 15 and data['mode'] == 'TIME_SPEED'
    assert 'expected=15' in data['error'] and 'readback=3' in data['error']


def test_yaml_time_speed_failure_has_no_completion_evidence(rig):
    dm, pump, wire = rig
    wire.after_write = lambda address: wire.put_float(4110, 3) if address == 4110 else None
    executor = StepExecutor(dm)
    step = ExperimentStep('drain', ActionType.PUMP_START, dict(device_id='pump1', channel=4,
        flow_rate=15, mode='TIME_SPEED', run_time=5, time_unit=1, flow_unit=1))
    assert not asyncio.run(executor.execute(step))
    assert 'readback=3' in executor.last_error
    assert ('pump1', 4) not in executor._pump_start_confirmed
