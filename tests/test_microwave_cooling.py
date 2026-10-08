import asyncio
import unittest

from src.experiment.actions import WaitCondition, WaitType
from src.experiment.executor import StepExecutor
from src.experiment.parser import parse_experiment_data


class CoolingTests(unittest.TestCase):
    def condition(self, **kwargs):
        return WaitCondition(type=WaitType.MICROWAVE_TEMPERATURE_BELOW,
                             device_id="microwave1", target_temperature=45,
                             **kwargs)

    def run_wait(self, values, **kwargs):
        class Manager:
            def read_microwave_data(self, device_id):
                value = values.pop(0)
                if isinstance(value, Exception):
                    raise value
                return {"material_temperature": value}
        executor = StepExecutor(Manager())
        return asyncio.run(executor._wait_condition(self.condition(**kwargs)))

    def test_threshold_is_strict_and_accepts_already_cold(self):
        values = [45.1, 45]
        self.assertTrue(self.run_wait(values))
        self.assertEqual(values, [])
        self.assertTrue(self.run_wait([30]))

    def test_invalid_read_never_releases_wait(self):
        for value in [None, True, float("nan"), float("inf"), -1, "40", IOError("read failed")]:
            with self.subTest(value=value):
                self.assertFalse(self.run_wait([value]))

    def test_timeout_and_stop(self):
        self.assertFalse(self.run_wait([80], timeout=0))
        executor = StepExecutor(None)
        executor._should_stop = lambda: True
        self.assertFalse(asyncio.run(executor._wait_condition(self.condition())))

    def test_pause_prevents_read_and_completion(self):
        class Manager:
            calls = 0
            def read_microwave_data(self, device_id):
                self.calls += 1
                return {"material_temperature": 40}
        async def scenario():
            manager = Manager()
            executor = StepExecutor(manager)
            paused = [True]
            stopped = [False]
            executor._is_paused = lambda: paused[0]
            executor._should_stop = lambda: stopped[0]
            task = asyncio.create_task(executor._wait_condition(self.condition()))
            await asyncio.sleep(0.05)
            self.assertEqual(manager.calls, 0)
            self.assertFalse(task.done())
            stopped[0] = True
            self.assertFalse(await task)
        asyncio.run(scenario())

    def test_parser_rejects_bypassed_or_invalid_guard(self):
        base = {"id": "cool", "type": "wait", "wait": {
            "type": "microwave_temperature_below", "device_id": "microwave1",
            "target_temperature": 45, "timeout": 3600}}
        parsed = parse_experiment_data({"steps": [base]}, validate_devices=False)
        self.assertEqual(parsed["steps"][0].wait.type, WaitType.MICROWAVE_TEMPERATURE_BELOW)
        for overrides in [{"on_error": "skip"}, {"enabled": False}]:
            with self.assertRaises(ValueError):
                parse_experiment_data({"steps": [{**base, **overrides}]}, validate_devices=False)
        for overrides in [{"target_temperature": float("nan")}, {"target_temperature": True},
                          {"timeout": 0}, {"device_id": ""}]:
            with self.assertRaises(ValueError):
                parse_experiment_data({"steps": [{**base, "wait": {**base["wait"], **overrides}}]},
                                      validate_devices=False)


if __name__ == "__main__":
    unittest.main()
