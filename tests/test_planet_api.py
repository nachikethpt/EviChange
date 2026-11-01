"""Planet monthly map: availability comes from delivered assets, gaps stay gaps."""
import copy

import pytest
from fastapi.testclient import TestClient

from agents import planet
from webapp.backend import main


CATALOG = {"collection": "projects/test/assets/planet", "source": planet.SOURCE,
           "scale_m": 3, "attribution": planet.ATTRIBUTION, "months": [
               {"month": "2025-01", "date": "2025-01-16", "clear_share": 0.9, "asset_id": "jan"},
               {"month": "2025-03", "date": "2025-03-20", "clear_share": 0.6, "asset_id": "mar"},
           ]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_planet_catalog_cache", {})
    monkeypatch.setattr(main, "_planet_tiles", {})
    monkeypatch.setattr(main.ee_engine, "_ee", lambda: object())
    calls = {"catalog": 0, "tiles": []}

    def catalog(_ee):
        calls["catalog"] += 1
        return copy.deepcopy(CATALOG)

    def tiles(aoi, month, layer):
        calls["tiles"].append((aoi, month, layer))
        return {"tiles": ["https://example/{z}/{x}/{y}"], "source": planet.SOURCE,
                "scale_m": 3, "attribution": planet.ATTRIBUTION}

    monkeypatch.setattr(planet, "month_catalog", catalog)
    monkeypatch.setattr(planet, "tile_layer", tiles)
    c = TestClient(main.app)
    c.calls = calls
    return c


def test_metadata_and_tiles_cached(client):
    assert client.get("/api/planet/months").json() == CATALOG
    params = {"month": "2025-03", "layer": "rgb"}
    r = client.get("/api/planet/layer", params=params)
    assert r.status_code == 200
    out = r.json()
    assert (out["date"], out["clear_share"], out["scale_m"]) == ("2025-03-20", 0.6, 3)
    assert out["asset_id"] == "mar" and "Planet Labs" in out["attribution"]
    assert client.get("/api/planet/layer", params=params).json() == out
    assert client.calls["catalog"] == 1 and len(client.calls["tiles"]) == 1
    assert client.calls["tiles"][0][0] == main.load_study_config()["aoi"]
    client.get("/api/planet/layer", params={**params, "layer": "ndwi"})
    assert len(client.calls["tiles"]) == 2  # each visualisation needs its own tiles


def test_gap_never_falls_back_to_another_month(client):
    r = client.get("/api/planet/layer?month=2025-02&layer=rgb")
    assert r.status_code == 404 and "gap" in r.json()["detail"]
    assert client.calls["tiles"] == []


@pytest.mark.parametrize("query", ["month=2025-13&layer=rgb", "month=2025-01x&layer=rgb",
                                   "month=2025-01&layer=mndwi", "month=2025-01&layer=class"])
def test_invalid_requests_never_call_ee(client, query):
    assert client.get(f"/api/planet/layer?{query}").status_code == 400
    assert client.calls["catalog"] == 0 and client.calls["tiles"] == []


def test_unavailable_collection_is_an_error_not_an_empty_catalog(client, monkeypatch):
    def fail(_ee):
        raise ValueError("collection not shared")
    monkeypatch.setattr(planet, "month_catalog", fail)
    r = client.get("/api/planet/months")
    assert r.status_code == 502 and "collection not shared" in r.json()["detail"]
    assert main._planet_catalog_cache == {}


def test_missing_ee_dependency_and_expired_tile_errors(client, monkeypatch):
    def fail(*_):
        raise RuntimeError("earthengine-api is required")
    monkeypatch.setattr(main.ee_engine, "_ee", fail)
    assert client.get("/api/planet/months").status_code == 503
    monkeypatch.setattr(main.ee_engine, "_ee", lambda: object())
    monkeypatch.setattr(planet, "tile_layer", fail)
    assert client.get("/api/planet/layer?month=2025-01").status_code == 503
    assert main._planet_tiles == {}


def test_cache_expires(client, monkeypatch):
    monkeypatch.setattr(main.time, "time", lambda: 100)
    client.get("/api/planet/layer?month=2025-01")
    monkeypatch.setattr(main.time, "time", lambda: 100 + main.INDEX_TILE_TTL_S + 1)
    client.get("/api/planet/layer?month=2025-01")
    assert client.calls["catalog"] == 2 and len(client.calls["tiles"]) == 2
