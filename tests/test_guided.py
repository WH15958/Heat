"""Real orchestration/engine tests with fake devices; never open serial hardware."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.experiment import guided
from src.experiment.parser import parse_experiment_data
from src.web.api import experiments, guided as api
from src.web.api import devices, valves, syringe_pumps


def spec(**kwargs):
    values = dict(axes=[[30], [30], [0.1], [0.2], [30], [0]],
        product_port="NO", drain_flow=1, product_drain_seconds=60, clean_drain_seconds=90,
        clean_volume=1, clean_flow=1,
        clean_dwell=0, clean_cycles=1, plumbing_confirmed=True, priming_confirmed=True,
        reactor_available_ml=20, source_available_a_ml=100, source_available_b_ml=100, waste_available_ml=500,
        prime_drain_seconds=480, prime_drain_flow=1)
    return guided.GuidedRequest(**{**values, **kwargs})


class FakeSyringe:
    def __init__(self, dm, did):
        self.dm, self.did = dm, did
        self.owner = None
        self.config = SimpleNamespace(capacity_ml=2.5)
        self.device = SimpleNamespace(is_connected=lambda: True)
        self.result = "completed"
        self.position = 0

    def claim(self, owner):
        if self.owner not in (None, owner):
            raise RuntimeError("owned")
        self.owner = owner

    def release(self, owner):
        if self.owner is owner:
            self.owner = None

    def read(self):
        return dict(read_ok=True, initialized=True, position_trusted=True,
            position=self.position, busy=False, fault_code=0, action=dict(result=self.result))

    def summary(self):
        return self.read()

    def stop(self):
        self.dm.calls.append(("syringe_stop", self.did))
        self.result = "stopped"
        return not self.dm.stop_failure


class FakeManager:
    def __init__(self):
        self.calls = []
        self.syringes = {did: FakeSyringe(self, did) for did in ("syringe_pump1", "syringe_pump2")}
        self.valves = {"valve1": SimpleNamespace(is_connected=lambda: True)}
        self.valve_owner = None
        self.heating = {}
        self.pump_reads = {}
        self.microwave_on = False
        self.temperature = 30
        self.fail_feed = False
        self.stop_failure = False
        self.barrier = threading.Barrier(2)

    def get_all_heaters(self):
        return {did: SimpleNamespace(is_connected=lambda: True) for did in ("heater1", "heater2")}

    def get_all_pumps(self):
        return {"pump1": SimpleNamespace(is_connected=lambda: True)}

    def get_all_microwaves(self):
        return {"microwave1": SimpleNamespace(is_connected=lambda: True)}

    def syringe(self, did):
        return self.syringes[did]

    def syringe_command(self, did, params, owner):
        self.syringes[did].claim(owner)
        self.calls.append((params["action"], did))
        if params["action"] == "dispense":
            # Both commands must be dispatched before either can finish.
            if params["volume"] < 1:
                self.barrier.wait(timeout=2)
            if self.fail_feed and did == "syringe_pump1":
                raise IOError("dose failed")
            self.syringes[did].position = 0
        else:
            self.syringes[did].position = 100
        self.syringes[did].result = "completed"
        return {"result": "completed"}

    def claim_valve(self, did, owner):
        if self.valve_owner not in (None, owner):
            raise RuntimeError("owned")
        self.valve_owner = owner

    def release_valve(self, did, owner):
        if self.valve_owner is owner:
            self.valve_owner = None

    def cancel_valve_operations(self, ids):
        pass

    def valve_operation(self, did, action, energized, owner, stop):
        assert self.valve_owner is owner
        assert not stop()
        self.calls.append(("valve", energized))
        return {"read_ok": True, "relay_energized": energized}

    def set_temperature(self, did, value):
        self.heating[did] = value
        self.calls.append(("temperature", did))
        return True

    def start_heater(self, did):
        self.calls.append(("heat", did))
        return True

    def stop_heater(self, did):
        self.calls.append(("heater_stop", did))
        return True

    def read_heater_data(self, did):
        return {"pv": self.heating[did], "sv": self.heating[did]}

    def configure_microwave_auto_power(self, did, segments):
        self.temperature = segments[0].heating_temperature
        self.calls.append(("microwave_config", did))
        return True

    def start_microwave(self, did, mode):
        self.microwave_on = True
        self.calls.append(("microwave_start", did))
        return True

    def stop_microwave(self, did):
        self.microwave_on = False
        self.calls.append(("microwave_stop", did))
        return True

    def read_microwave_data(self, did):
        return {"material_temperature": self.temperature, "fault_code": 0,
                "output_active": self.microwave_on, "control_active": self.microwave_on,
                "stop_confirmed": not self.microwave_on}

    def start_pump_channel(self, did, channel, *args):
        self.calls.append(("pump_start", channel))
        self.pump_reads[str(channel)] = 0
        return True

    def stop_pump_channel(self, did, channel):
        self.calls.append(("pump_stop", channel))
        self.pump_reads.pop(str(channel), None)
        return True

    def read_pump_status(self, did):
        channels = {}
        for channel in ("3", "4"):
            running = channel in self.pump_reads and self.pump_reads[channel] == 0
            if channel in self.pump_reads:
                self.pump_reads[channel] += 1
            channels[channel] = {"read_ok": True, "running": running, "run_status": "START" if running else "STOP"}
        return {"channels": channels}


async def until(predicate):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


class GuidedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.patches = [patch("serial.Serial.open", side_effect=AssertionError("real serial forbidden")),
            patch("src.experiment.experiment_logger.LOGS_DIR", self.directory / "logs"),
            patch("src.experiment.experiment_logger.write_sample_record", return_value=True),
            patch.object(guided, "BATCH_DIR", self.directory / "batches")]
        for p in self.patches:
            p.start()
        api._batches.clear()
        experiments._engines.clear()

    def tearDown(self):
        api._batches.clear()
        experiments._engines.clear()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_bounds_and_complete_recipe(self):
        request = spec(repeats=2)
        recipes = guided.compile_plan(request)
        self.assertEqual(len(recipes), 2)
        types = [s["type"] for s in recipes[0]["steps"]]
        self.assertLess(types.index("syringe_pair.dispense"), types.index("microwave.start"))
        ids = [s["id"] for s in recipes[0]["steps"]]
        self.assertLess(ids.index("recheck_temperature"), ids.index("collect_product"))
        with self.assertRaises(ValidationError):
            spec(repeats=200, axes=[[30, 31], [30], [0.1], [0.2], [30], [0]])
        with self.assertRaises(ValueError):
            guided.compile_plan(spec(axes=[[500], [30], [0.1], [0.2], [30], [0]]))
        data = recipes[0]
        pair = next(s for s in data["steps"] if s["type"] == "syringe_pair.dispense")
        pair["params"]["feeds"][0]["action"] = "initialize"
        with self.assertRaises(ValueError):
            parse_experiment_data(data)

    def test_priming_recipe_units_order_and_capacity(self):
        request = spec(prime_volume_a=1.5, prime_volume_b=2, prime_cycles=3,
                       prime_drain_seconds=123, prime_drain_flow=2, drain_flow=3)
        data = guided.priming_recipe(request, "test")
        motions = [s for s in data["steps"] if s["type"].startswith("syringe_pump.")]
        self.assertEqual([s["params"]["device_id"] for s in motions],
                         ["syringe_pump1"]*6+["syringe_pump2"]*6)
        self.assertEqual([s["type"].split(".")[1] for s in motions], ["aspirate", "dispense"]*6)
        drain = next(s for s in data["steps"] if s["id"] == "prime_drain")
        self.assertEqual(drain["params"]["run_time"], 123)
        self.assertEqual(drain["params"]["flow_rate"], 2)
        self.assertEqual(drain["params"]["dispense_volume"], 4.1)
        self.assertEqual(drain["wait"]["timeout"], 183)
        product = next(s for s in guided.recipe(request.rows()[0], request, "test", 0)["steps"]
                       if s["id"] == "collect_product")
        self.assertEqual(product["params"]["flow_rate"], 3)
        self.assertEqual(data["metadata"]["theoretical_volume_ml"], 10.5)
        self.assertEqual(data["metadata"]["waste_port"], "NC")
        self.assertFalse(any(s["type"] in ("heater.start", "microwave.start") for s in data["steps"]))
        for changes in (dict(reactor_available_ml=7), dict(source_available_a_ml=3),
                        dict(waste_available_ml=8), dict(prime_cycles=0), dict(prime_drain_seconds=0), dict(prime_drain_flow=0),
                        dict(prime_drain_seconds=10000), dict(prime_drain_flow=float("inf"))):
            with self.assertRaises(ValidationError):
                spec(**changes)
        with self.assertRaises(ValueError):
            guided.compile_plan(spec(prime_volume_a=3))

    def test_prime_then_explicit_start_and_signature(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            await batch.start(prime_only=True)
            await batch.task
            self.assertEqual(batch.record["phase"], "ready")
            self.assertEqual(batch.record["priming"]["completed_cycles"], [2, 2])
            self.assertTrue(batch.cleanup_pending)
            self.assertEqual(batch.record["groups"], [])
            self.assertFalse(any(c[0] in ("heat", "microwave_start") for c in dm.calls))
            prime_calls = [c for c in dm.calls if c[0] in ("aspirate", "dispense")]
            self.assertEqual(prime_calls, [(action, did) for did in ("syringe_pump1", "syringe_pump2")
                                          for _ in range(2) for action in ("aspirate", "dispense")])
            with self.assertRaises(ValueError):
                await batch.resume()
            with self.assertRaises(ValueError):
                await batch.begin_experiments(spec(prime_drain_seconds=485))
            await batch.begin_experiments(spec())
            with self.assertRaises(ValueError):
                await batch.begin_experiments(spec())
            await batch.task
            self.assertEqual(batch.state.value, "completed")
            self.assertEqual(sum(c == ("pump_start", 4) for c in dm.calls), 3)
            self.assertFalse(batch.cleanup_pending)
        asyncio.run(scenario())

    def test_changed_device_state_invalidates_precharge(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            await batch.start(prime_only=True)
            await batch.task
            dm.syringes["syringe_pump2"].position = 100
            with self.assertRaises(ValueError):
                await batch.begin_experiments(spec())
            self.assertEqual(batch.record["priming"]["status"], "invalidated")
            self.assertTrue(batch.record["recovery_required"])
            self.assertFalse(any(c[0] == "microwave_start" for c in dm.calls))
            await batch.stop()
        asyncio.run(scenario())

    def test_priming_failure_recovery_and_duplicate_api(self):
        import time
        app = FastAPI()
        dm = FakeManager()
        app.state.device_manager = dm
        app.include_router(api.router, prefix="/api")
        with TestClient(app) as client:
            started = client.post("/api/guided/prime", json=spec().model_dump())
            self.assertEqual(started.status_code, 200, started.text)
            bid = started.json()["batch_id"]
            for _ in range(200):
                if client.get(f"/api/guided/{bid}").json()["phase"] == "ready":
                    break
                time.sleep(0.01)
            self.assertEqual(client.get(f"/api/guided/{bid}").json()["phase"], "ready")
            calls = list(dm.calls)
            body = spec(priming_batch_id=bid).model_dump()
            self.assertEqual(client.post("/api/guided/prime", json=body).status_code, 200)
            self.assertEqual(dm.calls, calls)
            self.assertEqual(client.post("/api/guided/start", json=spec().model_dump()).status_code, 409)
            self.assertEqual(client.post("/api/guided/start", json=body).status_code, 200)
            client.post(f"/api/guided/{bid}/stop")

    def test_priming_failure_requires_explicit_recovery(self):
        async def scenario():
            dm = FakeManager()
            dm.fail_feed = True
            batch = guided.GuidedBatch(dm, spec())
            await batch.start(prime_only=True)
            await batch.task
            self.assertEqual(batch.record["priming"]["status"], "failed")
            self.assertEqual(batch.record["groups"], [])
            self.assertTrue(batch.record["recovery_required"])
            self.assertIn(("syringe_stop", "syringe_pump2"), dm.calls)
            self.assertIn(("pump_stop", 4), dm.calls)
            with self.assertRaises(ValueError):
                await batch.begin_experiments(spec())
            self.assertFalse(any(c[0] in ("heat", "microwave_start", "pump_start") for c in dm.calls))
        asyncio.run(scenario())

    def test_priming_valve_and_drain_failures_never_enter_experiments(self):
        async def scenario(failing_method):
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            with patch.object(dm, failing_method, side_effect=IOError("hardware failure")):
                await batch.start(prime_only=True)
                await batch.task
            self.assertEqual(batch.record["priming"]["status"], "failed")
            self.assertTrue(batch.record["recovery_required"])
            self.assertEqual(batch.record["groups"], [])
            self.assertFalse(any(c[0] in ("heat", "microwave_start") for c in dm.calls))
            self.assertIn(("syringe_stop", "syringe_pump1"), dm.calls)
            self.assertIn(("syringe_stop", "syringe_pump2"), dm.calls)
            self.assertIn(("pump_stop", 4), dm.calls)
        for method in ("valve_operation", "start_pump_channel"):
            with self.subTest(method=method):
                asyncio.run(scenario(method))

    def test_priming_stop_and_checkpoint_failure_lock(self):
        async def scenario():
            dm = FakeManager()
            dm.temperature = 60
            batch = guided.GuidedBatch(dm, spec(cooling_timeout=1))
            await batch.start(prime_only=True)
            await until(lambda: batch.record.get("last_step") == "prime_temperature")
            await batch.pause()
            self.assertEqual(batch.state.value, "paused")
            self.assertTrue(await batch.stop())
            self.assertTrue(batch.record["recovery_required"])
            self.assertEqual(batch.record["groups"], [])
            self.assertFalse(any(c[0] in ("aspirate", "dispense", "pump_start") for c in dm.calls))
        asyncio.run(scenario())

    def test_priming_checkpoint_failure_dispatches_no_movement(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            original = guided.atomic_record
            def save(record, directory=None):
                if record.get("last_step") == "prime_1_1_aspirate":
                    raise OSError("disk full during priming")
                return original(record, directory)
            with patch.object(guided, "atomic_record", side_effect=save):
                await batch.start(prime_only=True)
                await batch.task
            self.assertTrue(batch.record["recovery_required"])
            self.assertEqual(batch.record["persistence_status"], "error")
            self.assertFalse(any(c[0] in ("aspirate", "dispense", "pump_start") for c in dm.calls))
        asyncio.run(scenario())

    def test_ready_persistence_failure_never_leaves_reusable_priming(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            original = guided.atomic_record
            def save(record, directory=None):
                if record.get("phase") == "ready":
                    raise OSError("disk full at ready")
                return original(record, directory)
            with patch.object(guided, "atomic_record", side_effect=save):
                await batch.start(prime_only=True)
                await batch.task
            self.assertEqual(batch.state.value, "failed")
            self.assertTrue(batch.record["recovery_required"])
            self.assertEqual(batch.record["priming"]["status"], "failed")
            self.assertTrue(all(p.owner is None for p in dm.syringes.values()))
            with self.assertRaises(ValueError):
                await batch.begin_experiments(spec())
        asyncio.run(scenario())

    def test_ready_restart_requires_recovery(self):
        async def scenario():
            batch = guided.GuidedBatch(FakeManager(), spec())
            await batch.start(prime_only=True)
            await batch.task
            restored = api.read_record(batch.batch_id)
            self.assertEqual(restored["state"], "interrupted")
            self.assertTrue(restored["recovery_required"])
            self.assertEqual(restored["priming"]["status"], "completed")
            await batch.stop()
        asyncio.run(scenario())

    def test_device_configuration_changes_signature(self):
        import copy
        from src.utils.config import ConfigManager
        request = spec()
        original = guided.priming_signature(request)
        changed = copy.deepcopy(ConfigManager().load())
        changed.syringe_pumps[0].capacity_ml = 1
        with patch.object(ConfigManager, "load", return_value=changed):
            self.assertNotEqual(original, guided.priming_signature(request))

    def test_explicit_priming_time_and_flow_are_signed_and_required(self):
        original = guided.priming_signature(spec())
        self.assertNotEqual(original, guided.priming_signature(spec(prime_drain_seconds=123)))
        self.assertNotEqual(original, guided.priming_signature(spec(prime_drain_flow=2)))
        body = spec().model_dump()
        for field in ("prime_drain_seconds", "prime_drain_flow", "reactor_available_ml",
                      "source_available_a_ml", "source_available_b_ml", "waste_available_ml"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                guided.GuidedRequest.model_validate({k: v for k, v in body.items() if k != field})
        legacy = dict(body, prime_drain_factor=1.2, prime_extra_seconds=0)
        del legacy["prime_drain_seconds"]
        del legacy["prime_drain_flow"]
        with self.assertRaises(ValidationError):
            guided.GuidedRequest.model_validate(legacy)

    def test_legacy_records_remain_readable_without_reusable_execution(self):
        app = FastAPI()
        app.state.device_manager = FakeManager()
        app.include_router(api.router, prefix="/api")
        batch_id = "guided_" + "a"*32
        request = spec().model_dump()
        del request["prime_drain_seconds"]
        del request["prime_drain_flow"]
        request.update(prime_drain_factor=1.5, prime_extra_seconds=10)
        record = dict(batch_id=batch_id, request=request, state="paused", phase="ready",
                      created_at="2026-10-09T00:00:00+00:00", priming={"status": "completed"})
        guided.atomic_record(record)
        with TestClient(app) as client:
            response = client.get("/api/guided/current")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["request"], request)
            self.assertTrue(response.json()["recovery_required"])
            self.assertEqual(client.post("/api/guided/start",
                json=spec(priming_batch_id=batch_id).model_dump()).status_code, 409)

    def test_api_live_priming_failure_acknowledgement(self):
        import time
        app = FastAPI()
        dm = FakeManager()
        dm.fail_feed = True
        app.state.device_manager = dm
        app.include_router(api.router, prefix="/api")
        with TestClient(app) as client:
            response = client.post("/api/guided/prime", json=spec().model_dump())
            self.assertEqual(response.status_code, 200, response.text)
            bid = response.json()["batch_id"]
            for _ in range(200):
                record = client.get(f"/api/guided/{bid}").json()
                if record["state"] == "failed":
                    break
                time.sleep(0.01)
            self.assertTrue(record["recovery_required"])
            self.assertEqual(client.post("/api/guided/prime", json=spec().model_dump()).status_code, 409)
            path = f"/api/guided/{bid}/acknowledge-interrupted"
            self.assertEqual(client.post(path, json={"devices_stopped_confirmed": False}).status_code, 409)
            self.assertEqual(client.post(path, json={"devices_stopped_confirmed": True}).status_code, 200)
            self.assertFalse(client.get(f"/api/guided/{bid}").json()["recovery_required"])
            self.assertEqual(client.post("/api/guided/start", json=spec(priming_batch_id=bid).model_dump()).status_code, 409)

    def test_two_groups_complete_without_bottle_confirmation(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec(repeats=2))
            await guided.preflight(dm, batch.spec)
            await batch.start()
            await batch.task
            self.assertEqual(batch.state.value, "completed")
            self.assertEqual(len(batch.record["groups"]), 2)
            self.assertEqual(sum(c == ("pump_start", 4) for c in dm.calls), 5)
            self.assertEqual(sum(c == ("pump_start", 3) for c in dm.calls), 2)
            self.assertTrue(all(step["type"] != "operator.confirm"
                                for recipe in batch.recipes for step in recipe["steps"]))
            self.assertFalse(hasattr(batch, "confirm"))
            self.assertNotEqual(batch.record["groups"][0]["run_id"], batch.record["groups"][1]["run_id"])
            self.assertFalse(batch.cleanup_pending)
            self.assertTrue(all(c.owner is None for c in dm.syringes.values()))
            self.assertIsNone(dm.valve_owner)
            self.assertEqual(json.loads((guided.BATCH_DIR / (batch.batch_id+".json")).read_text(encoding="utf-8"))["state"], "completed")
            saved = json.loads((guided.BATCH_DIR / "plans" / (batch.batch_id+".json")).read_text(encoding="utf-8"))
            self.assertEqual(saved["recipes"], batch.recipes)
        asyncio.run(scenario())

    def test_pause_resume_and_stop_while_cooling(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec(repeats=2,
                axes=[[30], [30], [0.1], [0.2], [60], [0]]))
            await batch.start()
            await until(lambda: batch.record.get("last_step") == "cool_before_collection")
            await batch.pause()
            dm.temperature = 40
            await asyncio.sleep(0.1)
            self.assertEqual(batch.state.value, "paused")
            self.assertEqual(sum(c[0] == "pump_start" for c in dm.calls), 1)
            dm.temperature = 60
            await batch.resume()
            self.assertTrue(await batch.stop())
            self.assertEqual(batch.state.value, "stopped")
            self.assertEqual(sum(c[0] == "pump_start" for c in dm.calls), 1)
            self.assertEqual(len(batch.record["groups"]), 1)
        asyncio.run(scenario())

    def test_feed_failure_stops_both_and_never_starts_microwave(self):
        async def scenario():
            dm = FakeManager()
            dm.fail_feed = True
            batch = guided.GuidedBatch(dm, spec())
            await batch.start()
            await batch.task
            self.assertEqual(batch.state.value, "failed")
            self.assertIn(("syringe_stop", "syringe_pump1"), dm.calls)
            self.assertIn(("syringe_stop", "syringe_pump2"), dm.calls)
            self.assertFalse(any(c[0] == "microwave_start" for c in dm.calls))
            self.assertFalse(batch.executor._active_heaters)
            self.assertFalse(any(c[0] == "heat" for c in dm.calls))
        asyncio.run(scenario())

    def test_failed_plan_persistence_dispatches_nothing(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec())
            with patch.object(guided, "atomic_record", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    await batch.start()
            self.assertEqual(dm.calls, [])
            self.assertEqual(batch.record["persistence_status"], "error")
        asyncio.run(scenario())

    def test_hot_product_never_reaches_bottle_or_pump(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec(axes=[[30], [30], [0.1], [0.2], [60], [0]],
                                                cooling_timeout=0.02))
            await batch.start()
            await batch.task
            self.assertEqual(batch.state.value, "failed")
            self.assertEqual(sum(c[0] == "pump_start" for c in dm.calls), 1)
            self.assertEqual([c for c in dm.calls if c[0] == "valve"], [("valve", True)])
        asyncio.run(scenario())

    def test_checkpoint_save_failure_prevents_collection_and_next_group(self):
        async def scenario():
            dm = FakeManager()
            batch = guided.GuidedBatch(dm, spec(repeats=2))
            original = guided.atomic_record
            def save(record, directory=None):
                if record.get("last_step") == "collect_product":
                    raise OSError("disk full at collection")
                return original(record, directory)
            with patch.object(guided, "atomic_record", side_effect=save):
                await batch.start()
                await batch.task
            self.assertEqual(batch.state.value, "failed")
            self.assertEqual(sum(c[0] == "pump_start" for c in dm.calls), 1)
            self.assertEqual(len(batch.record["groups"]), 1)
            self.assertEqual(batch.record["persistence_status"], "error")
        asyncio.run(scenario())

    def test_cleanup_failure_retains_interlock(self):
        async def scenario():
            dm = FakeManager()
            dm.fail_feed = dm.stop_failure = True
            batch = guided.GuidedBatch(dm, spec())
            await batch.start()
            await batch.task
            self.assertEqual(batch.state.value, "failed")
            self.assertTrue(batch.cleanup_pending)
            dm.stop_failure = False
            self.assertTrue(await batch.stop())
            self.assertTrue(batch.record["recovery_required"])
            batch.record["recovery_required"] = False
            self.assertFalse(batch.cleanup_pending)
        asyncio.run(scenario())

    def test_unsafe_preflight(self):
        async def scenario():
            dm = FakeManager()
            dm.syringes["syringe_pump2"].position = 100
            with self.assertRaises(ValueError):
                await guided.preflight(dm, spec())
            dm.syringes["syringe_pump2"].position = 0
            dm.read_microwave_data = lambda did: dict(fault_code=0, output_active=False,
                                                       control_active=True, stop_confirmed=False)
            with self.assertRaises(ValueError):
                await guided.preflight(dm, spec())
            self.assertEqual(dm.calls, [])
        asyncio.run(scenario())

    def test_removed_confirmation_action_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_experiment_data({"steps": [{"id": "confirm", "type": "operator.confirm",
                                              "params": {"message": "换瓶"}}]})

    def test_api_preview_restart_lock_and_recovery(self):
        app = FastAPI()
        dm = FakeManager()
        app.state.device_manager = dm
        app.include_router(api.router, prefix="/api")
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/guided/preview", json=spec().model_dump()).status_code, 200)
            self.assertEqual(dm.calls, [])
            old = guided.GuidedBatch(dm, spec())
            old.state = guided.ExperimentState.RUNNING
            old.save()
            response = client.get("/api/guided/current").json()
            self.assertTrue(response["recovery_required"])
            self.assertEqual(response["state"], "interrupted")
            self.assertEqual(client.post("/api/guided/start", json=spec().model_dump()).status_code, 409)
            path = f"/api/guided/{old.batch_id}/acknowledge-interrupted"
            self.assertEqual(client.post(path, json={"devices_stopped_confirmed": False}).status_code, 409)
            self.assertEqual(client.post(path, json={"devices_stopped_confirmed": True}).status_code, 200)
            self.assertEqual(client.get("/api/guided/../bad").status_code, 404)

    def test_api_real_start_mutual_exclusion_and_manual_write_protection(self):
        app = FastAPI()
        dm = FakeManager()
        app.state.device_manager = dm
        for router in (api.router, devices.router, valves.router, syringe_pumps.router):
            app.include_router(router, prefix="/api")
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/guided/start", json=spec().model_dump()).status_code, 409)
            started = client.post("/api/guided/prime", json=spec().model_dump())
            self.assertEqual(started.status_code, 200, started.text)
            batch_id = started.json()["batch_id"]
            saved = client.get(f"/api/guided/{batch_id}/plan")
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(len(saved.json()["recipes"]), 1)
            self.assertEqual(client.post("/api/guided/start", json=spec().model_dump()).status_code, 409)
            self.assertEqual(client.post("/api/heater/heater1/set_temperature", json={"temperature": 40}).status_code, 409)
            self.assertEqual(client.post("/api/valve/valve1/switch", json={"energized": True}).status_code, 409)
            self.assertEqual(client.post("/api/syringe_pump/syringe_pump1/disconnect").status_code, 409)
            self.assertEqual(client.post(f"/api/guided/{batch_id}/confirm-bottle", json={"token": "stale"}).status_code, 404)
            stopped = client.post(f"/api/guided/{batch_id}/stop")
            self.assertEqual(stopped.status_code, 200)
            self.assertTrue(stopped.json()["success"])
            self.assertFalse(any(c[0] == "pump_start" for c in dm.calls))


if __name__ == "__main__":
    unittest.main()
