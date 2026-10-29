import json
import math

import pytest
from fastapi.testclient import TestClient

from agents import labels14 as l14
from agents import shoreline as s
from webapp.backend import main


def _transects(n_lines=2, per_line=40):
    """Straight east-west baselines with transects pointing south (land north, sea south)."""
    frame = s.LocalFrame(107.3, 21.0)
    feats = []
    for line in range(n_lines):
        for k in range(per_line):
            x, y = k * 100.0, line * 5000.0
            a, b = frame.to_lonlat(x, y + s.LAND_M), frame.to_lonlat(x, y - s.SEA_M)
            tid = f"t{line * per_line + k + 1:04d}"
            feats.append({"type": "Feature", "id": tid,
                          "geometry": {"type": "LineString", "coordinates": [list(a), list(b)]},
                          "properties": {"id": tid, "line": line, "chainage_m": k * 100.0, "lrr": 1.0, "nsm": 2.0,
                                         "trend": "too_few" if k % 7 == 0 else "stable", "change": "stable"}})
    return {"type": "FeatureCollection", "features": feats}


# ---------- (b) reference transects ----------
def test_sample_transects_is_spread_seeded_and_carries_no_statistics():
    fc = _transects()
    refs = l14.sample_transects(fc, n=10)
    assert len(refs) == 10 and refs == l14.sample_transects(fc, n=10)
    assert len({r["transect_id"] for r in refs}) == 10
    by_id = {f["id"]: f for f in fc["features"]}
    assert all(by_id[r["transect_id"]]["properties"]["trend"] != "too_few" for r in refs)
    assert all(set(r) == {"transect_id", "line", "chainage_m", "geometry", "extend_land_m", "extend_sea_m"} for r in refs)
    assert {r["line"] for r in refs} == {0, 1}                      # both lines get references
    assert all(0 <= r["extend_land_m"] <= l14.EXTEND_MAX_M for r in refs)


def test_sample_transects_needs_enough_usable():
    with pytest.raises(ValueError):
        l14.sample_transects(_transects(1, 5), n=10)


def test_drawn_segment_extends_and_converts_back_to_the_baseline_frame():
    ref = l14.sample_transects(_transects(), n=5)[0]
    start, end, length = l14.drawn_segment(ref)
    assert length == pytest.approx(s.LAND_M + s.SEA_M + ref["extend_land_m"] + ref["extend_sea_m"], abs=0.5)
    (lon_a, lat_a), _ = ref["geometry"]["coordinates"]
    x, y = s.LocalFrame(lon_a, lat_a).to_m(*start)
    assert math.hypot(x, y) == pytest.approx(ref["extend_land_m"], abs=0.5)
    # the baseline sits LAND_M past the real landward end
    assert l14.drawn_to_baseline(ref, ref["extend_land_m"] + s.LAND_M) == 0
    assert l14.drawn_to_baseline(ref, ref["extend_land_m"] + s.LAND_M + 40) == 40


def test_hidden_transect_ids_are_references_and_same_line_neighbours():
    fc = _transects()
    refs = [{"line": 0, "chainage_m": 500.0}, {"line": 1, "chainage_m": 0.0}]
    hidden = l14.hidden_transect_ids(fc, refs)
    assert hidden == {"t0005", "t0006", "t0007", "t0041", "t0042"}


# ---------- (c) coastal cells ----------
def test_sample_cells_fill_both_strips_landward_and_apart():
    fc = _transects()
    cells = l14.sample_cells(fc, n=10)
    assert cells == l14.sample_cells(fc, n=10)
    assert [c["cell_id"] for c in cells] == [f"c{i:02d}" for i in range(1, 11)]
    assert sum(c["strip"] == "0-200" for c in cells) == 5
    frame = s.LocalFrame(107.3, 21.0)
    for c in cells:
        lo, hi = map(int, c["strip"].split("-"))
        assert lo <= c["landward_m"] <= hi
        _, y = frame.to_m(c["lon"], c["lat"])
        line = round(y / 5000)
        assert y - line * 5000 == pytest.approx(c["landward_m"], abs=0.5)      # land is north of the baseline
        ring = c["outline"]["coordinates"][0]
        w, e = min(p[0] for p in ring), max(p[0] for p in ring)
        assert (e - w) * frame.kx == pytest.approx(l14.CELL_M, abs=0.1)
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            assert l14._dist_m(a["lon"], a["lat"], b["lon"], b["lat"]) >= l14.CELL_MIN_GAP_M


# ---------- records ----------
BASE = {"protocol": l14.PROTOCOL, "labeler": "labeler1", "confidence": "high"}


def test_validate_records():
    ok = {
        "classes": {**BASE, "site_id": "s01", "class_before": "trees", "class_after": "bare"},
        "shoreline": {**BASE, "transect_id": "t0016", "month": "2024-10", "status": "edge", "drawn_m": 410, "pos_m": -10},
        "cells": {**BASE, "cell_id": "c01", "dates": ["2024-10", "2025-09"], "months": {"2024-10": "not_built", "2025-09": "built"}},
        "change_month": {**BASE, "site_id": "s01", "lasting_change": "yes", "change_window": ["2025-01", "2025-03"]},
    }
    for kind, rec in ok.items():
        assert l14.validate_record(kind, rec) == [], kind
    assert l14.validate_record("classes", {**ok["classes"], "class_after": "forest"})
    assert l14.validate_record("shoreline", {**ok["shoreline"], "status": "not_visible"})       # pos_m left set
    assert l14.validate_record("shoreline", {**ok["shoreline"], "status": "not_visible", "pos_m": None, "drawn_m": None}) == []
    assert l14.validate_record("shoreline", {**ok["shoreline"], "month": "2024-13"})
    assert l14.validate_record("cells", {**ok["cells"], "months": {"2024-10": "built"}})
    assert l14.validate_record("change_month", {**ok["change_month"], "change_window": ["2025-03", "2025-01"]})
    assert l14.validate_record("change_month", {**ok["change_month"], "lasting_change": "no"})   # window must be null
    assert l14.validate_record("change_month", {**BASE, "site_id": "s02", "lasting_change": "no", "change_window": None}) == []
    assert l14.validate_record("classes", {**ok["classes"], "protocol": "labels_v1"})
    assert l14.validate_record("nope", {}) == ["unknown kind 'nope'"]


def test_load_labels_raises_on_a_bad_line(tmp_path):
    p = tmp_path / "x.jsonl"
    good = {**BASE, "site_id": "s01", "class_before": "trees", "class_after": "unsure"}
    p.write_text(json.dumps(good) + "\n\n" + json.dumps({**good, "confidence": "very"}) + "\n")
    with pytest.raises(ValueError, match=":3:"):
        l14.load_labels(p, "classes")
    p.write_text(json.dumps(good) + "\n")
    assert l14.load_labels(p, "classes") == [good]


# ---------- the app lock ----------
def test_hide_transects_and_lines():
    fc = _transects(1, 10)
    hidden = {"t0004", "t0005", "t0006"}
    out = s.hide_transects(fc, hidden)
    props = {f["id"]: f["properties"] for f in out["features"]}
    assert props["t0005"]["hidden"] and "lrr" not in props["t0005"] and "change" not in props["t0005"]
    assert props["t0003"]["lrr"] == 1.0 and "hidden" not in props["t0003"]
    assert fc["features"][4]["properties"]["lrr"] == 1.0                  # input untouched
    frame = s.LocalFrame(107.3, 21.0)
    line = [list(frame.to_lonlat(k * 100.0, 20.0)) for k in range(10)]   # 20 m seaward of the baseline
    lines = s.hide_lines({"features": [{"type": "Feature", "properties": {"month": "2024-10"},
                                        "geometry": {"type": "MultiLineString", "coordinates": [line]}}]}, fc, hidden)
    parts = lines["features"][0]["geometry"]["coordinates"]
    assert parts == [line[:3], line[6:]]
    assert s.hide_lines({"features": []}, fc, set()) == {"features": []}


def test_api_hides_reference_transects():
    if s.load("transects.geojson") is None or l14.load_samples(l14.TRANSECTS_FILE) is None:
        pytest.skip("no shoreline outputs or Phase 14 samples")
    client = TestClient(main.app)
    refs = l14.load_samples(l14.TRANSECTS_FILE)
    tid = refs[0]["transect_id"]
    feats = {f["id"]: f for f in client.get("/api/shoreline/transects").json()["features"]}
    assert feats[tid]["properties"].get("hidden") and "lrr" not in feats[tid]["properties"]
    detail = client.get(f"/api/shoreline/transects/{tid}").json()
    assert detail["series"] is None and detail["hidden"]
    assert sum(f["properties"].get("hidden", False) for f in feats.values()) == len(s.hidden_transects())


# ---------- (b) on Google Earth ----------
def _ge():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("ge", pathlib.Path(__file__).parent.parent / "scripts" / "shoreline_reference_ge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ge_kml_is_blind_and_ticked():
    refs = l14.sample_transects(_transects(), n=3)
    kml = l14.ge_kml(refs, "t")
    assert all(r["transect_id"] not in kml for r in refs) and "<name>1</name>" in kml and "<name>50</name>" in kml
    t = l14.ticks(refs[0])
    assert t[0][0] == 0 and t[1][0] == l14.TICK_M
    assert t[-1][0] <= l14.drawn_segment(refs[0])[2] < t[-1][0] + l14.TICK_M


def test_ge_records_validate_and_score():
    ge = _ge()
    refs = l14.sample_transects(_transects(), n=2)
    s_m = refs[0]["extend_land_m"] + s.LAND_M + 10            # 10 m seaward of the baseline
    saved = {"answers": [
        {"n": 1, "season": "2016-17", "status": "edge", "drawn_m": s_m, "month": "2017-01", "confidence": "high", "notes": None},
        {"n": 2, "season": "2016-17", "status": "not_visible", "drawn_m": None, "month": None, "confidence": "low", "notes": "cloud"}]}
    recs = ge.to_records(saved, refs, "P2")
    assert recs[0]["pos_m"] == 10 and recs[0]["source"] == "google_earth" and recs[1]["month"] == "2016-10"
    assert all(l14.validate_record("shoreline", r) == [] for r in recs)
    assert l14.validate_record("shoreline", {**recs[0], "source": "bing"}) and l14.validate_record("shoreline", {**recs[0], "season": "2016"})
    years = {"seasons": [["2016-17", "2016-10-01", "2017-04-01"]], "positions": {refs[0]["transect_id"]: [25.0]}}
    sc = ge.score(recs, years)
    assert sc["all"] == {"n": 1, "bias_m": 15.0, "rmse_m": 15.0, "mae_m": 15.0, "within_20m": 1.0, "within_30m": 1.0}
