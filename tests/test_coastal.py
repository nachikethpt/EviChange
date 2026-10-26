"""Phase 12 (D11): buildings near the shoreline. Pure helpers, outputs, API and the box evidence on small
fixtures; no Earth Engine calls."""
import json

import pytest
from fastapi.testclient import TestClient

from agents import coastal as c
from agents import shoreline
from agents.schema import COASTAL_STRIPS, validate_evidence, validate_strip
from agents.study import load_study_config
from agents.verifier import verify
from webapp.backend import main

M = 10_000   # m² per ha


def groups(**by_code):
    """An Earth Engine grouped-sum list from {code: ha}."""
    return [{"group": int(k.lstrip("g")), "sum": ha * M} for k, ha in by_code.items()]


# ---------- strip rule + constants ----------
def test_built_is_dynamic_worlds_class_6():
    assert c.BUILT == 6


@pytest.mark.parametrize("d, strip", [(0, "0-200"), (150, "0-200"), (200, "0-200"), (200.1, "200-500"), (500, "200-500"),
                                      (500.1, None), (-1, None), (None, None)])
def test_strip_for_distance(d, strip):
    assert c.strip_for_distance(d) == strip


def test_strip_names_match_the_schema():
    assert tuple(c.STRIP_CODES) == COASTAL_STRIPS and c.PATCH_MIN_PIXELS == 50


# ---------- reading results: gaps are gaps ----------
def test_strip_areas_ignores_unknown_codes():
    assert c.strip_areas(groups(g1=12.5, g2=30.0, g9=7.0)) == {"0-200": 12.5, "200-500": 30.0}
    assert c.strip_areas(None) == {}


def test_strip_row_clear_patchy_and_none():
    clear = c.strip_row(100.0, 95.0, 20.0)
    assert clear["status"] == "clear" and clear["built_ha"] == 20.0 and clear["cover"] == 0.95
    assert clear["built_share"] == pytest.approx(20 / 95, abs=1e-4)
    patchy = c.strip_row(100.0, 30.0, 8.0)                       # under half seen: a gap, not 8 ha
    assert patchy["status"] == "patchy" and patchy["built_ha"] is None and patchy["built_share"] is None and patchy["observed_ha"] == 30.0
    none = c.strip_row(100.0, 0.0, 0.0)                         # monsoon month with no Dynamic World image
    assert none["status"] == "none" and none["built_ha"] is None
    assert c.strip_row(100.0, 50.0, 5.0)["status"] == "clear"   # exactly half counts, as monthly.class_status
    assert c.strip_row(0.0, 0.0, 0.0)["status"] == "none"       # a strip with no land never divides by zero


def test_period_row_has_both_strips_and_a_gap_month_has_no_zeros():
    land = {"0-200": 100.0, "200-500": 300.0}
    row = c.period_row(land, groups(g1=100.0, g2=290.0), groups(g1=22.0, g2=40.0))
    assert set(row) == set(COASTAL_STRIPS) and row["0-200"]["built_ha"] == 22.0 and row["200-500"]["built_ha"] == 40.0
    gap = c.period_row(land, None, None)
    assert all(v["built_ha"] is None and v["status"] == "none" for v in gap.values())


SUMMARY = {"period": ["2024-10", "2024-12"], "months": [
    {"month": "2024-10", "strips": c.period_row({"0-200": 100.0, "200-500": 300.0}, groups(g1=100, g2=300), groups(g1=20, g2=50))},
    {"month": "2024-11", "strips": c.period_row({"0-200": 100.0, "200-500": 300.0}, groups(g1=100, g2=300), groups(g1=21, g2=51))},
    {"month": "2024-12", "strips": c.period_row({"0-200": 100.0, "200-500": 300.0}, None, None)}]}


def test_series_flat_for_one_strip_and_gaps_stay_null():
    s = c.series(SUMMARY, "0-200")
    assert [m["month"] for m in s] == ["2024-10", "2024-11", "2024-12"]
    assert [m["built_ha"] for m in s] == [20.0, 21.0, None] and s[2]["status"] == "none"
    both = c.series(SUMMARY)
    assert set(both[0]["strips"]) == set(COASTAL_STRIPS)
    with pytest.raises(ValueError):
        c.series(SUMMARY, "0-500")


def test_change_row_over_the_pixels_seen_in_both():
    row = c.change_row({"0-200": 100.0, "200-500": 300.0}, groups(g1=90, g2=250), groups(g1=4.0, g2=1.0), groups(g1=0.5))
    assert row["0-200"] == {"compared_ha": 90.0, "cover": 0.9, "gained_ha": 4.0, "lost_ha": 0.5, "net_ha": 3.5}
    assert row["200-500"]["lost_ha"] == 0.0 and row["200-500"]["net_ha"] == 1.0


# ---------- polygons, patches ----------
FRAME = shoreline.LocalFrame(107.3, 21.0)


def square(lon, lat, side_m):
    x0, y0 = FRAME.to_m(lon, lat)
    pts = [(x0, y0), (x0 + side_m, y0), (x0 + side_m, y0 + side_m), (x0, y0 + side_m), (x0, y0)]
    return [list(FRAME.to_lonlat(*p)) for p in pts]


def test_polygon_stats_area_centroid_holes_and_multipolygon():
    sq = {"type": "Polygon", "coordinates": [square(107.3, 21.0, 100)]}
    st = c.polygon_stats(sq, FRAME)
    assert st["area_ha"] == pytest.approx(1.0, rel=1e-6)
    lon, lat = FRAME.to_lonlat(50, 50)
    assert st["lon"] == pytest.approx(lon, abs=1e-8) and st["lat"] == pytest.approx(lat, abs=1e-8)
    holed = {"type": "Polygon", "coordinates": [square(107.3, 21.0, 100), square(107.3003, 21.0003, 30)[::-1]]}
    assert c.polygon_stats(holed, FRAME)["area_ha"] == pytest.approx(1.0 - 0.09, rel=1e-3)
    two = {"type": "MultiPolygon", "coordinates": [[square(107.3, 21.0, 100)], [square(107.31, 21.0, 100)]]}
    assert c.polygon_stats(two, FRAME)["area_ha"] == pytest.approx(2.0, rel=1e-3)
    with pytest.raises(ValueError):
        c.polygon_stats({"type": "Point", "coordinates": [0, 0]}, FRAME)


AOI = load_study_config()["aoi"]


def raw(code, side_m, lon=107.3, lat=21.0):
    return {"type": "Feature", "properties": {"strip": float(code)}, "geometry": {"type": "Polygon", "coordinates": [square(lon, lat, side_m)]}}


def test_finalise_patches_filters_orders_and_labels():
    f = c.finalise_patches([raw(1, 40), raw(2, 120, 107.25, 21.05), raw(1, 80, 107.35, 21.02), raw(9, 500)], AOI)
    assert [x["id"] for x in f["features"]] == ["p0001", "p0002"]      # 0.16 ha and the unknown strip code are gone; largest first
    big, small = (x["properties"] for x in f["features"])
    assert big["strip"] == "200-500" and big["area_ha"] == pytest.approx(1.44, abs=0.01) and big["location"] == "west"
    assert small["strip"] == "0-200" and small["area_ha"] == pytest.approx(0.64, abs=0.01) and small["location"] == "east"
    assert -1 < big["lon"] - 107.25 < 1 and "geometry" in f["features"][0]
    assert c.finalise_patches([raw(1, 60)], AOI, min_ha=0.1)["features"][0]["properties"]["area_ha"] == pytest.approx(0.36, abs=0.01)


def test_patch_threshold_default_is_half_a_hectare():
    kept = c.finalise_patches([raw(1, 70), raw(1, 80, 107.33, 21.0)], AOI)["features"]     # 0.49 ha, 0.64 ha
    assert [f["properties"]["area_ha"] for f in kept] == [pytest.approx(0.64, abs=0.01)]


def test_finalise_strips_and_patch_summary():
    fc = c.finalise_strips([raw(2, 100), raw(1, 100), raw(7, 100)])
    assert [f["properties"]["strip"] for f in fc["features"]] == ["0-200", "200-500"]
    patches = c.finalise_patches([raw(1, 100), raw(1, 120, 107.33, 21.0), raw(2, 110, 107.35, 21.0)], AOI)
    s = c.patch_summary(patches)
    assert s["count"] == 3 and s["by_strip"]["0-200"]["count"] == 2 and s["by_strip"]["0-200"]["largest_ha"] == pytest.approx(1.44, abs=0.01)
    assert c.patch_summary({"features": []})["by_strip"]["200-500"] == {"count": 0, "area_ha": 0, "largest_ha": None}


# ---------- Phase 14 (c) blind lock ----------
def test_hidden_cells_are_the_thirty_labelled_cells():
    boxes = c.hidden_cells()
    assert len(boxes) == 30 and all(w < e and s < n for w, s, e, n in boxes)


def test_hide_patches_until_unlocked():
    cell = (107.30, 21.00, 107.3003, 21.0003)
    on_cell = {"type": "Feature", "properties": {"id": "p1"}, "geometry": {"type": "Polygon", "coordinates": [square(107.3001, 21.0001, 20)]}}
    near = {"type": "Feature", "properties": {"id": "p2"}, "geometry": {"type": "Polygon", "coordinates": [square(107.3009, 21.0, 20)]}}   # ~ 60 m east
    far = {"type": "Feature", "properties": {"id": "p3"}, "geometry": {"type": "Polygon", "coordinates": [square(107.32, 21.02, 20)]}}
    fc = {"type": "FeatureCollection", "features": [on_cell, near, far]}
    kept = [f["properties"]["id"] for f in c.hide_patches(fc, [cell], unlocked=False)["features"]]
    assert kept == ["p2", "p3"]
    assert len(c.hide_patches(fc, [cell], unlocked=True)["features"]) == 3
    assert c.COASTAL_CELLS_UNLOCKED is False                          # the lock is on until the Phase 14 (c) labels exist


# ---------- Open Buildings ----------
def test_ob_row_reports_each_threshold_and_what_the_dataset_covers():
    row = c.ob_row(2020, 4, groups(g1=100, g2=290), {0.3: groups(g1=30, g2=60), 0.5: groups(g1=20, g2=40), 0.7: groups(g1=9)})
    assert row["year"] == 2020 and row["tiles"] == 4
    s = row["strips"]["0-200"]
    assert s["observed_ha"] == 100.0 and s["built_ha"] == {"0.3": 30.0, "0.5": 20.0, "0.7": 9.0}
    assert row["strips"]["200-500"]["built_ha"]["0.7"] == 0.0
    assert c.OB_HEADLINE in c.OB_THRESHOLDS and c.OB_YEARS == (2016, 2023)


# ---------- cells ----------
def test_cell_grid_fits_the_qn_aoi_and_refuses_one_that_does_not():
    g = c.cell_grid(AOI)
    assert g["lon0"] == 107.22 and g["lat0"] == 20.98 and g["nx"] == 180 and g["ny"] == 120
    big = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]]}
    with pytest.raises(ValueError, match="raise CELL_DEG"):
        c.cell_grid(big)


def test_cell_code_round_trip():
    code = 2 * c.CELL_BASE ** 2 + 179 * c.CELL_BASE + 119
    assert c.decode_cell(code) == (2, 179, 119) and c.decode_cell(float(code)) == (2, 179, 119)
    assert c.decode_cell(1 * c.CELL_BASE ** 2) == (1, 0, 0)


GRID = {"lon0": 107.30, "lat0": 21.00, "step": 0.001, "nx": 20, "ny": 20}


def code(strip, cx, cy):
    return strip * c.CELL_BASE ** 2 + cx * c.CELL_BASE + cy


def test_cells_from_groups_drops_unknown_strips_and_cells_off_the_grid():
    k = lambda *a: str(code(*a))
    land = [{"group": code(1, 0, 0), "sum": 1.0 * M}, {"group": code(2, 3, 4), "sum": 1.0 * M}, {"group": code(3, 0, 0), "sum": M}, {"group": code(1, 99, 0), "sum": M}]
    obs = [{"group": code(1, 0, 0), "sum": 0.9 * M}]
    rows = c.cells_from_groups(GRID, land, obs, [{"group": code(1, 0, 0), "sum": 0.2 * M}], [{"group": code(1, 0, 0), "sum": 0.5 * M}])
    assert rows == [[1, 0, 0, 1.0, 0.9, 0.2, 0.5], [2, 3, 4, 1.0, 0.0, 0.0, 0.0]]
    assert c.WINDOW_COLUMNS == ["strip", "cx", "cy", "land_ha", "observed_ha", "built_ha_before", "built_ha_after"]


def test_overlap_share():
    rect = (0.0, 0.0, 1.0, 1.0)
    assert c._overlap(rect, (0.5, 0.0, 2.0, 1.0))[0] == 0.5
    assert c._overlap(rect, (-1, -1, 2, 2)) == (1.0, (0.0, 0.0, 1.0, 1.0))
    assert c._overlap(rect, (2, 2, 3, 3)) == (0.0, None)
    assert c._overlap(rect, (1.0, 0.0, 2.0, 1.0))[0] == 0.0           # touching edges only


# ---------- box evidence ----------
def cells_file(rows, windows=(["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"])):
    return {"windows": [list(windows[0]), list(windows[1])], "grid": GRID, "columns": c.WINDOW_COLUMNS, "cells": rows}


def row(strip, cx, cy, land=1.0, obs=1.0, before=0.2, after=0.5):
    return [strip, cx, cy, land, obs, before, after]


BOX = (107.300, 21.000, 107.306, 21.006)         # 6 x 6 cells; middle third is cells 2-3


def test_evidence_strips_sums_cells_per_strip_and_location_and_is_valid():
    rows = [row(1, 0, 0), row(1, 5, 5), row(2, 2, 2, land=2.0, obs=2.0, before=0.4, after=1.0)]
    ev = c.evidence_strips(BOX, cells_file(rows))
    assert ev == [{"strip": "0-200", "built_ha_before": 0.2, "built_ha_after": 0.5, "location": "north-east"},
                  {"strip": "0-200", "built_ha_before": 0.2, "built_ha_after": 0.5, "location": "south-west"},
                  {"strip": "200-500", "built_ha_before": 0.4, "built_ha_after": 1.0, "location": "centre"}]
    assert all(validate_strip(e) == [] for e in ev)
    assert validate_evidence({"change_frac": 0.0, "regions": [], "coastal_strips": ev}) == []


def test_evidence_strips_clips_cells_on_the_box_edge_by_share():
    rows = [row(1, 5, 5, land=1.0, obs=1.0, before=0.4, after=0.8)]
    half = (107.300, 21.000, 107.3055, 21.006)                       # cuts the cell (cx 5) in half
    (e,) = c.evidence_strips(half, cells_file(rows), min_ha=0.1)
    assert e["built_ha_before"] == pytest.approx(0.2) and e["built_ha_after"] == pytest.approx(0.4)


def test_evidence_strips_leaves_out_what_it_cannot_back():
    rows = [row(1, 0, 0, land=0.3, obs=0.3), row(2, 2, 2, land=2.0, obs=0.6)]
    assert c.evidence_strips(BOX, cells_file(rows)) == []             # too little land / under half observed in both windows
    assert c.evidence_strips(BOX, cells_file([])) == []
    far = cells_file([row(1, 15, 15)])
    assert c.evidence_strips(BOX, far) == []                          # no strip crosses the box


def test_evidence_strips_feed_the_verifier():
    ev = {"change_frac": 0.0, "regions": [], "coastal_strips": c.evidence_strips(BOX, cells_file([row(1, 0, 0, before=3.0, after=6.5)]), min_ha=0.5)}
    claim = {"claim_id": "c1", "level": "L2", "type": "coastal_built", "text": "Built-up area within 200 m of the shore grew in the south-west.",
             "region_ref": None, "evidence_ref": [], "stated_conf": None}
    assert verify(claim, ev).verdict == "supported"
    assert verify({**claim, "text": "Built-up area within 200 m of the shore shrank in the south-west."}, ev).verdict == "unsupported"
    assert verify({**claim, "text": "Built-up area within 200 m of the shore grew in the north."}, ev).reason == "coastal_not_in_evidence"


def test_box_strips_needs_a_run_for_exactly_these_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "COASTAL_DIR", tmp_path)
    c._cache.clear()
    b, a = ["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]
    assert c.box_strips(BOX, b, a) is None                            # no run yet: shoreline claims stay uncertain
    path = c.windows_file(b, a)
    assert path.name == "windows_2018-11_2022-11.json"
    path.write_text(json.dumps(cells_file([row(1, 0, 0)], (b, a))))
    c._cache.clear()
    assert len(c.box_strips(BOX, b, a)) == 1
    assert c.box_strips(BOX, ["2018-11-02", "2019-03-31"], a) is None  # same months, other days: not this pair
    assert c.box_strips(BOX, [], a) is None
    c._cache.clear()


# ---------- outputs + API ----------
@pytest.fixture
def written(tmp_path, monkeypatch):
    land = {"0-200": 100.0, "200-500": 300.0}
    seasons = [{"season": "2024-25", "window": ["2024-10-01", "2025-04-01"], "strips": c.period_row(land, groups(g1=99, g2=299), groups(g1=20, g2=50))},
               {"season": "2025-26", "window": ["2025-10-01", "2026-04-01"], "strips": c.period_row(land, groups(g1=99, g2=299), groups(g1=26, g2=52))}]
    patches = c.finalise_patches([raw(1, 100), raw(2, 120, 107.33, 21.0), raw(1, 110, 107.35, 21.04)], AOI)
    result = {"period": ["2024-10", "2024-12"], "strips": {n: {"land_ha": v} for n, v in land.items()}, "months": SUMMARY["months"], "seasons": seasons,
              "season_change": [{"from": "2024-25", "to": "2025-26", "strips": c.change_row(land, groups(g1=98, g2=290), groups(g1=6.5), groups(g1=0.4))}],
              "patches": patches, "open_buildings": [c.ob_row(2022, 3, groups(g1=100, g2=290), {0.3: groups(g1=30), 0.5: groups(g1=20), 0.7: groups(g1=9)}),
                                                     c.ob_row(2023, 3, groups(g1=100, g2=290), {0.3: groups(g1=32), 0.5: groups(g1=22), 0.7: groups(g1=10)})],
              "strip_polygons": c.finalise_strips([raw(1, 200), raw(2, 300)]),
              "sea": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [square(107.2, 21.0, 100)]}}]}
    monkeypatch.setattr(c, "COASTAL_DIR", tmp_path)
    return tmp_path, c.write_outputs(result, tmp_path)


def test_write_outputs(written):
    path, summary = written
    assert {p.name for p in path.iterdir()} == {"summary.json", "strips.geojson", "patches.geojson", "sea.geojson"}
    assert summary["patches"]["count"] == 3 and summary["method"]["units"].startswith("hectares of built area")
    assert "geometry" not in json.dumps(summary)                      # the summary carries no per-patch geometry
    assert c.load("summary.json")["months"][2]["strips"]["0-200"]["built_ha"] is None
    assert c.load("missing.json") is None


def test_api(written, monkeypatch):
    monkeypatch.setattr(c, "hidden_cells", lambda: [])
    cl = TestClient(main.app)
    assert cl.get("/api/coastal").json()["strips"]["0-200"]["land_ha"] == 100.0
    assert {f["properties"]["strip"] for f in cl.get("/api/coastal/strips").json()["features"]} == set(COASTAL_STRIPS)
    one = cl.get("/api/coastal/monthly", params={"strip": "0-200"}).json()
    assert one["strip"] == "0-200" and [m["built_ha"] for m in one["series"]] == [20.0, 21.0, None] and one["period"] == ["2024-10", "2024-12"]
    both = cl.get("/api/coastal/monthly").json()
    assert set(both["series"][0]["strips"]) == set(COASTAL_STRIPS)
    seasons = cl.get("/api/coastal/seasons").json()
    assert [s["season"] for s in seasons["seasons"]] == ["2024-25", "2025-26"] and seasons["change"][0]["strips"]["0-200"]["net_ha"] == 6.1
    assert len(cl.get("/api/coastal/patches").json()["features"]) == 3
    assert len(cl.get("/api/coastal/patches", params={"strip": "200-500"}).json()["features"]) == 1
    assert len(cl.get("/api/coastal/patches", params={"min_ha": 1.1}).json()["features"]) == 2
    ob = cl.get("/api/coastal/open-buildings").json()
    assert [y["year"] for y in ob["years"]] == [2022, 2023] and ob["headline_threshold"] == 0.5
    flat = cl.get("/api/coastal/open-buildings", params={"strip": "0-200"}).json()["years"][1]
    assert flat["built_ha"]["0.5"] == 22.0 and flat["observed_ha"] == 100.0
    assert cl.get("/api/coastal/monthly", params={"strip": "0-500"}).status_code == 422
    assert cl.get("/api/coastal/patches", params={"min_ha": -1}).status_code == 422


def test_api_withholds_patches_on_phase_14_cells(written):
    cl = TestClient(main.app)
    fc = json.loads((written[0] / "patches.geojson").read_text())
    cells = c.hidden_cells()
    assert len(cells) == 30
    w, s, e, n = cells[0]                                              # a patch right on the first labelled cell
    on_cell = {"type": "Feature", "id": "px", "properties": {"id": "px", "strip": "0-200", "area_ha": 0.6, "location": "centre"},
               "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}
    (written[0] / "patches.geojson").write_text(json.dumps({**fc, "features": fc["features"] + [on_cell]}))
    ids = [f["id"] for f in cl.get("/api/coastal/patches").json()["features"]]
    assert "px" not in ids and len(ids) == 3


def test_api_before_any_run(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "COASTAL_DIR", tmp_path)
    cl = TestClient(main.app)
    for path in ("/api/coastal", "/api/coastal/strips", "/api/coastal/monthly", "/api/coastal/seasons", "/api/coastal/patches", "/api/coastal/open-buildings"):
        r = cl.get(path)
        assert r.status_code == 404 and "make_coastal" in r.json()["detail"], path


def test_method_states_what_the_numbers_are_not():
    assert "never building counts" in c.METHOD["units"] and "reference only" in c.METHOD["open_buildings"]
    assert "gap" in c.METHOD["gaps"]
