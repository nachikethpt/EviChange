"""Claim adjudication (Phase 5): the blinded queue the adjudication page shows, and the records it
writes, in the shape eval/metrics.py reads.

Rules: docs/adjudication_rules.md (D18, proposed). What this module enforces:
- the adjudicator never sees the condition, the verifier's verdict, region_ref / evidence_ref, or
  region ids and parenthesised index values in the claim text (blind_text);
- claims of all conditions are shuffled together within a site, and sites are shuffled, both seeded;
- a seeded 20 % of sites goes to the second adjudicator, so the overlap for kappa is fixed in advance;
- judgements are appended to one JSON-lines file per adjudicator, so a session can stop and resume.

Input: report records as scripts/report_dev.py writes them ({arm, box_id, stratum, box, claims,
evidence, parse_ok, dropped, ...}); the 30-site run writes the same shape.

    python -m eval.adjudication reports.jsonl judgements.jsonl claims.jsonl runs.jsonl
        joins one adjudicator's judgements with the reports and writes metrics' claims / runs files
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

from agents.schema import LOCATIONS, REPORT_CONDITIONS

from .metrics import SEED, SUPPORTS, TRUTHS, read_jsonl

SECOND_SHARE = 0.20
LABELS_FILE = Path(__file__).resolve().parent.parent / "data" / "quangninh" / "labels" / "labels_v1.jsonl"
JUDGEMENT_FIELDS = ("truth", "support", "about_detector", "compound", "note")

# "Region r12: ...", "In region r200 (north, ~12.8 ha) ...", "Transect t0042: ...", "(dNDVI -0.34)", "(+1.2 m/yr)"
_REGION_PREFIX = re.compile(r"^\s*(?:region|transect)\s+[A-Za-z]*\d+\s*:\s*", re.I)
# "in region r1 (north-east, ~182 ha)": the bracket says where and how much, so it stays as words
_REGION_PAREN = re.compile(r"\b(in\s+)?(?:region|transect)\s+[A-Za-z]*\d+\s*\(([^)]*)\)", re.I)
_REGION_REF = re.compile(r"\b(in\s+)?(?:region|transect)\s+[A-Za-z]*\d+\b", re.I)
_INDEX_PAREN = re.compile(r"\s*\((?:[^()]*\b(?:dNDVI|dNDBI|dMNDWI)\b[^()]*)\)", re.I)
_SPACES = re.compile(r"\s{2,}")


def _region_words(m: re.Match) -> str:
    where, *rest = [part.strip() for part in m.group(2).split(",")]
    if where.lower() not in LOCATIONS:
        return f"{m.group(1) or ''}an area ({m.group(2)})"
    return f"in the {where}" + (f" ({', '.join(rest)})," if rest else ",")


def blind_text(text: str) -> str:
    """The claim text as the adjudicator sees it: no region / transect ids and no parenthesised index
    values, which give the condition away (audit finding 8). Location words, areas and rates stay."""
    out = _REGION_PREFIX.sub("", text)
    out = _INDEX_PAREN.sub("", out)
    out = _REGION_PAREN.sub(_region_words, out)
    out = _REGION_REF.sub(lambda m: "" if m.group(1) else "an area", out)   # "in region r12" says nothing
    out = _SPACES.sub(" ", out).strip(" ,")
    out = re.sub(r"\s+([.,;])", r"\1", out)
    out = re.sub(r",([.;])", r"\1", out)
    return out[:1].upper() + out[1:] if out else text


def item_id(site_id: str, condition: str, claim_id: str) -> str:
    """Anonymous, stable id of one claim: shown on the page, joined back to the condition server-side."""
    return hashlib.sha256(f"{site_id}|{condition}|{claim_id}".encode()).hexdigest()[:10]


def latest_reports(records: list[dict]) -> list[dict]:
    """The last record per (site, condition): reruns replace earlier reports."""
    out: dict[tuple, dict] = {}
    for rec in records:
        out[(rec["box_id"], rec["arm"])] = rec
    return [r for r in out.values() if r["arm"] in REPORT_CONDITIONS]


def build_items(records: list[dict]) -> dict[str, dict]:
    """item id -> {site_id, condition, claim} for every claim in the latest reports."""
    items = {}
    for rec in latest_reports(records):
        for c in rec["claims"]:
            iid = item_id(rec["box_id"], rec["arm"], c["claim_id"])
            items[iid] = {"site_id": rec["box_id"], "condition": rec["arm"], "stratum": rec.get("stratum"), "claim": c}
    return items


def second_sites(site_ids: list[str], share: float = SECOND_SHARE, seed: int = SEED) -> set[str]:
    """The seeded share of sites (at least one) that the second adjudicator also does."""
    sites = sorted(set(site_ids))
    if not sites:
        return set()
    k = max(1, round(share * len(sites)))
    return set(random.Random(seed).sample(sites, k))


def queue(records: list[dict], role: str = "first", seed: int = SEED) -> list[dict]:
    """Sites in seeded random order, each with its claims from every condition shuffled together. Nothing
    in the output names the condition or the verdict. role "second": only the second adjudicator's sites."""
    items = build_items(records)
    by_site: dict[str, list[tuple[str, dict]]] = {}
    for iid, it in items.items():
        by_site.setdefault(it["site_id"], []).append((iid, it))
    sites = sorted(by_site)
    if role == "second":
        keep = second_sites(sites, seed=seed)
        sites = [s for s in sites if s in keep]
    rng = random.Random(seed)
    rng.shuffle(sites)
    evidence = {r["box_id"]: r.get("evidence") for r in latest_reports(records)}
    out = []
    for s in sites:
        claims = sorted(by_site[s], key=lambda pair: pair[0])     # stable before the shuffle
        rng.shuffle(claims)
        out.append({"site_id": s, "evidence": evidence.get(s),
                    "items": [{"item_id": iid, "text": blind_text(it["claim"]["text"]),
                               "level": it["claim"].get("level")} for iid, it in claims]})
    return out


def check_judgement(j: dict) -> list[str]:
    errs = [f"missing '{f}'" for f in ("item_id", "adjudicator") if not j.get(f)]
    if j.get("truth") is not None and j["truth"] not in TRUTHS:
        errs.append(f"truth must be one of {TRUTHS}")
    if j.get("support") is not None and j["support"] not in SUPPORTS:
        errs.append(f"support must be one of {SUPPORTS}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(j.get("adjudicator", ""))):
        errs.append("adjudicator must be 1-32 letters, digits, - or _")
    return errs


def latest_judgements(rows: list[dict]) -> dict[str, dict]:
    """item id -> the adjudicator's last judgement of it, merged field by field (truth on pass 1,
    support on pass 2)."""
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.setdefault(r["item_id"], {})
        cur.update({k: v for k, v in r.items() if k in JUDGEMENT_FIELDS and v is not None})
    return out


def to_metric_records(records: list[dict], judgements: list[dict], adjudicator: str,
                      drop_about_detector: bool = True) -> tuple[list[dict], list[dict]]:
    """(claims, runs) for eval/metrics.py: every fully judged claim, joined back to its condition and
    the verifier's verdict, and one run per site and condition. Claims tagged about_detector are left
    out of the claims (rule 2 of the proposed rules) unless drop_about_detector is False."""
    items = build_items(records)
    judged = latest_judgements(judgements)
    claims = []
    for iid, it in items.items():
        j = judged.get(iid)
        if not j or j.get("truth") is None or j.get("support") is None:
            continue
        if drop_about_detector and j.get("about_detector"):
            continue
        c = it["claim"]
        claims.append({"site_id": it["site_id"], "condition": it["condition"], "claim_id": c["claim_id"],
                       "type": c.get("type"), "level": c.get("level"), "text": c["text"],
                       "change_type": c.get("change_type"), "verdict": c.get("verdict"),
                       "truth": j["truth"], "support": j["support"],
                       "about_detector": bool(j.get("about_detector")), "compound": bool(j.get("compound")),
                       "adjudicator": adjudicator, "note": j.get("note", "")})
    runs = [{"site_id": r["box_id"], "condition": r["arm"], "n_claims": len(r["claims"]),
             "n_parse_failures": int(r.get("dropped") or 0) + (0 if r.get("parse_ok", True) else 1)}
            for r in latest_reports(records)]
    return claims, runs


def progress(records: list[dict], judgements: list[dict], role: str = "first") -> dict:
    ids = {it["item_id"] for site in queue(records, role) for it in site["items"]}
    judged = latest_judgements(judgements)
    return {"items": len(ids),
            "truth_done": sum(1 for i in ids if judged.get(i, {}).get("truth")),
            "support_done": sum(1 for i in ids if judged.get(i, {}).get("support"))}


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        sys.exit("usage: python -m eval.adjudication reports.jsonl judgements.jsonl claims.jsonl runs.jsonl")
    reports, judgements = read_jsonl(Path(argv[0])), read_jsonl(Path(argv[1]))
    adjudicator = judgements[0]["adjudicator"] if judgements else "unknown"
    claims, runs = to_metric_records(reports, judgements, adjudicator)
    for path, rows in ((argv[2], claims), (argv[3], runs)):
        Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(claims)} adjudicated claims, {len(runs)} runs")


if __name__ == "__main__":
    main(sys.argv[1:])
