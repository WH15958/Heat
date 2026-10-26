import csv
import os
import threading
from datetime import datetime
from typing import Iterable, Optional

from src.utils.logger import get_logger
from src.utils.runtime_paths import data_path

logger = get_logger(__name__)

SAMPLES_DIR = data_path("data/datasets")
SAMPLES_CSV = SAMPLES_DIR / "samples.csv"
_SAMPLE_FILE_LOCK = threading.Lock()

SAMPLE_HEADERS = [
    "sample_id",
    "batch_id",
    "condition_id",
    "run_id",
    "recipe_file",
    "material_system",
    "operator",
    "started_at",
    "finished_at",
    "status",
    "raw_log_path",
    "notes",
    "error_flag",
]


def _ensure_dir():
    try:
        SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create samples directory {SAMPLES_DIR}: {e}")
        raise


def _read_sample_rows():
    if not SAMPLES_CSV.exists():
        return list(SAMPLE_HEADERS), []
    with open(SAMPLES_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        try:
            fields = reader.fieldnames
        except (csv.Error, UnicodeError) as exc:
            raise OSError("samples.csv 表头损坏；原文件已保留") from exc
        if fields is None:
            return list(SAMPLE_HEADERS), []
        if (not {'sample_id', 'run_id'}.issubset(fields) or any(not field for field in fields)
                or len(set(fields)) != len(fields)):
            raise OSError("samples.csv 表头损坏；原文件已保留")
        try:
            rows = list(reader)
        except (csv.Error, UnicodeError) as exc:
            raise OSError("samples.csv 格式损坏；原文件已保留") from exc
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise OSError("samples.csv 行列数量不一致；原文件已保留")
        return fields, rows


def _existing_run_ids() -> set:
    _, rows = _read_sample_rows()
    return {row['run_id'].strip() for row in rows if row['run_id'].strip()}


def existing_sample_ids(*, strict: bool = False) -> set:
    if not SAMPLES_CSV.exists():
        return set()
    ids = set()
    try:
        if strict:
            _, rows = _read_sample_rows()
            return {row['sample_id'].strip() for row in rows if row['sample_id'].strip()}
        else:
            # Keep the legacy best-effort inspection mode; writes and ID
            # allocation always use the validated reader above.
            with open(SAMPLES_CSV, 'r', encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    sample_id = row.get('sample_id', '').strip()
                    if sample_id:
                        ids.add(sample_id)
    except Exception as e:
        logger.warning(f"Failed to read existing sample ids from {SAMPLES_CSV}: {e}")
        if strict:
            raise
    return ids


def _remove_sample_records_for_run_ids_unlocked(run_ids: Iterable[str]) -> int:
    run_ids = {str(run_id).strip() for run_id in run_ids if str(run_id).strip()}
    if not run_ids or not SAMPLES_CSV.exists():
        return 0

    temp_path = SAMPLES_CSV.with_suffix(SAMPLES_CSV.suffix + ".tmp")
    try:
        fieldnames, rows = _read_sample_rows()
        kept_rows = [row for row in rows if row['run_id'].strip() not in run_ids]
        removed = len(rows) - len(kept_rows)

        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in kept_rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, SAMPLES_CSV)

        if removed:
            logger.info(f"Removed {removed} sample records for deleted runs")
        return removed
    except Exception as e:
        logger.error(f"Failed to remove sample records from {SAMPLES_CSV}: {e}")
        raise
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def remove_sample_records_for_run_ids(run_ids: Iterable[str]) -> int:
    with _SAMPLE_FILE_LOCK:
        return _remove_sample_records_for_run_ids_unlocked(run_ids)


def _write_sample_record_unlocked(
    run_id: str,
    metadata: dict,
    *,
    status: str = "completed",
    notes: str = "",
    error_flag: bool = False,
    log_file_path: str = "",
) -> bool:
    if not run_id:
        logger.error("Cannot write sample record: run_id is empty")
        return False

    try:
        _ensure_dir()
        fieldnames, existing_rows = _read_sample_rows()
    except Exception as exc:
        logger.error(f"Cannot read sample history; original file preserved: {exc}")
        return False
    existing_ids = {row['run_id'].strip() for row in existing_rows}
    if run_id in existing_ids:
        logger.warning(f"Sample record already exists for run_id={run_id}, skipping")
        return False

    sample_id = metadata.get("sample_id", "")
    if sample_id:
        sample_id_set = {row['sample_id'].strip() for row in existing_rows}
        if sample_id in sample_id_set:
            logger.warning(
                f"sample_id={sample_id} already exists in {SAMPLES_CSV}. "
                f"Duplicate sample_id may indicate sample_id generation issue."
            )

    batch_id = metadata.get("batch_id", "")
    condition_id = metadata.get("condition_id", "")
    recipe_file = metadata.get("recipe_file", "")
    material_system = metadata.get("material_system", "")
    operator = metadata.get("operator", "")
    started_at = metadata.get("started_at", "")
    finished_at = metadata.get("finished_at", datetime.now().isoformat())
    raw_log_path = log_file_path or metadata.get("raw_log_path", "")

    temp_path = SAMPLES_CSV.with_suffix(SAMPLES_CSV.suffix + ".tmp")
    try:
        row = {
            "sample_id": sample_id,
            "batch_id": batch_id,
            "condition_id": condition_id,
            "run_id": run_id,
            "recipe_file": recipe_file,
            "material_system": material_system,
            "operator": operator,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "raw_log_path": raw_log_path,
            "notes": notes,
            "error_flag": str(error_flag).lower(),
        }
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            fieldnames = list(dict.fromkeys([*fieldnames, *SAMPLE_HEADERS]))
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for existing_row in existing_rows:
                writer.writerow({key: existing_row.get(key, "") for key in fieldnames})
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, SAMPLES_CSV)
        logger.info(f"Sample record written to {SAMPLES_CSV}: run_id={run_id}, sample_id={sample_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to write sample record: {e}")
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def write_sample_record(
    run_id: str,
    metadata: dict,
    *,
    status: str = "completed",
    notes: str = "",
    error_flag: bool = False,
    log_file_path: str = "",
) -> bool:
    with _SAMPLE_FILE_LOCK:
        return _write_sample_record_unlocked(
            run_id,
            metadata,
            status=status,
            notes=notes,
            error_flag=error_flag,
            log_file_path=log_file_path,
        )
