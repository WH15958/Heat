import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

SAMPLES_DIR = Path("data/datasets")
SAMPLES_CSV = SAMPLES_DIR / "samples.csv"

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
    except Exception:
        pass
    return ids


def existing_sample_ids() -> set:
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
    except Exception:
        pass
    return ids


def write_sample_record(
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
    batch_id = metadata.get("batch_id", "")
    condition_id = metadata.get("condition_id", "")
    recipe_file = metadata.get("recipe_file", "")
    material_system = metadata.get("material_system", "")
    operator = metadata.get("operator", "")
    started_at = metadata.get("started_at", "")
    finished_at = metadata.get("finished_at", datetime.now().isoformat())
    raw_log_path = log_file_path or metadata.get("raw_log_path", "")

    write_header = not SAMPLES_CSV.exists() or os.path.getsize(SAMPLES_CSV) == 0

    try:
        with open(SAMPLES_CSV, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(SAMPLE_HEADERS)
            row = [
                sample_id,
                batch_id,
                condition_id,
                run_id,
                recipe_file,
                material_system,
                operator,
                started_at,
                finished_at,
                status,
                raw_log_path,
                notes,
                str(error_flag).lower(),
            ]
            writer.writerow(row)
        logger.info(f"Sample record written to {SAMPLES_CSV}: run_id={run_id}, sample_id={sample_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to write sample record: {e}")
        return False