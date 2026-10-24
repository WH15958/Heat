"""Fail closed on corrupt scientific records; reject nonfinite input before writes."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.campaigns import store as storage
from src.web.api import campaigns as api


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    directory = tmp_path / "中文 科学记录"
    monkeypatch.setattr(storage, "CAMPAIGNS_DIR", directory)
    for name in ("CAMPAIGNS_JSON", "TRIALS_JSON", "RECOMMENDATIONS_JSON", "CHARACTERIZATIONS_JSON"):
        monkeypatch.setattr(storage, name, directory / getattr(storage, name).name)
    store = storage.CampaignStore()
    item = store.create_campaign(name="test", material_system="", objective_metric="score", parameter_names=["x"])
    trial = store.create_recommendation(campaign_id=item["campaign_id"], planner_name="manual",
                                        parameters_batch=[{"x": 1}])["trials"][0]
    monkeypatch.setattr(api, "store", store)
    app = FastAPI()
    app.include_router(api.router)
    return store, item["campaign_id"], trial["trial_id"], TestClient(app)


def snapshot():
    return {p.name: p.read_bytes() for p in storage.CAMPAIGNS_DIR.iterdir() if p.is_file()}


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e309", "-1e309"])
@pytest.mark.parametrize("kind", ["characterization", "recommendation"])
def test_http_rejects_nonfinite_nested_values_without_mutation(campaign, number, kind):
    _, cid, tid, client = campaign
    before = snapshot()
    if kind == "characterization":
        path = f"/campaigns/{cid}/characterizations"
        body = ('{"trial_id":' + json.dumps(tid) + ',"characterization_type":"PL",'
                '"metrics":{"score":1,"nested":[{"value":' + number + '}]}}')
    else:
        path = f"/campaigns/{cid}/recommendations/manual"
        body = '{"parameters_batch":[{"x":{"nested":[' + number + ']}}]}'
    response = client.post(path, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400, response.text
    assert "有限" in response.json()["detail"]
    assert snapshot() == before
    assert client.get(f"/campaigns/{cid}/history").status_code == 200


@pytest.mark.parametrize("method", ["create_characterization", "create_recommendation", "create_trials"])
def test_direct_store_call_rejects_nonfinite_values(campaign, method):
    store, cid, tid, _ = campaign
    before = snapshot()
    kwargs = {"campaign_id": cid}
    if method == "create_characterization":
        kwargs.update(trial_id=tid, characterization_type="PL", metrics={"score": [float("nan")]})
    else:
        kwargs.update(parameters_batch=[{"x": float("inf")}])
        kwargs["planner_name" if method == "create_recommendation" else "recommendation_id"] = "manual"
    with pytest.raises(ValueError, match="有限"):
        getattr(store, method)(**kwargs)
    assert snapshot() == before


@pytest.mark.parametrize("text", ['{"campaigns":[]}', "null", '"old"', "", "[null]", "[7]", '[{"x":1e309}]', "{bad", b"\xff\xfe\x01"])
def test_corrupt_root_is_preserved_and_api_reports_unavailable(campaign, text):
    store, _, _, client = campaign
    storage.CAMPAIGNS_JSON.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    before = snapshot()
    with pytest.raises(storage.CampaignStorageError):
        store.list_campaigns()
    with pytest.raises(storage.CampaignStorageError):
        store.create_campaign(name="new", material_system="", objective_metric="score", parameter_names=[])
    assert client.get("/campaigns/").status_code == 503
    response = client.post("/campaigns/", json={"name": "new", "objective_metric": "score"})
    assert response.status_code == 503
    assert "原文件已保留" in response.json()["detail"]
    assert snapshot() == before


@pytest.mark.parametrize("kind,other", [("recommendation", "recommendations"), ("characterization", "characterizations")])
@pytest.mark.parametrize("bad", [None, [4], [{"x": float("nan")}], [{"x": float("inf")}]])
def test_corrupt_recovery_journal_never_partially_rolls_back(campaign, kind, other, bad):
    store, _, _, client = campaign
    journal = storage.CAMPAIGNS_DIR / f"{kind}.pending.json"
    journal.write_text(json.dumps({"trials": [], other: bad}), encoding="utf-8")
    before = snapshot()
    with pytest.raises(storage.CampaignStorageError):
        store.list_campaigns()
    assert client.get("/campaigns/").status_code == 503
    assert snapshot() == before


def test_finite_nested_json_and_empty_list_remain_supported(campaign):
    store, cid, tid, client = campaign
    metrics = {"score": 1.2e100, "nested": [True, None, "未检出", {"value": -3.5}]}
    response = client.post(f"/campaigns/{cid}/characterizations", json={
        "trial_id": tid, "characterization_type": "PL", "metrics": metrics})
    assert response.status_code == 200
    assert store.build_history(cid)[0]["metrics"] == metrics
    storage.CAMPAIGNS_JSON.write_text("[]\n", encoding="utf-8")
    assert store.list_campaigns() == []


def test_writer_rejects_nonfinite_without_replacing_original(campaign):
    before = snapshot()
    with pytest.raises(ValueError):
        storage._write_json(storage.CAMPAIGNS_JSON, [{"x": float("nan")}])
    assert snapshot() == before
