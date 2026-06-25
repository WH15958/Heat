import asyncio
import csv
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
    from src.protocols.pump_params import PumpRunMode

    dm = DeviceManager()
    dm.add_pump(device_id="pump1", port="COM9", baudrate=19200, slave_address=1, parity="N")
    assert dm._pumps["pump1"].config.connection_params["parity"] == "N"

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
    assert dm.emergency_stop_all() is True
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
        "CW",
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


TESTS = [
    test_engine_start_failure_does_not_leave_running_state,
    test_start_experiment_cleans_engine_when_start_run_fails,
    test_generate_unique_sample_id_raises_when_existing_ids_unreadable,
    test_delete_history_removes_matching_sample_records_only,
    test_device_manager_payload_and_control_fixes,
    test_microwave_sensor_data_records_power_current_without_temperature,
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
