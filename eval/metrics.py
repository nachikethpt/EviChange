"""Evaluation metrics (PLAN "Evaluation", Phase 5; D13 extension, Phase 15; D16 secondary arm).

Inputs are plain records, so the adjudication page (Phase 5) and the label notebooks only have to
write JSON lines in these shapes:

    adjudicated claim {site_id, condition, claim_id, type, level, text, [change_type],
                       verdict (the verifier's), truth: true / false / unverifiable,
                       support: supported / unsupported}        human axes, condition hidden
    run               {site_id, condition, n_claims, n_parse_failures}   one per site and condition,
                                                                          also when it emitted nothing
    label             labels_v1 records (Phase 3); key: sites_key.json (detected / random)

Claim-level rates are clustered within sites, so their 95 % CI is a site-level cluster bootstrap
(resample sites, BOOT_REPS reps, seeded). Wilson is only for site-level proportions (detector
precision, background change rate). Paired per-site comparisons use the exact Wilcoxon signed-rank
test and the exact sign test. Everything is pure Python, like the rest of the evaluation side.

    python -m eval.metrics claims.jsonl runs.jsonl      prints the per-condition tables
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from agents.schema import CLAIM_TYPES, REPORT_CONDITIONS
from agents.verifier import claimed_change_types

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_DIR = REPO_ROOT / "data" / "quangninh" / "labels"
BOOT_REPS = 10_000
SEED = 20261023
TRUTHS = ("true", "false", "unverifiable")
SUPPORTS = ("supported", "unsupported")


# ---------- statistics ----------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None, float | None]:
    """(rate, lo, hi) Wilson score interval; Nones when n is 0."""
    if n == 0:
        return None, None, None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, centre - half), min(1.0, centre + half)


def cohen_kappa(a: list, b: list) -> float | None:
    """Cohen's kappa of two raters over the same items; None when undefined (no items, or both
    raters gave one identical answer throughout)."""
    if len(a) != len(b):
        raise ValueError("raters must label the same items")
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe)


def cluster_bootstrap(clusters: dict[str, tuple[int, int]], reps: int = BOOT_REPS, seed: int = SEED
                      ) -> tuple[float | None, float | None, float | None]:
    """Pooled rate sum(k) / sum(n) over clusters {site: (k, n)} with a percentile 95 % CI from
    resampling sites with replacement. Resamples with no claims at all are skipped."""
    total_n = sum(n for _, n in clusters.values())
    if total_n == 0:
        return None, None, None
    rate = sum(k for k, _ in clusters.values()) / total_n
    sites = list(clusters.values())
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        k = n = 0
        for _ in sites:
            ck, cn = sites[rng.randrange(len(sites))]
            k += ck
            n += cn
        if n:
            draws.append(k / n)
    draws.sort()
    q = lambda f: draws[min(len(draws) - 1, max(0, int(round(f * (len(draws) - 1)))))]
    return rate, q(0.025), q(0.975)


def sign_test(diffs: Iterable[float]) -> tuple[int, int, float | None]:
    """(positives, negatives, exact two-sided p); zero differences are dropped."""
    pos = sum(d > 0 for d in diffs if d)
    neg = sum(d < 0 for d in diffs if d)
    n = pos + neg
    if n == 0:
        return 0, 0, None
    tail = sum(math.comb(n, i) for i in range(min(pos, neg) + 1)) / 2 ** n
    return pos, neg, min(1.0, 2 * tail)


def wilcoxon_signed_rank(diffs: Iterable[float]) -> tuple[float | None, float | None]:
    """(W+, exact two-sided p) of the Wilcoxon signed-rank test. Zeros are dropped; ties get mid-ranks
    and the exact null distribution is built over the doubled (integer) ranks, so it stays exact."""
    d = [x for x in diffs if x]
    n = len(d)
    if n == 0:
        return None, None
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks2 = [0] * n                      # 2 x rank: mid-ranks of ties stay integers
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks2[order[k]] = i + j + 2
        i = j + 1
    w2 = sum(r for r, x in zip(ranks2, d) if x > 0)
    total = sum(ranks2)
    counts = {0: 1}                       # distribution of the doubled W+ under H0
    for r in ranks2:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c
            nxt[s + r] += c
        counts = nxt
    lo = min(w2, total - w2)
    tail = sum(c for s, c in counts.items() if s <= lo) / 2 ** n
    return w2 / 2, min(1.0, 2 * tail)


# ---------- claims ----------
def hallucinated(claim: dict) -> bool:
    """Metric 1: false or unverifiable per ground truth."""
    return claim["truth"] in ("false", "unverifiable")


def passed(claim: dict) -> bool:
    """What a user sees: the verifier's verdict is supported."""
    return claim.get("verdict") == "supported"


def check_claim(claim: dict) -> list[str]:
    errs = [f"missing '{f}'" for f in ("site_id", "condition", "truth", "support") if f not in claim]
    if claim.get("condition") not in REPORT_CONDITIONS:
        errs.append(f"condition must be one of {REPORT_CONDITIONS}")
    if "truth" in claim and claim["truth"] not in TRUTHS:
        errs.append(f"truth must be one of {TRUTHS}")
    if "support" in claim and claim["support"] not in SUPPORTS:
        errs.append(f"support must be one of {SUPPORTS}")
    if claim.get("type") is not None and claim["type"] not in CLAIM_TYPES:
        errs.append(f"type must be one of {CLAIM_TYPES}")
    return errs


def _clusters(claims: list[dict], sites: Iterable[str], hit: Callable[[dict], bool],
              keep: Callable[[dict], bool] = lambda c: True) -> dict[str, tuple[int, int]]:
    out = {s: (0, 0) for s in sites}
    for c in claims:
        if keep(c):
            k, n = out.get(c["site_id"], (0, 0))
            out[c["site_id"]] = (k + hit(c), n + 1)
    return out


def claim_rates(claims: list[dict], sites: Iterable[str], reps: int = BOOT_REPS) -> dict:
    """Metrics 1-4 for one condition's claims, each (rate, lo, hi) with the cluster bootstrap CI.
    Sites with no claims are kept as empty clusters, so resampling sees them."""
    sites = list(sites)
    rate = lambda hit, keep=lambda c: True: cluster_bootstrap(_clusters(claims, sites, hit, keep), reps)
    return {
        "n_claims": len(claims),
        "hallucination": rate(hallucinated),
        "post_gate_hallucination": rate(hallucinated, passed),
        "n_passed": sum(map(passed, claims)),
        "unsupported": rate(lambda c: c["support"] == "unsupported"),
        "faithful_but_false": rate(lambda c: c["support"] == "supported" and c["truth"] == "false"),
    }


def verifier_scores(claims: list[dict]) -> dict:
    """Metric 5: catch rate (recall on hallucinated claims), precision of what it rejects, and kappa
    of supported / not against the human support axis."""
    rejected = [c for c in claims if not passed(c)]
    bad = [c for c in claims if hallucinated(c)]
    return {
        "catch_rate": wilson(sum(not passed(c) for c in bad), len(bad)),
        "precision": wilson(sum(hallucinated(c) for c in rejected), len(rejected)),
        "kappa_vs_support": cohen_kappa([passed(c) for c in claims], [c["support"] == "supported" for c in claims]),
    }


def informativeness(claims: list[dict], runs: list[dict], labels: dict[str, dict]) -> dict:
    """Metric 6: true claims per site, change-type recall per site (label types named by a true claim,
    over sites whose label has types), abstention rate (sites with no parsed claim)."""
    sites = [r["site_id"] for r in runs]
    true_by_site: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        if c["truth"] == "true":
            true_by_site[c["site_id"]].append(c)
    recalls = []
    for s in sites:
        wanted = set(labels.get(s, {}).get("change_types") or [])
        if wanted:
            named = set().union(*(claimed_change_types(c) for c in true_by_site[s])) if true_by_site[s] else set()
            recalls.append(len(wanted & named) / len(wanted))
    return {
        "true_claims_per_site": sum(len(true_by_site[s]) for s in sites) / len(sites) if sites else None,
        "change_type_recall": sum(recalls) / len(recalls) if recalls else None,
        "abstention": wilson(sum(r["n_claims"] == 0 for r in runs), len(runs)),
    }


def parse_failure_rate(runs: list[dict]) -> tuple[float | None, float | None, float | None]:
    """Metric 8: items that broke the claim schema, over all items the model produced."""
    fails = sum(r["n_parse_failures"] for r in runs)
    return wilson(fails, fails + sum(r["n_claims"] for r in runs))


def detector_scores(labels: dict[str, dict], key: dict[str, dict]) -> dict:
    """Metric 7: precision = detected sites labelled change; background change rate = random sites
    labelled change. Sites labelled unsure are left out of both and counted."""
    out = {}
    for origin, name in (("detected", "precision"), ("random", "background_change_rate")):
        answers = [labels[s]["change_occurred"] for s, k in key.items() if k["origin"] == origin and s in labels]
        sure = [a for a in answers if a in ("yes", "no")]
        out[name] = wilson(sure.count("yes"), len(sure))
        out[f"{origin}_unsure"] = len(answers) - len(sure)
    return out


def paired_comparison(claims_a: list[dict], claims_b: list[dict], sites: Iterable[str],
                      only_passed: bool = True) -> dict:
    """Per-site hallucination counts and rates, condition a minus condition b (the primary
    comparison is gated vs ungated, post-gate). Counts are compared on every site; rates only on
    sites where both conditions have claims, and the excluded sites are counted."""
    sites = list(sites)
    keep = passed if only_passed else (lambda c: True)
    ca, cb = _clusters(claims_a, sites, hallucinated, keep), _clusters(claims_b, sites, hallucinated, keep)
    count_d = [ca[s][0] - cb[s][0] for s in sites]
    both = [s for s in sites if ca[s][1] and cb[s][1]]
    rate_d = [ca[s][0] / ca[s][1] - cb[s][0] / cb[s][1] for s in both]
    a_better = sum(d < 0 for d in count_d)
    return {
        "sites": len(sites), "sites_with_rates": len(both), "sites_without_rates": len(sites) - len(both),
        "a_fewer_on": a_better, "b_fewer_on": sum(d > 0 for d in count_d),
        "count_wilcoxon": wilcoxon_signed_rank(count_d), "count_sign": sign_test(count_d),
        "rate_wilcoxon": wilcoxon_signed_rank(rate_d), "rate_sign": sign_test(rate_d),
        "mean_rate_diff": sum(rate_d) / len(rate_d) if rate_d else None,
    }


def by_claim_type(claims: list[dict], sites: Iterable[str], reps: int = BOOT_REPS) -> dict[str, dict]:
    """Hallucination and post-gate hallucination per claim type (D13)."""
    sites = list(sites)
    out = {}
    for t in sorted({c.get("type") or "other" for c in claims}):
        sub = [c for c in claims if (c.get("type") or "other") == t]
        out[t] = {"n": len(sub),
                  "hallucination": cluster_bootstrap(_clusters(sub, sites, hallucinated), reps),
                  "post_gate_hallucination": cluster_bootstrap(_clusters(sub, sites, hallucinated, passed), reps)}
    return out


# ---------- extraction accuracy (D13, D14; Phase 14 labels) ----------
def shoreline_rmse(pairs: Iterable[tuple[float, float]]) -> dict:
    """Reference vs extracted shoreline position (m, both in the positions.json frame) per transect
    and date: RMSE, mean bias (extracted - reference, seaward +) and n."""
    d = [ext - ref for ref, ext in pairs]
    if not d:
        return {"n": 0, "rmse_m": None, "bias_m": None}
    return {"n": len(d), "rmse_m": math.sqrt(sum(x * x for x in d) / len(d)), "bias_m": sum(d) / len(d)}


def shoreline_pairs(labels: list[dict], positions: dict) -> list[tuple[float, float]]:
    """(reference pos_m, extracted position) for label records with an edge, matched by transect and
    month in positions.json; months or transects without an extracted position are skipped."""
    months = positions["months"]
    out = []
    for rec in labels:
        if rec.get("status") != "edge" or rec["month"] not in months:
            continue
        ext = positions["positions"].get(rec["transect_id"], [None] * len(months))[months.index(rec["month"])]
        if ext is not None:
            out.append((rec["pos_m"], ext))
    return out


def class_agreement(labels: list[dict], regions: dict[str, dict], key: dict[str, dict]) -> dict:
    """Dynamic World vs the Phase 14 (a) labels at the detected sites: kappa and raw agreement for the
    before class, the after class and the transition. Sites with an unsure label or without DW
    classes are dropped and counted."""
    rows = []
    for rec in labels:
        rid = (key.get(rec["site_id"]) or {}).get("region_id")
        r = regions.get(rid) if rid else None
        if not r or r.get("class_before") is None or r.get("class_after") is None:
            continue
        if "unsure" in (rec["class_before"], rec["class_after"]):
            continue
        rows.append(((rec["class_before"], rec["class_after"]), (r["class_before"], r["class_after"])))
    out = {"n": len(rows), "dropped": len(labels) - len(rows)}
    for name, pick in (("before", lambda t: t[0]), ("after", lambda t: t[1]), ("transition", lambda t: t)):
        a, b = [pick(lab) for lab, _ in rows], [pick(dw) for _, dw in rows]
        out[name] = {"kappa": cohen_kappa(a, b), "agreement": wilson(sum(x == y for x, y in zip(a, b)), len(rows))}
    return out


def built_accuracy(pairs: Iterable[tuple[str, bool]]) -> dict:
    """Coastal cells: (label built / not_built / unsure, Dynamic World built) per cell and date.
    Accuracy and kappa over the sure labels."""
    rows = [(lab == "built", dw) for lab, dw in pairs if lab in ("built", "not_built")]
    return {"n": len(rows), "accuracy": wilson(sum(a == b for a, b in rows), len(rows)),
            "kappa": cohen_kappa([a for a, _ in rows], [b for _, b in rows])}


def _month_index(m: str) -> int:
    y, mm = map(int, m.split("-"))
    return y * 12 + mm - 1


def change_month_agreement(pairs: Iterable[tuple[list[str], list[str]]]) -> dict:
    """D14: (label change_window, CCDC change_month window), both [last month before, first month
    after]. Within +-1 month: the windows' first-after months differ by at most 1. Within window: the
    two windows overlap."""
    rows = list(pairs)
    near = sum(abs(_month_index(lab[1]) - _month_index(ccdc[1])) <= 1 for lab, ccdc in rows)
    overlap = sum(_month_index(lab[0]) < _month_index(ccdc[1]) and _month_index(ccdc[0]) < _month_index(lab[1])
                  for lab, ccdc in rows)
    return {"n": len(rows), "within_1_month": wilson(near, len(rows)), "windows_overlap": wilson(overlap, len(rows))}


# ---------- loading and the report ----------
def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def load_claims(path: Path) -> list[dict]:
    claims = read_jsonl(path)
    for i, c in enumerate(claims, 1):
        errs = check_claim(c)
        if errs:
            raise ValueError(f"{path}:{i}: {'; '.join(errs)}")
    return claims


def load_phase3(labeler_file: str = "labels_v1.jsonl") -> tuple[dict[str, dict], dict[str, dict]]:
    labels = {r["site_id"]: r for r in read_jsonl(LABELS_DIR / labeler_file)}
    key = json.loads((LABELS_DIR / "sites_key.json").read_text(encoding="utf-8"))
    return labels, key


def report(claims: list[dict], runs: list[dict], labels: dict[str, dict], key: dict[str, dict],
           reps: int = BOOT_REPS) -> dict:
    """All per-condition metrics, pooled and per stratum (detected / random), plus the pre-specified
    comparisons: gated vs ungated (primary) and gated vs ungated_gpt (secondary, D16)."""
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        by_cond[c["condition"]].append(c)
    runs_by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        runs_by_cond[r["condition"]].append(r)
    out: dict = {"detector": detector_scores(labels, key), "conditions": {}, "comparisons": {}}
    for cond in REPORT_CONDITIONS:
        if cond not in runs_by_cond:
            continue
        sites = [r["site_id"] for r in runs_by_cond[cond]]
        cl = by_cond[cond]
        strata = {}
        for origin in ("detected", "random"):
            ss = [s for s in sites if key.get(s, {}).get("origin") == origin]
            strata[origin] = claim_rates([c for c in cl if c["site_id"] in ss], ss, reps)
        out["conditions"][cond] = {"pooled": claim_rates(cl, sites, reps), **strata,
                                   "verifier": verifier_scores(cl),
                                   "informativeness": informativeness(cl, runs_by_cond[cond], labels),
                                   "parse_failures": parse_failure_rate(runs_by_cond[cond]),
                                   "by_claim_type": by_claim_type(cl, sites, reps)}
    for name, a, b in (("primary", "gated", "ungated"), ("secondary_d16", "gated", "ungated_gpt")):
        if a in runs_by_cond and b in runs_by_cond:
            common = sorted({r["site_id"] for r in runs_by_cond[a]} & {r["site_id"] for r in runs_by_cond[b]})
            out["comparisons"][name] = {"a": a, "b": b, **paired_comparison(by_cond[a], by_cond[b], common)}
    return out


def _fmt(v: object) -> str:
    if isinstance(v, tuple) and len(v) == 3 and all(x is None or isinstance(x, float) for x in v):
        return "n/a" if v[0] is None else f"{v[0]:.1%} [{v[1]:.1%}, {v[2]:.1%}]"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def print_report(rep: dict, out=sys.stdout) -> None:
    def walk(d: dict, indent: int = 0):
        for k, v in d.items():
            if isinstance(v, dict):
                print(" " * indent + f"{k}:", file=out)
                walk(v, indent + 2)
            else:
                print(" " * indent + f"{k}: {_fmt(v)}", file=out)
    walk(rep)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m eval.metrics claims.jsonl runs.jsonl")
    labels, key = load_phase3()
    print_report(report(load_claims(Path(sys.argv[1])), read_jsonl(Path(sys.argv[2])), labels, key))
