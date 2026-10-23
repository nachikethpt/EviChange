"""scripts/vlm_compare.py on a hand-made answer log."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vlm_compare as vc  # noqa: E402

BW, AW = ["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]


def rec(region, model, chips, verdict, agreement, types=(), seconds=20.0, raw=None):
    return {"key": f"{region}{model}{chips}", "region_id": region, "model": model, "chips": chips,
            "prompt_version": "vlmcheck_v1" if chips == "rgb_swir" else f"vlmcheck_v1_{chips}",
            "verdict": verdict, "agreement": agreement, "change_types": list(types), "parse_ok": True,
            "seconds": seconds, "before_window": BW, "after_window": AW,
            "raw": raw or json.dumps({"verdict": verdict})}


Q25, Q3 = "Qwen/Qwen2.5-VL-7B-Instruct", "Qwen/Qwen3-VL-8B-Instruct"
LOG = [rec("r1", Q25, "rgb_swir", "no_change", "disagrees"),           # superseded by the next line
       rec("r1", Q25, "rgb_swir", "change", "agrees", ["vegetation_loss"]),
       rec("r2", Q25, "rgb_swir", "no_change", "disagrees"),
       rec("r1", Q3, "rgb_swir", "change", "agrees", ["vegetation_loss"]),
       rec("r2", Q3, "rgb_swir", "change", "partly", ["water_increase"]),
       rec("r3", Q3, "rgb", "unsure", "unsure")]


def test_latest_answer_per_condition_and_region():
    checks = vc.latest(LOG)
    assert len(checks) == 5
    assert checks[("Qwen2.5-VL-7B-Instruct · rgb_swir", "r1", tuple(BW), tuple(AW))]["verdict"] == "change"


def test_report_tables():
    text = vc.report(LOG, with_regions=True)
    assert "5 checks, 3 regions" in text
    assert "| Qwen2.5-VL-7B-Instruct · rgb_swir | 2 | 1 (50%) | 1 (50%) | 0 (0%) |" in text
    # Qwen2.5 vs Qwen3 on rgb_swir: r1 same, r2 different
    assert "| Qwen2.5-VL-7B-Instruct · rgb_swir | Qwen3-VL-8B-Instruct · rgb_swir | 2 | 1 (50%) | 1 (50%) |" in text
    assert "| r2 | ✗ no change |  | ≈ change: water_increase |" in text


def test_empty_log():
    assert "No Geo-VLM answers logged yet" in vc.report([])


def test_replay_file_for_one_condition():
    out = vc.replay_file(LOG, "Qwen3-VL-8B-Instruct · rgb_swir")
    assert set(out) == {"vlmcheck_v1:r1", "vlmcheck_v1:r2"} and json.loads(out["vlmcheck_v1:r2"])["verdict"] == "change"


# ---------- D15 dev report ----------
REGIONS = {"r1": {"class_before": "trees", "class_after": "bare"},      # Dynamic World changed
           "r2": {"class_before": "water", "class_after": "water"},     # unchanged
           "r3": {"class_before": None, "class_after": "built"}}        # unknown


def test_dw_reference():
    text = vc.dw_reference(vc.latest(LOG), REGIONS)
    # Qwen2.5 rgb_swir: r1 change (DW changed: hit), r2 no_change (DW same: hit)
    assert "| Qwen2.5-VL-7B-Instruct · rgb_swir | 2 | 1 (100%) | 1 (100%) | 2 (100%) |" in text
    # Qwen3 rgb_swir: r1 hit, r2 change on unchanged DW: miss; r3 (rgb) has no DW classes so it's left out
    assert "| Qwen3-VL-8B-Instruct · rgb_swir | 2 | 1 (100%) | 0 (0%) | 1 (50%) |" in text
    assert "rgb |" not in text.replace("rgb_swir", "")


def test_stability_across_image_sets():
    log = LOG + [rec("r1", Q25, "rgb", "change", "agrees"), rec("r2", Q25, "rgb", "change", "change_only")]
    text = vc.stability(vc.latest(log))
    assert "| Qwen2.5-VL-7B-Instruct | rgb, rgb_swir | 2 | 1 (50%) |" in text
    assert "Qwen3" not in text                     # Qwen3 has no region under both of its sets


def test_disagreements_and_adjudication():
    dis = vc.disagreements(vc.latest(LOG))
    assert [(d["region_id"], d["chips"]) for d in dis] == [("r2", "rgb_swir")]
    assert dis[0]["answers"] == {"Qwen2.5-VL-7B-Instruct": "no_change", "Qwen3-VL-8B-Instruct": "change"}
    text = vc.adjudicated(vc.latest(LOG), {"r2": "no_change"})
    assert "| Qwen2.5-VL-7B-Instruct · rgb_swir | 1 | 1 (100%) |" in text
    assert "| Qwen3-VL-8B-Instruct · rgb_swir | 1 | 0 (0%) |" in text


def test_dev_report_only_counts_the_sample():
    text = vc.dev_report(LOG, ["r1"], REGIONS)
    assert "2 checks on 1 of 1 development regions" in text      # r1 under Qwen2.5 and Qwen3, rgb_swir
    assert "## Model disagreements to look at (0)" in text
    assert "No answers on the development sample yet" in vc.dev_report(LOG, ["r9"], REGIONS)


def test_adjudication_sheet_is_blind():
    dis = vc.disagreements(vc.latest(LOG))
    page = vc.adjudication_sheet(dis, {"r2": {"before_rgb": b"png1", "after_rgb": b"png2"}})
    assert "r2" in page and page.count("<img") == 2 and 'value="no_change"' in page
    for leak in ("Qwen", "no change\"", "disagrees", "reason"):
        assert leak not in page                                  # no model names or answers on the page
