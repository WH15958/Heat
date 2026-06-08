from typing import Any, Dict, List, Protocol

from src.campaigns.store import CampaignStore


class Planner(Protocol):
    name: str

    def recommend(
        self,
        campaign: Dict[str, Any],
        history: List[Dict[str, Any]],
        batch_size: int,
        manual_parameters: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...


class ManualPlanner:
    name = "manual"

    def __init__(self, store: CampaignStore = None):
        self.store = store or CampaignStore()

    def recommend(
        self,
        campaign: Dict[str, Any],
        history: List[Dict[str, Any]],
        batch_size: int,
        manual_parameters: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        parameters_batch = list(manual_parameters or [])
        if not parameters_batch:
            raise ValueError("manual_parameters must contain at least one parameter set")
        if batch_size and batch_size != len(parameters_batch):
            raise ValueError("batch_size must match the number of manual parameter sets")
        if any(not isinstance(item, dict) for item in parameters_batch):
            raise ValueError("Each manual parameter set must be an object")

        return self.store.create_recommendation(
            campaign_id=campaign["campaign_id"],
            planner_name=self.name,
            parameters_batch=parameters_batch,
        )
