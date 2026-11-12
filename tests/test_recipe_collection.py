"""Recipe four-ring paths use fake devices and real paired controllers."""
import asyncio
from types import SimpleNamespace

import pytest

from src.experiment.actions import ActionType
from src.experiment.recipe_turntable import RecipeCollection, check_turntable_connections
from src.experiment.parser import parse_experiment_data
from test_guided_collection import rig, clock, no_hardware, position


def steps(count=2):
    return parse_experiment_data({'steps': [dict(id=str(i), type='turntable.' +
        ('home_bottle' if i == 0 else 'next_bottle'), params={'device_id': 'turntable1'})
        for i in range(count)]}, validate_devices=True)['steps']


def prepare(rig):
    dm, r, p, _, writes, _, _ = rig
    dm.get_pump = lambda _: SimpleNamespace(is_connected=lambda: True)
    dm.valve_energized = True
    check_turntable_connections(dm, steps())
    helper = RecipeCollection(dm, lambda: False, lambda _: None)
    return dm, r, p, writes, helper


def test_parser_72_not_73(rig):
    assert len(steps(72)) == 72
    with pytest.raises(ValueError, match='最后瓶位'):
        steps(73)


@pytest.mark.parametrize('source', [28, 48, 64])
def test_recipe_cross_ring_and_cleanup(rig, source):
    async def run():
        dm, r, p, writes, helper = prepare(rig)
        await helper.claim()
        await helper.execute_action(ActionType.TURNTABLE_HOME)
        position(r, p, source)
        helper.current_bottle = helper.bottle = source
        helper.expected_positions = [r.device.position, p.device.position]
        writes.clear()
        result = await helper.execute_action(ActionType.TURNTABLE_NEXT)
        assert result['current_bottle'] == source + 1
        assert len(result['axes']) == 2
        assert [w[0] for w in writes] == [r.config.device_id, p.config.device_id]
        assert await helper.cleanup(normal=True)
        assert r.owner is p.owner is None
    asyncio.run(run())


def test_stop_rehome_and_no_wrap(rig):
    async def run():
        _, r, p, _, helper = prepare(rig)
        await helper.claim()
        await helper.execute_action(ActionType.TURNTABLE_HOME)
        await helper.execute_action(ActionType.TURNTABLE_STOP)
        with pytest.raises(RuntimeError, match='回原点'):
            await helper.execute_action(ActionType.TURNTABLE_NEXT)
        helper.rearm_home()
        await helper.execute_action(ActionType.TURNTABLE_HOME)
        position(r, p, 72)
        helper.current_bottle = helper.bottle = 72
        helper.expected_positions = [r.device.position, p.device.position]
        with pytest.raises(ValueError, match='容量'):
            await helper.execute_action(ActionType.TURNTABLE_NEXT)
        assert await helper.cleanup()
    asyncio.run(run())


def test_route_failure_does_not_move(rig):
    async def run():
        dm, _, _, writes, helper = prepare(rig)
        await helper.claim()
        dm.valve_energized = False
        with pytest.raises(RuntimeError, match='废液'):
            await helper.execute_action(ActionType.TURNTABLE_HOME)
        assert all(w[1] == 'stop' for w in writes)
        assert await helper.cleanup()
    asyncio.run(run())


def test_executor_selects_pair_and_records_axes(rig):
    from src.experiment.executor import StepExecutor
    async def run():
        dm, r, p, _, _ = prepare(rig)
        executor = StepExecutor(dm)
        recipe = steps()
        await executor.reserve_turntables(recipe)
        assert isinstance(executor._turntables['turntable1'], RecipeCollection)
        for step in recipe:
            assert await executor._execute_turntable(step)
        assert executor.last_device_result['to_bottle'] == 2
        assert executor.last_device_result['collection_ring'] == 1
        assert len(executor.last_device_result['axes']) == 2
        assert await executor._turntables['turntable1'].cleanup(normal=True)
        assert r.owner is p.owner is None
    asyncio.run(run())
