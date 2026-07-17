from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class CampaignStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TrialStatus(str, Enum):
    PLANNED = "planned"
    READY_TO_RUN = "ready_to_run"
    RUNNING = "running"
    SYNTHESIZED = "synthesized"
    WAITING_CHARACTERIZATION = "waiting_characterization"
    CHARACTERIZED = "characterized"
    ACCEPTED_FOR_PLANNER = "accepted_for_planner"
    EXCLUDED = "excluded"
    FAILED = "failed"


@dataclass
class Campaign:
    campaign_id: str
    name: str
    material_system: str
    objective_metric: str
    parameter_names: List[str] = field(default_factory=list)
    status: str = CampaignStatus.ACTIVE.value
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Trial:
    trial_id: str
    campaign_id: str
    parameters: Dict[str, Any]
    status: str = TrialStatus.PLANNED.value
    recommendation_id: str = ""
    run_id: str = ""
    sample_id: str = ""
    notes: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Recommendation:
    recommendation_id: str
    campaign_id: str
    planner_name: str
    trial_ids: List[str]
    parameters_batch: List[Dict[str, Any]]
    created_at: str = field(default_factory=utc_now_iso)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CharacterizationResult:
    characterization_id: str
    campaign_id: str
    trial_id: str
    characterization_type: str
    metrics: Dict[str, Any]
    sample_id: str = ""
    raw_file_path: str = ""
    notes: str = ""
    measured_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_trial_status(status: str) -> str:
    valid = {item.value for item in TrialStatus}
    if status not in valid:
        raise ValueError(f"Invalid trial status: {status}")
    return status


def validate_campaign_status(status: str) -> str:
    valid = {item.value for item in CampaignStatus}
    if status not in valid:
        raise ValueError(f"Invalid campaign status: {status}")
    return status
