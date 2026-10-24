"""Monthly time series (D11, Phase 10): months, Otsu, result reading and the API.
Earth Engine itself is not called here."""
import json

import pytest
from fastapi.testclient import TestClient

from agents import monthly
from agents.schema import LANDCOVER_CLASSES
from webapp.backend import main


def test_month_windows_cross_year():
    w = monthly.month_windows("2024-11", "2025-02")
    assert w == [("2024-11", "2024-11-01", "2024-12-01"), ("2024-12", "2024-12-01", "2025-01-01"),
                 ("2025-01", "2025-01-01", "2025-02-01"), ("2025-02", "2025-02-01", "2025-03-01")]
    assert len(monthly.month_windows("2024-10", "2026-09")) == 24
    with pytest.raises(ValueError):
        monthly.month_windows("2025-03", "2025-01")


def test_previous_month():
    assert monthly.previous_month("2025-01") == "2024-12"
    assert monthly.previous_month("2025-10") == "2025-09"


def test_otsu_splits_two_modes():
    centers = [float(x) for x in range(-30, 1)]
    counts = [0.0] * len(centers)
    for x, n in ((-24, 50), (-23, 80), (-22, 50), (-8, 60), (-7, 90), (-6, 60)):   # water ~ -23 dB, land ~ -7 dB
        counts[centers.index(x)] = n
    t = monthly.otsu(counts, centers)
    assert -22 < t < -8
    assert monthly.otsu([0, 0, 0], [1, 2, 3]) is None


def test_scene_threshold_falls_back_outside_range():
    def hist(lo_mode, hi_mode):
        rows = [[x / 4, 0.0] for x in range(-140, 20)]                 # fixedHistogram-shaped, 0.25 dB buckets
        for row in rows:
            if abs(row[0] - lo_mode) < 1 or abs(row[0] - hi_mode) < 1:
                row[1] = 100.0
        return rows
    ok = monthly.scene_threshold(hist(-22, -8))
    assert ok["fallback"] is False and monthly.OTSU_RANGE_DB[0] <= ok["db"] <= monthly.OTSU_RANGE_DB[1]
    assert monthly.scene_threshold(hist(-34, -30)) == {"db": monthly.FALLBACK_DB, "fallback": True}   # no land / water split
    assert monthly.scene_threshold(None) == {"db": monthly.FALLBACK_DB, "fallback": True}


def test_class_status():
    assert monthly.class_status(0.0) == "none"
    assert monthly.class_status(None) == "none"
    assert monthly.class_status(0.3) == "patchy"
    assert monthly.class_status(0.9) == "clear"


def test_class_areas_and_transitions():
    trees, bare, water = (LANDCOVER_CLASSES.index(c) for c in ("trees", "bare", "water"))
    assert monthly.class_areas([{"group": trees, "sum": 25_000}, {"group": water, "sum": 10_000}]) == {"water": 1.0, "trees": 2.5}
    groups = [{"group": trees * 10 + trees, "sum": 80_000}, {"group": trees * 10 + bare, "sum": 30_000},
              {"group": water * 10 + bare, "sum": 10_000}]
    t = monthly.transitions(groups)
    assert t["compared_ha"] == 12.0 and t["changed_ha"] == 4.0
    assert t["top"][0] == {"from": "trees", "to": "bare", "ha": 3.0}
    assert monthly.transitions([]) == {"compared_ha": 0, "changed_ha": 0, "top": []}


def test_region_class_needs_cover():
    assert monthly.region_class(1.0, 0.8) == "trees"
    assert monthly.region_class(1.0, 0.2) is None          # Dynamic World saw too little of the region
    assert monthly.region_class(None, None) is None


def test_hide_classes():
    series = {"months": ["2025-01"], "regions": {"r1": {"class": ["trees"], "water": [0.1], "clear": [1.0]},
                                                 "r2": {"class": ["bare"], "water": [0.0], "clear": [1.0]}}}
    out = monthly.hide_classes(series, {"r1"})
    assert out["regions"]["r1"] == {"class": None, "water": [0.1], "clear": [1.0], "class_hidden": True}
    assert out["regions"]["r2"] == series["regions"]["r2"]


# ---------- API ----------
SUMMARY = {"period": ["2025-01", "2025-03"], "baseline": "2025-01", "method": {}, "months": [
    {"month": "2025-01", "dw_images": 3, "s1_thresholds_db": {"S1A_x": {"db": -18.0, "fallback": False}}},
    {"month": "2025-02", "dw_images": 0, "s1_thresholds_db": {"S1A_y": {"db": -17.0, "fallback": False}}},
    {"month": "2025-03", "dw_images": 2, "s1_thresholds_db": {}},
]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(monthly, "SUMMARY_FILE", tmp_path / "summary.json")
    monkeypatch.setattr(monthly, "REGIONS_FILE", tmp_path / "regions_monthly.json")
    monkeypatch.setattr(main, "_monthly_tiles", {})
    calls = []

    def fake_tiles(aoi, month, layer, ref=None, thresholds=None, ref_thresholds=None):
        calls.append((month[0], layer, ref and ref[0], thresholds, ref_thresholds))
        return {"tiles": ["https://example/{z}/{x}/{y}"], **monthly.LAYER_VIS[layer]}

    monkeypatch.setattr(monthly, "tile_layer", fake_tiles)
    c = TestClient(main.app)
    c.calls = calls
    return c


def test_monthly_404_before_the_script_ran(client):
    assert client.get("/api/monthly").status_code == 404
    assert client.get("/api/monthly/regions/r1").status_code == 404


def test_monthly_layer(client):
    monthly.SUMMARY_FILE.write_text(json.dumps(SUMMARY), encoding="utf-8")
    assert client.get("/api/monthly").json()["baseline"] == "2025-01"

    r = client.get("/api/monthly/layer", params={"month": "2025-03", "layer": "class_change"})
    assert r.status_code == 200 and r.json()["ref"] == "2025-01"
    assert client.calls[-1][:3] == ("2025-03", "class_change", "2025-01")

    r = client.get("/api/monthly/layer", params={"month": "2025-02", "layer": "water_change", "vs": "prev"})
    assert r.status_code == 200 and r.json()["ref"] == "2025-01"
    assert client.calls[-1][3:] == ({"S1A_y": {"db": -17.0, "fallback": False}}, {"S1A_x": {"db": -18.0, "fallback": False}})

    n = len(client.calls)
    client.get("/api/monthly/layer", params={"month": "2025-02", "layer": "water_change", "vs": "prev"})
    assert len(client.calls) == n                                   # cached

    gaps = [("2025-02", "class"), ("2025-03", "water")]             # no Dynamic World / no radar that month
    for month, layer in gaps:
        assert client.get("/api/monthly/layer", params={"month": month, "layer": layer}).status_code == 404
    assert client.get("/api/monthly/layer", params={"month": "2025-01", "layer": "water_change"}).status_code == 404  # base vs itself
    assert client.get("/api/monthly/layer", params={"month": "2024-12", "layer": "water"}).status_code == 404
    assert client.get("/api/monthly/layer", params={"month": "2025-13", "layer": "water"}).status_code == 400
    assert client.get("/api/monthly/layer", params={"month": "2025-01", "layer": "ndvi"}).status_code == 400


def test_monthly_region_hides_locked_classes(client, monkeypatch):
    series = {"months": ["2025-01"], "regions_file": "x.json",
              "regions": {"r1": {"class": ["trees"], "water": [0.0], "clear": [1.0]},
                          "r2": {"class": ["bare"], "water": [0.2], "clear": [0.5]}}}
    monthly.REGIONS_FILE.write_text(json.dumps(series), encoding="utf-8")
    monkeypatch.setattr(main, "_class_locked_ids", lambda regions_file: {"r1"})
    assert client.get("/api/monthly/regions/r1").json() == {"id": "r1", "months": ["2025-01"], "class": None,
                                                            "water": [0.0], "clear": [1.0], "class_hidden": True}
    assert client.get("/api/monthly/regions/r2").json()["class"] == ["bare"]
    assert client.get("/api/monthly/regions/r9").status_code == 404


def test_dry_seasons_inside_the_period():
    assert monthly.dry_seasons("2024-10", "2026-09") == [("2024-25", "2024-10-01", "2025-04-01"),
                                                         ("2025-26", "2025-10-01", "2026-04-01")]
    assert monthly.dry_seasons("2024-11", "2025-09") == []          # Oct 2024 missing: no full season


def _region(rid, ha, n_points=5):
    ring = [[107.3 + i * 1e-4, 21.0] for i in range(n_points)] + [[107.3, 21.0]]
    return {"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"id": rid, "area_ha": ha}}


def test_region_batches_cap_area_and_bytes():
    feats = [_region("a", 400), _region("b", 400), _region("big", 3_275), _region("c", 300)]
    assert [[f["properties"]["id"] for f in b] for b in monthly.region_batches(feats, max_ha=1_000)] == [["a", "b"], ["big"], ["c"]]
    small = monthly.region_batches(feats, max_bytes=len(json.dumps(feats[0]["geometry"])) + 1, max_ha=1e9)
    assert [len(b) for b in small] == [1, 1, 1, 1]


def test_get_info_retries_then_raises():
    class Flaky:
        def __init__(self, fails):
            self.fails, self.calls = fails, 0

        def getInfo(self):
            self.calls += 1
            if self.calls <= self.fails:
                raise TimeoutError("deadline exceeded")
            return {"ok": True}

    quiet = dict(log=lambda *_: None, sleep=lambda *_: None)
    obj = Flaky(fails=2)
    assert monthly.get_info(obj, "x", tries=3, **quiet) == {"ok": True} and obj.calls == 3
    with pytest.raises(TimeoutError):
        monthly.get_info(Flaky(fails=5), "x", tries=3, **quiet)


def test_series_from_saved_months():
    fc = {"features": [_region("r1", 1), _region("r2", 1)]}
    done = {"2025-01": {"r1": ["trees", 0.1, 1.0], "r2": [None, 0.0, 0.5]},
            "2025-02": {"r1": [None, 0.2, 0.0]}}                      # r2 missing that month
    out = monthly.series_from_months(fc, ["2025-01", "2025-02"], done)
    assert out["regions"]["r1"] == {"class": ["trees", None], "water": [0.1, 0.2], "clear": [1.0, 0.0]}
    assert out["regions"]["r2"] == {"class": [None, None], "water": [0.0, None], "clear": [0.5, None]}


def test_region_series_skips_months_already_done(monkeypatch):
    monkeypatch.setattr(monthly, "_ee", lambda: pytest.fail("no Earth Engine call when every month is done"))
    fc = {"features": [_region("r1", 1)]}
    done = {"2025-01": {"r1": ["water", 1.0, 1.0]}}
    out = monthly.region_series(fc, {}, "2025-01", "2025-01", done=done)
    assert out == {"months": ["2025-01"], "regions": {"r1": {"class": ["water"], "water": [1.0], "clear": [1.0]}}}
