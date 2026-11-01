import json
import math

import pytest
from fastapi.testclient import TestClient

from agents import shoreline as s
from webapp.backend import main


# ---------- geometry ----------
def test_local_frame_round_trip():
    f = s.LocalFrame(107.31, 21.04)
    x, y = f.to_m(107.32, 21.05)
    assert 1000 < x < 1100 and 1100 < y < 1120
    lon, lat = f.to_lonlat(x, y)
    assert abs(lon - 107.32) < 1e-9 and abs(lat - 21.05) < 1e-9


def test_douglas_peucker_drops_small_wiggles():
    pts = [(0, 0), (50, 3), (100, -2), (150, 4), (200, 0)]
    assert s.douglas_peucker(pts, 10) == [(0, 0), (200, 0)]
    corner = [(0, 0), (100, 0), (100, 100)]
    assert s.douglas_peucker(corner, 10) == corner


def test_split_off_edge_cuts_where_the_ring_follows_the_aoi_edge():
    box = (0, 0, 1000, 1000)
    # sea polygon in the bottom-right corner: its ring runs along the box edge on two sides
    ring = [(1000, 0), (400, 0), (400, 300), (700, 600), (1000, 600), (1000, 0)]
    pieces = s.split_off_edge(ring, box, 60)
    assert len(pieces) == 1 and pieces[0] == [(400, 300), (700, 600)]
    island = [(400, 400), (500, 400), (500, 500), (400, 500), (400, 400)]
    assert s.split_off_edge(island, box, 60) == [island]


def test_point_in_polygons_with_hole():
    sea = [[[(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)], [(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]]]
    assert s.point_in_polygons((10, 10), sea)
    assert not s.point_in_polygons((50, 50), sea)          # island
    assert not s.point_in_polygons((150, 50), sea)


def test_transects_point_to_the_sea():
    # straight coast along y = 0, sea below (y < 0)
    sea = [[[(-1000, 0), (2000, 0), (2000, -1000), (-1000, -1000), (-1000, 0)]]]
    line = [(0, 0), (1000, 0)]
    tr = s.make_transects([line], sea, spacing=100)
    assert len(tr) == 11 and [t["chainage"] for t in tr[:3]] == [0, 100, 200]
    assert all(abs(t["normal"][0]) < 1e-9 and t["normal"][1] == pytest.approx(-1) for t in tr)


def test_monthly_lines_break_at_gaps():
    f = s.LocalFrame(107.3, 21.0)
    trs = [{"id": f"t{i}", "line": 0, "index": i, "origin_m": (i * 100.0, 0.0), "normal": (0.0, -1.0)} for i in range(6)]
    pos = {"t0": [10.0], "t1": [12.0], "t2": [None], "t3": [None], "t4": [8.0], "t5": [9.0]}
    runs = s.monthly_lines(trs, pos, 0, f)
    assert len(runs) == 2 and len(runs[0]) == 2 and len(runs[1]) == 2      # 2 missing in a row breaks the line


# ---------- positions ----------
OFF = s.profile_offsets()


def profile(shore, noise=()):
    v = [0 if o < shore else 1 for o in OFF]
    for i in noise:
        v[i] = 1 - v[i]
    return v


@pytest.mark.parametrize("shore", [-150, 0, 40, 330])
def test_position_found_within_half_a_step(shore):
    r = s.shoreline_position(profile(shore), OFF)
    assert r["status"] == "ok" and abs(r["pos"] - (shore - s.STEP_M / 2)) <= s.STEP_M / 2


def test_position_ignores_a_pond_and_speckle():
    r = s.shoreline_position(profile(60, noise=(5, 6, 70)), OFF)
    assert r["pos"] == 55.0 and r["agreement"] > 0.95


def test_inland_pond_behind_the_coast_never_wins():
    """Settling ponds ~250 m inland made the old best-split flip between coast and pond."""
    v = profile(0)
    for i in range(3, 12):          # a big pond from -270 m to -190 m, behind solid land
        v[i] = 1
    r = s.shoreline_position(v, OFF)
    assert r["status"] == "ok" and r["pos"] == -5.0


def test_two_land_pixels_in_the_sea_dont_stop_the_walk():
    v = profile(0, noise=(50, 51))  # a boat / speckle 200 m out
    assert s.shoreline_position(v, OFF)["pos"] == -5.0


@pytest.mark.parametrize("values, status", [([1] * len(OFF), "all_water"), ([0] * len(OFF), "all_land"),
                                            ([None] * len(OFF), "no_data")])
def test_no_position_cases(values, status):
    r = s.shoreline_position(values, OFF)
    assert r["pos"] is None and r["status"] == status


def test_unclear_profile_gives_no_position():
    alternating = [i % 2 for i in range(len(OFF))]
    assert s.shoreline_position(alternating, OFF)["status"] == "unclear"


# ---------- rates ----------
def test_rate_recovers_a_trend_and_calls_noise_stable():
    trend = s.rate_stats([(i / 12, 20 * i / 12 + (3 if i % 2 else -3)) for i in range(24)])
    assert trend["trend"] == "advancing" and trend["lrr"] == pytest.approx(20, abs=1.5)
    retreat = s.rate_stats([(i / 12, -15 * i / 12 + (2 if i % 3 else -2)) for i in range(24)])
    assert retreat["trend"] == "retreating"
    noise = s.rate_stats([(i / 12, 5 if i % 2 else -5) for i in range(24)])
    assert noise["trend"] == "stable" and noise["ci95"] > abs(noise["lrr"])


def test_rate_needs_enough_months_and_skips_gaps():
    few = s.rate_stats([(i / 12, 1.0 if i < 4 else None) for i in range(24)])
    assert few["trend"] == "too_few" and few["n"] == 4
    gappy = s.rate_stats([(i / 12, 10 * i / 12 if i % 4 else None) for i in range(24)])
    assert gappy["n"] == 18 and gappy["lrr"] == pytest.approx(10, abs=0.01)


def test_t95_table():
    assert s.t95(22) == pytest.approx(2.086) and s.t95(1) == pytest.approx(12.706) and s.t95(500) == 1.96
    assert math.isinf(s.t95(0))


def test_years_since():
    assert s.years_since("2025-10", "2024-10") == 1.0 and s.years_since("2024-11", "2024-10") == pytest.approx(1 / 12)


# ---------- outputs + API ----------
@pytest.fixture
def written(tmp_path, monkeypatch):
    f = s.LocalFrame(107.3, 21.0)
    trs = [{"id": f"t{i + 1:04d}", "line": 0, "index": i, "chainage": i * 100.0, "origin_m": (i * 100.0, 0.0), "normal": (0.0, -1.0)}
           for i in range(4)]
    keys = [f"2024-{m}" for m in ("10", "11", "12")] + [f"2025-{m:02d}" for m in range(1, 10)]
    positions = {t["id"]: [float(j * (i + 1)) for j in range(len(keys))] for i, t in enumerate(trs)}
    qs = s.quarters(keys)
    qpos = {t["id"]: [float(qi * 3 * (i + 1)) for qi in range(len(qs))] for i, t in enumerate(trs)}
    for i, t in enumerate(trs):
        st = s.rate_stats([(qi * 0.25, p) for qi, p in enumerate(qpos[t["id"]])], min_months=4)   # 12-month fixture: 4 quarters
        t["stats"] = {**st, "monthly_iqr": 5.0, "tidal": False, **s.confirm(st["trend"], 0.0, 30.0 if i < 3 else 0.0)}
    result = {"frame": f, "keys": keys, "quarters": qs, "lines": [[(0, 0), (300, 0)]], "transects": trs,
              "positions": positions, "qpositions": qpos, "status_counts": {"ok": 48}}
    monkeypatch.setattr(s, "SHORELINE_DIR", tmp_path)
    summary = s.write_outputs(result, tmp_path)
    return tmp_path, summary


def test_write_outputs(written):
    path, summary = written
    assert summary["transects"] == 4 and summary["radar_trends"] == {"advancing": 4} and summary["baseline_km"] == 0.3
    assert summary["changes"] == {"advancing": 3, "unconfirmed": 1}
    tr = json.loads((path / "transects.geojson").read_text())
    assert tr["features"][0]["geometry"]["type"] == "LineString" and tr["features"][0]["properties"]["lrr"] == pytest.approx(12, abs=0.01)
    assert tr["features"][0]["properties"]["tidal"] is False
    lines = json.loads((path / "shorelines.geojson").read_text())
    assert len(lines["features"]) == 12 + 4 and lines["features"][0]["properties"]["month"] == "2024-10"
    assert [f["properties"]["quarter"] for f in lines["features"] if f["properties"]["kind"] == "quarter"][0] == "2024-10/2024-12"
    assert summary["quarters"] == ["2024-10/2024-12", "2025-01/2025-03", "2025-04/2025-06", "2025-07/2025-09"]


def test_api(written, monkeypatch):
    path, _ = written
    monkeypatch.setattr(main.shoreline, "SHORELINE_DIR", path)
    c = TestClient(main.app)
    assert c.get("/api/shoreline").json()["transects"] == 4
    assert len(c.get("/api/shoreline/transects", params={"trend": "advancing"}).json()["features"]) == 4
    assert c.get("/api/shoreline/transects", params={"trend": "retreating"}).json()["features"] == []
    assert len(c.get("/api/shoreline/transects", params={"change": "advancing"}).json()["features"]) == 3
    assert [f["id"] for f in c.get("/api/shoreline/transects", params={"change": "unconfirmed"}).json()["features"]] == ["t0004"]
    one = c.get("/api/shoreline/transects/t0002").json()
    assert one["trend"] == "advancing" and len(one["series"]) == 12 and one["series"][1] == {"month": "2024-11", "pos": 2.0}
    assert len(c.get("/api/shoreline/lines", params={"month": "2025-03"}).json()["features"]) == 1
    assert len(c.get("/api/shoreline/lines", params={"kind": "quarter"}).json()["features"]) == 4
    assert one["quarterly"][0] == {"quarter": "2024-10/2024-12", "pos": 0.0} and len(one["quarterly"]) == 4
    assert c.get("/api/shoreline/lines", params={"month": "bad"}).status_code == 400
    assert c.get("/api/shoreline/transects/t9999").status_code == 404
    pos = json.loads((path / "positions.json").read_text())       # a transect in positions.json only
    pos["positions"]["t0099"] = pos["positions"]["t0002"]
    (path / "positions.json").write_text(json.dumps(pos))
    assert c.get("/api/shoreline/transects/t0099").status_code == 404


def test_api_before_any_run(tmp_path, monkeypatch):
    monkeypatch.setattr(main.shoreline, "SHORELINE_DIR", tmp_path)
    r = TestClient(main.app).get("/api/shoreline")
    assert r.status_code == 404 and "make_shoreline" in r.json()["detail"]


def test_resample_and_smooth_keep_ends_and_flatten_wiggles():
    zig = [(x, 30 * math.sin(x / 40)) for x in range(0, 1001, 10)]
    r = s.resample(zig, 20)
    assert r[0] == zig[0] and r[-1] == pytest.approx(zig[-1])
    sm = s.smooth(zig)
    assert sm[0] == zig[0] and max(abs(y) for _, y in sm[15:-15]) < 6


def test_smoothed_transects_on_a_wiggly_coast_stay_near_parallel():
    sea = [[[(-1000, 0), (2000, 0), (2000, -1000), (-1000, -1000), (-1000, 0)]]]
    wiggly = [(x, 25 * math.sin(x / 30)) for x in range(0, 1001, 10)]
    raw = s.make_transects([s.douglas_peucker(wiggly, 5)], sea)
    smoothed = s.make_transects([s.smooth(s.douglas_peucker(wiggly, 5))], sea)
    spread = lambda trs: max(abs(math.degrees(math.atan2(t["normal"][0], -t["normal"][1]))) for t in trs)
    assert spread(smoothed) < 15 < spread(raw)



def test_quarters_and_iqr():
    keys = [f"2024-{m}" for m in ("10", "11", "12")] + [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]
    q = s.quarters(keys)
    assert len(q) == 8 and q[0] == ["2024-10", "2024-11", "2024-12"] and q[-1] == ["2026-07", "2026-08", "2026-09"]
    assert s.quarters(keys[:7]) == [keys[0:3], keys[3:6]]            # a 1-month tail is dropped
    assert s.iqr([0, 5, 10, 400, 410, 15, -5, 20]) == 15.0 and s.iqr([1, 2]) is None


def test_tide_flips_dont_make_a_quarterly_trend():
    """Monthly positions flipping between coast (~0) and a low-tide flat edge (~+400), more flips
    late in the period: the monthly fit says advancing, the tide-averaged quarterly series is flat."""
    monthly = [0, 0, 400, 0, 0, 0, 0, 400, 0, 0, 0, 0, 400, 0, 400, 0, 400, 400, 0, 400, 400, 0, 400, 400]
    assert s.rate_stats([(i / 12, p) for i, p in enumerate(monthly)])["trend"] == "advancing"
    quarterly = [5, -5, 0, 10, -5, 5, 0, -5]                         # water in >= half the quarter's looks
    assert s.rate_stats([(i / 4, p) for i, p in enumerate(quarterly)], min_months=s.MIN_QUARTERS)["trend"] == "stable"
    assert s.iqr(monthly) > s.TIDAL_IQR_M



@pytest.mark.parametrize("trend, first, last, change", [
    ("advancing", 0, 40, "advancing"), ("advancing", 0, 10, "unconfirmed"), ("advancing", 0, -40, "unconfirmed"),
    ("retreating", 50, 10, "retreating"), ("retreating", 50, None, "unconfirmed"),
    ("stable", 0, 300, "stable"), ("too_few", None, None, "too_few")])
def test_optical_confirmation(trend, first, last, change):
    assert s.confirm(trend, first, last)["change"] == change


def test_fastest_retreat_is_none_without_confirmed_retreat(written):
    _, summary = written
    assert summary["fastest_advance_m_yr"] is not None and summary["fastest_retreat_m_yr"] is None


def test_years_stats_and_lines():
    labels = [f"{y}-{(y + 1) % 100:02d}" for y in range(2015, 2021)]
    st = s.years_stats(labels, [0, 10, 21, 30, 39, 50], [None, None, None, 5.0, None, 40.0])
    assert st["trend"] == "advancing" and st["lrr"] == pytest.approx(10, abs=0.3) and st["change"] == "advancing"
    assert s.years_stats(labels, [0, None, None, 30, None, None], [None] * 6)["change"] == "too_few"
    assert s.years_stats(labels, [0, 10, 21, 30, 39, 50], [None] * 6)["change"] == "unconfirmed"   # no optical before S2 SR
    feats = [{"id": f"t{i}", "properties": {"line": 0}, "geometry": {"type": "LineString", "coordinates": [[0, i * 0.001], [0.008, i * 0.001]]}}
             for i in range(4)]
    runs = s.season_lines(feats, {"t0": [0.0], "t1": [100.0], "t2": [None], "t3": [-300.0]}, 0)
    assert runs == [[(0.003, 0.0), (0.004, 0.001), (0.0, 0.003)]]   # one missing transect (t2) is bridged, as monthly_lines


def test_years_api(written, monkeypatch):
    path, _ = written
    monkeypatch.setattr(main.shoreline, "SHORELINE_DIR", path)
    c = TestClient(main.app)
    assert c.get("/api/shoreline/years").status_code == 404
    transects = json.loads((path / "transects.geojson").read_text())
    ids = [f["id"] for f in transects["features"]]
    seasons = [["2015-16", "2015-10-01", "2016-04-01"], ["2016-17", "2016-10-01", "2017-04-01"]]
    result = {"seasons": seasons, "positions": {t: [0.0, 40.0] for t in ids}, "optical": {t: [0.0, 35.0] for t in ids},
              "transects": {t: {"n": 2, "lrr": 40.0, "ci95": None, "r2": None, "nsm": 40.0, "trend": "advancing",
                                "opt_first": 0.0, "opt_last": 35.0, "opt_shift": 35.0, "change": "advancing"} for t in ids},
              "status_counts": {"advancing": len(ids)}, "method": s.YEARS_METHOD}
    out = s.years_outputs(result, transects, path)
    assert out["seasons"] == ["2015-16", "2016-17"] and out["lines"] == 2
    assert c.get("/api/shoreline/years").json()["seasons"] == ["2015-16", "2016-17"]
    assert len(c.get("/api/shoreline/years/lines").json()["features"]) == 2
    assert c.get("/api/shoreline/years/lines", params={"season": "2016-17"}).json()["features"][0]["properties"]["season"] == "2016-17"
    assert c.get("/api/shoreline/years/lines", params={"season": "1999-00"}).status_code == 404
    tr = c.get("/api/shoreline/years/transects").json()["features"]
    assert len(tr) == len(ids) and tr[0]["properties"]["change"] == "advancing" and "monthly_iqr" not in tr[0]["properties"]
    one = c.get(f"/api/shoreline/transects/{ids[0]}").json()
    assert one["yearly"] == [{"season": "2015-16", "pos": 0.0, "optical": 0.0}, {"season": "2016-17", "pos": 40.0, "optical": 35.0}]
    assert one["yearly_stats"]["change"] == "advancing"


# ---------- Planet 3 m shoreline (Phase 13c) ----------
def test_diff_stats_and_dry_months():
    st = s.diff_stats([10.0, -20.0, 30.0, 5.0])
    assert st["n"] == 4 and st["bias_m"] == 6.2 and st["mae_m"] == 16.2 and st["median_abs_m"] == 15.0
    assert st["within_20m"] == 0.75 and st["within_30m"] == 1.0
    assert s.diff_stats([])["rmse_m"] is None
    assert s.is_dry_month("2024-10") and s.is_dry_month("2025-03") and not s.is_dry_month("2025-04")


def test_planet_compare_splits_dry_and_monsoon_and_skips_blind():
    months = ["2024-10", "2025-04"]
    planet = {"a": [5.0, 30.0], "b": [None, 10.0], "ref": [100.0, 100.0]}
    radar = {"a": [0.0, 0.0], "b": [0.0, None], "ref": [0.0, 0.0]}
    out = s.planet_compare(months, planet, months, radar, yearly={"a": 1.0, "ref": 0.0}, skip={"ref"})
    assert out["dry"]["n"] == 1 and out["dry"]["bias_m"] == 5.0          # a only: ref is blind, b has no Planet position
    assert out["monsoon"]["n"] == 1 and out["monsoon"]["bias_m"] == 30.0  # b has Planet but no radar
    assert out["per_month"][1]["n_planet"] == 2
    assert out["yearly"]["n"] == 1 and out["yearly"]["bias_m"] == 4.0     # median dry Planet (5) - yearly (1)


def test_planet_outputs_and_api(written, monkeypatch):
    path, _ = written
    monkeypatch.setattr(main.shoreline, "SHORELINE_DIR", path)
    c = TestClient(main.app)
    assert c.get("/api/shoreline/planet").status_code == 404
    transects = json.loads((path / "transects.geojson").read_text())
    ids = [f["id"] for f in transects["features"]]
    result = {"months": ["2024-10", "2025-04"], "dates": ["2024-10-05", "2025-04-16"],
              "positions": {t: [3.0, None] for t in ids}, "status_counts": {"ok": 4}, "method": s.PLANET_METHOD}
    out = s.planet_outputs(result, transects, path)
    assert out["lines"] == 1 and out["dry"]["n"] == len(ids) and out["monsoon"]["n"] == 0
    summary = c.get("/api/shoreline/planet").json()
    assert summary["months"] == ["2024-10", "2025-04"] and summary["compare"]["dry"]["n"] == len(ids)
    assert c.get("/api/shoreline/planet/lines", params={"month": "2024-10"}).json()["features"][0]["properties"]["date"] == "2024-10-05"
    assert c.get("/api/shoreline/planet/lines", params={"month": "2025-04"}).status_code == 404
    one = c.get(f"/api/shoreline/transects/{ids[0]}").json()
    assert one["planet"] == [{"month": "2024-10", "date": "2024-10-05", "pos": 3.0}, {"month": "2025-04", "date": "2025-04-16", "pos": None}]
    assert c.get("/api/planet/layer", params={"month": "2025-02"}).status_code == 404     # no Planet image that month
    assert c.get("/api/planet/layer", params={"month": "2024-10", "kind": "swir"}).status_code == 400


def test_planet_position_cloud_checks():
    offs = [float(o) for o in range(-50, 55, 5)]                       # 21 samples, landward first
    clean = [0] * 10 + [1] * 11                                        # land then sea: edge near 0 m
    assert s.planet_position(clean, offs)["pos"] is not None
    cloudy = [None] * 6 + clean[6:]                                    # 6 of 21 unclear: under 80 % valid
    assert s.planet_position(cloudy, offs)["status"] == "cloudy"
    gap = clean[:15] + [None] + clean[16:]                             # a cloud seaward of the edge
    assert s.planet_position(gap, offs)["status"] == "cloud_gap"


def test_planet_corroboration():
    radar_months = [f"2024-{m}" for m in ("10", "11", "12")] + [f"2025-{m:02d}" for m in range(1, 10)]
    months = ["2024-10", "2024-11", "2025-07", "2025-08"]
    adv = {"trend": "advancing", "tidal": False}
    assert s.planet_corroboration(months, [0.0, 4.0, 30.0, 34.0], radar_months, adv)["status"] == "confirmed"
    assert s.planet_corroboration(months, [0.0, 4.0, 5.0, 6.0], radar_months, adv)["status"] == "not_confirmed"
    assert s.planet_corroboration(months, [0.0, None, 30.0, 34.0], radar_months, adv)["status"] == "pending_coverage"
    assert s.planet_corroboration(months, [0.0, 4.0, 30.0, 34.0], radar_months, {**adv, "tidal": True})["status"] == "tidal_uncertainty"
    assert s.planet_corroboration(months, [0.0, 4.0, 30.0, 34.0], radar_months, {"trend": "stable"})["status"] == "no_radar_trend"
