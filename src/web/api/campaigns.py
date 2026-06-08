from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.campaigns.models import TrialStatus
from src.campaigns.store import CampaignStore
from src.ml.planner import ManualPlanner
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])
store = CampaignStore()


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1)
    material_system: str = ""
    objective_metric: str = Field(..., min_length=1)
    parameter_names: List[str] = Field(default_factory=list)
    notes: str = ""


class ManualRecommendationRequest(BaseModel):
    parameters_batch: List[Dict[str, Any]]
    batch_size: Optional[int] = None


class UpdateTrialRequest(BaseModel):
    status: Optional[str] = None
    run_id: Optional[str] = None
    sample_id: Optional[str] = None
    notes: Optional[str] = None


class CreateCharacterizationRequest(BaseModel):
    trial_id: str
    characterization_type: str = Field(..., min_length=1)
    metrics: Dict[str, Any]
    sample_id: str = ""
    raw_file_path: str = ""
    notes: str = ""
    measured_at: Optional[str] = None


@router.get("")
@router.get("/")
async def list_campaigns():
    return store.list_campaigns()


@router.post("")
@router.post("/")
async def create_campaign(body: CreateCampaignRequest):
    try:
        return store.create_campaign(
            name=body.name,
            material_system=body.material_system,
            objective_metric=body.objective_metric,
            parameter_names=body.parameter_names,
            notes=body.notes,
        )
    except Exception as e:
        logger.error(f"Failed to create campaign: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/{campaign_id}/recommendations/manual")
async def create_manual_recommendation(campaign_id: str, body: ManualRecommendationRequest):
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        planner = ManualPlanner(store)
        return planner.recommend(
            campaign=campaign,
            history=store.build_history(campaign_id),
            batch_size=body.batch_size or len(body.parameters_batch),
            manual_parameters=body.parameters_batch,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{campaign_id}/trials")
async def list_trials(campaign_id: str):
    if store.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return store.list_trials(campaign_id)


@router.patch("/{campaign_id}/trials/{trial_id}")
async def update_trial(campaign_id: str, trial_id: str, body: UpdateTrialRequest):
    if store.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        return store.update_trial(campaign_id, trial_id, body.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(status_code=404, detail="Trial not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{campaign_id}/characterizations")
async def create_characterization(campaign_id: str, body: CreateCharacterizationRequest):
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if store.get_trial(campaign_id, body.trial_id) is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    if campaign.get("objective_metric") not in body.metrics:
        raise HTTPException(
            status_code=400,
            detail=f"metrics must include objective_metric '{campaign.get('objective_metric')}'",
        )
    try:
        return store.create_characterization(
            campaign_id=campaign_id,
            trial_id=body.trial_id,
            characterization_type=body.characterization_type,
            metrics=body.metrics,
            sample_id=body.sample_id,
            raw_file_path=body.raw_file_path,
            notes=body.notes,
            measured_at=body.measured_at,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Trial not found")


@router.get("/{campaign_id}/history")
async def get_history(campaign_id: str):
    if store.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return store.build_history(campaign_id)


@router.get("/{campaign_id}/characterizations")
async def list_characterizations(campaign_id: str):
    if store.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return store.list_characterizations(campaign_id)


@router.get("/meta/trial-statuses")
async def list_trial_statuses():
    return [status.value for status in TrialStatus]
