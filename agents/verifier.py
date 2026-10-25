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
  4b shoreline (D13) vs the transect statistics (evidence transects[])
                                     -> shoreline_matches / shoreline_mismatch / shoreline_unconfirmed /
                                        extent_mismatch / unknown_transect / no_transect_at_location /
                                        shoreline_not_in_evidence
  4c coastal_built (D13) vs the coastal-strip built areas (evidence coastal_strips[])
                                     -> coastal_built_matches / coastal_built_mismatch / extent_mismatch /
                                        coastal_not_in_evidence
  5 L1 presence vs change mask       -> denies_detected_change / change_not_in_evidence
  6 resolve region(s): region_ref, else location words in the text
  7 L2 extent / location             -> extent_mismatch / location_mismatch / ...
  8 L3 change type vs index sign     -> contradicts_index / below_threshold
  8b land_cover (D13) vs the region's Dynamic World classes
                                     -> class_transition_matches / class_transition_mismatch /
                                        class_not_in_evidence
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
SHORE_ABS_TOL_M = 20     # stated shoreline movement may differ from nsm by 2 Sentinel pixels ...
SHORE_REL_TOL = 0.25     # ... or 25% relative, whichever is larger; a stated rate by its 95 % CI or 25%
COASTAL_MIN_HA = 0.5     # built-area change below this is "no clear change" (provisional until Phase 12 is checked)


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
_BARE = re.compile(r"\b(built|urban|building|construct|bare(?!ly)|soil|exposed|excavat|pit|spoil|road|paved|concrete|settlement)", re.I)
_WATER = re.compile(r"\b(water|reservoir|lake|pond|flood|river|wetland|inundat)", re.I)
_LOSS = re.compile(r"\b(loss|lost|los[ei]|clear(?:ed|ing|ance|s\b|-?cut)|remov|replac|declin|decreas|reduc|destroy|disappear|fewer|less|drain|dr(?:y|ied)|shr[iau]nk|demolish)", re.I)
_GAIN = re.compile(r"\b(gain|increas|(?:re)?gr[eo]w|recover|greener|more|new|expan|appear|planted|reforest)", re.I)


# Words that name a Dynamic World class. Deliberately a short, conservative list: a word that is
# not here makes the claim "uncertain", never "unsupported".
_CLASS_WORDS = {
    "trees": r"trees?|forests?|woodland|canopy",
    "grass": r"grass(?:es|land)?|meadows?|pasture",
    "crops": r"crops?|cropland|farmland|paddy|paddies|agricultur\w*",
    "shrub_and_scrub": r"shrub(?:s|land)?|scrub|bush(?:es)?",
    "flooded_vegetation": r"flooded[\s-]vegetation|mangroves?|marsh(?:es)?|swamp",
    "built": r"built(?:[\s-]up)?|urban|buildings?|construction|settlements?|roads?|paved|concrete",
    "bare": r"bare|soil|exposed|excavat\w*|pit|spoil|quarry",
    "water": r"water|reservoir|lake|pond|river|sea|lagoon",
    "snow_and_ice": r"snow|ice",
}
_CLASS_RES = {name: re.compile(rf"\b(?:{words})\b", re.I) for name, words in _CLASS_WORDS.items()}
# "A was replaced by / with B", "from A to B", "A became B", "A -> B": the first class is the "before"
_FORWARD_RE = re.compile(
    r"\bfrom\b.+\bto\b|→|->"
    r"|\b(?:became|becomes|becoming|turned\s+into|turned\s+to|convert(?:ed|s|ing)?\s+(?:in)?to"
    r"|chang(?:ed|es|ing)\s+(?:in)?to|transform(?:ed|s|ing)?\s+(?:in)?to|cleared\s+for|gave\s+way\s+to"
    r"|replac(?:ed|es|ing)\s+(?:by|with))\b", re.I)
# "B replaced A", "B took over A": active voice, so the first class is the "after"
_REVERSE_RE = re.compile(r"\b(?:replac(?:ed|es|ing)|took\s+over|taking\s+over|displac(?:ed|es|ing))\b", re.I)


def claimed_class_transition(claim: dict) -> tuple[str | None, str | None]:
    """(class_before, class_after) a land_cover claim states; None where it states nothing.

    Structured class_before / class_after win. Otherwise the text is read only when it names exactly
    two classes with a clear direction ("trees were replaced by bare ground", "from trees to built").
    Anything ambiguous returns (None, None), which the verifier turns into "uncertain".
    """
    before, after = claim.get("class_before"), claim.get("class_after")
    if before is not None or after is not None:
        return before, after
    text = claim.get("text", "")
    found = sorted((m.start(), name) for name, rx in _CLASS_RES.items() if (m := rx.search(text)))
    names = [name for _, name in found]
    if len(names) != 2:
        return None, None
    if _FORWARD_RE.search(text):
        return names[0], names[1]
    if _REVERSE_RE.search(text):
        return names[1], names[0]
    return None, None


_SHORE_ADV = re.compile(r"\b(advanc|seaward|accret|reclaim|prograd|grew|grown|extend|built\s+out|gain)", re.I)
_SHORE_RET = re.compile(r"\b(retreat|landward|erod|erosion|recede|receded|receding|lost|loss|eaten)", re.I)
_STABLE = re.compile(r"\b(stable|unchanged|did\s+not\s+(?:move|change)|no\s+(?:clear\s+|significant\s+|net\s+)?"
                     r"(?:shoreline\s+)?(?:change|movement))", re.I)
_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)\s*(?:/|per\s+)\s*(?:yr|year|a)\b", re.I)
_DIST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|kilomet(?:re|er)s?|m|met(?:re|er)s?)\b", re.I)
_STRIP_RE = re.compile(r"\b(200|500)\b(?!\s*(?:ha\b|hectares?|%))", re.I)
_BUILT_UP = re.compile(r"\b(grew|grow|increas|expan|new|more|added|rose|risen)", re.I)
_BUILT_DOWN = re.compile(r"\b(decreas|declin|shr[iau]nk|fewer|less|lost|demolish|removed|fell)", re.I)
_TO_FROM_RE = re.compile(r"\b(to|from)\s+(?:about\s+|around\s+|roughly\s+|approximately\s+|~\s*)?$", re.I)


def claimed_shoreline(claim: dict) -> tuple[str | None, list[float], list[float]]:
    """(direction, distances m, rates m/yr) a shoreline claim states. Structured shoreline_change wins
    for the direction; a text naming both directions states none."""
    text = claim.get("text", "")
    direction = claim.get("shoreline_change")
    if direction is None:
        if _STABLE.search(text):
            direction = "stable"
        else:
            adv, ret = bool(_SHORE_ADV.search(text)), bool(_SHORE_RET.search(text))
            direction = "advancing" if adv and not ret else "retreating" if ret and not adv else None
    rates = [float(m.group(1)) for m in _RATE_RE.finditer(text)]
    rest = _RATE_RE.sub(" ", text)
    dists = [float(m.group(1)) * (1000 if m.group(2).lower().startswith("k") else 1) for m in _DIST_RE.finditer(rest)]
    return direction, dists, rates


def claimed_strip(claim: dict) -> str:
    """The coastal strip a coastal_built claim is about: "0-200", "200-500" or "0-500" (both)."""
    if claim.get("strip"):
        return claim["strip"]
    found = {m.group(1) for m in _STRIP_RE.finditer(claim.get("text", ""))}
    if found == {"200", "500"}:
        return "200-500"
    return "0-200" if found == {"200"} else "0-500"


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


def _check_land_cover(claim: dict, pool: list[dict], min_conf: float) -> Verdict:
    """A land_cover claim against the Dynamic World classes of the region(s) it is about (D10)."""
    before, after = claimed_class_transition(claim)
    if before is None and after is None:
        return Verdict("uncertain", "type_not_checkable")
    if not pool:
        return Verdict("unsupported", "change_not_in_evidence")
    with_classes = [r for r in pool if r.get("class_before") is not None and r.get("class_after") is not None]
    if not with_classes:
        return Verdict("uncertain", "class_not_in_evidence")   # no usable Dynamic World scene: never a guess
    supporting = [r for r in with_classes
                  if (before is None or r["class_before"] == before) and (after is None or r["class_after"] == after)]
    if supporting:
        return _with_confidence(Verdict("supported", "class_transition_matches"), supporting, min_conf)
    return Verdict("unsupported", "class_transition_mismatch")


def _shoreline_numbers_match(tr: dict, dists: list[float], rates: list[float]) -> bool:
    if (dists and tr.get("nsm") is None) or (rates and tr.get("lrr") is None):
        return False
    nsm, lrr = abs(tr.get("nsm") or 0.0), abs(tr.get("lrr") or 0.0)
    rate_tol = max(tr.get("ci95") or 0.0, SHORE_REL_TOL * lrr, 1.0)
    return (all(abs(d - nsm) <= max(SHORE_ABS_TOL_M, SHORE_REL_TOL * nsm) for d in dists)
            and all(abs(r - lrr) <= rate_tol for r in rates))


def _check_shoreline(claim: dict, ev: dict, locations: set[str]) -> Verdict:
    """A shoreline claim against the transect statistics (D11): the confirmed trend, nsm and lrr."""
    transects = ev.get("transects") or []
    if not transects:
        return Verdict("uncertain", "shoreline_not_in_evidence")
    if claim.get("transect_ref") is not None:
        ref = next((t for t in transects if t["id"] == claim["transect_ref"]), None)
        if ref is None:
            return Verdict("unsupported", "unknown_transect")
        if locations and not any(_location_matches(loc, ref["location"]) for loc in locations):
            return Verdict("unsupported", "location_mismatch")
        pool = [ref]
    elif locations:
        pool = [t for t in transects if any(_location_matches(loc, t["location"]) for loc in locations)]
        if not pool:
            return Verdict("unsupported", "no_transect_at_location")
    else:
        pool = transects
    direction, dists, rates = claimed_shoreline(claim)
    if direction is None and not dists and not rates:
        return Verdict("uncertain", "type_not_checkable")
    measured = [t for t in pool if t["change"] != "too_few"]
    if not measured:
        return Verdict("uncertain", "shoreline_not_in_evidence")
    if direction == "stable":
        # like "no change": wrong if any transect it covers moved
        if any(t["change"] in ("advancing", "retreating") for t in measured):
            return Verdict("unsupported", "shoreline_mismatch")
        if any(t["change"] == "unconfirmed" for t in measured):
            return Verdict("uncertain", "shoreline_unconfirmed")
        return Verdict("supported", "shoreline_matches")
    if direction is None:
        supporting = measured
    else:
        supporting = [t for t in measured if t["change"] == direction]
        if not supporting:
            sign = 1 if direction == "advancing" else -1
            if any(t["change"] == "unconfirmed" and sign * (t.get("lrr") or 0) > 0 for t in measured):
                return Verdict("uncertain", "shoreline_unconfirmed")
            return Verdict("unsupported", "shoreline_mismatch")
    if (dists or rates) and not any(_shoreline_numbers_match(t, dists, rates) for t in supporting):
        return Verdict("unsupported", "extent_mismatch")
    return Verdict("supported", "shoreline_matches")


def _check_coastal_built(claim: dict, ev: dict, locations: set[str]) -> Verdict:
    """A coastal_built claim against the built area in the coastal strips (D11, Phase 12)."""
    strips = ev.get("coastal_strips") or []
    if locations:
        strips = [s for s in strips if s.get("location") and any(_location_matches(loc, s["location"]) for loc in locations)]
    which = claimed_strip(claim)
    names = ("0-200", "200-500") if which == "0-500" else (which,)
    pool = [s for s in strips if s["strip"] in names]
    if not all(any(s["strip"] == n for s in pool) for n in names):
        return Verdict("uncertain", "coastal_not_in_evidence")
    before = sum(s["built_ha_before"] for s in pool)
    after = sum(s["built_ha_after"] for s in pool)
    delta = after - before
    text = claim.get("text", "")
    if _STABLE.search(text) or _DENIES_RE.search(text):
        direction = 0
    else:
        up, down = bool(_BUILT_UP.search(text)), bool(_BUILT_DOWN.search(text))
        direction = 1 if up and not down else -1 if down and not up else None
    amounts = []
    for m in _HA_RE.finditer(text):
        word = _TO_FROM_RE.search(text[:m.start()])
        actual = {"to": after, "from": before}.get(word.group(1).lower() if word else "", abs(delta))
        amounts.append((float(m.group(1).replace(",", "")), actual))
    if direction is None and not amounts:
        return Verdict("uncertain", "type_not_checkable")
    changed = abs(delta) >= COASTAL_MIN_HA
    if direction == 0:
        return Verdict("unsupported", "coastal_built_mismatch") if changed else Verdict("supported", "coastal_built_matches")
    if direction is not None and (not changed or direction * delta < 0):
        return Verdict("unsupported", "coastal_built_mismatch")
    if any(abs(value - actual) > AREA_REL_TOL * max(actual, 1.0) for value, actual in amounts):
        return Verdict("unsupported", "extent_mismatch")
    return Verdict("supported", "coastal_built_matches")


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

    # shoreline and coastal-strip claims are about their own evidence, not the change regions
    if ctype == "shoreline":
        return _check_shoreline(claim, ev, claimed_locations(text))
    if ctype == "coastal_built":
        return _check_coastal_built(claim, ev, claimed_locations(text))

    has_change = bool(regions) or ev.get("change_frac", 0) > 0
    locations = claimed_locations(text)
    if level == "L1":
        if locations:   # "no change in the south" is about the south only
            has_change = any(_location_matches(loc, r["location"]) for r in regions for loc in locations)
        if _DENIES_RE.search(text):
            return Verdict("unsupported", "denies_detected_change") if has_change else Verdict("supported", "consistent_with_mask")
        if has_change:
            return Verdict("supported", "consistent_with_mask")
        return Verdict("unsupported", "no_change_at_location" if locations else "change_not_in_evidence")

    # ---- resolve which region(s) the claim is about
    if claim.get("region_ref") is not None:
        if ref_region is None:
            return Verdict("unsupported", "unknown_region")
        if locations and not any(_location_matches(loc, ref_region["location"]) for loc in locations):
            return Verdict("unsupported", "location_mismatch")
        candidates = [ref_region]
    elif locations:
        candidates = [r for r in regions if any(_location_matches(loc, r["location"]) for loc in locations)]
        if not candidates and not _DENIES_RE.search(text):
            return Verdict("unsupported", "no_change_at_location")
    else:
        candidates = []   # unlocated: judged against all regions below

    if _DENIES_RE.search(text):
        # "no change in the north" — wrong if any region there changed
        return Verdict("unsupported", "denies_detected_change") if (candidates or (not locations and has_change)) \
            else Verdict("supported", "consistent_with_mask")

    if ctype == "land_cover":
        return _check_land_cover(claim, candidates or regions, min_conf)

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