"""Deterministic claim verifier: checks one claim against the evidence and returns
a verdict plus a reason code (agents/schema.py REASONS).

This is the automatic half of the evaluation. It is scored against human
reference labels (docs/PLAN.md, evaluation plan), never treated as ground truth
itself — otherwise the gated condition would be graded by its own rules.

Claims carry structure where the producer knows it (region_ref, evidence_ref,
change_type). Free-text claims from the ungated extractor may lack it, so the
verifier falls back to reading location words, change-type keywords, and
quoted numbers from the text. Rules run in order; the first decisive one wins:

  1 malformed claim                  -> uncertain   malformed_claim
  2 L4 (cause/intent/legality/future)-> unsupported beyond_evidence
  3 cites a field not in evidence    -> unsupported cites_missing_evidence
  4 quotes an index value wrongly    -> unsupported misquoted_evidence
  5 L1 presence vs change mask       -> denies_detected_change / change_not_in_evidence
  6 resolve region(s): region_ref, else location words in the text
  7 L2 extent / location             -> extent_mismatch / location_mismatch / ...
  8 L3 change type vs index sign     -> contradicts_index / below_threshold
  9 supported but weak detection     -> uncertain   low_detection_confidence
"""
from __future__ import annotations

import re
from typing import NamedTuple

from .schema import CHANGE_TYPES, CONF_MIN, EVIDENCE_REF_FIELDS, T_IDX, region_change_types, validate_claim

AREA_REL_TOL = 0.25      # stated hectares may differ from evidence by 25%
FRAC_ABS_TOL = 0.02      # stated change fraction may differ by 2 percentage points ...
FRAC_REL_TOL = 0.25      # ... or 25% relative, whichever is larger
QUOTE_ABS_TOL = 0.02     # a quoted index value may differ by rounding only


class Verdict(NamedTuple):
    verdict: str
    reason: str


_LOCATION_RE = re.compile(
    r"\b(?:(north|south)[\s-]?(east|west)(?:ern)?|(north|south|east|west)(?:ern)?|cent(?:re|er|ral)|middle)\b", re.I)
_DENIES_RE = re.compile(
    r"\bno\s+(?:significant\s+|clear\s+|visible\s+|detectable\s+|major\s+|notable\s+)?(?:land[\s-]cover\s+)?changes?\b"
    r"|\bunchanged\b|\bnothing\s+(?:has\s+)?changed\b|\bremain(?:s|ed)?\s+(?:largely\s+|mostly\s+)?(?:the\s+same|stable|unchanged)\b",
    re.I)
_HA_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:ha\b|hectares?\b)", re.I)
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.I)
_QUOTE_RE = re.compile(r"\b(dNDVI|dNDBI|dMNDWI)\s*[:=]?\s*([+-]?\d*\.\d+)")

_VEG = re.compile(r"\b(vegetat|forest|tree|green|crop|plant|grass|canopy)", re.I)
_BARE = re.compile(r"\b(built|urban|building|construct|bare|soil|exposed|excavat|pit|spoil|road|paved|concrete|settlement)", re.I)
_WATER = re.compile(r"\b(water|reservoir|lake|pond|flood|river|wetland|inundat)", re.I)
_LOSS = re.compile(r"\b(loss|lost|los[ei]|clear|remov|replac|declin|decreas|reduc|destroy|disappear|fewer|less|drain|dr(?:y|ied)|shr[iau]nk|demolish)", re.I)
_GAIN = re.compile(r"\b(gain|increas|regrow|recover|greener|more|new|expan|appear|planted|reforest)", re.I)


def claimed_locations(text: str) -> set[str]:
    """Location words in the text, normalized to schema.LOCATIONS ("northern" -> "north")."""
    found = set()
    for m in _LOCATION_RE.finditer(text):
        if m.group(1):
            found.add(f"{m.group(1).lower()}-{m.group(2).lower()}")
        elif m.group(3):
            found.add(m.group(3).lower())
        else:
            found.add("centre")
    return found


def _location_matches(claimed: str, actual: str) -> bool:
    # "in the south" covers south, south-east and south-west; compound directions must match exactly
    return claimed == actual or ("-" not in claimed and claimed in actual.split("-"))


def claimed_change_types(claim: dict) -> set[str]:
    """Structured change_type if the producer set one, otherwise keywords in the text."""
    if claim.get("change_type"):
        return {claim["change_type"]}
    text = claim.get("text", "")
    types = set()
    if _VEG.search(text):
        if _LOSS.search(text):
            types.add("vegetation_loss")
        elif _GAIN.search(text):
            types.add("vegetation_gain")
    if _BARE.search(text):
        # "forest replaced with exposed soil": the loss word belongs to the vegetation, so bare
        # surface only counts as decreasing when there is no vegetation-loss reading already
        if _LOSS.search(text) and "vegetation_loss" not in types:
            types.add("built_up_decrease")
        else:
            types.add("built_up_increase")
    if _WATER.search(text):
        types.add("water_decrease" if _LOSS.search(text) and not _GAIN.search(text) else "water_increase")
    return types


def _check_extent(text: str, area_ha: float, change_frac: float | None) -> Verdict | None:
    """None when the text states no checkable number."""
    stated = False
    for m in _HA_RE.finditer(text):
        stated = True
        value = float(m.group(1).replace(",", ""))
        if abs(value - area_ha) > AREA_REL_TOL * max(area_ha, 1.0):
            return Verdict("unsupported", "extent_mismatch")
    if change_frac is not None:
        for m in _PCT_RE.finditer(text):
            stated = True
            value, actual = float(m.group(1)) / 100, change_frac
            if abs(value - actual) > max(FRAC_ABS_TOL, FRAC_REL_TOL * actual):
                return Verdict("unsupported", "extent_mismatch")
    return Verdict("supported", "extent_matches") if stated else None


def _with_confidence(verdict: Verdict, regions: list[dict], min_conf: float) -> Verdict:
    if verdict.verdict == "supported" and regions and max(r["mean_conf"] for r in regions) < min_conf:
        return Verdict("uncertain", "low_detection_confidence")
    return verdict


def verify(claim: dict, ev: dict, min_conf: float = CONF_MIN) -> Verdict:
    if validate_claim(claim):
        return Verdict("uncertain", "malformed_claim")
    level, ctype, text = claim["level"], claim["type"], claim["text"]
    regions = ev.get("regions", [])
    by_id = {r["id"]: r for r in regions}

    if level == "L4" or ctype == "cause":
        return Verdict("unsupported", "beyond_evidence")
    if any(ref not in EVIDENCE_REF_FIELDS for ref in claim.get("evidence_ref") or []):
        return Verdict("unsupported", "cites_missing_evidence")

    # quoted index values must match the region they are about (or, if unlocated, some region)
    ref_region = by_id.get(claim.get("region_ref"))
    for field, value in _QUOTE_RE.findall(text):
        pool = [ref_region] if ref_region else regions
        if not any(abs(r[field] - float(value)) <= QUOTE_ABS_TOL for r in pool):
            return Verdict("unsupported", "misquoted_evidence")

    has_change = bool(regions) or ev.get("change_frac", 0) > 0
    if level == "L1":
        if _DENIES_RE.search(text):
            return Verdict("unsupported", "denies_detected_change") if has_change else Verdict("supported", "consistent_with_mask")
        return Verdict("supported", "consistent_with_mask") if has_change else Verdict("unsupported", "change_not_in_evidence")

    # ---- resolve which region(s) the claim is about
    locations = claimed_locations(text)
    if claim.get("region_ref") is not None:
        if ref_region is None:
            return Verdict("unsupported", "unknown_region")
        if locations and not any(_location_matches(loc, ref_region["location"]) for loc in locations):
            return Verdict("unsupported", "location_mismatch")
        candidates = [ref_region]
    elif locations:
        candidates = [r for r in regions if any(_location_matches(loc, r["location"]) for loc in locations)]
        if not candidates:
            return Verdict("unsupported", "no_change_at_location")
    else:
        candidates = []   # unlocated: judged against all regions below

    if _DENIES_RE.search(text):
        # "no change in the north" — wrong if any region there changed
        return Verdict("unsupported", "denies_detected_change") if (candidates or (not locations and has_change)) \
            else Verdict("supported", "consistent_with_mask")

    if level == "L2":
        if ctype == "extent" or not candidates:
            if candidates:
                area = sum(r["area_ha"] for r in candidates)
                frac = None
            else:
                area, frac = sum(r["area_ha"] for r in regions), ev.get("change_frac")
            result = _check_extent(text, area, frac)
            if result is None:
                return Verdict("uncertain", "extent_not_quantified" if ctype == "extent" else "unlocated_claim")
            return _with_confidence(result, candidates, min_conf)
        result = _check_extent(text, sum(r["area_ha"] for r in candidates), None)
        if result is not None and result.verdict == "unsupported":
            return result
        return _with_confidence(Verdict("supported", "region_located"), candidates, min_conf)

    # ---- L3 change type
    types = claimed_change_types(claim)
    if not types:
        return Verdict("uncertain", "type_not_checkable")
    pool = candidates or regions
    if not pool:
        return Verdict("unsupported", "change_not_in_evidence")
    supporting = [r for r in pool if types <= set(region_change_types(r))]
    if supporting:
        return _with_confidence(Verdict("supported", "index_supports_type"), supporting, min_conf)
    for name in types:
        field, sign, _ = CHANGE_TYPES[name]
        if all(-sign * r[field] > T_IDX for r in pool):
            return Verdict("unsupported", "contradicts_index")
    return Verdict("unsupported", "below_threshold")
