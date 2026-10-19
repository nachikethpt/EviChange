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
