"""Gated report arm (Phase 4): the Geo-VLM sees the chips AND the evidence, and may only make
claims that cite it. Every claim names what it is about (region_ref, transect_ref or strip) and
the evidence fields it rests on (evidence_ref); anything the evidence can't show (cause, purpose,
legality, who, the future) goes into "abstain" instead of a claim. The verifier then checks each
claim against the same evidence, as for the other arms.

Covers every claim type the verifier checks (schema.CLAIM_TYPES): presence, extent, location,
change_type, land_cover (D10), shoreline and coastal_built (D13). The evidence shown to the model
is the evidence the verifier gets, minus geometry, so the model can't cite what the verifier lacks.

Prompt is a draft (v0): develop it on QN regions outside the 30 labelled sites (vlm_check's
labelled-site lock applies) and freeze it with the other Phase-4 prompts.
"""
from __future__ import annotations

import json
import re

from . import vlm_check
from .schema import CHANGE_TYPES, COASTAL_STRIPS, EVIDENCE_REF_FIELDS, LANDCOVER_CLASSES, T_IDX, validate_claim

PROMPT_VERSION = "gated_report_v0"
GATED_TYPES = ("presence", "extent", "location", "change_type", "land_cover", "shoreline", "coastal_built")
_REGION_KEYS = ("id", "area_ha", "mean_conf", "location", "dNDVI", "dNDBI", "dMNDWI", "class_before", "class_after")
_TRANSECT_KEYS = ("id", "location", "change", "nsm", "lrr", "ci95")
_STRIP_KEYS = ("strip", "location", "built_ha_before", "built_ha_after")

PROMPT = """You are a remote-sensing analyst writing a change report that a checker will verify against the
EVIDENCE below. You get {count} Sentinel-2 images of the same place:
{images}
Before: {before}. After: {after}. Both dates use the same colour stretch, so colour differences are real.
{keys}
EVIDENCE (measured by the change detector and the shoreline / coastal analyses; the images are for context):
{evidence}

What the evidence fields mean:
- change_frac: share of the area that changed. regions: detected change regions, area_ha in hectares,
  location within the whole area, dNDVI / dNDBI / dMNDWI = after minus before (|value| <= {t_idx} is no clear
  change; dNDVI < 0 vegetation loss, dNDBI > 0 more built-up or bare surface, dMNDWI > 0 more water),
  mean_conf = detection confidence, class_before / class_after = dominant land-cover class (null = unknown).
- transects (if any): shoreline transects. change = advancing (land moved seaward), retreating (sea moved
  landward), stable, unconfirmed (radar trend the imagery does not confirm) or too_few; nsm = net movement
  in metres and lrr = rate in m/yr, both seaward positive.
- coastal_strips (if any): built area in hectares at 0-200 m and 200-500 m inland of the shoreline, before
  and after.

Rules:
1. Only state what the evidence shows. Every claim cites the item it is about ("region_ref": a region id,
   "transect_ref": a transect id, or "strip": {strips} or "0-500") and the evidence fields it uses
   ("evidence_ref", from: {ref_fields}).
2. Copy numbers from the evidence (round them, never invent them). Use the evidence location words.
3. Do not claim a change type where the index change is within +-{t_idx}, and do not call a shoreline
   advancing or retreating unless its change says so.
4. Never state a cause, purpose, legality, who did it or what will happen next. Put each such topic in
   "abstain" with the reason the evidence can't show it. Also abstain on anything the evidence leaves unknown.
5. If the evidence shows no change, say so in one L1 claim and stop.

Claim fields: "text" (one sentence), "level" (L1 = whether change happened, L2 = how much or where,
L3 = what kind), "type" (one of {types}), and where they apply: "region_ref", "transect_ref", "strip",
"change_type" (one of {change_types}), "class_before" / "class_after" (one of {classes}),
"shoreline_change" (advancing, retreating or stable), "evidence_ref" (list).

Answer with JSON only, no other text:
{{"claims": [ ... ], "abstain": [{{"topic": "...", "reason": "..."}}]}}"""


def prompt_evidence(ev: dict) -> dict:
    """The evidence as the model sees it: the verifier's evidence without geometry or other extras."""
    out = {"change_frac": ev.get("change_frac", 0.0),
           "regions": [{k: r.get(k) for k in _REGION_KEYS if k in r} for r in ev.get("regions", [])]}
    if ev.get("transects"):
        out["transects"] = [{k: t.get(k) for k in _TRANSECT_KEYS} for t in ev["transects"]]
    if ev.get("coastal_strips"):
        out["coastal_strips"] = [{k: s[k] for k in _STRIP_KEYS if s.get(k) is not None} for s in ev["coastal_strips"]]
    return out


def build_prompt(ev: dict, before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = vlm_check.chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    text = vlm_check._CHIP_TEXT
    labels = [f"{n}. {when}, {text[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(text[kind][2] + "\n" for kind in kinds if text[kind][2])
    return PROMPT.format(count=vlm_check._COUNT[2 * len(kinds)], images="   ".join(labels), keys=keys,
                         before=" to ".join(before_window), after=" to ".join(after_window),
                         evidence=json.dumps(prompt_evidence(ev), separators=(", ", ": ")), t_idx=T_IDX,
                         strips=", ".join(COASTAL_STRIPS), ref_fields=", ".join(sorted(EVIDENCE_REF_FIELDS)),
                         types=", ".join(GATED_TYPES), change_types=", ".join(CHANGE_TYPES),
                         classes=", ".join(LANDCOVER_CLASSES))


_CLAIM_FIELDS = ("region_ref", "transect_ref", "strip", "change_type", "class_before", "class_after", "shoreline_change")


def parse_report(text: str) -> tuple[list[dict], list[dict], bool, int]:
    """(claims, abstain, parse_ok, dropped) from the model's text. Claims that break the claim schema
    are dropped and counted (metric 8), never repaired; the verifier judges the rest."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        raw = None
    if not isinstance(raw, dict) or not isinstance(raw.get("claims"), list):
        return [], [], False, 0
    claims, dropped = [], 0
    for item in raw["claims"]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            dropped += 1
            continue
        refs = item.get("evidence_ref") or []
        claim = {"level": item.get("level"), "type": item.get("type"), "text": str(item["text"]).strip(),
                 "region_ref": None, "evidence_ref": refs if isinstance(refs, list) else None, "stated_conf": None}
        for field in _CLAIM_FIELDS:
            if item.get(field) is not None:
                claim[field] = item[field]
        if validate_claim(claim):
            dropped += 1
            continue
        claims.append(claim)
    for i, c in enumerate(claims, 1):
        c["claim_id"] = f"c{i}"
    abstain = [{"topic": str(a.get("topic", ""))[:200], "reason": str(a.get("reason", ""))[:300]}
               for a in raw.get("abstain") or [] if isinstance(a, dict) and a.get("topic")]
    return claims, abstain, True, dropped


def run_gated(vlm, key: str, ev: dict, before_window: list[str], after_window: list[str],
              images: list[bytes], chip_set: str = "rgb_swir") -> dict:
    """One gated report from the Geo-VLM. `key` names the site or selection for replay files.
    Raises VLMUnavailable if the model is unavailable."""
    out = vlm.generate(build_prompt(ev, before_window, after_window, chip_set), images, max_new_tokens=1200,
                       replay_key=f"{PROMPT_VERSION}:gated:{key}")
    claims, abstain, parse_ok, dropped = parse_report(out["text"])
    return {"raw": out["text"], "model": out["model"], "claims": claims, "abstain": abstain,
            "parse_ok": parse_ok, "dropped": dropped, "prompt_version": PROMPT_VERSION, "chips": chip_set}

