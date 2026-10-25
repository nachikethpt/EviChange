"""eval/metrics.py: the statistics against known values, and the report on a small synthetic study."""
import io
import itertools
import math

import pytest

from eval import metrics as m


def test_wilson_known_values():
    rate, lo, hi = m.wilson(5, 10)
    assert rate == 0.5 and lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    assert m.wilson(0, 0) == (None, None, None)
    assert m.wilson(0, 20)[1] == 0.0


def test_cohen_kappa():
    # 20 items: 15 agree; marginals a = 10 / 10, b = 9 / 11
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 7 + ["n"] * 3 + ["y"] * 2 + ["n"] * 8
    pe = 0.5 * 9 / 20 + 0.5 * 11 / 20
    assert m.cohen_kappa(a, b) == pytest.approx((0.75 - pe) / (1 - pe))
    assert m.cohen_kappa(["y", "y"], ["y", "y"]) is None
    with pytest.raises(ValueError):
        m.cohen_kappa(["y"], [])


def test_sign_test_exact():
    assert m.sign_test([1] * 9 + [-1] + [0, 0]) == (9, 1, pytest.approx(2 * 11 / 1024))
    assert m.sign_test([0, 0]) == (0, 0, None)


def _brute_wilcoxon_p(d):
    d = [x for x in d if x]
    ranks = {}
    absd = sorted(abs(x) for x in d)
    for v in set(absd):
        idx = [i + 1 for i, x in enumerate(absd) if x == v]
        ranks[v] = sum(idx) / len(idx)
    r = [ranks[abs(x)] for x in d]
    w = sum(ri for ri, x in zip(r, d) if x > 0)
    total = sum(r)
    lo = min(w, total - w)
    hits = sum(sum(ri for ri, s in zip(r, signs) if s) <= lo + 1e-9 for signs in itertools.product([0, 1], repeat=len(d)))
    return w, min(1.0, 2 * hits / 2 ** len(d))


@pytest.mark.parametrize("diffs", [
    [1, 2, 3, 4, 5],
    [1, 2, 3, 4, 5, 6],
    [1, 1, -1, 2, 0, 3, -2],         # ties and a zero
    [-0.5, 0.25, 0.25, 1.0, -1.0, 2.0, 0.75, 0.75],
])
def test_wilcoxon_matches_brute_force(diffs):
    assert m.wilcoxon_signed_rank(diffs) == pytest.approx(_brute_wilcoxon_p(diffs))


def test_wilcoxon_textbook():
    assert m.wilcoxon_signed_rank([1, 2, 3, 4, 5])[1] == pytest.approx(0.0625)
    assert m.wilcoxon_signed_rank([]) == (None, None)


def test_cluster_bootstrap_brackets_rate():
    clusters = {f"s{i}": (i % 3, 3) for i in range(30)}
    rate, lo, hi = m.cluster_bootstrap(clusters, reps=2000)
    assert rate == pytest.approx(30 / 90)
    assert lo < rate < hi
    assert m.cluster_bootstrap({"s1": (0, 0)}) == (None, None, None)
    assert m.cluster_bootstrap(clusters, reps=500) == m.cluster_bootstrap(clusters, reps=500)   # seeded


# ---------- a synthetic study: 4 sites, gated is right more often than ungated ----------
KEY = {"s1": {"origin": "detected", "region_id": "r1"}, "s2": {"origin": "detected", "region_id": "r2"},
       "s3": {"origin": "random", "region_id": None}, "s4": {"origin": "random", "region_id": None}}
LABELS = {"s1": {"change_occurred": "yes", "change_types": ["vegetation_loss"]},
          "s2": {"change_occurred": "no", "change_types": []},
          "s3": {"change_occurred": "yes", "change_types": ["water_increase"]},
          "s4": {"change_occurred": "unsure", "change_types": []}}


def c(site, cond, truth, support, verdict, ctype="change_type", text="Vegetation loss here."):
    return {"site_id": site, "condition": cond, "claim_id": f"{site}{cond}{truth}", "type": ctype, "level": "L3",
            "text": text, "truth": truth, "support": support, "verdict": verdict}


CLAIMS = [
    c("s1", "gated", "true", "supported", "supported"),
    c("s1", "ungated", "true", "unsupported", "supported"),
    c("s1", "ungated", "false", "unsupported", "unsupported", text="Mining caused this."),
    c("s2", "ungated", "unverifiable", "unsupported", "supported", ctype="cause"),
    c("s2", "gated", "false", "supported", "supported"),
    c("s3", "ungated", "false", "unsupported", "supported", ctype="shoreline", text="The shoreline advanced."),
]
RUNS = [{"site_id": s, "condition": cond, "n_claims": sum(x["site_id"] == s and x["condition"] == cond for x in CLAIMS),
         "n_parse_failures": 1 if (s, cond) == ("s4", "ungated") else 0}
        for s in KEY for cond in ("gated", "ungated")]


def test_claim_rates():
    gated = [x for x in CLAIMS if x["condition"] == "gated"]
    r = m.claim_rates(gated, KEY, reps=200)
    assert r["hallucination"][0] == 0.5
    assert r["post_gate_hallucination"][0] == 0.5
    assert r["faithful_but_false"][0] == 0.5
    assert r["unsupported"][0] == 0.0
    ungated = [x for x in CLAIMS if x["condition"] == "ungated"]
    r = m.claim_rates(ungated, KEY, reps=200)
    assert r["hallucination"][0] == 0.75
    assert r["post_gate_hallucination"][0] == pytest.approx(2 / 3)
    assert r["n_passed"] == 3


def test_verifier_scores():
    v = m.verifier_scores(CLAIMS)
    assert v["catch_rate"][0] == 0.25          # 4 hallucinated claims, 1 rejected
    assert v["precision"][0] == 1.0


def test_informativeness_and_detector():
    gated = [x for x in CLAIMS if x["condition"] == "gated"]
    inf = m.informativeness(gated, [r for r in RUNS if r["condition"] == "gated"], LABELS)
    assert inf["true_claims_per_site"] == 0.25
    assert inf["change_type_recall"] == 0.5       # s1 named, s3 not
    assert inf["abstention"][0] == 0.5            # s3, s4
    det = m.detector_scores(LABELS, KEY)
    assert det["precision"][0] == 0.5 and det["background_change_rate"][0] == 1.0 and det["random_unsure"] == 1
    assert m.parse_failure_rate([r for r in RUNS if r["condition"] == "ungated"])[0] == pytest.approx(1 / 5)


def test_report_and_comparison():
    rep = m.report(CLAIMS, RUNS, LABELS, KEY, reps=200)
    assert set(rep["conditions"]) == {"gated", "ungated"}
    prim = rep["comparisons"]["primary"]
    assert prim["sites"] == 4 and prim["a_fewer_on"] == 1 and prim["b_fewer_on"] == 0   # post-gate: s3 gated fewer, s2 a tie
    assert "secondary_d16" not in rep["comparisons"]
    assert set(rep["conditions"]["ungated"]["by_claim_type"]) == {"change_type", "cause", "shoreline"}
    assert rep["conditions"]["gated"]["detected"]["n_claims"] == 2
    out = io.StringIO()
    m.print_report(rep, out=out)
    assert out.getvalue()


def test_claim_records_are_checked():
    assert m.check_claim(CLAIMS[0]) == []
    assert m.check_claim({**CLAIMS[0], "truth": "maybe"})
    assert m.check_claim({**CLAIMS[0], "condition": "gpt5"})


# ---------- extraction accuracy ----------
def test_shoreline_rmse_and_pairs():
    positions = {"months": ["2024-10", "2026-09"], "positions": {"t1": [10.0, None], "t2": [0.0, 30.0]}}
    labels = [{"transect_id": "t1", "month": "2024-10", "status": "edge", "pos_m": 6.0},
              {"transect_id": "t1", "month": "2026-09", "status": "edge", "pos_m": 5.0},     # no extracted position
              {"transect_id": "t2", "month": "2026-09", "status": "edge", "pos_m": 33.0},
              {"transect_id": "t2", "month": "2024-10", "status": "not_visible", "pos_m": None}]
    pairs = m.shoreline_pairs(labels, positions)
    assert pairs == [(6.0, 10.0), (33.0, 30.0)]
    r = m.shoreline_rmse(pairs)
    assert r["rmse_m"] == pytest.approx(math.sqrt((16 + 9) / 2)) and r["bias_m"] == 0.5


def test_class_agreement():
    regions = {"r1": {"class_before": "trees", "class_after": "bare"}, "r2": {"class_before": "crops", "class_after": "built"}}
    labels = [{"site_id": "s1", "class_before": "trees", "class_after": "bare"},
              {"site_id": "s2", "class_before": "crops", "class_after": "crops"},
              {"site_id": "s3", "class_before": "water", "class_after": "water"}]       # random site: no DW region
    r = m.class_agreement(labels, regions, KEY)
    assert r["n"] == 2 and r["dropped"] == 1
    assert r["before"]["agreement"][0] == 1.0 and r["transition"]["agreement"][0] == 0.5


def test_built_and_change_month():
    b = m.built_accuracy([("built", True), ("not_built", True), ("unsure", False), ("not_built", False)])
    assert b["n"] == 3 and b["accuracy"][0] == pytest.approx(2 / 3)
    cm = m.change_month_agreement([(["2025-03", "2025-06"], ["2025-04", "2025-07"]),
                                   (["2025-01", "2025-02"], ["2025-09", "2025-10"])])
    assert cm["within_1_month"][0] == 0.5 and cm["windows_overlap"][0] == 0.5
