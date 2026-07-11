import csv
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

SAMPLES_DIR = Path("data/datasets")
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


def _existing_run_ids() -> set:
    if not SAMPLES_CSV.exists():
        return set()
    ids = set()
    try:
        with open(SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = row.get("run_id", "").strip()
                if rid:
                    ids.add(rid)
    except Exception as e:
        logger.warning(f"Failed to read existing sample ids from {SAMPLES_CSV}: {e}")
        pass
    return ids


def existing_sample_ids(*, strict: bool = False) -> set:
    if not SAMPLES_CSV.exists():
        return set()
    ids = set()
    try:
        with open(SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("sample_id", "").strip()
                if sid:
                    ids.add(sid)
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
        with open(SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or SAMPLE_HEADERS
            kept_rows = []
            removed = 0
            for row in reader:
                if row.get("run_id", "").strip() in run_ids:
                    removed += 1
                else:
                    kept_rows.append(row)

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
        return 0
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

    _ensure_dir()

    existing_ids = _existing_run_ids()
    if run_id in existing_ids:
        logger.warning(f"Sample record already exists for run_id={run_id}, skipping")
        return False

    sample_id = metadata.get("sample_id", "")
    if sample_id:
        sample_id_set = existing_sample_ids()
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
        existing_rows = []
        if SAMPLES_CSV.exists() and os.path.getsize(SAMPLES_CSV) > 0:
            with open(SAMPLES_CSV, "r", encoding="utf-8", newline="") as f:
                existing_rows = list(csv.DictReader(f))

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
            writer = csv.DictWriter(f, fieldnames=SAMPLE_HEADERS)
            writer.writeheader()
            for existing_row in existing_rows:
                writer.writerow({key: existing_row.get(key, "") for key in SAMPLE_HEADERS})
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
