import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "src"))


def _patch_campaign_store(tmp_path, monkeypatch):
    from src.campaigns import store as store_mod

    data_dir = tmp_path / "campaigns"
    monkeypatch.setattr(store_mod, "CAMPAIGNS_DIR", data_dir)
    monkeypatch.setattr(store_mod, "CAMPAIGNS_JSON", data_dir / "campaigns.json")
    monkeypatch.setattr(store_mod, "TRIALS_JSON", data_dir / "trials.json")
    monkeypatch.setattr(store_mod, "RECOMMENDATIONS_JSON", data_dir / "recommendations.json")
    monkeypatch.setattr(store_mod, "CHARACTERIZATIONS_JSON", data_dir / "characterizations.json")
    return store_mod.CampaignStore()


def test_campaign_store_initializes_files(tmp_path, monkeypatch):
    store = _patch_campaign_store(tmp_path, monkeypatch)

    assert store.list_campaigns() == []
    assert (tmp_path / "campaigns" / "campaigns.json").exists()
    assert (tmp_path / "campaigns" / "trials.json").exists()
    assert (tmp_path / "campaigns" / "recommendations.json").exists()
    assert (tmp_path / "campaigns" / "characterizations.json").exists()


def test_manual_planner_creates_recommendation_and_trials(tmp_path, monkeypatch):
    store = _patch_campaign_store(tmp_path, monkeypatch)
    campaign = store.create_campaign(
        name="CsPbBr3 PL optimization",
        material_system="CsPbBr3",
        objective_metric="pl_intensity",
        parameter_names=["temperature_c", "flow_a"],
    )

    from src.ml.planner import ManualPlanner

    result = ManualPlanner(store).recommend(
        campaign=campaign,
        history=[],
        batch_size=2,
        manual_parameters=[
            {"temperature_c": 120, "flow_a": 0.4},
            {"temperature_c": 140, "flow_a": 0.5},
        ],
    )

    recommendation = result["recommendation"]
    trials = result["trials"]
    assert recommendation["planner_name"] == "manual"
    assert len(recommendation["trial_ids"]) == 2
    assert len(trials) == 2
    assert trials[0]["status"] == "planned"
    assert trials[0]["parameters"]["temperature_c"] == 120
    assert store.list_trials(campaign["campaign_id"])[1]["parameters"]["flow_a"] == 0.5


def test_trial_status_validation(tmp_path, monkeypatch):
    store = _patch_campaign_store(tmp_path, monkeypatch)
    campaign = store.create_campaign(
        name="status test",
        material_system="Test",
        objective_metric="score",
        parameter_names=["x"],
    )
    result = store.create_recommendation(
        campaign_id=campaign["campaign_id"],
        planner_name="manual",
        parameters_batch=[{"x": 1}],
    )
    trial = result["trials"][0]

    updated = store.update_trial(
        campaign["campaign_id"],
        trial["trial_id"],
        {"status": "waiting_characterization", "sample_id": "S001"},
    )
    assert updated["status"] == "waiting_characterization"
    assert updated["sample_id"] == "S001"

    try:
        store.update_trial(campaign["campaign_id"], trial["trial_id"], {"status": "not_a_status"})
    except ValueError as e:
        assert "Invalid trial status" in str(e)
    else:
        raise AssertionError("Expected invalid status to raise ValueError")


def test_characterization_builds_planner_history(tmp_path, monkeypatch):
    store = _patch_campaign_store(tmp_path, monkeypatch)
    campaign = store.create_campaign(
        name="history test",
        material_system="CsPbBr3",
        objective_metric="pl_intensity",
        parameter_names=["temperature_c"],
    )
    trial = store.create_recommendation(
        campaign_id=campaign["campaign_id"],
        planner_name="manual",
        parameters_batch=[{"temperature_c": 130}],
    )["trials"][0]

    result = store.create_characterization(
        campaign_id=campaign["campaign_id"],
        trial_id=trial["trial_id"],
        characterization_type="PL",
        metrics={"pl_intensity": 8200, "peak_nm": 516.4},
        sample_id="CSPB_S001",
        raw_file_path="data/characterization/pl/CSPB_S001.csv",
    )
    history = store.build_history(campaign["campaign_id"])

    assert result["metrics"]["pl_intensity"] == 8200
    assert history[0]["parameters"]["temperature_c"] == 130
    assert history[0]["metrics"]["peak_nm"] == 516.4
    assert store.get_trial(campaign["campaign_id"], trial["trial_id"])["status"] == "characterized"


def test_campaign_api_flow(tmp_path, monkeypatch):
    store = _patch_campaign_store(tmp_path, monkeypatch)

    import src.web.api.campaigns as campaigns_api

    monkeypatch.setattr(campaigns_api, "store", store)

    app = FastAPI()
    app.include_router(campaigns_api.router)
    client = TestClient(app)

    campaign_resp = client.post(
        "/campaigns/",
        json={
            "name": "API campaign",
            "material_system": "CsPbBr3",
            "objective_metric": "pl_intensity",
            "parameter_names": ["temperature_c", "flow_a"],
        },
    )
    assert campaign_resp.status_code == 200
    campaign = campaign_resp.json()

    rec_resp = client.post(
        f"/campaigns/{campaign['campaign_id']}/recommendations/manual",
        json={"parameters_batch": [{"temperature_c": 120, "flow_a": 0.4}]},
    )
    assert rec_resp.status_code == 200
    trial = rec_resp.json()["trials"][0]

    patch_resp = client.patch(
        f"/campaigns/{campaign['campaign_id']}/trials/{trial['trial_id']}",
        json={"status": "waiting_characterization", "run_id": "run_001", "sample_id": "S001"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["run_id"] == "run_001"

    char_resp = client.post(
        f"/campaigns/{campaign['campaign_id']}/characterizations",
        json={
            "trial_id": trial["trial_id"],
            "sample_id": "S001",
            "characterization_type": "PL",
            "metrics": {"pl_intensity": 9000},
            "raw_file_path": "data/pl/S001.csv",
        },
    )
    assert char_resp.status_code == 200

    history_resp = client.get(f"/campaigns/{campaign['campaign_id']}/history")
    assert history_resp.status_code == 200
    assert history_resp.json()[0]["metrics"]["pl_intensity"] == 9000
