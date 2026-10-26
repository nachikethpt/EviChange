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
