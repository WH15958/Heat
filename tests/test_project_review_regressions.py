"""Review regressions using fake devices and isolated persistence only."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
from src.experiment.engine import ExperimentEngine
from src.experiment.executor import StepExecutor
from src.web.device_manager import DeviceManager
from src.web.syringe_control import SyringeController


def test_global_emergency_stop_prevents_later_experiment_start(monkeypatch):
    from src.web.api import experiments
    from src.web.api.devices import emergency_stop

    async def scenario():
        calls = []
        dm = DeviceManager()
        dm._heaters['h'] = SimpleNamespace(
            config=SimpleNamespace(device_id='h'), is_connected=lambda: True,
            start=lambda: calls.append('start') or True,
            stop=lambda: calls.append('stop') or True,
            emergency_stop=lambda: calls.append('emergency_stop') or True,
        )
        entered = asyncio.Event()
        executor = StepExecutor(dm)
        original_sleep = executor._pause_aware_sleep

        async def sleep(seconds):
            entered.set()
            return await original_sleep(seconds)

        executor._pause_aware_sleep = sleep
        engine = ExperimentEngine(executor, Mock())
        engine.load_steps([
            ExperimentStep(id='wait', type=ActionType.WAIT,
                           wait=WaitCondition(type=WaitType.DURATION, seconds=1)),
            ExperimentStep(id='heat', type=ActionType.HEATER_START, params={'device_id': 'h'}),
        ])
        monkeypatch.setattr(experiments, '_engines', {'fake.yaml': engine})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(device_manager=dm)))
        await engine.start()
        await entered.wait()
        result = await emergency_stop(request)
        assert result['success'] is True
        assert calls == ['emergency_stop']
        assert engine.state.value == 'stopped'

    asyncio.run(scenario())


@pytest.mark.parametrize('terminal', [
    {'running': False, 'fault_code': 3, 'stop_confirmed': True},
    {'running': False, 'fault_code': 3, 'completed': True},
    {'running': False, 'fault_code': 0, 'control_active': True},
    {'running': False, 'fault_code': 0},
])
def test_microwave_fault_or_unconfirmed_output_stop_is_not_completion(terminal):
    payloads = [{'running': True, 'fault_code': 0}, terminal]
    executor = StepExecutor(SimpleNamespace(read_microwave_data=lambda _: payloads.pop(0) if len(payloads) > 1 else payloads[0]))
    condition = WaitCondition(type=WaitType.MICROWAVE_COMPLETE, device_id='m', timeout=.05)
    assert asyncio.run(executor._wait_condition(condition)) is False


@pytest.mark.parametrize('kind', ['heater', 'pump', 'microwave'])
def test_disconnected_fingerprint_binding_is_resolved_again(kind, monkeypatch):
    from src.utils.config import DeviceConnectionConfig, SerialBindingConfig
    from src.utils.serial_binding import SerialBindingResolution

    dm = DeviceManager()
    connection = DeviceConnectionConfig(port='COM10', binding=SerialBindingConfig(mode='fingerprint', serial_number='unique'))
    device = SimpleNamespace(is_connected=lambda: False, config=SimpleNamespace(connection_params={'port': 'COM10'}))
    binding = {'_connection_config': connection, 'resolved_port': 'COM10',
               'binding_resolved': True, 'connection_binding_mode': 'fingerprint'}
    resolver = Mock(return_value=SerialBindingResolution(
        resolved_port='COM20', connection_binding_mode='fingerprint', binding_label='unique',
        binding_resolved=True, binding_match_count=1, binding_error=None, binding_candidates=[]))
    monkeypatch.setattr('src.web.device_manager.resolve_connection', resolver)
    dm._refresh_binding_if_needed('device', kind, binding, device)
    resolver.assert_called_once_with(connection)
    assert device.config.connection_params['port'] == 'COM20'


def test_web_timeout_returns_unknown_without_waiting_for_controller_lock():
    from src.web.api.ws import build_realtime_payload

    async def scenario():
        class Coordinator:
            async def read(self, *args):
                raise asyncio.TimeoutError('timeout')

        controller = SimpleNamespace(
            config=SimpleNamespace(name='pump', capacity_ml=2.5,
                                   connection=SimpleNamespace(port='COM12', binding=SimpleNamespace(serial_number='id'))),
            read=Mock(), summary=Mock(side_effect=AssertionError('must not wait for I/O lock')),
            device=SimpleNamespace(is_connected=lambda: True,
                                   unknown=lambda error: {'read_ok': False, 'read_error': error}),
        )
        dm = SimpleNamespace(get_all_heaters=lambda: {}, get_all_pumps=lambda: {},
                             get_all_microwaves=lambda: {}, syringe_pumps={'s': controller})
        payload = await build_realtime_payload(dm, Coordinator())
        assert payload['syringe_pumps']['s']['read_ok'] is False
        controller.summary.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize('completed', [True, False])
def test_syringe_deadline_checks_fresh_completion_before_stopping(completed):
    action = {'result': 'accepted', 'deadline': 0}
    device = SimpleNamespace(action=action)
    controller = SyringeController(SimpleNamespace(), device=device)

    def read():
        if completed:
            action['result'] = 'completed'

    controller.read = Mock(side_effect=read)
    controller.stop = Mock(return_value=True)
    controller.enforce_timeout()
    controller.read.assert_called_once()
    assert action['result'] == ('completed' if completed else 'failed')
    assert controller.stop.call_count == (0 if completed else 1)


@pytest.mark.parametrize('interruption', [OSError, KeyboardInterrupt])
def test_recommendation_partial_write_recovers_original_pair(tmp_path, monkeypatch, interruption):
    from src.campaigns import store as module

    monkeypatch.setattr(module, 'CAMPAIGNS_DIR', tmp_path)
    for name, filename in [('CAMPAIGNS_JSON', 'campaigns.json'), ('TRIALS_JSON', 'trials.json'),
                           ('RECOMMENDATIONS_JSON', 'recommendations.json'), ('CHARACTERIZATIONS_JSON', 'characterizations.json')]:
        monkeypatch.setattr(module, name, tmp_path / filename)
    store = module.CampaignStore()
    first = store.create_recommendation(campaign_id='c', planner_name='manual', parameters_batch=[{'x': 1}])
    write = module._write_json
    failed = False

    def interrupted_write(path, value):
        nonlocal failed
        if path == module.RECOMMENDATIONS_JSON and not failed:
            failed = True
            raise interruption('simulated second-file failure')
        write(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(module, '_write_json', interrupted_write)
        with pytest.raises(interruption):
            store.create_recommendation(campaign_id='c', planner_name='manual', parameters_batch=[{'x': 2}])
    assert store.list_trials('c') == first['trials']
    assert store.list_recommendations('c') == [first['recommendation']]
    assert not (tmp_path / 'recommendation.pending.json').exists()
    store.create_recommendation(campaign_id='c', planner_name='manual', parameters_batch=[{'x': 2}])
    assert len(store.list_trials('c')) == 2
