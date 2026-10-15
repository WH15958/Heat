"""Acceptance cases based on vendor status semantics and interruption requirements."""
import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.devices.heater import AIHeaterDevice, HeaterConfig
from src.experiment.actions import WaitCondition, WaitType
from src.experiment.executor import StepExecutor
from src.protocols.aibus import AIBUSProtocol
from src.protocols.parameters import RunStatus, get_parameter_info


@pytest.fixture(autouse=True)
def no_hardware(monkeypatch):
    monkeypatch.setattr('serial.Serial.open', Mock(side_effect=AssertionError('Physical serial forbidden')))


@pytest.mark.parametrize('state', [0, 1, 2, 3])
@pytest.mark.parametrize('flags', [0, 4, 8, 12])
def test_heater_decodes_real_aibus_status_parameter(state, flags):
    protocol = AIBUSProtocol('FAKE', address=1)
    status_word = 0x3f00 | flags | state
    # Vendor AIBUS ten-byte reply: PV/SV, MV/alarm, parameter, checksum.
    def reply(command):
        parameter = status_word if command[3] == 77 else 600
        values = [600, 600, 0, parameter]
        raw = struct.pack('<5H', *values, (sum(values) + 1) & 0xffff)
        return protocol._parse_response(raw)
    protocol._serial = SimpleNamespace(is_open=True)
    protocol._send_and_receive = reply
    heater = AIHeaterDevice(HeaterConfig(device_id='heater1', retry_count=1))
    heater._protocol = protocol
    data = heater.read_data()
    assert data.run_status == {0: RunStatus.RUN, 1: RunStatus.STOP, 2: RunStatus.HOLD, 3: RunStatus.UNKNOWN}[state]
    assert data.is_auto_tuning is bool(flags & 4)
    assert data.is_manual is bool(flags & 8)


@pytest.mark.parametrize('code', [75, 76, 77, 78])
def test_heater_parameter_metadata_uses_same_vendor_code(code):
    assert get_parameter_info(code).code == code


@pytest.mark.parametrize('address,hex_frame', [(0, '02 31 31 51 03 50'), (1, '02 32 31 51 03 53')])
def test_syringe_oem_sequence_is_fixed_per_manual_page_20(address, hex_frame):
    from src.protocols.syringe_pump import SyringeProtocol
    protocol = SyringeProtocol(None, address=address)
    for _ in range(9):
        assert protocol.frame('Q') == bytes.fromhex(hex_frame)


@pytest.mark.parametrize('kind', ['heater', 'pump', 'microwave'])
@pytest.mark.parametrize('interruption', ['stop', 'pause', 'timeout'])
def test_wait_rechecks_state_after_inflight_read(kind, interruption):
    async def scenario():
        dm = Mock()
        executor = StepExecutor(dm)
        state = dict(stop=False, pause=False, clock=0.0)
        executor.set_stop_checker(lambda: state['stop'])
        executor.set_pause_checker(lambda: state['pause'])
        executor._wait_clock = lambda: state['clock']
        reads = []
        def read(_):
            reads.append(1)
            if interruption == 'timeout':
                state['clock'] = 2.0
            else:
                state[interruption] = True
            return {
                'heater': dict(pv=60.0, sv=60.0),
                'pump': dict(channels={'1': dict(read_ok=True, running=False, run_status='STOP')}),
                'microwave': dict(completed=True, fault_code=0, stop_confirmed=True),
            }[kind]
        dm.read_heater_data = dm.read_pump_status = dm.read_microwave_data = read
        executor._pump_start_confirmed.add(('device', 1))
        condition = WaitCondition(type={'heater': WaitType.TEMPERATURE_REACHED,
            'pump': WaitType.PUMP_COMPLETE, 'microwave': WaitType.MICROWAVE_COMPLETE}[kind],
            device_id='device', channel=1, timeout=1)
        paused = asyncio.Event()
        async def resume():
            if state['pause']:
                paused.set()
                state['stop'] = True
                return None
            return 0
        executor._wait_for_resume = resume
        assert await executor._wait_condition(condition) is False
        assert len(reads) == 1
        if interruption == 'pause':
            assert paused.is_set(), 'A paused read must not complete the wait'
    asyncio.run(scenario())


@pytest.mark.parametrize('state', ['running', 'paused', 'cleanup'])
def test_manual_writes_cannot_change_a_regular_yaml_run(monkeypatch, state):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.web.api import experiments
    from src.web.api.devices import router
    engine = ExperimentEngine(StepExecutor(Mock()), exp_logger=Mock())
    engine._state = ExperimentState.FAILED if state == 'cleanup' else ExperimentState(state)
    if state == 'cleanup':
        engine._cleanup_result = False
    monkeypatch.setattr(experiments, '_engines', {'water.yaml': engine})
    app = FastAPI()
    app.include_router(router, prefix='/api')
    dm = Mock()
    dm.set_temperature.return_value = True
    dm.stop_heater.return_value = True
    dm.read_heater_data.return_value = {'pv': 25, 'sv': 60}
    app.state.device_manager = dm
    with TestClient(app) as client:
        changed = client.post('/api/heater/heater1/set_temperature', json={'temperature': 90})
        assert changed.status_code == 409
        dm.set_temperature.assert_not_called()
        assert client.get('/api/heater/heater1/data').status_code == 200
        stopped = client.post('/api/heater/heater1/stop')
        assert stopped.json()['success'] is True
        assert engine._stop_flag is True


def test_pump_log_does_not_invent_validity_or_stopped_state():
    from src.experiment.experiment_logger import ExperimentLogger, ExperimentRun
    logger = ExperimentLogger(save_log=False)
    logger._active_run = ExperimentRun('test', 'test', 'test.yaml')
    for values in ({'flow_rate': 10}, {'read_ok': True, 'flow_rate': 10}):
        logger.record_sensor_data({'pumps': {'pump1': {'channels': {'1': values}}}})
    series = logger.active_run.sensor_data['pumps']['pump1']['1']
    assert [p['v'] for p in series['read_ok']] == [False, True]
    assert [p['v'] for p in series['running']] == [None, None]
    assert series['flow_rate'][0]['v'] is None


def test_pump_history_does_not_label_changed_units_as_the_initial_unit():
    from src.experiment.experiment_logger import ExperimentLogger, ExperimentRun
    logger = ExperimentLogger(save_log=False)
    logger._active_run = ExperimentRun('test', 'test', 'test.yaml')
    for unit in ('ML_MIN', 'UL_MIN', 'ML_MIN'):
        logger.record_sensor_data({'pumps': {'pump1': {'channels': {'1': {
            'read_ok': True, 'running': True, 'flow_rate': 10, 'flow_unit': unit,
        }}}}})
    assert logger.active_run.sensor_data['pumps']['pump1']['1']['flow_unit'] == 'MIXED'


@pytest.mark.parametrize('payload', [{}, {'pumps': {'pump1': {'error': 'read_timeout'}}},
                                   {'pumps': {'pump1': {'channels': {}}}}])
def test_missing_pump_payload_leaves_explicit_history_gap(payload):
    from src.experiment.experiment_logger import ExperimentLogger, ExperimentRun
    logger = ExperimentLogger(save_log=False)
    logger._active_run = ExperimentRun('test', 'test', 'test.yaml')
    valid = {'pumps': {'pump1': {'channels': {'1': {
        'read_ok': True, 'running': True, 'flow_rate': 10, 'flow_unit': 'ML_MIN',
    }}}}}
    logger.record_sensor_data(valid)
    logger.record_sensor_data(payload)
    logger.record_sensor_data(valid)
    series = logger.active_run.sensor_data['pumps']['pump1']['1']
    assert [p['v'] for p in series['flow_rate']] == [10, None, 10]
    assert [p['v'] for p in series['read_ok']] == [True, False, True]


def test_heater_registry_exposes_configured_temperature_bounds():
    from src.web.device_manager import DeviceManager
    dm = DeviceManager()
    dm.add_heater('heater1', 'FAKE', min_temperature=10, max_temperature=80, safety_limit=70)
    status = dm.get_all_status()['heaters']['heater1']
    assert status['min_temperature'] == 10
    assert status['max_temperature'] == 70
