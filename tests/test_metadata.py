import sys
import os
import tempfile
import shutil
import csv
import json
from pathlib import Path

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "src"))

from datetime import datetime
from unittest.mock import Mock, patch, MagicMock


def test_parser_old_yaml_no_metadata():
    print("\n=== 测试1: 老 YAML 无 metadata 字段 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        yaml_content = """name: simple_test
description: A simple test
steps:
  - id: step1
    type: wait
    params: {}
    wait:
      type: duration
      seconds: 1
"""
        yaml_path = os.path.join(tmp_dir, "old_test.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        from src.experiment.parser import EXPERIMENTS_DIR, parse_experiment

        original_dir = EXPERIMENTS_DIR
        try:
            import src.experiment.parser as parser_mod
            parser_mod.EXPERIMENTS_DIR = Path(tmp_dir)
            result = parse_experiment(yaml_path)
        finally:
            parser_mod.EXPERIMENTS_DIR = original_dir

        assert result["metadata"] == {}, f"Expected empty dict, got {result['metadata']}"
        assert result["name"] == "simple_test"
        assert len(result["steps"]) == 1
        print("[OK] 老 YAML 无 metadata 时返回空 dict")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_parser_new_yaml_with_metadata():
    print("\n=== 测试2: 新 YAML 带 metadata 字段 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        yaml_content = """name: cspbbr3_test
description: Test with metadata
metadata:
  material_system: CsPbBr3
  batch_id: CsPbBr3_20260528_B01
  condition_id: T140_t180_R2
  sample_index: 3
  operator: WH
  recipe_version: v0.1
steps:
  - id: heat_up
    type: heater.set_temperature
    params:
      device_id: heater1
      temperature: 140.0
    wait:
      type: duration
      seconds: 1
"""
        yaml_path = os.path.join(tmp_dir, "new_test.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        from src.experiment.parser import EXPERIMENTS_DIR, parse_experiment

        import src.experiment.parser as parser_mod
        original_dir = parser_mod.EXPERIMENTS_DIR
        try:
            parser_mod.EXPERIMENTS_DIR = Path(tmp_dir)
            result = parse_experiment(yaml_path)
        finally:
            parser_mod.EXPERIMENTS_DIR = original_dir

        assert result["metadata"] is not None
        assert result["metadata"]["material_system"] == "CsPbBr3"
        assert result["metadata"]["batch_id"] == "CsPbBr3_20260528_B01"
        assert result["metadata"]["condition_id"] == "T140_t180_R2"
        assert result["metadata"]["sample_index"] == 3
        assert result["metadata"]["operator"] == "WH"
        print("[OK] 新 YAML 正确解析 metadata 字段")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sample_id_generation():
    print("\n=== 测试3: sample_id 生成 ===")

    from src.science.sample_id import generate_sample_id, generate_batch_id, generate_condition_id

    sid = generate_sample_id(batch_id="CsPbBr3_20260528_B01", sample_index=3)
    assert sid == "CsPbBr3_20260528_B01_S003"
    print(f"  sample_id: {sid}")

    sid2 = generate_sample_id(batch_id="CsPbBr3_20260528_B01", sample_index=1)
    assert sid2 == "CsPbBr3_20260528_B01_S001"

    sid3 = generate_sample_id(batch_id="CsPbBr3_20260528_B01", sample_index=12)
    assert sid3 == "CsPbBr3_20260528_B01_S012"

    print("[OK] sample_id 格式正确")


def test_sample_id_auto_generation_no_batch_id():
    print("\n=== 测试4: sample_id 无 batch_id 时自动生成 ===")

    from src.science.sample_id import generate_sample_id

    sid = generate_sample_id(batch_id="", sample_index=1)
    assert sid.endswith("_S001")
    assert "UNKNOWN" in sid
    print(f"  auto sample_id: {sid}")
    print("[OK] 无 batch_id 时自动生成带 UNKNOWN 前缀的 sample_id")


def test_sample_id_min_index():
    print("\n=== 测试5: sample_id sample_index < 1 时强制为 1 ===")

    from src.science.sample_id import generate_sample_id

    sid = generate_sample_id(batch_id="TEST_B01", sample_index=0)
    assert sid == "TEST_B01_S001"
    print(f"  corrected sample_id: {sid}")

    sid2 = generate_sample_id(batch_id="TEST_B01", sample_index=-5)
    assert sid2 == "TEST_B01_S001"
    print("[OK] sample_index < 1 时自动修正为 1")


def test_batch_id_generation():
    print("\n=== 测试6: batch_id 生成 ===")

    from src.science.sample_id import generate_batch_id

    bid = generate_batch_id(material_system="CsPbBr3", batch_number=1)
    today = datetime.now().strftime("%Y%m%d")
    assert bid == f"CsPbBr3_{today}_B01"
    print(f"  batch_id: {bid}")

    bid2 = generate_batch_id(material_system="", batch_number=2)
    assert "UNKNOWN" in bid2
    assert bid2.endswith("_B02")
    print(f"  auto batch_id: {bid2}")
    print("[OK] batch_id 生成正确")


def test_condition_id_generation():
    print("\n=== 测试7: condition_id 生成 ===")

    from src.science.sample_id import generate_condition_id

    cid = generate_condition_id(params={"temperature": 140, "time": 180}, repeat=2)
    assert cid == "T140_t180_R2"
    print(f"  condition_id: {cid}")

    cid2 = generate_condition_id(repeat=1)
    assert cid2 == "R1"
    print(f"  empty condition_id: {cid2}")
    print("[OK] condition_id 生成正确")


def test_sample_record_write():
    print("\n=== 测试8: samples.csv 写入 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import SAMPLES_DIR, SAMPLES_CSV, write_sample_record, _existing_run_ids
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "CsPbBr3_20260528_B01_S003",
                "batch_id": "CsPbBr3_20260528_B01",
                "condition_id": "T140_t180_R2",
                "material_system": "CsPbBr3",
                "operator": "WH",
                "recipe_file": "cspbbr3_baseline.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }

            result = write_sample_record(
                run_id="20260528_100000_abc123",
                metadata=metadata,
                status="completed",
                error_flag=False,
            )
            assert result is True
            assert sr_mod.SAMPLES_CSV.exists()

            with open(sr_mod.SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                row = rows[0]
                assert row["sample_id"] == "CsPbBr3_20260528_B01_S003"
                assert row["batch_id"] == "CsPbBr3_20260528_B01"
                assert row["run_id"] == "20260528_100000_abc123"
                assert row["error_flag"] == "false"
                assert row["status"] == "completed"

            print("[OK] samples.csv 写入正确，header 自动生成")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_dir / "samples.csv"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sample_record_duplicate_prevention():
    print("\n=== 测试9: samples.csv 防止重复 run_id ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "TEST_S001",
                "batch_id": "TEST_B01",
                "condition_id": "R1",
                "material_system": "Test",
                "operator": "TEST",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }

            result1 = write_sample_record(run_id="dup_run_001", metadata=metadata, status="completed")
            assert result1 is True

            result2 = write_sample_record(run_id="dup_run_001", metadata=metadata, status="completed")
            assert result2 is False

            with open(sr_mod.SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1

            print("[OK] 重复 run_id 不会写入第二行")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_dir / "samples.csv"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sample_record_failed_experiment():
    print("\n=== 测试10: 失败实验写入 samples.csv 且 error_flag=true ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "FAIL_S001",
                "batch_id": "FAIL_B01",
                "condition_id": "R1",
                "material_system": "Test",
                "operator": "TEST",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:05:00",
            }

            result = write_sample_record(
                run_id="fail_run_001",
                metadata=metadata,
                status="failed",
                error_flag=True,
            )
            assert result is True

            with open(sr_mod.SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row["error_flag"] == "true"
                assert row["status"] == "failed"
                assert row["sample_id"] == "FAIL_S001"

            print("[OK] 失败实验正确记录 error_flag=true")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_dir / "samples.csv"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_experiment_logger_start_run_generates_sample_id():
    print("\n=== 测试11: ExperimentLogger.start_run 自动生成 sample_id ===")

    from src.experiment.experiment_logger import ExperimentLogger

    exp_logger = ExperimentLogger(save_log=False)

    run_id = exp_logger.start_run(
        experiment_name="test",
        experiment_file="test.yaml",
        total_steps=3,
        metadata={
            "batch_id": "CsPbBr3_20260528_B01",
            "sample_index": 3,
            "material_system": "CsPbBr3",
            "operator": "WH",
        },
    )

    assert exp_logger.active_run is not None
    metadata = exp_logger.active_run.metadata
    assert metadata["sample_id"] == "CsPbBr3_20260528_B01_S003"
    assert metadata["recipe_file"] == "test.yaml"
    assert "started_at" in metadata
    print(f"  run_id: {run_id}")
    print(f"  sample_id: {metadata['sample_id']}")
    print("[OK] start_run 时自动生成 sample_id 并写入 metadata")


def test_experiment_logger_start_run_no_metadata():
    print("\n=== 测试12: ExperimentLogger.start_run 无 metadata 时正常启动 ===")

    from src.experiment.experiment_logger import ExperimentLogger

    exp_logger = ExperimentLogger(save_log=False)

    run_id = exp_logger.start_run(
        experiment_name="test",
        experiment_file="test.yaml",
        total_steps=2,
    )

    assert exp_logger.active_run is not None
    metadata = exp_logger.active_run.metadata
    assert "sample_id" in metadata
    assert "UNKNOWN" in metadata["sample_id"]
    assert metadata["recipe_file"] == "test.yaml"
    print(f"  run_id: {run_id}")
    print(f"  auto sample_id: {metadata['sample_id']}")
    print("[OK] 无 metadata 时自动生成 sample_id，不报错")


def test_experiment_logger_finish_run_writes_samples_csv():
    print("\n=== 测试13: finish_run 写入 samples.csv ===")

    tmp_dir = Path(tempfile.mkdtemp())
    samples_tmp = tmp_dir / "samples.csv"
    try:
        from src.experiment.experiment_logger import ExperimentLogger, LOGS_DIR
        from src.science import sample_record as sr_mod
        import src.experiment.experiment_logger as el_mod

        original_logs_dir = el_mod.LOGS_DIR
        original_samples_dir = sr_mod.SAMPLES_DIR
        original_samples_csv = sr_mod.SAMPLES_CSV

        el_mod.LOGS_DIR = tmp_dir
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = samples_tmp
        try:
            exp_logger = ExperimentLogger(save_log=True)

            exp_logger.start_run(
                experiment_name="test",
                experiment_file="test.yaml",
                total_steps=1,
                metadata={
                    "batch_id": "TEST_B01",
                    "sample_index": 1,
                    "material_system": "Test",
                    "operator": "WH",
                },
            )

            exp_logger.finish_run("completed")

            assert samples_tmp.exists()
            with open(samples_tmp, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                row = rows[0]
                assert row["error_flag"] == "false"
                assert row["status"] == "completed"
                assert row["sample_id"] == "TEST_B01_S001"
                assert row["raw_log_path"] != ""

            print(f"  sample_id in CSV: {rows[0]['sample_id']}")
            print("[OK] finish_run 正确写入 samples.csv")
        finally:
            el_mod.LOGS_DIR = original_logs_dir
            sr_mod.SAMPLES_DIR = original_samples_dir
            sr_mod.SAMPLES_CSV = original_samples_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_experiment_logger_finish_run_failed_writes_error_flag():
    print("\n=== 测试14: 失败实验 finish_run 写入 error_flag=true ===")

    tmp_dir = Path(tempfile.mkdtemp())
    samples_tmp = tmp_dir / "samples.csv"
    try:
        from src.experiment.experiment_logger import ExperimentLogger
        from src.science import sample_record as sr_mod
        import src.experiment.experiment_logger as el_mod

        original_logs_dir = el_mod.LOGS_DIR
        original_samples_dir = sr_mod.SAMPLES_DIR
        original_samples_csv = sr_mod.SAMPLES_CSV

        el_mod.LOGS_DIR = tmp_dir
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = samples_tmp
        try:
            exp_logger = ExperimentLogger(save_log=True)

            exp_logger.start_run(
                experiment_name="fail_test",
                experiment_file="fail_test.yaml",
                total_steps=1,
                metadata={
                    "batch_id": "FAIL_B01",
                    "sample_index": 1,
                    "material_system": "Test",
                    "operator": "WH",
                },
            )

            exp_logger.finish_run("failed")

            with open(samples_tmp, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row["error_flag"] == "true"
                assert row["status"] == "failed"

            print("[OK] 失败实验 samples.csv 中 error_flag=true")
        finally:
            el_mod.LOGS_DIR = original_logs_dir
            sr_mod.SAMPLES_DIR = original_samples_dir
            sr_mod.SAMPLES_CSV = original_samples_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_engine_load_steps_backward_compatible():
    print("\n=== 测试15: engine.load_steps 向后兼容（无 metadata 参数）===")

    from src.experiment.engine import ExperimentEngine
    from src.experiment.executor import StepExecutor

    mock_dm = Mock()
    executor = StepExecutor(mock_dm)
    engine = ExperimentEngine(executor)

    from src.experiment.actions import ExperimentStep, ActionType, WaitCondition, WaitType

    steps = [
        ExperimentStep(
            id="step1",
            type=ActionType.WAIT,
            params={},
            wait=WaitCondition(type=WaitType.DURATION, seconds=1),
        )
    ]

    engine.load_steps(steps, name="test", filename="test.yaml")
    assert engine._metadata == {}
    print("[OK] load_steps 无 metadata 参数时默认空 dict")

    engine2 = ExperimentEngine(executor)
    engine2.load_steps(steps, name="test", filename="test.yaml", metadata={"batch_id": "TEST"})
    assert engine2._metadata == {"batch_id": "TEST"}
    print("[OK] load_steps 带 metadata 参数时正确传递")


def test_list_experiments_includes_metadata_yaml():
    print("\n=== 测试16: list_experiments 展示带 metadata 的 YAML ===")

    from src.experiment.parser import list_experiments

    exps = list_experiments()
    names = [e["name"] for e in exps]
    assert "cspbbr3_baseline" in names or any("CsPbBr3" in e.get("description", "") for e in exps)
    print(f"  当前实验列表: {names}")
    print("[OK] list_experiments 正常工作")


def test_sample_record_utf8_encoding():
    print("\n=== 测试17: samples.csv UTF-8 编码支持中文 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "中文_S001",
                "batch_id": "中文批次_B01",
                "condition_id": "R1",
                "material_system": "量子点材料",
                "operator": "张三",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }

            write_sample_record(run_id="utf8_test_001", metadata=metadata, status="completed")

            with open(sr_mod.SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row["sample_id"] == "中文_S001"
                assert row["batch_id"] == "中文批次_B01"
                assert row["operator"] == "张三"

            print("[OK] UTF-8 编码中文内容正确写入和读取")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_dir / "samples.csv"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_all():
    tests = [
        test_parser_old_yaml_no_metadata,
        test_parser_new_yaml_with_metadata,
        test_sample_id_generation,
        test_sample_id_auto_generation_no_batch_id,
        test_sample_id_min_index,
        test_batch_id_generation,
        test_condition_id_generation,
        test_sample_record_write,
        test_sample_record_duplicate_prevention,
        test_sample_record_failed_experiment,
        test_experiment_logger_start_run_generates_sample_id,
        test_experiment_logger_start_run_no_metadata,
        test_experiment_logger_finish_run_writes_samples_csv,
        test_experiment_logger_finish_run_failed_writes_error_flag,
        test_engine_load_steps_backward_compatible,
        test_list_experiments_includes_metadata_yaml,
        test_sample_record_utf8_encoding,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            import traceback
            print(f"\n[FAIL] {test.__name__}: {e}")
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"测试结果: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)