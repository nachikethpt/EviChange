"""Gated report arm (agents/gated.py), box evidence (agents/site_evidence.py) and the development
runner (scripts/report_dev.py), with fake model servers; no GPU, no Earth Engine."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import report_dev as rd  # noqa: E402
from agents import gated, site_evidence as se, vlm_check  # noqa: E402
from webapp.backend.report import build_report  # noqa: E402


def square(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def feature(rid, geom, dndvi=-0.3, dndbi=0.0, conf=0.4, **extra):
    return {"geometry": geom, "properties": {"id": rid, "area_ha": 99.0, "mean_conf": conf, "dNDVI": dndvi, "dNDBI": dndbi,
                                             "dMNDWI": 0.0, "location": "north", **extra}}


BOX = (107.30, 21.00, 107.31, 21.01)


# ---------- site evidence ----------
def test_evidence_is_cut_to_the_box():
    holed = {"type": "Polygon", "coordinates": [
        [[107.29, 21.005], [107.303, 21.005], [107.303, 21.02], [107.29, 21.02], [107.29, 21.005]],
        [[107.300, 21.006], [107.302, 21.006], [107.302, 21.008], [107.300, 21.008], [107.300, 21.006]]]}
    feats = [feature("r1", square(107.305, 20.99, 107.32, 21.02)), feature("r2", holed),
             feature("r3", square(107.40, 21.0, 107.41, 21.01))]
    ev = se.site_evidence(BOX, feats, ["a", "b"], ["c", "d"], "test", "p")
    box_ha = se.box_area_m2(BOX) / 10_000
    got = {r["id"]: r for r in ev["regions"]}
    assert set(got) == {"r1", "r2"}                                      # r3 is outside
    assert got["r1"]["area_ha"] == pytest.approx(box_ha / 2, rel=1e-3) and got["r1"]["location"] == "east"
    assert got["r2"]["area_ha"] == pytest.approx(box_ha * 0.11, rel=1e-3) and got["r2"]["location"] == "north-west"
    assert got["r1"]["area_ha_whole_region"] == 99.0 and got["r1"]["dNDVI"] == -0.3     # region fields kept
    assert ev["change_frac"] == pytest.approx(0.61, abs=1e-3)


def test_empty_box_has_no_regions():
    ev = se.site_evidence(BOX, [feature("r3", square(107.40, 21.0, 107.41, 21.01))], ["a", "b"], ["c", "d"], "t", "p")
    assert ev["regions"] == [] and ev["change_frac"] == 0


def test_sliver_under_one_pixel_is_not_an_overlap():
    """Less than MIN_INSIDE_M2 (one 10 m pixel) inside the box doesn't count: no region, change_frac 0."""
    sliver = feature("r4", square(107.31 - 0.00005, 21.002, 107.32, 21.0021))     # ~5 m x 11 m inside
    ev = se.site_evidence(BOX, [sliver], ["a", "b"], ["c", "d"], "t", "p")
    assert se.inside_part(sliver["geometry"], BOX)[0] > 0
    assert ev["regions"] == [] and ev["change_frac"] == 0


def test_reversed_ring_gives_the_same_area():
    ring = square(107.302, 21.002, 107.304, 21.004)["coordinates"][0]
    cw = {"type": "Polygon", "coordinates": [ring[::-1]]}
    assert se.inside_part(cw, BOX)[0] == pytest.approx(se.inside_part(square(107.302, 21.002, 107.304, 21.004), BOX)[0])


# ---------- prompt and parsing ----------
EV = {"pair_id": "p", "dates": [["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]], "source": "t",
      "change_frac": 0.31, "regions": [{"id": "r200", "area_ha": 12.795, "location": "centre", "mean_conf": 0.4123,
                                        "dNDVI": -0.31234, "dNDBI": 0.21, "dMNDWI": 0.0, "class_before": "trees",
                                        "class_after": "bare", "area_ha_whole_region": 40.0}]}


def test_prompt_carries_the_evidence_not_the_whole_region():
    p = gated.build_prompt(EV, *EV["dates"])
    assert '"r200"' in p and "-0.312" in p and '"trees"' in p and "12.795" in p
    assert "area_ha_whole_region" not in p and "40.0" not in p
    assert "Never say what caused the change" in p and "SWIR false colour" in p          # rules + the same images as ungated


GOOD = json.dumps({"claims": [
    {"level": "L1", "type": "presence", "text": "Change was detected in the box.", "region_ref": None, "evidence_ref": ["change_frac"]},
    {"level": "L3", "type": "change_type", "text": "Region r200 lost vegetation (dNDVI -0.31).", "region_ref": "r200",
     "evidence_ref": ["dNDVI"], "change_type": "vegetation_loss"},
    {"level": "L9", "type": "presence", "text": "Bad level.", "region_ref": None, "evidence_ref": []},
    {"level": "L2", "type": "extent", "text": "", "region_ref": None, "evidence_ref": []}],
    "abstain": [{"topic": "cause", "reason": "not in the evidence"}, {"reason": "no topic"}]})


def test_parse_drops_bad_items_and_keeps_abstentions():
    claims, abstain, ok, dropped = gated.parse_report("Sure!\n" + GOOD)
    assert ok and dropped == 2 and [c["claim_id"] for c in claims] == ["c1", "c2"]
    assert claims[1]["change_type"] == "vegetation_loss" and claims[1]["region_ref"] == "r200"
    assert abstain == [{"topic": "cause", "reason": "not in the evidence"}]
    assert gated.parse_report("no json here") == ([], [], False, 0)
    assert gated.parse_report('{"abstain": []}')[2] is False                      # no claims list


def test_build_report_verifies_real_gated_claims():
    out = {"raw": GOOD, "model": "Qwen/Qwen2.5-VL-7B-Instruct", "claims": gated.parse_report(GOOD)[0],
           "abstain": [{"topic": "cause", "reason": "x"}], "parse_ok": True, "dropped": 2, "prompt_version": gated.PROMPT_VERSION}
    rep = build_report(EV, "gated", gated=out)
    assert rep["model"].startswith("Qwen") and rep["dropped"] == 2 and rep["abstain"][0]["topic"] == "cause"
    assert [c["verdict"] for c in rep["claims"]] == ["supported", "supported"]
    assert build_report(EV, "gated")["model"] == "demo (no AI yet)"                 # without output: the stand-in


# ---------- development runner ----------
class FakeVLM:
    """Answers each prompt kind: gated JSON, ungated free text, extractor JSON list."""
    mode = "http"

    def __init__(self):
        self.calls = []

    def status(self):
        return {"available": True, "mode": "http", "model": "Qwen/Qwen2.5-VL-7B-Instruct", "detail": ""}

    def generate(self, prompt, images, max_new_tokens=400, replay_key=None):
        self.calls.append(replay_key)
        if prompt.startswith("You are writing a short change report"):
            no_regions = '"regions": []' in prompt
            claim = ({"level": "L1", "type": "presence", "text": "No change was detected in the box.", "region_ref": None,
                      "evidence_ref": ["change_frac"]} if no_regions else
                     {"level": "L1", "type": "presence", "text": "Change was detected in the box.", "region_ref": None,
                      "evidence_ref": ["change_frac"]})
            text = json.dumps({"claims": [claim], "abstain": [{"topic": "cause", "reason": "not in evidence"}]})
        elif prompt.startswith("Split the satellite change report"):
            text = json.dumps([{"text": "Forest was cleared for a mine.", "level": "L4", "type": "cause"}])
        else:
            text = "Forest was cleared for a mine."
        return {"text": text, "model": "Qwen/Qwen2.5-VL-7B-Instruct"}


@pytest.fixture
def dev_env(tmp_path, monkeypatch):
    """Two detected development regions and one control, no labelled sites, chips rendered by a fake."""
    feats = [{"type": "Feature", "geometry": square(107.25, 21.0, 107.252, 21.002),
              "properties": {"id": "r1", "area_ha": 4.0, "mean_conf": 0.5, "dNDVI": -0.3, "dNDBI": 0.0, "dMNDWI": 0.0, "location": "west"}},
             {"type": "Feature", "geometry": square(107.26, 21.0, 107.262, 21.002),
              "properties": {"id": "r2", "area_ha": 4.0, "mean_conf": 0.5, "dNDVI": 0.3, "dNDBI": 0.0, "dMNDWI": 0.0, "location": "west"}}]
    meta = {"aoi": square(107.2, 20.9, 107.5, 21.2), "before_window": ["2018-11-01", "2019-03-31"],
            "after_window": ["2022-11-01", "2023-03-31"], "thresholds": {"max_cloud_pct": 30}, "code_version": "t"}
    (tmp_path / "regions.json").write_text(json.dumps({"type": "FeatureCollection", "metadata": meta, "features": feats}))
    (tmp_path / "sample.json").write_text(json.dumps({"ids": ["r1", "r2"]}))
    ctrl = {"type": "Feature", "geometry": square(107.35, 21.05, 107.352, 21.052),
            "properties": {"id": "c1", "control": True, "area_ha": 0.0, "mean_conf": 0.0, "dNDVI": 0.0, "dNDBI": 0.0,
                           "dMNDWI": 0.0, "location": "centre"}}
    (tmp_path / "controls.json").write_text(json.dumps({"type": "FeatureCollection", "features": [ctrl]}))
    import vlm_batch
    monkeypatch.setattr(vlm_batch, "REGIONS", tmp_path / "regions.json")
    monkeypatch.setattr(vlm_batch, "SAMPLE", tmp_path / "sample.json")
    monkeypatch.setattr(vlm_batch, "CONTROLS", tmp_path / "controls.json")
    monkeypatch.setattr(vlm_batch, "CHIP_DIR", tmp_path / "chips")
    monkeypatch.setattr(vlm_check, "_site_boxes", [])
    render = lambda aoi, bw, aw, cloud, box, kinds: {f"{w}_{k}": b"png" for k in kinds for w in ("before", "after")}
    return tmp_path, render


def test_dev_run_all_arms_then_resume(dev_env):
    tmp, render = dev_env
    log = tmp / "reports.jsonl"
    vlm = FakeVLM()
    quiet = dict(log=lambda *_: None, sleep=lambda *_: None)
    assert rd.run(vlm, list(rd.ARMS), log_path=log, render=render, **quiet) == {"done": 9, "skipped": 0, "failed": 0}
    recs = rd.read_log(log)
    by = {(r["arm"], r["box_id"]): r for r in recs}
    assert by[("gated", "c1")]["evidence"]["regions"] == [] and by[("gated", "c1")]["claims"][0]["verdict"] == "supported"
    assert by[("gated", "r1")]["evidence"]["regions"][0]["location"] == "centre"         # box-relative (option A)
    assert by[("ungated", "r1")]["claims"][0]["verdict"] == "unsupported"                  # L4: beyond evidence
    assert by[("template", "r1")]["model"] == "rules"
    assert len(vlm.calls) == 3 + 2 * 3                                                       # gated 3, ungated 2 x 3
    assert rd.run(vlm, list(rd.ARMS), log_path=log, render=render, **quiet)["skipped"] == 9
    text = rd.summary(recs)
    assert "| gated | Qwen2.5-VL-7B-Instruct | gated_report_v6 | control | 1 |" in text
    assert "ungated: beyond_evidence × 3" in text
    assert "No change was detected" in rd.show(recs, "c1")


def test_claims_change():
    assert rd.claims_change({"claims": [{"level": "L1", "text": "No change was detected in the box."}]}) is False
    assert rd.claims_change({"claims": [{"level": "L1", "text": "Change occurred."}]}) is True
    assert rd.claims_change({"claims": [{"level": "L4", "text": "It is a mine."}]}) is False
    assert rd.claims_change({"claims": [{"level": "L3", "text": "Vegetation loss."}]}) is True


# ---------- shoreline / coastal claims (D13) ----------
COAST_EV = {
    "change_frac": 0.02,
    "regions": [{"id": "r1", "area_ha": 182.4, "mean_conf": 0.86, "dNDVI": -0.34, "dNDBI": 0.21, "dMNDWI": -0.03,
                 "location": "north-east", "class_before": "trees", "class_after": "bare"}],
    "transects": [
        {"id": "t0001", "location": "north-east", "change": "advancing", "nsm": 42.0, "lrr": 21.5, "ci95": 6.0},
        {"id": "t0004", "location": "west", "change": "unconfirmed", "nsm": -35.0, "lrr": -17.0, "ci95": 9.0},
    ],
    "coastal_strips": [
        {"strip": "0-200", "built_ha_before": 12.0, "built_ha_after": 15.1},
        {"strip": "200-500", "built_ha_before": 30.0, "built_ha_after": 30.2},
    ],
}


def test_prompt_offers_coast_claim_types_only_with_coast_evidence():
    """gated_report_v1+: shoreline / coastal_built (and their fields) only when the box has transects / strips."""
    p = gated.build_prompt({"change_frac": 0.0, "regions": []}, ["a", "b"], ["c", "d"])
    assert "shoreline" not in p and "coastal_built" not in p and "built_ha_before" not in p and "{" + "coast" not in p
    shore_only = gated.build_prompt({**COAST_EV, "coastal_strips": []}, ["a", "b"], ["c", "d"])
    assert "transect_ref" in shore_only and '"t0001"' in shore_only and "coastal_built" not in shore_only
    assert "ci95" not in shore_only                                        # not shown to the model
    both = gated.build_prompt(COAST_EV, ["a", "b"], ["c", "d"])
    assert "coastal_built" in both and "7. Make coastal_built claims" in both
    strips_only = gated.build_prompt({**COAST_EV, "transects": []}, ["a", "b"], ["c", "d"])
    assert "6. Make coastal_built claims" in strips_only and "transect_ref" not in strips_only


def test_parser_keeps_coast_fields():
    answer = json.dumps({"claims": [
        {"text": "At transect t0001 the shoreline moved about 42 m seaward.", "level": "L2", "type": "shoreline",
         "transect_ref": "t0001", "shoreline_change": "advancing", "evidence_ref": ["change", "nsm"]},
        {"text": "Built area within 200 m of the shore grew by about 3 ha.", "level": "L2", "type": "coastal_built",
         "strip": "0-200", "evidence_ref": ["built_ha_before", "built_ha_after"]}], "abstain": []})
    claims, _, ok, dropped = gated.parse_report(answer)
    assert ok and dropped == 0 and claims[0]["transect_ref"] == "t0001" and claims[1]["strip"] == "0-200"
    rep = build_report(COAST_EV, "gated", gated={"raw": answer, "model": "m", "claims": claims, "abstain": [],
                                                 "parse_ok": True, "dropped": 0, "prompt_version": gated.PROMPT_VERSION})
    assert rep["counts"] == {"supported": 2, "unsupported": 0, "uncertain": 0}


def test_template_states_the_coast_and_the_verifier_agrees():
    from webapp.backend.report import template_claims
    coast = [c for c in template_claims(COAST_EV) if c["type"] in ("shoreline", "coastal_built")]
    assert [c["type"] for c in coast] == ["shoreline", "coastal_built", "coastal_built"]   # unconfirmed transect: no claim
    rep = build_report(COAST_EV, "template")
    assert all(c["verdict"] == "supported" for c in rep["claims"] if c["type"] in ("shoreline", "coastal_built"))
    no_regions = template_claims({**COAST_EV, "regions": []})
    assert no_regions[0]["type"] == "presence" and len(no_regions) == 4


def test_demo_gated_abstains_on_unconfirmed_shoreline():
    rep = build_report(COAST_EV, "gated")
    assert any("t0004" in a["topic"] for a in rep["abstain"])


# ---------- shoreline between the box's own windows (D13 / D16) ----------
def test_window_stats_confirms_with_the_optical_shift():
    from agents import shoreline as sh
    assert sh.window_stats(10, 60, 0, 40, 4.0)["change"] == "advancing"
    assert sh.window_stats(10, 60, 0, 5, 4.0)["change"] == "unconfirmed"          # optical doesn't follow
    st = sh.window_stats(60, 10, None, None, 4.0)
    assert st["change"] == "unconfirmed" and st["nsm"] == -50 and st["lrr"] == -12.5 and st["ci95"] is None
    assert sh.window_stats(10, 25, 0, 0, 4.0)["change"] == "stable"
    assert sh.window_stats(None, 25, 0, 0, 4.0)["change"] == "too_few"
    assert sh.window_years(["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]) == pytest.approx(4.0, abs=0.01)


def test_box_evidence_takes_transects_only_from_the_same_windows(tmp_path, monkeypatch):
    from agents import shoreline as sh
    from agents.schema import validate_evidence
    tr = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "t0001", "geometry": {"type": "LineString", "coordinates": [[107.305, 21.012], [107.305, 20.998]]},
         "properties": {"id": "t0001"}},
        {"type": "Feature", "id": "t0002", "geometry": {"type": "LineString", "coordinates": [[107.5, 21.012], [107.5, 21.002]]},
         "properties": {"id": "t0002"}}]}
    (tmp_path / "transects.geojson").write_text(json.dumps(tr))
    win = [["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]]
    stats = {"windows": win, "transects": {"t0001": sh.window_stats(0, 50, 0, 45, 4.0), "t0002": sh.window_stats(0, 0, 0, 0, 4.0)}}
    (tmp_path / sh.windows_file(*win).name).write_text(json.dumps(stats))
    monkeypatch.setattr(sh, "SHORELINE_DIR", tmp_path)
    se._coast_cache.clear()
    ev = se.site_evidence(BOX, [], *win, "t", "p")
    assert ev["transects"] == [{"id": "t0001", "location": "centre", "change": "advancing", "nsm": 50, "lrr": 12.5, "ci95": None}]
    assert validate_evidence(ev) == []
    assert "transects" not in se.site_evidence(BOX, [], ["2018-12-01", "2019-03-31"], win[1], "t", "p")   # other windows
    assert "transects" not in se.site_evidence(BOX, [], *win, "t", "p", coast=False)
    far = se.site_evidence((107.0, 20.0, 107.01, 20.01), [], *win, "t", "p")
    assert far["transects"] == []                                               # run exists, no coast in this box
    se._coast_cache.clear()
