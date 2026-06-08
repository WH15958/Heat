import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.campaigns.models import (
    Campaign,
    CampaignStatus,
    CharacterizationResult,
    Recommendation,
    Trial,
    TrialStatus,
    utc_now_iso,
    validate_campaign_status,
    validate_trial_status,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

CAMPAIGNS_DIR = Path("data/campaigns")
CAMPAIGNS_JSON = CAMPAIGNS_DIR / "campaigns.json"
TRIALS_JSON = CAMPAIGNS_DIR / "trials.json"
RECOMMENDATIONS_JSON = CAMPAIGNS_DIR / "recommendations.json"
CHARACTERIZATIONS_JSON = CAMPAIGNS_DIR / "characterizations.json"


def _ensure_store() -> None:
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
    for path in (CAMPAIGNS_JSON, TRIALS_JSON, RECOMMENDATIONS_JSON, CHARACTERIZATIONS_JSON):
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")


def _read_list(path: Path) -> List[Dict[str, Any]]:
    _ensure_store()
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, list):
            return data
        logger.warning(f"Expected list in {path}, got {type(data).__name__}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        raise


def _write_list(path: Path, rows: List[Dict[str, Any]]) -> None:
    _ensure_store()
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _make_id(prefix: str) -> str:
    return f"{prefix}_{utc_now_iso().replace(':', '').replace('-', '').replace('Z', '')}_{uuid4().hex[:8]}"


class CampaignStore:
    def list_campaigns(self) -> List[Dict[str, Any]]:
        return _read_list(CAMPAIGNS_JSON)

    def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        for campaign in self.list_campaigns():
            if campaign.get("campaign_id") == campaign_id:
                return campaign
        return None

    def create_campaign(
        self,
        *,
        name: str,
        material_system: str,
        objective_metric: str,
        parameter_names: List[str],
        notes: str = "",
    ) -> Dict[str, Any]:
        now = utc_now_iso()
        campaign = Campaign(
            campaign_id=_make_id("camp"),
            name=name.strip(),
            material_system=material_system.strip(),
            objective_metric=objective_metric.strip(),
            parameter_names=[p.strip() for p in parameter_names if p.strip()],
            status=CampaignStatus.ACTIVE.value,
            created_at=now,
            updated_at=now,
            notes=notes.strip(),
        ).to_dict()
        rows = self.list_campaigns()
        rows.append(campaign)
        _write_list(CAMPAIGNS_JSON, rows)
        return campaign

    def list_trials(self, campaign_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_list(TRIALS_JSON) if row.get("campaign_id") == campaign_id]

    def get_trial(self, campaign_id: str, trial_id: str) -> Optional[Dict[str, Any]]:
        for trial in self.list_trials(campaign_id):
            if trial.get("trial_id") == trial_id:
                return trial
        return None

    def create_trials(
        self,
        *,
        campaign_id: str,
        recommendation_id: str,
        parameters_batch: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = utc_now_iso()
        trials = _read_list(TRIALS_JSON)
        created = []
        for parameters in parameters_batch:
            trial = Trial(
                trial_id=_make_id("trial"),
                campaign_id=campaign_id,
                parameters=parameters,
                status=TrialStatus.PLANNED.value,
                recommendation_id=recommendation_id,
                created_at=now,
                updated_at=now,
            ).to_dict()
            trials.append(trial)
            created.append(trial)
        _write_list(TRIALS_JSON, trials)
        return created

    def update_trial(self, campaign_id: str, trial_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        rows = _read_list(TRIALS_JSON)
        for idx, trial in enumerate(rows):
            if trial.get("campaign_id") == campaign_id and trial.get("trial_id") == trial_id:
                if "status" in updates and updates["status"] not in (None, ""):
                    trial["status"] = validate_trial_status(updates["status"])
                for key in ("run_id", "sample_id", "notes"):
                    if key in updates and updates[key] is not None:
                        trial[key] = updates[key]
                trial["updated_at"] = utc_now_iso()
                rows[idx] = trial
                _write_list(TRIALS_JSON, rows)
                return trial
        raise KeyError(f"Trial not found: {trial_id}")

    def list_recommendations(self, campaign_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_list(RECOMMENDATIONS_JSON) if row.get("campaign_id") == campaign_id]

    def create_recommendation(
        self,
        *,
        campaign_id: str,
        planner_name: str,
        parameters_batch: List[Dict[str, Any]],
        notes: str = "",
    ) -> Dict[str, Any]:
        recommendation_id = _make_id("rec")
        trials = self.create_trials(
            campaign_id=campaign_id,
            recommendation_id=recommendation_id,
            parameters_batch=parameters_batch,
        )
        recommendation = Recommendation(
            recommendation_id=recommendation_id,
            campaign_id=campaign_id,
            planner_name=planner_name,
            trial_ids=[trial["trial_id"] for trial in trials],
            parameters_batch=parameters_batch,
            notes=notes.strip(),
        ).to_dict()
        rows = _read_list(RECOMMENDATIONS_JSON)
        rows.append(recommendation)
        _write_list(RECOMMENDATIONS_JSON, rows)
        return {"recommendation": recommendation, "trials": trials}

    def list_characterizations(self, campaign_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_list(CHARACTERIZATIONS_JSON) if row.get("campaign_id") == campaign_id]

    def create_characterization(
        self,
        *,
        campaign_id: str,
        trial_id: str,
        characterization_type: str,
        metrics: Dict[str, Any],
        sample_id: str = "",
        raw_file_path: str = "",
        notes: str = "",
        measured_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = CharacterizationResult(
            characterization_id=_make_id("char"),
            campaign_id=campaign_id,
            trial_id=trial_id,
            characterization_type=characterization_type.strip(),
            metrics=metrics,
            sample_id=sample_id.strip(),
            raw_file_path=raw_file_path.strip(),
            notes=notes.strip(),
            measured_at=measured_at,
        ).to_dict()
        rows = _read_list(CHARACTERIZATIONS_JSON)
        rows.append(result)
        _write_list(CHARACTERIZATIONS_JSON, rows)
        if trial_id:
            self.update_trial(
                campaign_id,
                trial_id,
                {
                    "status": TrialStatus.CHARACTERIZED.value,
                    "sample_id": sample_id or None,
                },
            )
        return result

    def build_history(self, campaign_id: str) -> List[Dict[str, Any]]:
        trials = {trial["trial_id"]: trial for trial in self.list_trials(campaign_id)}
        history = []
        for result in self.list_characterizations(campaign_id):
            trial = trials.get(result.get("trial_id"), {})
            history.append(
                {
                    "trial_id": result.get("trial_id", ""),
                    "sample_id": result.get("sample_id") or trial.get("sample_id", ""),
                    "parameters": trial.get("parameters", {}),
                    "metrics": result.get("metrics", {}),
                    "characterization_type": result.get("characterization_type", ""),
                    "accepted_for_planner": trial.get("status") == TrialStatus.ACCEPTED_FOR_PLANNER.value,
                    "trial_status": trial.get("status", ""),
                    "measured_at": result.get("measured_at"),
                }
            )
        return history

    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        rows = self.list_campaigns()
        for idx, campaign in enumerate(rows):
            if campaign.get("campaign_id") == campaign_id:
                campaign["status"] = validate_campaign_status(status)
                campaign["updated_at"] = utc_now_iso()
                rows[idx] = campaign
                _write_list(CAMPAIGNS_JSON, rows)
                return campaign
        raise KeyError(f"Campaign not found: {campaign_id}")
