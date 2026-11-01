"""agents/ccdc.py (D14) without Earth Engine: break windows, the site result, and the blind lock of
scripts/ccdc_change_month.py."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ccdc_change_month as cm  # noqa: E402
from agents import ccdc  # noqa: E402

ms = ccdc.ms_of


def test_months_and_period():
    assert ccdc.month_of(ms("2025-03-15")) == "2025-03"
    assert ccdc.in_period(ms("2024-10-01")) and ccdc.in_period(ms("2026-09-30"))
    assert not ccdc.in_period(ms("2024-09-30")) and not ccdc.in_period(ms("2026-10-01"))


def test_break_window_spans_the_monsoon_gap():
    looks = [ms(d) for d in ("2025-01-10", "2025-03-20", "2025-10-05", "2025-11-01")]
    assert ccdc.break_window(ms("2025-10-05"), looks) == ["2025-03", "2025-10"]     # no clear look Apr-Sep
    assert ccdc.break_window(ms("2025-03-20"), looks) == ["2025-01", "2025-03"]
    assert ccdc.break_window(ms("2025-01-10"), []) == ["2018-01", "2025-01"]        # no history: from its start
    same = [ms("2025-03-02")]
    assert ccdc.break_window(ms("2025-03-20"), same) == ["2025-02", "2025-03"]      # same month: one month back


def test_site_result():
    looks = [ms("2025-02-01"), ms("2025-04-02")]
    breaks = [ms("2025-04-02")] * 6 + [ms("2025-11-03")] * 2 + [ms("2023-05-01")] * 3   # 3 outside the period
    r = ccdc.site_result(breaks, n_pixels=12, clear_looks_ms=looks)
    assert r["n_break"] == 8 and r["share"] == pytest.approx(0.667, abs=1e-3)
    assert r["lasting"] and r["break_month"] == "2025-04" and r["change_window"] == ["2025-02", "2025-04"]
    seasonal = ccdc.site_result([ms("2025-04-02")] * 2, n_pixels=12, clear_looks_ms=looks)
    assert not seasonal["lasting"] and seasonal["change_window"] is None
    assert ccdc.site_result([], 0, [])["lasting"] is False
    assert ccdc.windows_for_report({"s1": r, "s2": seasonal, "s3": {"error": "x"}}) == {"s1": ["2025-02", "2025-04"]}


def test_sites_are_locked_until_labelled(monkeypatch, tmp_path):
    monkeypatch.setattr(cm.l14, "LABELS_DIR", tmp_path)                 # no change-month labels at all
    with pytest.raises(SystemExit, match="Blind: 30 of the 30 sites"):
        cm.run("sites", [], site_fn=lambda box: ([], 0, []))


def test_labels_complete_counts(tmp_path):
    sites = json.loads(cm.SITES.read_text())
    rows = [{"protocol": "labels14_v1", "labeler": "labeler1", "confidence": "high", "site_id": s["site_id"],
             "lasting_change": "no", "change_window": None} for s in sites[:29]]
    (tmp_path / "labels14_change_month.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert cm.labels_complete(tmp_path) == (False, 1)
    rows.append({**rows[0], "site_id": sites[29]["site_id"]})
    (tmp_path / "labels14_change_month.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert cm.labels_complete(tmp_path) == (True, 0)


def test_dev_run_with_a_fake_ccdc(tmp_path):
    import vlm_batch
    rid = json.loads(vlm_batch.SAMPLE.read_text())["ids"][0]
    fake = lambda box: ([ms("2025-11-05")] * 9, 10, [ms("2025-03-01"), ms("2025-11-05")])
    out = cm.run("dev", [rid], site_fn=fake, log=lambda *_: None)
    assert out["windows"] == {rid: ["2025-03", "2025-11"]} and out["params"]["lasting_share"] == ccdc.LASTING_SHARE
    failing = cm.run("dev", [rid], site_fn=lambda box: (_ for _ in ()).throw(RuntimeError("quota")), log=lambda *_: None)
    assert failing["results"][rid] == {"error": "quota"} and failing["windows"] == {}


# ---------- change regions (Phase 10b) ----------
from agents import ccdc  # noqa: E402


def test_month_index_and_detection_period():
    assert ccdc.month_index(ccdc.ms_of("2018-01-15")) == 0 and ccdc.month_from_index(15) == "2019-04"
    assert ccdc.detection_period("2018-11-01/2019-03-31", "2022-11-01/2023-03-31") == ("2019-04-01", "2023-03-31")


def test_region_result_dates_the_most_common_month():
    r = ccdc.region_result({"22": 3, "21": 5, "40": 5}, 20, {"NDVI": -0.21, "NDBI": 0.1, "MNDWI": None})
    assert r["n_break"] == 13 and r["share"] == 0.65 and r["lasting"]
    assert r["break_month"] == "2019-10"                          # 21 and 40 tie at 5: the earlier month wins
    assert ccdc.region_result({}, 50)["break_month"] is None and not ccdc.region_result({}, 50)["lasting"]
    assert not ccdc.region_result({"30": 2}, 50)["lasting"]       # 4 % of the pixels: not dated


def test_matches_detector_and_main_index():
    region = {"dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.02}
    assert ccdc.matches_detector(region, {"NDVI": -0.4, "NDBI": 0.3, "MNDWI": 0.5}) is True    # MNDWI not counted (|d| <= 0.1)
    assert ccdc.matches_detector(region, {"NDVI": 0.4, "NDBI": 0.3, "MNDWI": 0}) is False
    assert ccdc.matches_detector({"dNDVI": 0.0}, {"NDVI": 0.4}) is None
    assert ccdc.main_index(region) == "NDVI" and ccdc.main_index({}) == "NDVI"


def test_attach_hides_locked_and_dates_matching():
    fc = {"features": [{"properties": {"id": "a", "dNDVI": -0.3}}, {"properties": {"id": "b"}}, {"properties": {"id": "c"}}]}
    data = {"locked": ["b"], "regions": {"a": {"detection": {"lasting": True, "share": 0.7, "break_month": "2020-05",
                                                             "magnitude": {"NDVI": -0.2, "NDBI": 0, "MNDWI": 0}},
                                               "monitoring": {"lasting": False, "break_month": "2025-01"}}}}
    a, b, c = (f["properties"] for f in ccdc.attach(fc, data)["features"])
    assert a["ccdc_month"] == "2020-05" and a["ccdc_matches"] is True and a["ccdc_again"] is False and a["ccdc_again_month"] is None
    assert b == {"id": "b", "ccdc_hidden": True} and c == {"id": "c"}


def test_harmonic_fit_and_series():
    import math
    t = [i / 24 for i in range(48)]
    coef = ccdc.harmonic_fit(t, [0.3 + 0.1 * math.cos(2 * math.pi * x) for x in t])
    assert [round(v, 3) for v in coef] == [0.3, 0.0, 0.1, 0.0]
    assert ccdc.harmonic_fit([0, 1], [1, 2]) is None
    month = 30 * 86_400_000
    looks = [{"t": ccdc.ms_of("2019-01-01") + i * month, "NDVI": 0.8 if i < 12 else 0.3} for i in range(24)]
    s = ccdc.series_result(looks, "2020-01")
    assert len(s["curves"]) == 2 and all(s["curves"]) and s["change_window"][1] == "2020-01"
    assert ccdc.series_result(looks, None)["curves"][0] and ccdc.series_result(looks, None)["change_window"] is None


def test_ccdc_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from webapp.backend import main
    c = TestClient(main.app)
    monkeypatch.setattr(main, "_ccdc_regions", lambda: None)
    assert c.get("/api/ccdc/regions/r1").status_code == 404
    fc = main.data_store.get_change_regions(None)
    rid = fc["features"][0]["properties"]["id"]
    data = {"params": {}, "locked": ["rX"], "regions": {rid: {"detection": {"lasting": True, "share": 0.6, "break_month": "2020-01",
                                                                       "magnitude": {"NDVI": -0.1, "NDBI": 0.1, "MNDWI": 0}},
                                                         "monitoring": {"lasting": False}}}}
    monkeypatch.setattr(main, "_ccdc_regions", lambda: data)
    monkeypatch.setattr(main, "CCDC_SERIES_DIR", tmp_path)
    looks = [{"t": ccdc.ms_of("2019-01-01") + i * 30 * 86_400_000, "NDVI": 0.5, "NDBI": 0.1 * (i > 12), "MNDWI": 0.0} for i in range(30)]
    (tmp_path / f"{rid}.json").write_text(json.dumps(looks))
    assert c.get("/api/ccdc/regions/rX").status_code == 403
    body = c.get(f"/api/ccdc/regions/{rid}").json()
    assert body["series"]["break_month"] == "2020-01" and len(body["series"]["looks"]) == 30
    regions = c.get("/api/data/change_regions").json()["features"]
    assert next(f for f in regions if f["properties"]["id"] == rid)["properties"]["ccdc_month"] == "2020-01"
