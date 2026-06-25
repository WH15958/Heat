from datetime import datetime
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_sample_index(sample_index) -> int:
    try:
        sample_index = int(sample_index) if sample_index not in (None, "") else 1
    except (ValueError, TypeError):
        sample_index = 1
    if sample_index < 1:
        sample_index = 1
    return sample_index


def generate_sample_id(
    batch_id: str,
    sample_index,
    *,
    date_format: str = "%Y%m%d",
) -> str:
    if not batch_id:
        today = datetime.now().strftime(date_format)
        batch_id = f"UNKNOWN_{today}_B01"

    sample_index = _normalize_sample_index(sample_index)

    return f"{batch_id}_S{sample_index:03d}"


def generate_unique_sample_id(metadata: dict) -> str:
    from src.science.sample_record import existing_sample_ids

    explicit_sample_id = (metadata.get("sample_id") or "").strip()

    if explicit_sample_id:
        existing = existing_sample_ids(strict=True)
        if explicit_sample_id not in existing:
            return explicit_sample_id

        logger.warning(
            f"Explicit sample_id={explicit_sample_id} already exists in samples.csv, "
            f"auto-incrementing to find unique sample_id"
        )
        batch_id = metadata.get("batch_id", "")
        sample_index = _normalize_sample_index(metadata.get("sample_index", 1))
        base_batch = batch_id if batch_id else ""
        existing = existing_sample_ids(strict=True)
        while True:
            sample_index += 1
            candidate = generate_sample_id(batch_id=base_batch, sample_index=sample_index)
            if candidate not in existing:
                return candidate

    batch_id = metadata.get("batch_id", "")
    sample_index = _normalize_sample_index(metadata.get("sample_index", 1))

    existing = existing_sample_ids(strict=True)
    candidate = generate_sample_id(batch_id=batch_id, sample_index=sample_index)
    while candidate in existing:
        sample_index += 1
        candidate = generate_sample_id(batch_id=batch_id, sample_index=sample_index)

    return candidate


def generate_batch_id(
    material_system: str,
    *,
    date_format: str = "%Y%m%d",
    batch_number: int = 1,
) -> str:
    if not material_system:
        material_system = "UNKNOWN"

    today = datetime.now().strftime(date_format)
    return f"{material_system}_{today}_B{batch_number:02d}"


def generate_condition_id(
    params: Optional[dict] = None,
    *,
    repeat: int = 1,
) -> str:
    if not params:
        return f"R{repeat}"

    parts = []
    if "temperature" in params:
        parts.append(f"T{params['temperature']}")
    if "time" in params:
        parts.append(f"t{params['time']}")
    if "flow_rate" in params:
        parts.append(f"F{params['flow_rate']}")
    parts.append(f"R{repeat}")

    return "_".join(parts)
