"""Gated report arm (Phase 4): the Geo-VLM writes claims FROM THE EVIDENCE, each citing the evidence
fields it rests on, and abstains on everything the evidence can't support (causes, legality, the
future, change where none was detected). The verifier then checks every claim.

Input, as the evaluation design says: the same before/after chips as the ungated arms, plus the box's
evidence (agents/site_evidence.py: regions cut to the box, locations relative to the box). The model
answers with JSON; items that break the claim schema are dropped and counted (parse failures,
evaluation metric 8), never repaired.

Prompt is a draft (v0): develop it on boxes outside the 30 labelled sites (scripts/report_dev.py) and
freeze it with the other Phase-4 prompts. The web app's report panel still uses the rule-based
stand-in in webapp/backend/report.py until the freeze.
"""
from __future__ import annotations

import json
import re

from . import vlm_check
from .schema import CHANGE_TYPES, LOCATIONS, T_IDX, validate_claim

PROMPT_VERSION = "gated_report_v0"
EVIDENCE_FIELDS = ("id", "area_ha", "location", "mean_conf", "dNDVI", "dNDBI", "dMNDWI", "class_before", "class_after")
# The box evidence (site_evidence) has regions only, so v0 offers the region claim types and fields. shoreline /
# coastal_built (D13) join with the transect / coastal-strip evidence, in a new prompt version.
PROMPT_TYPES = ("presence", "extent", "location", "change_type", "land_cover")
PROMPT_REF_FIELDS = ("area_ha", "change_frac", "class_after", "class_before", "class_frac_after", "class_frac_before",
                     "dMNDWI", "dNDBI", "dNDVI", "location", "mean_conf")

PROMPT = """You are writing a short change report about the area inside the yellow box, for a decision maker.
You get {count} Sentinel-2 images of the same place:
{images}
Before: {before}. After: {after}. Both dates use the same colour stretch, so colour differences are real.
{keys}
You also get the EVIDENCE: what the change detector measured inside the box. Every claim you make must
rest on the evidence. The images only help you describe what the evidence shows.

EVIDENCE:
{evidence}

What the fields mean:
- change_frac: share of the box the detector marked as changed (0 to 1).
- regions: the detected change regions inside the box. id: the region's name. area_ha: hectares inside
  the box. location: where in the box ({locations}). mean_conf: detector confidence (0 to 1).
  dNDVI, dNDBI, dMNDWI: change of the vegetation, built-up/bare and water index (after minus before);
  above +{t} means a clear increase, below -{t} a clear decrease, in between no clear change.
  class_before, class_after: Dynamic World land cover, or null when unknown.

Rules:
1. Write 1 to 8 claims. Each claim is one statement with:
   "level": "L1" whether change happened, "L2" how much or where, "L3" what kind of change or land cover;
   "type": one of {types};
   "region_ref": the region id the claim is about, or null for the whole box;
   "evidence_ref": the evidence fields the claim rests on, from: {fields};
   "change_type": one of {change_types}, only for type "change_type", else null;
   "class_before", "class_after": only for type "land_cover", copied from the evidence, else null.
2. Copy numbers from the evidence. Do not invent numbers or regions.
3. Name a change type only where its index moved beyond +/-{t} in that direction.
4. If "regions" is empty, make one L1 claim that no change was detected in the box (evidence_ref
   ["change_frac"]) and no other claim about change.
5. Never say what caused the change, what it is for, whether it is legal, who did it, or what will
   happen next. Put each such topic, and anything else the evidence can't support, under "abstain".

Answer with JSON only, no other text:
{{"claims": [{{"level": ..., "type": ..., "text": ..., "region_ref": ..., "evidence_ref": [...],
              "change_type": ..., "class_before": ..., "class_after": ...}}],
 "abstain": [{{"topic": ..., "reason": ...}}]}}"""


def evidence_for_prompt(ev: dict) -> str:
    """The evidence as the model sees it: change_frac and the regions' prompt fields, rounded."""
    regions = []
    for r in ev["regions"]:
        row = {k: r.get(k) for k in EVIDENCE_FIELDS}
        for k in ("mean_conf", "dNDVI", "dNDBI", "dMNDWI"):
            if row[k] is not None:
                row[k] = round(float(row[k]), 3)
        regions.append(row)
    return json.dumps({"change_frac": ev["change_frac"], "regions": regions}, indent=1)


def build_prompt(ev: dict, before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = vlm_check.chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    text = vlm_check._CHIP_TEXT
    labels = [f"{n}. {when}, {text[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(text[kind][2] + "\n" for kind in kinds if text[kind][2])
    return PROMPT.format(count=vlm_check._COUNT[2 * len(kinds)], images="   ".join(labels), keys=keys,
                         before=" to ".join(before_window), after=" to ".join(after_window),
                         evidence=evidence_for_prompt(ev), locations=", ".join(LOCATIONS), t=f"{T_IDX:.2f}",
                         types=", ".join(PROMPT_TYPES), fields=", ".join(PROMPT_REF_FIELDS),
                         change_types=", ".join(CHANGE_TYPES))


def parse_report(text: str) -> tuple[list[dict], list[dict], bool, int]:
    """(claims, abstain, parse_ok, dropped) from the model's text. Claims that break the claim schema
    are dropped and counted, never repaired; abstentions without a topic are dropped silently."""
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
        refs = item.get("evidence_ref")
        claim = {"level": item.get("level"), "type": item.get("type"), "text": str(item["text"]).strip(),
                 "region_ref": item.get("region_ref") if isinstance(item.get("region_ref"), str) else None,
                 "evidence_ref": [str(f) for f in refs] if isinstance(refs, list) else refs, "stated_conf": None}
        for field in ("change_type", "class_before", "class_after", "transect_ref", "shoreline_change", "strip"):
            if item.get(field) is not None:
                claim[field] = item[field]
        if validate_claim(claim):
            dropped += 1
            continue
        claims.append(claim)
    for i, c in enumerate(claims, 1):
        c["claim_id"] = f"c{i}"
    abstain = [{"topic": str(a["topic"]).strip(), "reason": str(a.get("reason", "")).strip()}
               for a in raw.get("abstain") or [] if isinstance(a, dict) and str(a.get("topic", "")).strip()]
    return claims, abstain, True, dropped


def run_gated(vlm, key: str, ev: dict, before_window: list[str], after_window: list[str], images: list[bytes],
              chip_set: str = "rgb_swir") -> dict:
    """One gated report for one box. `key` names the box for replay files. Raises VLMUnavailable."""
    out = vlm.generate(build_prompt(ev, before_window, after_window, chip_set), images, max_new_tokens=900,
                       replay_key=f"{PROMPT_VERSION}:{key}")
    claims, abstain, parse_ok, dropped = parse_report(out["text"])
    return {"raw": out["text"], "model": out["model"], "claims": claims, "abstain": abstain, "parse_ok": parse_ok,
            "dropped": dropped, "prompt_version": PROMPT_VERSION, "chips": chip_set}
