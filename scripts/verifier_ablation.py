r"""Ablation: the rule verifier (agents/verifier.py) against a learned NLI verifier
(agents/nli_verifier.py), both scored against the human support labels of the adjudicated claims.

    python scripts\verifier_ablation.py reports_sites.jsonl claims.jsonl [--model MoritzLaurer/...] [--out docs\results]

reports: the report records with each box's evidence (scripts/report_dev.py shape); claims: the
adjudicated metric records (python -m eval.adjudication ...). For each verifier: agreement with the
human support axis (accuracy, Cohen's kappa), catch rate on hallucinated claims and precision of what
it rejects, as eval/metrics.py defines them; then an exact McNemar test on the claims where exactly
one verifier agrees with the human support label. The NLI model needs transformers + torch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import nli_verifier                      # noqa: E402
from eval import adjudication, metrics               # noqa: E402


def evidence_by_claim(reports: list[dict]) -> dict[tuple, dict]:
    """(site_id, condition, claim_id) -> the box evidence that claim was verified against."""
    out = {}
    for r in adjudication.latest_reports(reports):
        for c in r["claims"]:
            out[(r["box_id"], r["arm"], c["claim_id"])] = r["evidence"]
    return out


def scores(claims: list[dict], verdict_key: str) -> dict:
    as_metric = [{**c, "verdict": c[verdict_key]} for c in claims]
    passed = [c[verdict_key] == "supported" for c in claims]
    human = [c["support"] == "supported" for c in claims]
    return {"n": len(claims),
            "accuracy_vs_support": metrics.wilson(sum(a == b for a, b in zip(passed, human)), len(claims)),
            **metrics.verifier_scores(as_metric)}


def compare(reports: list[dict], claims: list[dict], model) -> dict:
    ev = evidence_by_claim(reports)
    rows = []
    for c in claims:
        e = ev.get((c["site_id"], c["condition"], c["claim_id"]))
        if e is None:
            continue
        rows.append({**c, "rule": c["verdict"], "nli": nli_verifier.nli_verify(c, e, model).verdict})
    right = lambda c, k: (c[k] == "supported") == (c["support"] == "supported")
    # McNemar: +1 where only the rule verifier agrees with the human label, -1 where only NLI does
    discordant = [1 if right(c, "rule") else -1 for c in rows if right(c, "rule") != right(c, "nli")]
    rule_only, nli_only, p = metrics.sign_test(discordant)
    return {"rule": scores(rows, "rule"), "nli": scores(rows, "nli"),
            "mcnemar": {"rule_right_nli_wrong": rule_only, "nli_right_rule_wrong": nli_only, "p_exact": p},
            "n_without_evidence": len(claims) - len(rows)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Rule verifier vs NLI verifier against human support labels")
    ap.add_argument("reports", type=Path)
    ap.add_argument("claims", type=Path)
    ap.add_argument("--model", default=nli_verifier.DEFAULT_MODEL)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    res = compare(metrics.read_jsonl(args.reports), metrics.load_claims(args.claims), nli_verifier.hf_nli(args.model))
    res["model"] = args.model
    metrics.print_report(res)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "verifier_ablation.json").write_text(json.dumps(res, indent=1, default=list), encoding="utf-8")


if __name__ == "__main__":
    main()
