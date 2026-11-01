import json

import pytest
from fastapi.testclient import TestClient

from agents import monthly, planet_shoreline as ps, shoreline
from webapp.backend import main

MONTHS = [m for m, *_ in monthly.month_windows("2024-10", "2026-09")]
RADAR = {"trend": "advancing", "tidal": False}


def test_clouds_never_create_or_bridge_a_planet_shoreline():
    offsets = shoreline.profile_offsets(step=3)
    values = [int(o >= 0) for o in offsets]
    assert ps.profile_position(values, offsets)["pos"] == -1.5
    cloudy = values.copy()
    cloudy[offsets.index(90)] = None
    assert ps.profile_position(cloudy, offsets)["status"] == "cloud_gap"
    assert ps.profile_position(cloudy, offsets)["pos"] is None
    cloudy[-1] = None
    assert ps.profile_position(cloudy, offsets)["pos"] is None
    assert ps.profile_position([None] * len(offsets), offsets)["status"] == "insufficient_clear"
    values[0] = None  # missing far inland, outside the position's landward check, is harmless
    assert ps.profile_position(values, offsets)["pos"] == -1.5


def test_2025_coverage_cannot_confirm_a_2026_trend():
    positions = [0.0] * 3 + [60.0] * 9 + [None] * 12
    result = ps.confirmation(MONTHS, positions, RADAR)
    assert result["status"] == "pending_coverage" and result["shift_m"] is None
    assert result["endpoint_months"] == [MONTHS[:3], MONTHS[-3:]]
    assert result["n"] == [3, 0]


@pytest.mark.parametrize("last,radar,status", [
    (40, RADAR, "confirmed"), (-40, RADAR, "not_confirmed"), (10, RADAR, "not_confirmed"),
    (40, {**RADAR, "tidal": True}, "tidal_uncertainty"),
    (40, {"trend": "stable"}, "no_significant_radar_trend"),
    (-40, {"trend": "retreating"}, "confirmed"),
])
def test_confirmation_uses_matched_quarters_and_keeps_tide_caveat(last, radar, status):
    positions = [0, 0, 150] + [None] * 18 + [last, last, None]
    result = ps.confirmation(MONTHS, positions, radar)
    assert result["status"] == status and result["n"] == [3, 2]
    assert result["positions_m"] == [0, last]  # medians resist an endpoint outlier
    assert "unknown tide" in result["tide_caveat"]
    positions[-2] = None
    expected = "no_significant_radar_trend" if radar["trend"] == "stable" else "pending_coverage"
    assert ps.confirmation(MONTHS, positions, radar)["status"] == expected


def transects():
    return {"type": "FeatureCollection", "features": [
        {"id": f"t{i}", "type": "Feature", "properties": {"id": f"t{i}", "line": 0, **RADAR},
         "geometry": {"type": "LineString", "coordinates": [[107.0, 21 + i * .001], [107.008, 21 + i * .001]]}}
        for i in range(4)]}


@pytest.fixture
def planet_data(tmp_path, monkeypatch):
    monkeypatch.setattr(shoreline, "SHORELINE_DIR", tmp_path)
    monkeypatch.setattr(shoreline, "hidden_transects", lambda *_: {"t1"})
    catalog = [{"month": MONTHS[0], "date": "2024-10-05", "clear_share": .9, "asset_id": "oct"}]
    data = {"months": MONTHS, "catalog": catalog, "method": ps.METHOD, "transects": {
        f"t{i}": {"positions": [999 if i == 1 else 0] + [None] * 23,
                  "quality": ["ok"] + ["missing_month"] * 23,
                  "confirmation": ps.confirmation(MONTHS, [0] + [None] * 23, RADAR)} for i in range(4)}}
    for name, value in [(ps.FILE, data), ("transects.geojson", transects()),
                        ("positions.json", {"months": MONTHS, "positions": {f"t{i}": [0] * 24 for i in range(4)}})]:
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    return data


def test_planet_api_reapplies_blind_lock_and_breaks_lines(planet_data):
    client = TestClient(main.app)
    summary = client.get("/api/shoreline/planet").json()
    assert summary["transects"] == 3 and summary["withheld_transects"] == 1
    assert summary["position_counts"]["2024-10"] == 3
    assert summary["confirmation_counts"] == {"pending_coverage": 3}
    body = client.get("/api/shoreline/planet/lines?month=2024-10").json()
    runs = body["features"][0]["geometry"]["coordinates"]
    assert len(runs) == 1 and len(runs[0]) == 2  # t0 cannot bridge the hidden t1 to t2
    assert body["features"][0]["properties"]["date"] == "2024-10-05"
    assert client.get("/api/shoreline/transects/t1").json()["planet"] is None
    detail = client.get("/api/shoreline/transects/t0").json()["planet"]
    assert detail["series"][0]["date"] == "2024-10-05" and detail["series"][1]["pos"] is None
    assert client.get("/api/shoreline/planet/lines?month=2025-02").status_code == 404
    assert client.get("/api/shoreline/planet/lines?month=2025-13").status_code == 400


def test_no_planet_run_is_an_explicit_404(tmp_path, monkeypatch):
    monkeypatch.setattr(shoreline, "SHORELINE_DIR", tmp_path)
    assert TestClient(main.app).get("/api/shoreline/planet").status_code == 404


def test_no_delivered_months_do_not_call_ee_or_manufacture_positions(tmp_path, monkeypatch):
    from agents import ee_engine
    monkeypatch.setattr(ee_engine, "_ee", lambda: pytest.fail("no EE request with an empty catalog"))
    monkeypatch.setattr(shoreline, "hidden_transects", lambda *_: {"t1"})
    result = ps.build(transects(), MONTHS, {"months": []}, cache_dir=tmp_path, log=lambda *_: None)
    assert "t1" not in result["transects"]
    assert result["transects"]["t0"]["positions"] == [None] * 24
    assert result["transects"]["t0"]["confirmation"]["status"] == "pending_coverage"


def test_build_resumes_cached_batches_and_invalidates_changed_acquisition(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents import ee_engine, planet
    image = SimpleNamespace(unmask=lambda *_: image, rename=lambda *_: image)
    ee = SimpleNamespace(data=SimpleNamespace(setDeadline=lambda *_: None),
                         Image=SimpleNamespace(cat=lambda *_: image))
    monkeypatch.setattr(ee_engine, "_ee", lambda: ee)
    monkeypatch.setattr(planet, "water_image", lambda *_: image)
    monkeypatch.setattr(shoreline, "hidden_transects", lambda *_: {"t1"})
    calls = []
    offsets = shoreline.profile_offsets(step=3)
    def sample(_ee, _stack, points, bands, log, scale):
        calls.append(points)
        assert scale == 3 and all(t != "t1" for t, *_ in points)
        return {tid: {b: {i: int(o >= 0) for i, o in enumerate(offsets)} for b in bands}
                for tid, *_ in points}
    monkeypatch.setattr(shoreline, "sample_profiles", sample)
    catalog = {"months": [{"month": "2024-10", "date": "2024-10-05", "asset_id": "oct"}]}
    first = ps.build(transects(), MONTHS, catalog, cache_dir=tmp_path, log=lambda *_: None)
    assert first["transects"]["t0"]["positions"][0] == -1.5
    assert len(calls) == 1
    second = ps.build(transects(), MONTHS, catalog, cache_dir=tmp_path, log=lambda *_: None)
    assert second == first and len(calls) == 1
    catalog["months"][0]["date"] = "2024-10-06"
    ps.build(transects(), MONTHS, catalog, cache_dir=tmp_path, log=lambda *_: None)
    assert len(calls) == 2
