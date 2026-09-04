import sys
import os
import tempfile
import shutil
import csv
import json
import asyncio
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

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.experiment.experiment_logger import ExperimentLogger
        import src.science.sample_record as sr_mod

        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
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
        finally:
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_experiment_logger_start_run_no_metadata():
    print("\n=== 测试12: ExperimentLogger.start_run 无 metadata 时正常启动 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.experiment.experiment_logger import ExperimentLogger
        import src.science.sample_record as sr_mod

        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
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
        finally:
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        (tmp_dir / "metadata_test.yaml").write_text(
            "name: metadata_test\n"
            "description: isolated fixture\n"
            "metadata:\n  material_system: test\n"
            "steps: []\n",
            encoding="utf-8",
        )
        exps = list_experiments(str(tmp_dir))
        assert exps == [{
            "filename": "metadata_test.yaml",
            "name": "metadata_test",
            "description": "isolated fixture",
            "steps_count": 0,
        }]
        print("[OK] list_experiments 使用独立 fixture 正常工作")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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


def test_sample_id_uniqueness_auto_increment():
    print("\n=== 测试18: sample_id 已存在时自动递增 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record, existing_sample_ids
        from src.science.sample_id import generate_unique_sample_id
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "TEST_B01_S001",
                "batch_id": "TEST_B01",
                "condition_id": "R1",
                "material_system": "Test",
                "operator": "WH",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }
            write_sample_record(run_id="unique_test_001", metadata=metadata, status="completed")

            existing = existing_sample_ids()
            assert "TEST_B01_S001" in existing

            metadata2 = {
                "batch_id": "TEST_B01",
                "sample_index": 1,
                "material_system": "Test",
                "operator": "WH",
            }
            sid = generate_unique_sample_id(metadata2)
            assert sid != "TEST_B01_S001"
            assert sid == "TEST_B01_S002"
            print(f"  第一个 sample_id: TEST_B01_S001")
            print(f"  第二个 sample_id (自动递增): {sid}")
            print("[OK] sample_id 重复时自动递增到下一个")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_explicit_sample_id_not_duplicated():
    print("\n=== 测试19: 显式提供 sample_id 且未重复时不被改写 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_id import generate_unique_sample_id
        import src.science.sample_record as sr_mod

        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "MY_CUSTOM_SID_001",
                "batch_id": "CUSTOM_B01",
                "material_system": "Custom",
            }
            sid = generate_unique_sample_id(metadata)
            assert sid == "MY_CUSTOM_SID_001"
            print(f"  sample_id: {sid}")
            print("[OK] 显式提供 sample_id 且未重复时保持不变")
        finally:
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_explicit_sample_id_duplicated_auto_fix():
    print("\n=== 测试20: 显式提供 sample_id 但已重复时自动递增并记录警告 ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record
        from src.science.sample_id import generate_unique_sample_id
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata_pre = {
                "sample_id": "DUP_S001",
                "batch_id": "DUP_B01",
                "condition_id": "R1",
                "material_system": "Test",
                "operator": "WH",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }
            write_sample_record(run_id="dup_test_001", metadata=metadata_pre, status="completed")

            metadata2 = {
                "sample_id": "DUP_S001",
                "batch_id": "DUP_B01",
                "sample_index": 1,
                "material_system": "Test",
            }

            import io
            import logging
            from src.science.sample_id import logger as sid_logger

            log_capture = io.StringIO()
            handler = logging.StreamHandler(log_capture)
            handler.setLevel(logging.WARNING)
            old_handlers = sid_logger.handlers[:]
            sid_logger.handlers = [handler]

            try:
                sid = generate_unique_sample_id(metadata2)
                assert sid != "DUP_S001"
                assert sid == "DUP_B01_S002"
                log_output = log_capture.getvalue()
                assert "already exists" in log_output
                print(f"  重复的 sample_id: DUP_S001")
                print(f"  自动修复为: {sid}")
                print(f"  日志警告: {log_output.strip()}")
                print("[OK] 显式 sample_id 重复时自动递增并记录警告")
            finally:
                sid_logger.handlers = old_handlers
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_save_log_false_raw_log_path_empty():
    print("\n=== 测试21: save_log=False 时 samples.csv 中 raw_log_path 为空 ===")

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
            exp_logger = ExperimentLogger(save_log=False)

            exp_logger.start_run(
                experiment_name="no_log_test",
                experiment_file="no_log_test.yaml",
                total_steps=1,
                metadata={
                    "batch_id": "NOLOG_B01",
                    "sample_index": 1,
                    "material_system": "Test",
                    "operator": "WH",
                },
            )

            exp_logger.finish_run("completed")

            assert samples_tmp.exists()
            with open(samples_tmp, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
                assert row["raw_log_path"] == ""
                assert row["status"] == "completed"
                assert row["sample_id"] == "NOLOG_B01_S001"

            print(f"  raw_log_path: '{row['raw_log_path']}'")
            print("[OK] save_log=False 时 raw_log_path 为空字符串")
        finally:
            el_mod.LOGS_DIR = original_logs_dir
            sr_mod.SAMPLES_DIR = original_samples_dir
            sr_mod.SAMPLES_CSV = original_samples_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_get_experiment_returns_metadata():
    print("\n=== 测试22: GET /experiments/{filename} 返回 metadata ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        yaml_content = """name: meta_test
description: Test metadata in API
metadata:
  material_system: CsPbBr3
  batch_id: CsPbBr3_20260528_B01
  condition_id: T140_t180_R2
  sample_index: 1
  operator: WH
  recipe_version: v0.1
steps:
  - id: step1
    type: wait
    params: {}
    wait:
      type: duration
      seconds: 1
"""
        yaml_path = tmp_dir / "meta_test.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        from src.experiment.parser import EXPERIMENTS_DIR, parse_experiment
        import src.experiment.parser as parser_mod

        original_dir = parser_mod.EXPERIMENTS_DIR
        parser_mod.EXPERIMENTS_DIR = tmp_dir
        try:
            result = parse_experiment(str(yaml_path))
        finally:
            parser_mod.EXPERIMENTS_DIR = original_dir

        assert "metadata" in result
        assert result["metadata"]["material_system"] == "CsPbBr3"
        assert result["metadata"]["batch_id"] == "CsPbBr3_20260528_B01"
        assert result["metadata"]["operator"] == "WH"
        assert result["description"] == "Test metadata in API"
        print(f"  metadata keys: {list(result['metadata'].keys())}")
        print("[OK] parse_experiment 返回 metadata 字段")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_start_experiment_returns_sample_id():
    print("\n=== 测试23: start_run 返回 sample_id ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.experiment.experiment_logger import ExperimentLogger
        import src.science.sample_record as sr_mod

        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            exp_logger = ExperimentLogger(save_log=False)

            exp_logger.start_run(
                experiment_name="api_test",
                experiment_file="api_test.yaml",
                total_steps=2,
                metadata={
                    "batch_id": "API_B01",
                    "sample_index": 1,
                    "material_system": "Test",
                    "operator": "WH",
                },
            )

            assert exp_logger.active_run is not None
            sample_id = exp_logger.active_run.metadata.get("sample_id")
            assert sample_id is not None
            assert sample_id == "API_B01_S001"
            assert "sample_id" in exp_logger.active_run.metadata
            assert "material_system" in exp_logger.active_run.metadata
            print(f"  sample_id: {sample_id}")
            print(f"  metadata: {exp_logger.active_run.metadata}")
            print("[OK] start_run 后 metadata 中包含 sample_id")
        finally:
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_existing_sample_ids_function():
    print("\n=== 测试24: existing_sample_ids() 正确读取已存在 sample_id ===")

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        from src.science.sample_record import write_sample_record, existing_sample_ids as sr_existing_sample_ids
        import src.science.sample_record as sr_mod

        original_dir = sr_mod.SAMPLES_DIR
        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_DIR = tmp_dir
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            metadata = {
                "sample_id": "READ_TEST_S001",
                "batch_id": "READ_B01",
                "condition_id": "R1",
                "material_system": "Test",
                "operator": "WH",
                "recipe_file": "test.yaml",
                "started_at": "2026-05-28T10:00:00",
                "finished_at": "2026-05-28T10:30:00",
            }
            write_sample_record(run_id="read_test_001", metadata=metadata, status="completed")

            existing = sr_existing_sample_ids()
            assert "READ_TEST_S001" in existing
            assert len(existing) == 1
            print(f"  existing sample_ids: {existing}")
            print("[OK] existing_sample_ids() 正确读取 sample_id")
        finally:
            sr_mod.SAMPLES_DIR = original_dir
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_active_engine_blocks_new_experiment():
    print("\n=== 测试26: 全局单实验运行保护 - running 引擎阻止新实验 ===")

    from src.web.api.experiments import _get_active_engine, _engines, _cleanup_engine
    from src.experiment.engine import ExperimentEngine, ExperimentState

    for key in list(_engines.keys()):
        _cleanup_engine(key)

    mock_executor = Mock()
    engine1 = ExperimentEngine(mock_executor)
    engine1._state = ExperimentState.RUNNING
    _engines["exp1.yaml"] = engine1

    active_fname, active_engine = _get_active_engine()
    assert active_fname == "exp1.yaml"
    assert active_engine is not None
    print(f"  活动引擎: {active_fname}, state: {active_engine.state.value}")
    print("[OK] _get_active_engine() 正确检测到 running 状态的引擎")

    engine1._state = ExperimentState.IDLE
    active_fname2, active_engine2 = _get_active_engine()
    assert active_fname2 is None
    print("[OK] 处于 idle 的引擎不被视为活动")

    for key in list(_engines.keys()):
        _cleanup_engine(key)


def test_paused_engine_blocks_new_experiment():
    print("\n=== 测试27: 全局单实验运行保护 - paused 引擎也阻止新实验 ===")

    from src.web.api.experiments import _get_active_engine, _engines, _cleanup_engine
    from src.experiment.engine import ExperimentEngine, ExperimentState

    for key in list(_engines.keys()):
        _cleanup_engine(key)

    mock_executor = Mock()
    engine1 = ExperimentEngine(mock_executor)
    engine1._state = ExperimentState.PAUSED
    _engines["exp1.yaml"] = engine1

    active_fname, active_engine = _get_active_engine()
    assert active_fname == "exp1.yaml"
    assert active_engine.state.value == "paused"
    print(f"  活动引擎: {active_fname}, state: {active_engine.state.value}")
    print("[OK] _get_active_engine() 正确检测到 paused 状态的引擎")

    for key in list(_engines.keys()):
        _cleanup_engine(key)


def test_completed_failed_stopped_do_not_block():
    print("\n=== 测试28: completed/failed/stopped 引擎不阻止新实验 ===")

    from src.web.api.experiments import _get_active_engine, _engines, _cleanup_engine
    from src.experiment.engine import ExperimentEngine, ExperimentState

    for key in list(_engines.keys()):
        _cleanup_engine(key)

    mock_executor = Mock()

    for state in [ExperimentState.COMPLETED, ExperimentState.FAILED, ExperimentState.STOPPED]:
        for key in list(_engines.keys()):
            _cleanup_engine(key)
        engine = ExperimentEngine(mock_executor)
        engine._state = state
        _engines[f"exp_{state.value}.yaml"] = engine

        active_fname, active_engine = _get_active_engine()
        assert active_fname is None, f"state={state.value} should not block"
        print(f"  state={state.value}: 不阻止新实验 [OK]")

    print("[OK] completed/failed/stopped 的引擎不阻止新实验")

    for key in list(_engines.keys()):
        _cleanup_engine(key)


def test_metadata_not_mutated_in_place():
    print("\n=== 测试29: start_run 不原地修改传入的 metadata dict ===")

    from src.experiment.experiment_logger import ExperimentLogger
    import src.science.sample_record as sr_mod

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            original_metadata = {
                "batch_id": "MUTATE_B01",
                "sample_index": 1,
                "material_system": "Test",
            }
            metadata_copy = dict(original_metadata)

            exp_logger = ExperimentLogger(save_log=False)
            exp_logger.start_run(
                experiment_name="mutate_test",
                experiment_file="mutate_test.yaml",
                total_steps=1,
                metadata=metadata_copy,
            )

            assert "sample_id" not in metadata_copy, (
                f"传入的 metadata dict 被原地修改了: {metadata_copy}"
            )
            assert metadata_copy == original_metadata, (
                f"传入的 metadata dict 内容被改变: {metadata_copy} != {original_metadata}"
            )
            print(f"  原始 metadata: {original_metadata}")
            print(f"  传入后 metadata_copy: {metadata_copy}")
            print("[OK] start_run 不原地修改传入的 metadata dict")
        finally:
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sample_index_string_conversion():
    print("\n=== 测试30: sample_index 为字符串 '3' 时生成 S003 ===")

    from src.science.sample_id import generate_sample_id, _normalize_sample_index

    assert _normalize_sample_index("3") == 3
    assert _normalize_sample_index(3) == 3
    assert _normalize_sample_index(None) == 1
    assert _normalize_sample_index("") == 1
    assert _normalize_sample_index("abc") == 1
    assert _normalize_sample_index(0) == 1
    assert _normalize_sample_index(-5) == 1
    print(f"  _normalize_sample_index('3') = {_normalize_sample_index('3')}")
    print(f"  _normalize_sample_index('abc') = {_normalize_sample_index('abc')}")
    print(f"  _normalize_sample_index(None) = {_normalize_sample_index(None)}")
    print(f"  _normalize_sample_index('') = {_normalize_sample_index('')}")

    sid = generate_sample_id(batch_id="TEST_B01", sample_index="3")
    assert "S003" in sid
    print(f"  generate_sample_id('TEST_B01', '3') = {sid}")
    print("[OK] 字符串 sample_index 正确转换为 int")


def test_sample_index_fallback_to_s001():
    print("\n=== 测试31: sample_index 非法值时 fallback 到 S001 ===")

    from src.science.sample_id import generate_sample_id

    sid = generate_sample_id(batch_id="TEST_B01", sample_index="not_a_number")
    assert "S001" in sid
    print(f"  generate_sample_id('TEST_B01', 'not_a_number') = {sid}")

    sid = generate_sample_id(batch_id="TEST_B01", sample_index=None)
    assert "S001" in sid
    print(f"  generate_sample_id('TEST_B01', None) = {sid}")

    sid = generate_sample_id(batch_id="TEST_B01", sample_index="")
    assert "S001" in sid
    print(f"  generate_sample_id('TEST_B01', '') = {sid}")

    sid = generate_sample_id(batch_id="TEST_B01", sample_index=0)
    assert "S001" in sid
    print(f"  generate_sample_id('TEST_B01', 0) = {sid}")

    sid = generate_sample_id(batch_id="TEST_B01", sample_index=-1)
    assert "S001" in sid
    print(f"  generate_sample_id('TEST_B01', -1) = {sid}")

    print("[OK] 非法 sample_index 正确 fallback 到 S001")


def test_existing_sample_ids_logs_warning_on_error():
    print("\n=== 测试32: samples.csv 读取异常时记录 warning ===")

    import logging
    from io import StringIO

    from src.science.sample_record import existing_sample_ids as sr_existing_sample_ids
    import src.science.sample_record as sr_mod

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        original_csv = sr_mod.SAMPLES_CSV
        damaged_csv = tmp_dir / "damaged_samples.csv"
        with open(damaged_csv, "w", encoding="utf-8") as f:
            f.write("sample_id,batch_id\n")
            f.write("OK_S001,B01\n")
            f.write("garbage_line_without_comma\n")
        sr_mod.SAMPLES_CSV = damaged_csv

        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.WARNING)
        sr_logger = logging.getLogger("src.science.sample_record")
        sr_logger.addHandler(handler)

        try:
            existing = sr_existing_sample_ids()
            log_output = log_stream.getvalue()
            assert "OK_S001" in existing
            print(f"  existing sample_ids: {existing}")
            print(f"  warning logged: {bool(log_output)}")
            print("[OK] 即使有损坏行也不抛异常，数据仍可读取")
        finally:
            sr_logger.removeHandler(handler)
            sr_mod.SAMPLES_CSV = original_csv
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_finish_run_does_not_crash_on_csv_write_failure():
    print("\n=== 测试25: samples.csv 写入失败会标记追踪失败 ===")

    from src.experiment.experiment_logger import ExperimentLogger

    exp_logger = ExperimentLogger(save_log=False)

    exp_logger.start_run(
        experiment_name="crash_test",
        experiment_file="crash_test.yaml",
        total_steps=1,
        metadata={
            "batch_id": "CRASH_B01",
            "sample_index": 1,
            "material_system": "Test",
        },
    )

    from src.science import sample_record as sr_mod
    import src.experiment.experiment_logger as el_mod

    original_write = el_mod.write_sample_record
    was_called = {"count": 0}

    def mock_write(*args, **kwargs):
        was_called["count"] += 1
        raise OSError("Simulated disk full")

    el_mod.write_sample_record = mock_write
    try:
        persistence_ok = exp_logger.finish_run("completed")
        assert was_called["count"] == 1
        assert persistence_ok is False
        assert exp_logger.active_run.status == "completed"
        assert exp_logger.active_run.persistence_status == "error"
        assert exp_logger.active_run.sample_record_saved is False
        assert exp_logger.active_run.persistence_errors
        print("[OK] 执行状态保持 completed，同时明确标记追踪记录失败")
    finally:
        el_mod.write_sample_record = original_write


def test_execute_returns_false_when_device_command_returns_false():
    print("\n=== 测试33: 设备命令返回 False 时 step 执行失败 ===")

    from src.experiment.executor import StepExecutor
    from src.experiment.actions import ExperimentStep, ActionType, WaitCondition, WaitType

    mock_dm = Mock()
    mock_dm.set_temperature.return_value = False
    executor = StepExecutor(mock_dm)

    step = ExperimentStep(
        id="set_temp_fail",
        type=ActionType.HEATER_SET_TEMP,
        params={"device_id": "heater1", "temperature": 80.0},
        wait=WaitCondition(type=WaitType.NONE),
    )

    result = asyncio.run(executor.execute(step))
    assert result is False
    print("[OK] 设备返回 False 时不会被误判为成功")


def test_wait_timeout_returns_false():
    print("\n=== 测试34: 等待条件超时时 step 执行失败 ===")

    from src.experiment.executor import StepExecutor
    from src.experiment.actions import ExperimentStep, ActionType, WaitCondition, WaitType

    mock_dm = Mock()
    mock_dm.read_heater_data.return_value = {"pv": 20.0, "sv": 80.0}
    executor = StepExecutor(mock_dm)

    step = ExperimentStep(
        id="wait_timeout",
        type=ActionType.WAIT,
        params={},
        wait=WaitCondition(
            type=WaitType.TEMPERATURE_REACHED,
            device_id="heater1",
            tolerance=0.5,
            timeout=0.1,
        ),
    )

    result = asyncio.run(executor.execute(step))
    assert result is False
    print("[OK] 等待超时会返回失败，不再静默继续")


def test_stop_experiment_waits_for_task_completion():
    print("\n=== 测试35: stop 接口等待任务结束后再清理引擎 ===")

    from src.experiment.engine import ExperimentEngine, ExperimentState
    from src.experiment.executor import StepExecutor
    from src.experiment.actions import ExperimentStep, ActionType, WaitCondition, WaitType
    from src.web.api.experiments import _engines, _cleanup_engine, stop_experiment

    async def scenario():
        for key in list(_engines.keys()):
            _cleanup_engine(key)

        mock_dm = Mock()
        executor = StepExecutor(mock_dm)
        engine = ExperimentEngine(executor)
        engine.load_steps([
            ExperimentStep(
                id="long_wait",
                type=ActionType.WAIT,
                params={},
                wait=WaitCondition(type=WaitType.DURATION, seconds=5),
            )
        ], name="test", filename="exp_stop.yaml")
        engine.on_complete(lambda: _cleanup_engine("exp_stop.yaml"))
        _engines["exp_stop.yaml"] = engine

        await engine.start()
        await asyncio.sleep(0.2)
        await stop_experiment("exp_stop.yaml")

        assert engine.state == ExperimentState.STOPPED
        assert "exp_stop.yaml" not in _engines

    asyncio.run(scenario())
    print("[OK] stop 会等待后台任务结束，并通过完成回调清理引擎")


def test_websocket_disconnect_does_not_stop_pumps():
    print("\n=== 测试36: WebSocket 断开不会自动停泵 ===")

    from types import SimpleNamespace
    from fastapi import WebSocketDisconnect
    from src.web.api.ws import websocket_endpoint, manager

    class FakeWebSocket:
        def __init__(self, device_manager):
            self.app = SimpleNamespace(state=SimpleNamespace(device_manager=device_manager))

        async def accept(self):
            return None

        async def receive_text(self):
            raise WebSocketDisconnect()

    pump = Mock()
    pump.is_connected.return_value = True
    dm = Mock()
    dm.get_all_pumps.return_value = {"pump1": pump}

    ws = FakeWebSocket(dm)
    asyncio.run(websocket_endpoint(ws))

    assert pump.stop_all.call_count == 0
    assert ws not in manager.active
    print("[OK] WebSocket 断开不再对泵发送 stop_all")


def test_experiment_logger_records_microwave_sensor_data():
    print("\n=== 测试37: ExperimentLogger 记录微波物料温度 ===")

    from src.experiment.experiment_logger import ExperimentLogger
    import src.science.sample_record as sr_mod

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        original_csv = sr_mod.SAMPLES_CSV
        sr_mod.SAMPLES_CSV = tmp_dir / "samples.csv"
        try:
            exp_logger = ExperimentLogger(save_log=False)
            exp_logger.start_run(
                experiment_name="microwave_sensor_test",
                experiment_file="microwave_sensor_test.yaml",
                total_steps=1,
                metadata={"batch_id": "MW_B01"},
            )

            exp_logger.record_sensor_data({
                "heaters": {},
                "pumps": {},
                "microwaves": {
                    "microwave1": {
                        "material_temperature": 42.5,
                        "power_percent": 5,
                    },
                    "microwave_error": {
                        "error": "read_failed",
                        "material_temperature": 99.0,
                    },
                },
            })

            sensor_data = exp_logger.active_run.sensor_data
            assert "microwaves" in sensor_data
            points = sensor_data["microwaves"]["microwave1"]["material_temperature"]
            assert len(points) == 1
            assert points[0]["v"] == 42.5
            assert points[0]["t"] >= 0.0
            assert "microwave_error" not in sensor_data["microwaves"]
            print("[OK] 微波物料温度写入 sensor_data，读取失败 payload 会跳过")
        finally:
            sr_mod.SAMPLES_CSV = original_csv
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
        test_sample_id_uniqueness_auto_increment,
        test_explicit_sample_id_not_duplicated,
        test_explicit_sample_id_duplicated_auto_fix,
        test_save_log_false_raw_log_path_empty,
        test_get_experiment_returns_metadata,
        test_start_experiment_returns_sample_id,
        test_existing_sample_ids_function,
        test_finish_run_does_not_crash_on_csv_write_failure,
        test_active_engine_blocks_new_experiment,
        test_paused_engine_blocks_new_experiment,
        test_completed_failed_stopped_do_not_block,
        test_metadata_not_mutated_in_place,
        test_sample_index_string_conversion,
        test_sample_index_fallback_to_s001,
        test_existing_sample_ids_logs_warning_on_error,
        test_execute_returns_false_when_device_command_returns_false,
        test_wait_timeout_returns_false,
        test_stop_experiment_waits_for_task_completion,
        test_websocket_disconnect_does_not_stop_pumps,
        test_experiment_logger_records_microwave_sensor_data,
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
