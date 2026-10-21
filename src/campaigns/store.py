import json
import os
import threading
from functools import wraps
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
    validate_finite_numbers,
)
from src.utils.logger import get_logger
from src.utils.runtime_paths import data_path

logger = get_logger(__name__)

CAMPAIGNS_DIR = data_path("data/campaigns")
CAMPAIGNS_JSON = CAMPAIGNS_DIR / "campaigns.json"
TRIALS_JSON = CAMPAIGNS_DIR / "trials.json"
RECOMMENDATIONS_JSON = CAMPAIGNS_DIR / "recommendations.json"
CHARACTERIZATIONS_JSON = CAMPAIGNS_DIR / "characterizations.json"
_STORE_LOCK = threading.RLock()


class CampaignStorageError(RuntimeError):
    """Existing records are unreadable; preserve them for explicit recovery."""


def _validate_rows(value, filename):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CampaignStorageError(f"{filename} 必须是 JSON 对象列表；原文件已保留")
    try:
        validate_finite_numbers(value)
    except ValueError as exc:
        raise CampaignStorageError(f"{filename} 包含非有限数值；原文件已保留") from exc
    return value


def _synchronized(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _STORE_LOCK:
            return func(*args, **kwargs)
    return wrapper


@_synchronized
def _ensure_store() -> None:
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
    for path in (CAMPAIGNS_JSON, TRIALS_JSON, RECOMMENDATIONS_JSON, CHARACTERIZATIONS_JSON):
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")
    _recover_recommendation()
    _recover_characterization()


@_synchronized
def _read_list(path: Path) -> List[Dict[str, Any]]:
    _ensure_store()
    try:
        text = path.read_text(encoding="utf-8").strip()
        data = json.loads(text)
        return _validate_rows(data, path.name)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        raise CampaignStorageError(f"{path.name} 不是有效 JSON；原文件已保留") from e


@_synchronized
def _write_list(path: Path, rows: List[Dict[str, Any]]) -> None:
    _ensure_store()
    _write_json(path, rows)


def _write_json(path: Path, value) -> None:
    validate_finite_numbers(value)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_recovery(journal, keys):
    try:
        previous = json.loads(journal.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CampaignStorageError(f"{journal.name} 不是有效 JSON；恢复文件已保留") from exc
    if not isinstance(previous, dict) or any(key not in previous for key in keys):
        raise CampaignStorageError(f"{journal.name} 恢复结构无效；恢复文件已保留")
    for key in keys:
        _validate_rows(previous[key], journal.name)
    return previous


def _recover_recommendation() -> None:
    """Roll back an interrupted pair of writes before exposing store contents."""
    journal = CAMPAIGNS_DIR / "recommendation.pending.json"
    if not journal.exists():
        return
    previous = _read_recovery(journal, ("trials", "recommendations"))
    _write_json(TRIALS_JSON, previous["trials"])
    _write_json(RECOMMENDATIONS_JSON, previous["recommendations"])
    journal.unlink()


def _new_trials(campaign_id, recommendation_id, parameters_batch):
    now = utc_now_iso()
    return [Trial(
        trial_id=_make_id("trial"), campaign_id=campaign_id,
        parameters=parameters, status=TrialStatus.PLANNED.value,
        recommendation_id=recommendation_id, created_at=now, updated_at=now,
    ).to_dict() for parameters in parameters_batch]


def _recover_characterization() -> None:
    journal = CAMPAIGNS_DIR / "characterization.pending.json"
    if not journal.exists():
        return
    previous = _read_recovery(journal, ("trials", "characterizations"))
    _write_json(TRIALS_JSON, previous["trials"])
    _write_json(CHARACTERIZATIONS_JSON, previous["characterizations"])
    journal.unlink()


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

    @_synchronized
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

    @_synchronized
    def create_trials(
        self,
        *,
        campaign_id: str,
        recommendation_id: str,
        parameters_batch: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        validate_finite_numbers(parameters_batch)
        trials = _read_list(TRIALS_JSON)
        created = _new_trials(campaign_id, recommendation_id, parameters_batch)
        trials.extend(created)
        _write_list(TRIALS_JSON, trials)
        return created

    @_synchronized
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

    @_synchronized
    def create_recommendation(
        self,
        *,
        campaign_id: str,
        planner_name: str,
        parameters_batch: List[Dict[str, Any]],
        notes: str = "",
    ) -> Dict[str, Any]:
        validate_finite_numbers(parameters_batch)
        recommendation_id = _make_id("rec")
        previous_trials = _read_list(TRIALS_JSON)
        previous_recommendations = _read_list(RECOMMENDATIONS_JSON)
        trials = _new_trials(campaign_id, recommendation_id, parameters_batch)
        recommendation = Recommendation(
            recommendation_id=recommendation_id,
            campaign_id=campaign_id,
            planner_name=planner_name,
            trial_ids=[trial["trial_id"] for trial in trials],
            parameters_batch=parameters_batch,
            notes=notes.strip(),
        ).to_dict()
        journal = CAMPAIGNS_DIR / "recommendation.pending.json"
        _write_json(journal, {"trials": previous_trials, "recommendations": previous_recommendations})
        try:
            _write_json(TRIALS_JSON, previous_trials + trials)
            _write_json(RECOMMENDATIONS_JSON, previous_recommendations + [recommendation])
            journal.unlink()
        except Exception:
            # If rollback also fails, retain the journal and fail subsequent
            # access until recovery succeeds; never return a partial pair.
            _recover_recommendation()
            raise
        return {"recommendation": recommendation, "trials": trials}

    def list_characterizations(self, campaign_id: str) -> List[Dict[str, Any]]:
        return [row for row in _read_list(CHARACTERIZATIONS_JSON) if row.get("campaign_id") == campaign_id]

    @_synchronized
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
        validate_finite_numbers(metrics)
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
        previous_trials = _read_list(TRIALS_JSON)
        trials = [dict(trial) for trial in previous_trials]
        trial = next((t for t in trials if t.get("campaign_id") == campaign_id and t.get("trial_id") == trial_id), None)
        if trial is None:
            raise KeyError(f"Trial not found: {trial_id}")
        trial.update(status=TrialStatus.CHARACTERIZED.value, updated_at=utc_now_iso())
        if sample_id:
            trial["sample_id"] = sample_id
        journal = CAMPAIGNS_DIR / "characterization.pending.json"
        _write_json(journal, {"trials": previous_trials, "characterizations": rows})
        try:
            _write_json(CHARACTERIZATIONS_JSON, rows + [result])
            _write_json(TRIALS_JSON, trials)
            journal.unlink()
        except Exception:
            _recover_characterization()
            raise
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

    @_synchronized
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
