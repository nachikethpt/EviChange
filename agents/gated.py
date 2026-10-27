"""Gated report arm (Phase 4): the Geo-VLM writes claims FROM THE EVIDENCE, each citing the evidence
fields it rests on, and abstains on everything the evidence can't support (causes, legality, the
future, change where none was detected). The verifier then checks every claim.

Input, as the evaluation design says: the same before/after chips as the ungated arms, plus the box's
evidence (agents/site_evidence.py: regions cut to the box, locations relative to the box). The model
answers with JSON; items that break the claim schema are dropped and counted (parse failures,
evaluation metric 8), never repaired.

Prompt is a draft (v1): develop it on boxes outside the 30 labelled sites (scripts/report_dev.py) and
freeze it with the other Phase-4 prompts. The web app's report panel still uses the rule-based
stand-in in webapp/backend/report.py until the freeze.
"""
from __future__ import annotations

import json
import re

from . import vlm_check
from .schema import CHANGE_TYPES, LOCATIONS, T_IDX, validate_claim

PROMPT_VERSION = "gated_report_v5"    # v5: 1-6 claims, region_ref only region ids (v4: 2 cut off, a transect as region); v4: no null fields; v3: never "unchanged"; v2: "presence"
EVIDENCE_FIELDS = ("id", "area_ha", "location", "mean_conf", "dNDVI", "dNDBI", "dMNDWI", "class_before", "class_after")
TRANSECT_PROMPT_FIELDS = ("id", "location", "change", "nsm", "lrr")
STRIP_PROMPT_FIELDS = ("strip", "built_ha_before", "built_ha_after")
# Region claim types always; shoreline / coastal_built (D13) only when the box's evidence has transects /
# coastal strips, so a box without coast evidence isn't invited to make claims nothing can check.
PROMPT_TYPES = ("presence", "extent", "location", "change_type", "land_cover")
PROMPT_REF_FIELDS = ("area_ha", "change_frac", "class_after", "class_before", "class_frac_after", "class_frac_before",
                     "dMNDWI", "dNDBI", "dNDVI", "location", "mean_conf")
SHORE_REF_FIELDS = ("change", "nsm", "lrr")
STRIP_REF_FIELDS = ("built_ha_before", "built_ha_after")

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
{coast_fields}
Rules:
1. Write 1 to 6 claims, no two saying the same thing. Each claim is one statement with:
   "level": "L1" whether change happened, "L2" how much or where, "L3" what kind of change or land cover;
   "type": one of {types};
   "region_ref": the id of the REGION the claim is about (from "regions"), or null for the whole box
     or a transect / coastal strip;
   "evidence_ref": the evidence fields the claim rests on, from: {fields};
   "change_type": one of {change_types}, only for type "change_type", else null;
   "class_before", "class_after": only for type "land_cover", copied from the evidence, else null.
{coast_keys}2. Copy numbers from the evidence. Do not invent numbers or regions.
3. Name a change type only where its index moved beyond +/-{t} in that direction. Every region in the
   evidence is a detected change: never say a region, or anything in it, did not change. If its
   class_before equals class_after, say the land cover stayed that class and state what its indices
   show instead (e.g. "stayed water, but the water index fell by 0.24").
4. If "regions" is empty, make one L1 claim of type "presence" that no land-cover change was detected
   in the box (evidence_ref ["change_frac"]) and no other claim about land-cover change.
5. Never say what caused the change, what it is for, whether it is legal, who did it, or what will
   happen next. Put each such topic, and anything else the evidence can't support, under "abstain".
{coast_rules}
Answer with JSON only, no other text. Leave out every field that does not apply to a claim (no null fields):
{{"claims": [{{"level": ..., "type": ..., "text": ..., "region_ref": ..., "evidence_ref": [...],
              "change_type": ..., "class_before": ..., "class_after": ...{coast_json}}}],
 "abstain": [{{"topic": ..., "reason": ...}}]}}"""


TRANSECT_TEXT = """- transects: shoreline transects (lines across the coast) crossing the box. id: the transect's name.
  location: where in the box. change: how the shoreline moved between the two dates, "advancing" (land
  moved seaward), "retreating" (sea moved landward), "stable", "unconfirmed" (the radar saw a move the
  images do not confirm) or "too_few" (not measured). nsm: movement in metres, seaward positive.
  lrr: the same as metres per year.
"""
STRIP_TEXT = """- coastal_strips: built-up area near the shore. strip: "0-200" or "200-500" metres from the shoreline.
  built_ha_before, built_ha_after: hectares of built-up land in that strip at each date.
"""
TRANSECT_KEYS = """   "transect_ref", "shoreline_change": only for type "shoreline": the transect id, and its change
     ("advancing", "retreating" or "stable"), else null;
"""
STRIP_KEYS = """   "strip": only for type "coastal_built": "0-200", "200-500" or "0-500", else null;
"""
TRANSECT_RULES = """6. Make shoreline claims only from transects whose change is advancing, retreating or stable, citing
   one transect each. Put "unconfirmed" and "too_few" transects under "abstain".
"""
STRIP_RULES = """{n}. Make coastal_built claims only from the coastal_strips numbers: say which strip, and the change.
"""


def coast_parts(ev: dict) -> tuple[bool, bool]:
    """(has transects, has coastal strips) in this box's evidence."""
    return bool(ev.get("transects")), bool(ev.get("coastal_strips"))


def evidence_for_prompt(ev: dict) -> str:
    """The evidence as the model sees it: change_frac, the regions' prompt fields (rounded) and, when
    the box has them, its transects and coastal strips."""
    regions = []
    for r in ev["regions"]:
        row = {k: r.get(k) for k in EVIDENCE_FIELDS}
        for k in ("mean_conf", "dNDVI", "dNDBI", "dMNDWI"):
            if row[k] is not None:
                row[k] = round(float(row[k]), 3)
        regions.append(row)
    out = {"change_frac": ev["change_frac"], "regions": regions}
    shore, strips = coast_parts(ev)
    if shore:
        out["transects"] = [{k: t.get(k) for k in TRANSECT_PROMPT_FIELDS} for t in ev["transects"]]
    if strips:
        out["coastal_strips"] = [{k: c.get(k) for k in STRIP_PROMPT_FIELDS} for c in ev["coastal_strips"]]
    return json.dumps(out, indent=1)


def build_prompt(ev: dict, before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = vlm_check.chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    text = vlm_check._CHIP_TEXT
    labels = [f"{n}. {when}, {text[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(text[kind][2] + "\n" for kind in kinds if text[kind][2])
    shore, strips = coast_parts(ev)
    types = PROMPT_TYPES + (("shoreline",) if shore else ()) + (("coastal_built",) if strips else ())
    fields = PROMPT_REF_FIELDS + (SHORE_REF_FIELDS if shore else ()) + (STRIP_REF_FIELDS if strips else ())
    coast_json = (', "transect_ref": ..., "shoreline_change": ...' if shore else "") + (', "strip": ...' if strips else "")
    return PROMPT.format(count=vlm_check._COUNT[2 * len(kinds)], images="   ".join(labels), keys=keys,
                         before=" to ".join(before_window), after=" to ".join(after_window),
                         evidence=evidence_for_prompt(ev), locations=", ".join(LOCATIONS), t=f"{T_IDX:.2f}",
                         types=", ".join(types), fields=", ".join(fields),
                         change_types=", ".join(CHANGE_TYPES),
                         coast_fields=(TRANSECT_TEXT if shore else "") + (STRIP_TEXT if strips else ""),
                         coast_keys=(TRANSECT_KEYS if shore else "") + (STRIP_KEYS if strips else ""),
                         coast_rules=(TRANSECT_RULES if shore else "") + (STRIP_RULES.format(n=7 if shore else 6) if strips else ""),
                         coast_json=coast_json)


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
    out = vlm.generate(build_prompt(ev, before_window, after_window, chip_set), images, max_new_tokens=1500,
                       replay_key=f"{PROMPT_VERSION}:{key}")
    claims, abstain, parse_ok, dropped = parse_report(out["text"])
    return {"raw": out["text"], "model": out["model"], "claims": claims, "abstain": abstain, "parse_ok": parse_ok,
            "dropped": dropped, "prompt_version": PROMPT_VERSION, "chips": chip_set}
