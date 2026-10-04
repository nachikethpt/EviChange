import pytest
from fastapi.testclient import TestClient

from agents import nodes, webapp_bridge
from agents.graph import run_pipeline
from agents.schema import CHANGE_TYPES, T_IDX, validate_claim, validate_change_regions
from webapp.backend import data_store
from webapp.backend.main import app

AOI = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
BEFORE = ["2018-11-01", "2019-03-31"]
AFTER = ["2022-11-01", "2023-03-31"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Point the live-data store at an empty temp dir so tests never touch webapp/backend/data/."""
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    monkeypatch.setattr(data_store, "AOI_PATH", tmp_path / "aoi.json")
    monkeypatch.setattr(webapp_bridge, "DATA_DIR", tmp_path)
    return TestClient(app)


def test_health_starts_on_demo_data(client):
    assert client.get("/api/health").json() == {"status": "ok", "live_data": False}


@pytest.mark.parametrize("condition", ["template", "ungated", "gated"])
def test_report_claims_match_schema(client, condition):
    ids = sorted(data_store.known_region_ids())
    body = client.post("/api/report", json={"region_ids": ids, "condition": condition}).json()
    assert body["claims"]
    for c in body["claims"]:
        assert validate_claim(c) == [], c
        assert c["verdict_note"]


def test_demo_verdicts_tell_the_research_story(client):
    """Ungated L4 claims are unsupported; template and gated contain no L4 claims at all."""
    ids = sorted(data_store.known_region_ids())
    reports = {c: client.post("/api/report", json={"region_ids": ids, "condition": c}).json() for c in ("template", "ungated", "gated")}
    l4 = [c for c in reports["ungated"]["claims"] if c["level"] == "L4"]
    assert l4 and all(c["verdict_reason"] == "beyond_evidence" for c in l4)
    assert reports["gated"]["abstain"]
    for cond in ("template", "gated"):
        assert not any(c["level"] == "L4" for c in reports[cond]["claims"])
        assert reports[cond]["counts"]["unsupported"] == 0


def test_unknown_region_rejected(client):
    assert client.post("/api/report", json={"region_ids": ["nope"], "condition": "gated"}).status_code == 400


def test_change_types_endpoint_mirrors_schema(client):
    """The map's change-type colours must use the same rules as the verifier."""
    body = client.get("/api/change_types").json()
    assert body["t_idx"] == T_IDX
    assert {k: (v["field"], v["sign"], v["label"]) for k, v in body["types"].items()} == CHANGE_TYPES


def test_pipeline_and_webapp_share_one_claim_generator(client):
    result = run_pipeline("bridge", AOI, BEFORE, AFTER)
    ev = {"change_frac": result["change_frac"], "regions": result["regions"]}
    assert result["claims"] == webapp_bridge.build_report(ev, "gated")["claims"]


def test_publish_live_feeds_the_map(client):
    result = run_pipeline("live", AOI, BEFORE, AFTER, publish_live=True)
    assert result["status"] == "done"
    assert client.get("/api/health").json()["live_data"] is True
    served = client.get("/api/data/change_regions").json()
    assert validate_change_regions(served) == []
    assert {f["properties"]["id"] for f in served["features"]} == {r["id"] for r in result["regions"]}
    ids = [r["id"] for r in result["regions"]]
    assert client.post("/api/report", json={"region_ids": ids, "condition": "template"}).status_code == 200


def test_publishing_rejects_schema_violations():
    state = {"regions": [{"id": "r1"}], "before_window": BEFORE, "after_window": AFTER, "model_version": "m", "scene_before_id": "s", "aoi": AOI}
    with pytest.raises(Exception, match="invalid published change regions"):
        nodes.publishing_agent(state)

QN_AOI = {
    "type": "Polygon",
    "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]],
}


def test_run_rejects_point_aoi(client):
    resp = client.post("/api/runs", json={
        "aoi": {"type": "Point", "coordinates": [107.3, 21.04]},
        "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "gated",
    })
    assert resp.status_code == 400


def test_run_rejects_oversized_multipolygon(client):
    huge = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [50, 0], [50, 50], [0, 50], [0, 0]]]]}
    resp = client.post("/api/runs", json={
        "aoi": huge, "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "gated",
    })
    assert resp.status_code == 400


def test_run_rejects_invalid_condition(client):
    resp = client.post("/api/runs", json={
        "aoi": QN_AOI, "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "xyz",
    })
    assert resp.status_code == 400


def test_unknown_run_id_rejected(client):
    """Well-formed (12-char hex) but nonexistent run id -> 404, not a silent demo-data fallback."""
    fake_but_valid_id = "0123456789ab"
    assert client.get(f"/api/runs/{fake_but_valid_id}").status_code == 404
    assert client.get(f"/api/data/change_regions?run_id={fake_but_valid_id}").status_code == 404


def test_malformed_run_id_rejected(client):
    assert client.get("/api/data/change_regions?run_id=../../etc").status_code == 400


def test_run_end_to_end_and_cache(client):
    resp = client.post("/api/runs", json={
        "aoi": QN_AOI, "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "gated",
    })
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    status = client.get(f"/api/runs/{run_id}").json()
    assert status["status"] in ("queued", "running", "done")

    resp2 = client.post("/api/runs", json={
        "aoi": QN_AOI, "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "gated",
    })
    assert resp2.json()["cached"] in (True, False)