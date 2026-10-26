r"""Report prompts on development boxes (Phase 4): run the report arms on the D15 boxes, verify every
claim against that box's evidence, and summarise, so the gated / ungated prompts can be developed and
frozen without touching the 30 labelled sites.

Boxes: the 60 detected development regions (data/quangninh/vlm_dev_sample.json; box = the region's
outline box, as on the chips) and the 20 controls with no detection nearby
(data/quangninh/vlm_dev_controls.json): the evaluation's "detected" and "random site" strata.
Evidence per box: agents/site_evidence.py (regions cut to the box, locations relative to it).

    python scripts\report_dev.py                       # gated + ungated with the server's model (VLM_URL / VLM_TOKEN)
    python scripts\report_dev.py --arms template       # no model needed
    python scripts\report_dev.py --limit 5             # first 5 detected boxes + first 5 controls
    python scripts\report_dev.py --summary [--out docs\report_dev.md]
    python scripts\report_dev.py --show r200           # one box: evidence, raw output, claims with verdicts

Every report goes to data/reports_dev.jsonl. A report already there (same arm, box, prompt versions,
model and image set) is skipped, so after a Colab disconnect just reconnect and rerun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import vlm_batch                                         # noqa: E402
from agents import gated, site_evidence, ungated, vlm_check   # noqa: E402
from webapp.backend.report import build_report           # noqa: E402

LOG = ROOT / "data" / "reports_dev.jsonl"
ARMS = ("template", "gated", "ungated")
CHIP_SET = vlm_check.DEFAULT_CHIP_SET if vlm_check.DEFAULT_CHIP_SET in vlm_check.CHIP_SETS else "rgb_swir"


# ---------- boxes ----------
def dev_boxes(limit: int | None = None) -> tuple[dict, list[dict]]:
    """(regions fc, [{'id', 'stratum', 'box'}]) for the detected development regions and the controls."""
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    sample = json.loads(vlm_batch.SAMPLE.read_text(encoding="utf-8"))["ids"]
    controls = json.loads(vlm_batch.CONTROLS.read_text(encoding="utf-8"))["features"] if vlm_batch.CONTROLS.exists() else []
    boxes = [{"id": rid, "stratum": "detected", "box": vlm_batch.bbox(by_id[rid]["geometry"])} for rid in sample[:limit]]
    boxes += [{"id": c["properties"]["id"], "stratum": "control", "box": vlm_batch.bbox(c["geometry"])} for c in controls[:limit]]
    for b in boxes:
        if vlm_check.touches_labelled_site(b["box"]):
            raise SystemExit(f"{b['id']} overlaps a labelled site: development boxes must not")
    return fc, boxes


def box_evidence(fc: dict, box: dict) -> dict:
    params = vlm_batch.analysis_params(fc)
    meta = fc.get("metadata") or {}
    return site_evidence.site_evidence(box["box"], fc["features"], params["before_window"], params["after_window"],
                                       source=meta.get("code_version", "regions"), pair_id=f"dev:{box['id']}")


# ---------- log ----------
def versions(arm: str) -> list[str]:
    return {"template": ["template"], "gated": [gated.PROMPT_VERSION],
            "ungated": [ungated.REPORT_PROMPT_VERSION, ungated.EXTRACT_PROMPT_VERSION]}[arm]


def evidence_tag(ev: dict) -> str:
    """Fingerprint of a box's evidence: a report verified against older evidence (e.g. before the
    shoreline transects joined it) is not reused."""
    return hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()[:12]


def report_key(arm: str, box_id: str, model: str | None, chip_set: str, ev_tag: str = "") -> str:
    blob = json.dumps([arm, box_id, versions(arm), model, chip_set if arm != "template" else None, ev_tag])
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def read_log(path: Path | None = None) -> list[dict]:
    path = Path(path or LOG)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("key"):
            out.append(rec)
    return out


def append_log(rec: dict, path: Path | None = None) -> None:
    path = Path(path or LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- run ----------
def one_report(arm: str, vlm, fc: dict, box: dict, ev: dict, chips: dict[str, bytes] | None) -> dict:
    """build_report() output for one arm and box (claims verified against `ev`)."""
    params = vlm_batch.analysis_params(fc)
    if arm == "template":
        return build_report(ev, "template")
    images = [chips[k] for k in vlm_check.chip_keys(CHIP_SET)]
    if arm == "gated":
        out = gated.run_gated(vlm, box["id"], ev, params["before_window"], params["after_window"], images, CHIP_SET)
        return build_report(ev, "gated", gated=out)
    out = ungated.run_ungated(vlm, vlm, "ungated", box["id"], params["before_window"], params["after_window"], images, CHIP_SET)
    return build_report(ev, "ungated", ungated=out)


def run(vlm, arms: list[str], limit: int | None = None, log_path: Path | None = None, render=None, log=print,
        sleep=time.sleep) -> dict:
    """Every arm on every development box; skips reports already logged. Returns counts."""
    from agents.vlm_client import VLMUnavailable
    model = None
    if any(a != "template" for a in arms):
        status = vlm.status()
        if not status["available"]:
            raise SystemExit(f"Geo-VLM not available: {status['detail']}")
        model = status["model"]
    fc, boxes = dev_boxes(limit)
    params = vlm_batch.analysis_params(fc)
    done_keys = {r["key"] for r in read_log(log_path)}
    counts = {"done": 0, "skipped": 0, "failed": 0}
    total, n = len(arms) * len(boxes), 0
    log(f"{len(boxes)} boxes x {len(arms)} arms = {total} reports" + (f" (model {model})" if model else ""))
    for arm in arms:
        arm_model = model if arm != "template" else None
        for box in boxes:
            n += 1
            ev = box_evidence(fc, box)
            key = report_key(arm, box["id"], arm_model, CHIP_SET, evidence_tag(ev))
            if key in done_keys:
                counts["skipped"] += 1
                continue
            t0 = time.time()
            rep = None
            for attempt in range(1, vlm_batch.SERVER_TRIES + 1):
                try:
                    chips = None if arm == "template" else vlm_batch.chips_for(params, box["box"], vlm_check.chip_kinds(CHIP_SET), render)
                    rep = one_report(arm, vlm, fc, box, ev, chips)
                    break
                except VLMUnavailable as exc:
                    if attempt == vlm_batch.SERVER_TRIES:
                        raise SystemExit(f"server stopped answering ({exc}); reconnect and rerun to resume")
                    log(f"[{n}/{total}] {arm} {box['id']}: server did not answer, retrying in {vlm_batch.RETRY_WAIT_S * attempt} s")
                    sleep(vlm_batch.RETRY_WAIT_S * attempt)
                except Exception as exc:
                    counts["failed"] += 1
                    log(f"[{n}/{total}] {arm} {box['id']}: FAILED {str(exc)[:150]}")
                    break
            if rep is None:
                continue
            rec = {"key": key, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "arm": arm, "box_id": box["id"],
                   "stratum": box["stratum"], "box": [round(v, 6) for v in box["box"]], "chips": CHIP_SET if arm != "template" else None,
                   "versions": versions(arm), "seconds": round(time.time() - t0, 1),
                   **{k: rep.get(k) for k in ("model", "raw_output", "claims", "abstain", "counts", "parse_ok", "dropped",
                                               "extractor_model", "extract_raw", "evidence")}}
            if arm == "template":
                rec["model"] = "rules"
            append_log(rec, log_path)
            counts["done"] += 1
            c = rep["counts"]
            log(f"[{n}/{total}] {arm} {box['id']} ({box['stratum']}): {len(rep['claims'])} claims "
                f"{c['supported']}/{c['unsupported']}/{c['uncertain']} s/u/?, {len(rep['abstain'])} abstain, {rec['seconds']} s")
    return counts


# ---------- summary ----------
def latest(records: list[dict]) -> dict[tuple, dict]:
    """(arm, model, versions, box) -> latest record."""
    out = {}
    for r in records:
        out[(r["arm"], r.get("model"), tuple(r["versions"]), r["box_id"])] = r
    return out


def _pct(n: int, d: int) -> str:
    return f"{n} ({100 * n / d:.0f}%)" if d else "–"


_NO_CHANGE_RE = re.compile(r"\bno\b(?:\s+[\w-]+){0,2}\s+change|\bnot\s+detected|\bno\s+detected", re.I)


def claims_change(rec: dict) -> bool:
    """The report claims change happened (any L2/L3 claim, or an L1 claim not saying 'no change')."""
    for c in rec.get("claims") or []:
        if c["level"] in ("L2", "L3") or (c["level"] == "L1" and not _NO_CHANGE_RE.search(c["text"])):
            return True
    return False


def summary(records: list[dict]) -> str:
    groups: dict[tuple, list[dict]] = {}
    for (arm, model, vers, _), r in latest(records).items():
        groups.setdefault((arm, (model or "rules").split("/")[-1], "+".join(vers), r["stratum"]), []).append(r)
    lines = ["| Arm | model | prompt | stratum | boxes | claims/box | supported | unsupported | uncertain | L4 claims "
             "| claims change | abstain/box | parse fails | dropped items | median s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (arm, model, vers, stratum), recs in sorted(groups.items()):
        claims = [c for r in recs for c in r.get("claims") or []]
        v = Counter(c.get("verdict") for c in claims)
        secs = [r["seconds"] for r in recs if r.get("seconds") is not None]
        lines.append(f"| {arm} | {model} | {vers} | {stratum} | {len(recs)} | {len(claims) / len(recs):.1f} | "
                     f"{_pct(v['supported'], len(claims))} | {_pct(v['unsupported'], len(claims))} | {_pct(v['uncertain'], len(claims))} | "
                     f"{_pct(sum(c['level'] == 'L4' for c in claims), len(claims))} | {_pct(sum(claims_change(r) for r in recs), len(recs))} | "
                     f"{sum(len(r.get('abstain') or []) for r in recs) / len(recs):.1f} | {sum(r.get('parse_ok') is False for r in recs)} | "
                     f"{sum(r.get('dropped') or 0 for r in recs)} | {round(statistics.median(secs), 1) if secs else '–'} |")
    reasons = Counter((arm, c.get("verdict_reason")) for (arm, *_), r in latest(records).items() for c in r.get("claims") or []
                      if c.get("verdict") != "supported")
    parts = ["# Report prompts on development boxes", "Detected = 60 development regions, control = 20 boxes with no detection "
             "within 200 m (the evaluation's random-site stratum). Verdicts from agents/verifier.py against each box's evidence.",
             "## Per arm", "\n".join(lines) if len(lines) > 2 else "_No reports yet._",
             "## Why claims were not supported (all strata)",
             "\n".join(f"- {arm}: {reason} × {n}" for (arm, reason), n in sorted(reasons.items(), key=lambda x: (x[0][0], -x[1]))) or "_None._"]
    return "\n\n".join(parts) + "\n"


def show(records: list[dict], box_id: str) -> str:
    out = []
    for (arm, model, vers, bid), r in sorted(latest(records).items()):
        if bid != box_id:
            continue
        out.append(f"## {arm} · {model} · {'+'.join(vers)}")
        if r.get("raw_output"):
            out.append("Raw output:\n" + r["raw_output"])
        for c in r.get("claims") or []:
            out.append(f"- [{c['level']} {c['type']}] {c['text']}  -> {c.get('verdict')} ({c.get('verdict_reason')})")
        for a in r.get("abstain") or []:
            out.append(f"- abstain: {a['topic']}: {a['reason']}")
    if not out:
        return f"No reports for {box_id}."
    ev = next(r for (_, _, _, bid), r in latest(records).items() if bid == box_id)["evidence"]
    shown = {"change_frac": ev["change_frac"], "regions": [{k: r.get(k) for k in gated.EVIDENCE_FIELDS} for r in ev["regions"]]}
    if "transects" in ev:
        shown["transects"] = ev["transects"]
    return f"# {box_id}\nEvidence: {json.dumps(shown)}\n\n" + "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default=",".join(ARMS), help="comma-separated: template, gated, ungated")
    ap.add_argument("--limit", type=int, help="first N detected boxes and first N controls")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out", type=Path, help="with --summary: write Markdown here")
    ap.add_argument("--show", help="one box id: evidence, raw outputs, claims with verdicts")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if args.summary or args.show:
        text = summary(read_log()) if args.summary else show(read_log(), args.show)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"-> {args.out}")
        else:
            print(text)
        return
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms if a not in ARMS]
    if bad:
        raise SystemExit(f"unknown arms {bad}; choose from {ARMS}")
    from agents.vlm_client import VLMClient
    counts = run(VLMClient(), arms, args.limit)
    print(f"done {counts['done']}, already logged {counts['skipped']}, failed {counts['failed']}")


if __name__ == "__main__":
    main()
