import asyncio
import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))


def test_engine_start_failure_does_not_leave_running_state():
    from src.experiment.engine import ExperimentEngine, ExperimentState

    executor = Mock()
    exp_logger = Mock()
    exp_logger.start_run.side_effect = OSError("samples.csv unreadable")
    engine = ExperimentEngine(executor, exp_logger=exp_logger)
    engine.load_steps([], name="bad_start", filename="bad_start.yaml")

    async def scenario():
        try:
            await engine.start()
            raise AssertionError("engine.start() should raise when start_run fails")
        except OSError:
            pass

    asyncio.run(scenario())
    assert engine.state == ExperimentState.IDLE
    assert engine._task is None


def test_start_experiment_cleans_engine_when_start_run_fails():
    from fastapi import HTTPException
    from src.web.api import experiments as exp_api

    class Request:
        app = SimpleNamespace(state=SimpleNamespace(device_manager=Mock()))

    original_start_run = exp_api.ExperimentLogger.start_run
    exp_api._engines.clear()

    def fail_start_run(self, *args, **kwargs):
        raise OSError("samples.csv unreadable")

    async def scenario():
        exp_api.ExperimentLogger.start_run = fail_start_run
        try:
            try:
                await exp_api.start_experiment(
                    "simple_heat_test.yaml",
                    exp_api.StartExperimentRequest(save_log=False),
                    Request(),
                )
                raise AssertionError("start_experiment should raise HTTPException")
            except HTTPException as e:
                assert e.status_code == 500
            assert "simple_heat_test.yaml" not in exp_api._engines
        finally:
            exp_api.ExperimentLogger.start_run = original_start_run
            exp_api._engines.clear()

    asyncio.run(scenario())


def test_generate_unique_sample_id_raises_when_existing_ids_unreadable():
    import src.science.sample_record as sr_mod
    from src.science.sample_id import generate_unique_sample_id

    tmp_dir = Path(tempfile.mkdtemp())
    original_csv = sr_mod.SAMPLES_CSV
    try:
        sr_mod.SAMPLES_CSV = tmp_dir
        assert sr_mod.existing_sample_ids() == set()
        try:
            generate_unique_sample_id({"batch_id": "STRICT_B01", "sample_index": 1})
            raise AssertionError("generate_unique_sample_id should fail when samples.csv cannot be read")
        except OSError:
            pass
    finally:
        sr_mod.SAMPLES_CSV = original_csv
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_delete_history_removes_matching_sample_records_only():
    import src.experiment.experiment_logger as el_mod
    import src.science.sample_record as sr_mod

    tmp_dir = Path(tempfile.mkdtemp())
    original_logs_dir = el_mod.LOGS_DIR
    original_samples_csv = sr_mod.SAMPLES_CSV
    try:
        logs_dir = tmp_dir / "logs"
        logs_dir.mkdir()
        samples_csv = tmp_dir / "samples.csv"
        el_mod.LOGS_DIR = logs_dir
        sr_mod.SAMPLES_CSV = samples_csv

        run1 = "20260625_010203_abcdef"
        run2 = "20260625_010204_bcdef0"
        (logs_dir / f"{run1}_one.json").write_text("{}", encoding="utf-8")
        (logs_dir / f"{run2}_two.json").write_text("{}", encoding="utf-8")

        with open(samples_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sr_mod.SAMPLE_HEADERS)
            writer.writeheader()
            writer.writerow({"sample_id": "S1", "run_id": run1, "raw_log_path": str(logs_dir / f"{run1}_one.json")})
            writer.writerow({"sample_id": "S2", "run_id": run2, "raw_log_path": str(logs_dir / f"{run2}_two.json")})

        assert el_mod.delete_experiment_run(run1) is True
        with open(samples_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert [row["run_id"] for row in rows] == [run2]

        assert el_mod.delete_all_experiment_runs() == 1
        with open(samples_csv, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows == []
    finally:
        el_mod.LOGS_DIR = original_logs_dir
        sr_mod.SAMPLES_CSV = original_samples_csv
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_device_manager_payload_and_control_fixes():
    from src.web.device_manager import DeviceManager
    from src.protocols.microwave_params import CONTROL_MANUAL_POWER
    from src.protocols.pump_params import PumpDirection, PumpRunMode

    dm = DeviceManager()
    assert dm.emergency_stop_all() is False
    dm.add_heater(
        device_id="heater_config_test",
        port="COM8",
        timeout=0.7,
        max_temperature=123.0,
        safety_limit=130.0,
        retry_count=5,
    )
    heater_config = dm._heaters["heater_config_test"].config
    assert heater_config.timeout == 0.7
    assert heater_config.max_temperature == 123.0
    assert heater_config.safety_limit == 130.0
    assert heater_config.retry_count == 5
    try:
        dm._heaters["heater_config_test"].set_temperature(124.0)
        raise AssertionError("configured heater maximum should be enforced")
    except ValueError as e:
        assert "configured maximum" in str(e)

    dm.add_pump(
        device_id="pump1",
        port="COM9",
        baudrate=19200,
        slave_address=1,
        parity="N",
        timeout=0.8,
        retry_count=4,
        stopbits=2,
        bytesize=7,
    )
    assert dm._pumps["pump1"].config.connection_params["parity"] == "N"
    assert dm._pumps["pump1"].config.timeout == 0.8
    assert dm._pumps["pump1"].config.retry_count == 4
    assert dm._pumps["pump1"].config.stopbits == 2
    assert dm._pumps["pump1"].config.bytesize == 7

    microwave = SimpleNamespace(
        config=SimpleNamespace(
            device_id="microwave1",
            connection_params={"port": "COM12"},
            allow_experiment_control=True,
            allow_real_hardware_writes=True,
            enable_control_writes=True,
        )
    )
    payload = dm._microwave_payload(
        microwave,
        {"power_percent": 0, "current": 1.2, "current_mode_code": CONTROL_MANUAL_POWER},
    )
    assert payload["running"] is True
    assert payload["mode"] == "manual_power"

    unknown_payload = dm._microwave_payload(
        microwave,
        {"power_percent": 0, "current": 0, "current_mode_code": 6},
    )
    assert unknown_payload["running"] is False
    assert unknown_payload["mode"] == "unknown"
    assert unknown_payload["current_mode_code"] == 6

    heater = Mock()
    heater.is_connected.return_value = False
    heater.config.device_id = "heater1"
    dm._heaters["heater1"] = heater
    assert dm.emergency_stop_all() is False
    heater.emergency_stop.assert_not_called()

    pump = Mock()
    pump.enable_channel.return_value = True
    pump.stop_channel.return_value = True
    pump.get_tube_model.return_value = 1
    pump.set_direction.return_value = True
    pump.set_run_mode.return_value = True
    pump.set_flow_rate.return_value = True
    pump.set_repeat_count.return_value = True
    pump.start_channel.return_value = True
    assert dm._start_pump_channel_inner(
        pump,
        "pump1",
        1,
        1.0,
        PumpDirection.CLOCKWISE,
        PumpRunMode.FLOW_MODE,
        None,
        None,
        repeat_count=1.0,
    ) is True
    pump.set_repeat_count.assert_called_once_with(1, 1)


def test_microwave_sensor_data_records_power_current_without_temperature():
    import src.science.sample_record as sr_mod
    from src.experiment.experiment_logger import ExperimentLogger

    tmp_dir = Path(tempfile.mkdtemp())
    original_csv = sr_mod.SAMPLES_CSV
    try:
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        exp_logger = ExperimentLogger(save_log=False)
        exp_logger.start_run(
            experiment_name="microwave_sensor",
            experiment_file="microwave_sensor.yaml",
            total_steps=1,
            metadata={"batch_id": "MW_B01", "sample_index": 1},
        )
        exp_logger.record_sensor_data({
            "heaters": {},
            "pumps": {},
            "microwaves": {
                "microwave1": {
                    "material_temperature": None,
                    "power_percent": 35,
                    "current": 1.5,
                    "runtime_seconds": 12,
                }
            },
        })

        mdata = exp_logger.active_run.sensor_data["microwaves"]["microwave1"]
        assert "material_temperature" in mdata
        assert mdata["material_temperature"] == []
        assert mdata["power_percent"][0]["v"] == 35
        assert mdata["current"][0]["v"] == 1.5
        assert mdata["runtime_seconds"][0]["v"] == 12
    finally:
        sr_mod.SAMPLES_CSV = original_csv
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_parser_rejects_unknown_wait_and_on_error_values():
    import src.experiment.parser as parser_mod

    tmp_dir = Path(tempfile.mkdtemp())
    original_dir = parser_mod.EXPERIMENTS_DIR
    parser_mod.EXPERIMENTS_DIR = tmp_dir
    try:
        (tmp_dir / "bad_wait.yaml").write_text(
            "steps:\n  - id: bad\n    type: wait\n    wait:\n      type: temperature_reched\n",
            encoding="utf-8",
        )
        try:
            parser_mod.parse_experiment("bad_wait.yaml")
            raise AssertionError("unknown wait type should be rejected")
        except ValueError as e:
            assert "Unknown wait type" in str(e)

        (tmp_dir / "bad_policy.yaml").write_text(
            "steps:\n  - id: bad\n    type: wait\n    on_error: continue\n",
            encoding="utf-8",
        )
        try:
            parser_mod.parse_experiment("bad_policy.yaml")
            raise AssertionError("unknown on_error policy should be rejected")
        except ValueError as e:
            assert "Unknown on_error policy" in str(e)
    finally:
        parser_mod.EXPERIMENTS_DIR = original_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_pause_blocks_current_wait_until_resume():
    from src.experiment.actions import ActionType, ExperimentStep, WaitCondition, WaitType
    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor

    exp_logger = Mock()
    executor = StepExecutor(Mock())
    engine = ExperimentEngine(executor, exp_logger=exp_logger)
    engine.load_steps([
        ExperimentStep(
            id="pause_wait",
            type=ActionType.WAIT,
            wait=WaitCondition(type=WaitType.DURATION, seconds=0.15),
        )
    ])

    async def scenario():
        await engine.start()
        await asyncio.sleep(0.03)
        await engine.pause()
        await asyncio.sleep(0.25)
        assert engine.state == ExperimentState.PAUSED
        assert engine._task is not None and not engine._task.done()
        await engine.resume()
        await engine._task

    asyncio.run(scenario())
    assert engine.state == ExperimentState.COMPLETED


def test_pump_complete_requires_fresh_running_to_stopped_transition():
    from src.experiment.actions import WaitCondition, WaitType
    from src.experiment.executor import StepExecutor

    class PumpDM:
        def __init__(self):
            self.calls = 0
            self.statuses = [
                {"channels": {"1": {"running": False, "read_ok": False}}},
                {"channels": {"1": {"running": True, "read_ok": True}}},
                {"channels": {"1": {"running": False, "read_ok": True}}},
            ]

        def read_pump_status(self, _device_id):
            self.calls += 1
            return self.statuses.pop(0)

    dm = PumpDM()
    executor = StepExecutor(dm)

    async def no_sleep(_seconds):
        return 0.0

    executor._pause_aware_sleep = no_sleep
    condition = WaitCondition(
        type=WaitType.PUMP_COMPLETE,
        device_id="pump1",
        channel=1,
        timeout=1,
    )
    assert asyncio.run(executor._wait_condition(condition)) is True
    assert dm.calls == 3


def test_auxiliary_program_controller_propagates_failures_and_stops_heater():
    from src.control.program_controller import ProgramController, ProgramStep, StepType

    missing = ProgramController()
    heat_step = ProgramStep(step_id=1, step_type=StepType.HEAT, temperature=50)
    assert asyncio.run(missing._execute_heat(heat_step)) is False

    heater = Mock()
    heater.stop.return_value = False
    pump = Mock()
    pump.stop_all.return_value = True
    controller = ProgramController(heater=heater, pump=pump)
    assert asyncio.run(controller.stop()) is False
    heater.stop.assert_called_once_with()
    pump.stop_all.assert_called_once_with()


def test_successful_persistence_is_atomic_and_recorded():
    import src.experiment.experiment_logger as el_mod
    import src.science.sample_record as sr_mod

    tmp_dir = Path(tempfile.mkdtemp())
    original_logs_dir = el_mod.LOGS_DIR
    original_samples_csv = sr_mod.SAMPLES_CSV
    try:
        el_mod.LOGS_DIR = tmp_dir / "logs"
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        logger = el_mod.ExperimentLogger(save_log=True)
        logger.start_run(
            experiment_name="unsafe/name",
            experiment_file="safe.yaml",
            total_steps=0,
            metadata={"batch_id": "PERSIST_B01", "sample_index": 1},
        )
        assert logger.finish_run("completed") is True
        assert logger.active_run.persistence_status == "ok"
        assert logger.active_run.log_saved is True
        assert logger.active_run.sample_record_saved is True

        log_files = list(el_mod.LOGS_DIR.glob("*.json"))
        assert len(log_files) == 1
        saved = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert saved["persistence_status"] == "ok"
        assert not list(tmp_dir.rglob("*.tmp"))
    finally:
        el_mod.LOGS_DIR = original_logs_dir
        sr_mod.SAMPLES_CSV = original_samples_csv
        shutil.rmtree(tmp_dir, ignore_errors=True)


TESTS = [
    test_engine_start_failure_does_not_leave_running_state,
    test_start_experiment_cleans_engine_when_start_run_fails,
    test_generate_unique_sample_id_raises_when_existing_ids_unreadable,
    test_delete_history_removes_matching_sample_records_only,
    test_device_manager_payload_and_control_fixes,
    test_microwave_sensor_data_records_power_current_without_temperature,
    test_parser_rejects_unknown_wait_and_on_error_values,
    test_pause_blocks_current_wait_until_resume,
    test_pump_complete_requires_fresh_running_to_stopped_transition,
    test_auxiliary_program_controller_propagates_failures_and_stops_heater,
    test_successful_persistence_is_atomic_and_recorded,
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f"[OK] {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {test.__name__}: {e}")
    print(f"\nResult: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
