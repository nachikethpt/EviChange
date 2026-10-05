import json
import time

import pytest
from fastapi.testclient import TestClient

from agents import ee_engine, nodes, tools, webapp_bridge
from agents.graph import run_pipeline
from agents.schema import CHANGE_TYPES, T_IDX, validate_claim, validate_change_regions
from webapp.backend import data_store, main
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


def run_request(**overrides):
    return {"aoi": QN_AOI, "before_window": BEFORE, "after_window": AFTER, "condition": "gated", **overrides}


def test_run_rejects_point_aoi(client):
    resp = client.post("/api/runs", json=run_request(aoi={"type": "Point", "coordinates": [107.3, 21.04]}))
    assert resp.status_code == 400


def test_run_rejects_oversized_multipolygon(client):
    huge = {"type": "MultiPolygon", "coordinates": [[[[0, 0], [50, 0], [50, 50], [0, 50], [0, 0]]]]}
    assert client.post("/api/runs", json=run_request(aoi=huge)).status_code == 400


def test_run_rejects_invalid_condition(client):
    assert client.post("/api/runs", json=run_request(condition="xyz")).status_code == 400


@pytest.mark.parametrize("before, after", [
    (AFTER, BEFORE),                                    # before after after
    (["2018-11-01", "2020-03-31"], AFTER),              # window longer than 12 months
    (["2018-11-01", "2023-01-31"], AFTER),              # windows overlap
    (["2019-03-31", "2018-11-01"], AFTER),              # start after end
    (["2018-11-01"], AFTER),                            # not [start, end]
    (["Nov 2018", "Mar 2019"], AFTER),                  # not ISO dates
])
def test_run_rejects_bad_windows(client, before, after):
    assert client.post("/api/runs", json=run_request(before_window=before, after_window=after)).status_code == 400


def test_run_rejects_old_single_date_fields(client):
    old = {"aoi": QN_AOI, "date_before": "2018-01-01", "date_after": "2022-06-01", "condition": "gated"}
    assert client.post("/api/runs", json=old).status_code == 422


def test_unknown_run_id_rejected(client):
    """Well-formed (12-char hex) but nonexistent run id -> 404, not a silent demo-data fallback."""
    fake_but_valid_id = "0123456789ab"
    assert client.get(f"/api/runs/{fake_but_valid_id}").status_code == 404
    assert client.get(f"/api/data/change_regions?run_id={fake_but_valid_id}").status_code == 404


def test_malformed_run_id_rejected(client):
    assert client.get("/api/data/change_regions?run_id=../../etc").status_code == 400


def test_run_end_to_end_and_cache(client, monkeypatch):
    """A run must actually finish in the background worker and serve its own regions;
    the identical request afterwards is answered from the cache."""
    monkeypatch.setattr(tools, "run_preprocessing", lambda *a: (True, "ok"))   # no random too-cloudy retries
    with client:                                       # 'with' runs the app lifespan, i.e. starts the worker
        resp = client.post("/api/runs", json=run_request())
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]

        for _ in range(100):
            status = client.get(f"/api/runs/{run_id}").json()
            if status["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert status["status"] == "done", status
        assert status["before_window"] == BEFORE and status["after_window"] == AFTER

        regions = client.get(f"/api/data/change_regions?run_id={run_id}").json()
        assert regions["features"] and validate_change_regions(regions) == []

        again = client.post("/api/runs", json=run_request()).json()
        assert again == {"run_id": run_id, "status": "done", "cached": True}

# ---------- Phase 7b (D8): index rasters ----------

def test_index_layer_needs_an_analysis(client):
    """Demo data has no Earth Engine analysis behind it, so there is nothing to draw."""
    assert client.get("/api/index_layer", params={"index": "NDVI", "kind": "change"}).status_code == 404


def test_index_layer_rejects_unknown_index(client):
    assert client.get("/api/index_layer", params={"index": "EVI", "kind": "change"}).status_code == 400
    assert client.get("/api/index_layer", params={"index": "NDVI", "kind": "delta"}).status_code == 400


def test_index_layer_uses_the_regions_own_analysis(client, monkeypatch):
    """Tiles come from the AOI + windows + cloud limit in the live regions' metadata, and are cached."""
    (data_store.REGIONS_PATH).write_text(json.dumps({"type": "FeatureCollection", "features": [], "metadata": {
        "aoi": QN_AOI, "before_window": BEFORE, "after_window": AFTER, "thresholds": {"max_cloud_pct": 20}}}))
    calls = []

    def fake_layer(aoi, before, after, index, kind, max_cloud):
        calls.append((aoi, before, after, index, kind, max_cloud))
        return {"tiles": ["https://example/{z}/{x}/{y}"], "min": -0.4, "max": 0.4, "palette": ["#000", "#fff"]}

    monkeypatch.setattr(ee_engine, "index_tile_layer", fake_layer)
    main._index_tiles.clear()
    for _ in range(2):
        body = client.get("/api/index_layer", params={"index": "MNDWI", "kind": "after"}).json()
    assert body["tiles"] == ["https://example/{z}/{x}/{y}"] and body["after_window"] == AFTER
    assert calls == [(QN_AOI, BEFORE, AFTER, "MNDWI", "after", 20.0)]


def test_index_layer_reports_earth_engine_errors(client, monkeypatch):
    (data_store.REGIONS_PATH).write_text(json.dumps({"type": "FeatureCollection", "features": [], "metadata": {
        "aoi": QN_AOI, "before_window": BEFORE, "after_window": AFTER}}))

    def boom(*a):
        raise ValueError("No Sentinel-2 SR scenes found")

    monkeypatch.setattr(ee_engine, "index_tile_layer", boom)
    main._index_tiles.clear()
    resp = client.get("/api/index_layer", params={"index": "NDVI", "kind": "before"})
    assert resp.status_code == 502 and "No Sentinel-2" in resp.json()["detail"]
