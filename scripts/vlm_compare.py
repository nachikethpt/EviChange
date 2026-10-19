"""Compare Geo-VLM answers across models and image sets, from the answer log (data/vlm_checks.jsonl).

    python scripts/vlm_compare.py                      # summary per condition + pairwise agreement
    python scripts/vlm_compare.py --regions            # also one row per region
    python scripts/vlm_compare.py --out docs/vlm_compare.md
    python scripts/vlm_compare.py --replay-out replay.json --condition "Qwen2.5-VL-7B-Instruct · rgb_swir"

A condition is model + image set. A region checked more than once under the same condition and
date windows counts once (the latest answer). Regions on the 30 labelled sites are never in the log
while they are locked (agents/vlm_check.py), so this compares on development regions only.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import vlm_check  # noqa: E402

AGREEMENTS = ("agrees", "partly", "change_only", "different_type", "disagrees", "unsure")
SYMBOL = {"agrees": "✓", "partly": "≈", "change_only": "✓?", "different_type": "≠", "disagrees": "✗", "unsure": "?"}


def condition(rec: dict) -> str:
    return f"{rec['model'].split('/')[-1]} · {rec.get('chips') or 'rgb_swir'}"


def latest(records: list[dict]) -> dict[tuple, dict]:
    """(condition, region, windows) -> the latest record."""
    out = {}
    for rec in records:
        out[(condition(rec), rec["region_id"], tuple(rec["before_window"]), tuple(rec["after_window"]))] = rec
    return out


def _pct(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.0f}%)" if total else "0"


def summary(checks: dict[tuple, dict]) -> str:
    by_cond: dict[str, list[dict]] = {}
    for (cond, *_), rec in checks.items():
        by_cond.setdefault(cond, []).append(rec)
    lines = ["| Condition | n | change | no change | unsure | " + " | ".join(SYMBOL[a] + " " + a for a in AGREEMENTS)
             + " | unparsed | median s |",
             "|---|---|---|---|---|" + "---|" * len(AGREEMENTS) + "---|---|"]
    for cond in sorted(by_cond):
        recs = by_cond[cond]
        n = len(recs)
        v = Counter(r["verdict"] for r in recs)
        a = Counter(r["agreement"] for r in recs)
        secs = [r["seconds"] for r in recs if r.get("seconds") is not None]
        lines.append(f"| {cond} | {n} | {_pct(v['change'], n)} | {_pct(v['no_change'], n)} | {_pct(v['unsure'], n)} | "
                     + " | ".join(_pct(a[x], n) for x in AGREEMENTS)
                     + f" | {sum(not r.get('parse_ok', True) for r in recs)} | {statistics.median(secs) if secs else '–'} |")
    return "\n".join(lines)


def pairwise(checks: dict[tuple, dict]) -> str:
    """For each pair of conditions: regions both checked, and how often the verdicts match."""
    answers: dict[str, dict[tuple, dict]] = {}
    for (cond, region, bw, aw), rec in checks.items():
        answers.setdefault(cond, {})[(region, bw, aw)] = rec
    lines = ["| Condition A | Condition B | regions in both | same verdict | same verdict + types |", "|---|---|---|---|---|"]
    for a, b in combinations(sorted(answers), 2):
        both = sorted(set(answers[a]) & set(answers[b]))
        if not both:
            continue
        same = sum(answers[a][r]["verdict"] == answers[b][r]["verdict"] for r in both)
        same_t = sum(answers[a][r]["verdict"] == answers[b][r]["verdict"]
                     and set(answers[a][r]["change_types"]) == set(answers[b][r]["change_types"]) for r in both)
        lines.append(f"| {a} | {b} | {len(both)} | {_pct(same, len(both))} | {_pct(same_t, len(both))} |")
    return "\n".join(lines) if len(lines) > 2 else "_No region was checked under two conditions yet._"


def region_table(checks: dict[tuple, dict]) -> str:
    conds = sorted({k[0] for k in checks})
    regions = sorted({(k[1], k[2], k[3]) for k in checks})
    lines = ["| Region | " + " | ".join(conds) + " |", "|---|" + "---|" * len(conds)]
    for region, bw, aw in regions:
        cells = []
        for c in conds:
            rec = checks.get((c, region, bw, aw))
            cells.append("" if rec is None else f"{SYMBOL.get(rec['agreement'], '?')} {rec['verdict'].replace('_', ' ')}"
                         + (f": {', '.join(rec['change_types'])}" if rec["change_types"] else ""))
        lines.append(f"| {region} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(records: list[dict], with_regions: bool = False) -> str:
    checks = latest(records)
    if not checks:
        return "No Geo-VLM answers logged yet. Check some regions in the app's Find changes first."
    windows = sorted({(k[2], k[3]) for k in checks})
    parts = [f"# Geo-VLM answers: {len(checks)} checks, {len({k[1] for k in checks})} regions",
             "Date windows: " + "; ".join(f"{' to '.join(b)} vs {' to '.join(a)}" for b, a in windows),
             "Agreement compares the model's answer with the detector's change types (agents/vlm_check.compare).",
             "## Per condition", summary(checks), "## Between conditions", pairwise(checks)]
    if with_regions:
        parts += ["## Per region", region_table(checks)]
    return "\n\n".join(parts) + "\n"


def replay_file(records: list[dict], cond: str) -> dict[str, str]:
    """{"<prompt_version>:<region>": raw answer} for VLM_REPLAY_FILE, latest answer per region."""
    return {f"{r['prompt_version']}:{r['region_id']}": r["raw"] for r in latest(records).values() if condition(r) == cond}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, default=vlm_check.LOG_FILE)
    ap.add_argument("--regions", action="store_true", help="add one row per region")
    ap.add_argument("--out", type=Path, help="write the report to a Markdown file")
    ap.add_argument("--replay-out", type=Path, help="write a VLM_REPLAY_FILE for --condition")
    ap.add_argument("--condition", help='e.g. "Qwen2.5-VL-7B-Instruct · rgb_swir" (as shown in the report)')
    args = ap.parse_args(argv)
    records = vlm_check.read_log(args.log)
    if args.replay_out:
        if not args.condition:
            raise SystemExit("--replay-out needs --condition")
        answers = replay_file(records, args.condition)
        args.replay_out.write_text(json.dumps(answers, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len(answers)} answers -> {args.replay_out}")
        return
    text = report(records, args.regions)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"report -> {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
