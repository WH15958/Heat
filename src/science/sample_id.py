from datetime import datetime
from typing import Optional


def generate_sample_id(
    batch_id: str,
    sample_index: int,
    *,
    date_format: str = "%Y%m%d",
) -> str:
    if not batch_id:
        today = datetime.now().strftime(date_format)
        batch_id = f"UNKNOWN_{today}_B01"

    if sample_index < 1:
        sample_index = 1

    return f"{batch_id}_S{sample_index:03d}"


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