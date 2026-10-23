"""Compare Geo-VLM answers across models and image sets, from the answer log (data/vlm_checks.jsonl).

    python scripts/vlm_compare.py                      # summary per condition + pairwise agreement
    python scripts/vlm_compare.py --regions            # also one row per region
    python scripts/vlm_compare.py --out docs/vlm_compare.md
    python scripts/vlm_compare.py --replay-out replay.json --condition "Qwen2.5-VL-7B-Instruct · rgb_swir"
    python scripts/vlm_compare.py --dev --out docs/vlm_compare_d15.md   # D15: the development sample only, with
                                       # Dynamic World reference, image-set stability, model disagreements
    python scripts/vlm_compare.py --dev --sheet adjudicate.html      # blind page for the hand decisions (D15)

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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agents import vlm_check  # noqa: E402

SAMPLE = ROOT / "data" / "quangninh" / "vlm_dev_sample.json"          # scripts/vlm_batch.py --draw
ADJUDICATION = ROOT / "data" / "quangninh" / "vlm_dev_adjudication.json"   # hand decisions, {region_id: verdict}

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


# ---------- D15: model / image-set comparison on the development sample ----------
def model_of(cond: str) -> str:
    return cond.split(" · ")[0]


def chips_of(cond: str) -> str:
    return cond.split(" · ")[1]


def dw_reference(checks: dict[tuple, dict], regions: dict[str, dict]) -> str:
    """Per condition: how the verdicts line up with Dynamic World's class change (D10), an independent
    but weak reference (a class can stay while the land changes, and Dynamic World makes errors)."""
    lines = ["| Condition | n | DW changed → change | DW same → no change | agreement (unsure counts as miss) |",
             "|---|---|---|---|---|"]
    by_cond: dict[str, list[dict]] = {}
    for (cond, rid, *_), rec in checks.items():
        if rid in regions and regions[rid].get("class_before") and regions[rid].get("class_after"):
            by_cond.setdefault(cond, []).append(rec)
    for cond in sorted(by_cond):
        recs = by_cond[cond]
        changed = [r for r in recs if regions[r["region_id"]]["class_before"] != regions[r["region_id"]]["class_after"]]
        same = [r for r in recs if r not in changed]
        hit_c = sum(r["verdict"] == "change" for r in changed)
        hit_s = sum(r["verdict"] == "no_change" for r in same)
        lines.append(f"| {cond} | {len(recs)} | {_pct(hit_c, len(changed))} | {_pct(hit_s, len(same))} | "
                     f"{_pct(hit_c + hit_s, len(recs))} |")
    return "\n".join(lines) if len(lines) > 2 else "_No checked region has Dynamic World classes._"


def stability(checks: dict[tuple, dict]) -> str:
    """Per model: regions checked under every image set the model has, and how often the verdict is the same in all."""
    per: dict[str, dict[tuple, dict[str, str]]] = {}
    for (cond, rid, bw, aw), rec in checks.items():
        per.setdefault(model_of(cond), {}).setdefault((rid, bw, aw), {})[chips_of(cond)] = rec["verdict"]
    lines = ["| Model | image sets | regions in all | same verdict in all |", "|---|---|---|---|"]
    for model in sorted(per):
        sets = sorted({s for v in per[model].values() for s in v})
        full = [v for v in per[model].values() if len(v) == len(sets)]
        if len(sets) < 2 or not full:
            continue
        lines.append(f"| {model} | {', '.join(sets)} | {len(full)} | {_pct(sum(len(set(v.values())) == 1 for v in full), len(full))} |")
    return "\n".join(lines) if len(lines) > 2 else "_No model has answers under two image sets yet._"


def disagreements(checks: dict[tuple, dict]) -> list[dict]:
    """Regions where two models answered differently under the same image set: these get a hand look (D15)."""
    by: dict[tuple, dict[str, dict]] = {}
    for (cond, rid, bw, aw), rec in checks.items():
        by.setdefault((chips_of(cond), rid, bw, aw), {})[model_of(cond)] = rec
    out = []
    for (chips, rid, *_), answers in sorted(by.items()):
        if len(answers) > 1 and len({r["verdict"] for r in answers.values()}) > 1:
            out.append({"region_id": rid, "chips": chips, "answers": {m: r["verdict"] for m, r in sorted(answers.items())},
                        "reasons": {m: r.get("reason", "") for m, r in sorted(answers.items())}})
    return out


def adjudicated(checks: dict[tuple, dict], adj: dict[str, str]) -> str:
    """Per condition: answers matching the hand decision on the adjudicated regions ({region: verdict})."""
    lines = ["| Condition | adjudicated regions | matches |", "|---|---|---|"]
    by_cond: dict[str, list[dict]] = {}
    for (cond, rid, *_), rec in checks.items():
        if adj.get(rid) in vlm_check.VERDICTS:
            by_cond.setdefault(cond, []).append(rec)
    for cond in sorted(by_cond):
        recs = by_cond[cond]
        lines.append(f"| {cond} | {len(recs)} | {_pct(sum(r['verdict'] == adj[r['region_id']] for r in recs), len(recs))} |")
    return "\n".join(lines) if len(lines) > 2 else "_Nothing adjudicated yet._"


def adjudication_sheet(dis: list[dict], chips: dict[str, dict[str, bytes]], seed: int = 15) -> str:
    """A standalone HTML page for the hand decisions (D15): each disagreement region's chips in a
    shuffled order, with NO model answers on the page, and buttons that save {region_id: verdict}."""
    import base64
    import html
    import random
    ids = sorted({d["region_id"] for d in dis})
    random.Random(seed).shuffle(ids)
    cards = []
    for n, rid in enumerate(ids, 1):
        imgs = "".join(f'<figure><img src="data:image/png;base64,{base64.b64encode(png).decode()}"><figcaption>'
                       f'{html.escape(name.replace("_", " "))}</figcaption></figure>' for name, png in sorted(chips.get(rid, {}).items()))
        radios = "".join(f'<label><input type="radio" name="{rid}" value="{v}"> {v.replace("_", " ")}</label>' for v in vlm_check.VERDICTS)
        cards.append(f'<section><h2>{n}. {html.escape(rid)}</h2><div class="imgs">{imgs}</div><p>{radios}</p></section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>D15 hand decisions</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;max-width:1200px}}section{{border-top:1px solid #ccc;padding:8px 0}}
.imgs{{display:flex;flex-wrap:wrap;gap:6px}}figure{{margin:0}}img{{width:260px}}figcaption{{font-size:12px;color:#555}}
label{{margin-right:14px}}button{{font-size:15px;padding:6px 14px}}</style></head><body>
<h1>Geo-VLM hand decisions ({len(ids)} regions)</h1>
<p>For each region: did real land-cover change happen <b>inside the yellow box</b> between before and after?
The models' answers are not shown. Development regions only, never a labelled site.</p>
{''.join(cards) or '<p>No disagreements.</p>'}
<p><button onclick="save()">Save vlm_dev_adjudication.json</button> <span id="n"></span></p>
<script>
function save() {{
  const out = {{}};
  document.querySelectorAll('input[type=radio]:checked').forEach(r => out[r.name] = r.value);
  document.getElementById('n').textContent = Object.keys(out).length + ' of {len(ids)} decided';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}}));
  a.download = 'vlm_dev_adjudication.json'; a.click();
}}
</script></body></html>
"""


def controls_table(checks: dict[tuple, dict]) -> str:
    """Per condition on the negative controls (no detection near the box): a model that can tell change
    from no change should mostly say no_change here (D15 specificity)."""
    by_cond: dict[str, list[dict]] = {}
    for (cond, *_), rec in checks.items():
        by_cond.setdefault(cond, []).append(rec)
    lines = ["| Condition | n | no change (wanted) | unsure | change |", "|---|---|---|---|---|"]
    for cond in sorted(by_cond):
        v = Counter(r["verdict"] for r in by_cond[cond])
        n = len(by_cond[cond])
        lines.append(f"| {cond} | {n} | {_pct(v['no_change'], n)} | {_pct(v['unsure'], n)} | {_pct(v['change'], n)} |")
    return "\n".join(lines) if len(lines) > 2 else "_No control answers yet._"


def dev_report(records: list[dict], sample_ids: list[str], regions: dict[str, dict], adj: dict[str, str] | None = None,
               control_ids: list[str] = ()) -> str:
    keep, ctrl = set(sample_ids), set(control_ids)
    all_checks = latest(records)
    checks = {k: r for k, r in all_checks.items() if k[1] in keep}
    controls = {k: r for k, r in all_checks.items() if k[1] in ctrl}
    if not checks and not controls:
        return "No answers on the development sample yet: run scripts/vlm_batch.py first."
    dis = disagreements({**checks, **controls})
    parts = [f"# D15 model / image-set comparison: {len(checks)} checks on {len({k[1] for k in checks})} "
             f"of {len(keep)} development regions",
             "Regions outside the 30 labelled sites only (data/quangninh/vlm_dev_sample.json). Criteria in "
             "docs/decisions.md D15.",
             "## Per condition (detected regions)", summary(checks) if checks else "_None yet._",
             f"## Negative controls ({len(ctrl)} boxes with no detection within 200 m)", controls_table(controls),
             "## Against Dynamic World class change (weak reference)", dw_reference(checks, regions),
             "## Same verdict across image sets", stability(checks),
             "## Between conditions", pairwise(checks),
             f"## Model disagreements to look at ({len(dis)})",
             "\n".join(f"- {d['region_id']} ({d['chips']}): " + "; ".join(f"{m} {v}" for m, v in d["answers"].items())
                       for d in dis) or "_None yet._"]
    if adj is not None:
        parts += ["## Against the hand decisions on disagreements", adjudicated(checks, adj)]
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
    ap.add_argument("--dev", action="store_true", help="D15 report on the development sample (scripts/vlm_batch.py)")
    ap.add_argument("--adjudication", type=Path, default=ADJUDICATION,
                    help="with --dev: hand decisions on the disagreements, {region_id: verdict}")
    ap.add_argument("--sheet", type=Path, help="with --dev: write the blind hand-decision page (HTML) for the disagreements")
    args = ap.parse_args(argv)
    records = vlm_check.read_log(args.log)
    if args.dev:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
        fc = json.loads((ROOT / sample["regions_file"]).read_text(encoding="utf-8"))
        import vlm_batch
        fc, control_ids = vlm_batch.with_controls(fc)
        regions = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        adj = json.loads(args.adjudication.read_text(encoding="utf-8")) if args.adjudication.exists() else None
        if args.sheet:
            keep = set(sample["ids"]) | set(control_ids)
            dis = disagreements({k: r for k, r in latest(records).items() if k[1] in keep})
            params = vlm_batch.analysis_params(fc)
            by_id = {f["properties"]["id"]: f for f in fc["features"]}
            chips = {}
            for rid in {d["region_id"] for d in dis}:
                folder = vlm_batch.chip_dir(params, vlm_batch.bbox(by_id[rid]["geometry"]))
                chips[rid] = {p.stem: p.read_bytes() for p in sorted(folder.glob("*.png"))}
            args.sheet.write_text(adjudication_sheet(dis, chips), encoding="utf-8")
            print(f"{len(chips)} regions -> {args.sheet}  (open it, decide, Save, move the file to {ADJUDICATION})")
            return
        text = dev_report(records, sample["ids"], regions, adj, control_ids)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"report -> {args.out}")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            print(text)
        return
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
