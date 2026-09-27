"""The one EviChange data contract: change regions, evidence, claims, verdicts.

Every producer and consumer (the Earth Engine and labeling notebooks, the agent
pipeline, the web app, the evaluation scripts) validates against this module
instead of keeping its own list of field names. If a field changes, it changes
here and the tests catch every place that disagrees.

    region   {id, area_ha, mean_conf, dNDVI, dNDBI, dMNDWI, location,
              [date_before, date_after, source]}
    evidence {pair_id, dates, source, change_frac, regions[]}
    claim    {claim_id, level, type, text, region_ref, evidence_ref[], stated_conf,
              [change_type], [verdict, verdict_reason]}
"""
from __future__ import annotations

from typing import Iterable

T_IDX = 0.10      # |index change| at or below this is "no clear change" (notebooks, report, verifier)
CONF_MIN = 0.5    # detections with mean_conf below this only support "uncertain" claims

CONDITIONS = ("template", "ungated", "gated")
LEVELS = ("L1", "L2", "L3", "L4")
CLAIM_TYPES = ("presence", "extent", "location", "change_type", "cause", "other")
VERDICTS = ("supported", "unsupported", "uncertain")
LOCATIONS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west", "centre")
INDEX_FIELDS = ("dNDVI", "dNDBI", "dMNDWI")

REGION_FIELDS = ("id", "area_ha", "mean_conf", "dNDVI", "dNDBI", "dMNDWI", "location")
REGION_PROVENANCE_FIELDS = ("date_before", "date_after", "source")
EVIDENCE_REF_FIELDS = frozenset({"change_frac", "area_ha", "location", "mean_conf", *INDEX_FIELDS})

# change_type -> (evidence field, sign the field must have beyond T_IDX, human label)
CHANGE_TYPES = {
    "vegetation_loss": ("dNDVI", -1, "vegetation loss"),
    "vegetation_gain": ("dNDVI", +1, "vegetation gain"),
    "built_up_increase": ("dNDBI", +1, "increase in built-up or bare surface"),
    "built_up_decrease": ("dNDBI", -1, "decrease in built-up or bare surface"),
    "water_increase": ("dMNDWI", +1, "increase in surface water"),
    "water_decrease": ("dMNDWI", -1, "decrease in surface water"),
}

# Verdict reason codes — aggregated in the evaluation and shown in the web app.
REASONS = {
    "consistent_with_mask": "Agrees with the change mask.",
    "region_located": "The cited region exists at the stated location.",
    "extent_matches": "Stated area/fraction matches the evidence within tolerance.",
    "index_supports_type": "The spectral index change supports this change type.",
    "beyond_evidence": "Causes, intent, legality and forecasts cannot be established from the evidence.",
    "denies_detected_change": "Claims no change, but the evidence shows change.",
    "change_not_in_evidence": "Claims change, but the evidence shows none.",
    "cites_missing_evidence": "Cites an evidence field that does not exist.",
    "misquoted_evidence": "Quotes an index value that differs from the evidence.",
    "unknown_region": "Refers to a region id that is not in the evidence.",
    "location_mismatch": "The stated location does not match the cited region.",
    "no_change_at_location": "No detected change region at the stated location.",
    "extent_mismatch": "Stated area/fraction disagrees with the evidence.",
    "contradicts_index": "The spectral index moved in the opposite direction.",
    "below_threshold": "The spectral index change is too small to support this.",
    "extent_not_quantified": "Extent is stated without a checkable number.",
    "type_not_checkable": "The change type cannot be mapped to any evidence field.",
    "unlocated_claim": "The claim cannot be tied to any detected region.",
    "low_detection_confidence": "The supporting region's detection confidence is below the threshold.",
    "malformed_claim": "The claim is missing required fields.",
}


class SchemaError(ValueError):
    """Raised by check() when data does not match the contract."""


def region_change_types(region: dict) -> list[str]:
    """Change types the region's index deltas clearly support (|delta| > T_IDX, right sign)."""
    return [name for name, (field, sign, _) in CHANGE_TYPES.items() if sign * region[field] > T_IDX]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_region(region: object) -> list[str]:
    if not isinstance(region, dict):
        return ["region is not an object"]
    errors = [f"missing field '{f}'" for f in REGION_FIELDS if f not in region]
    for f in ("area_ha", "mean_conf", *INDEX_FIELDS):
        if f in region and not _is_number(region[f]):
            errors.append(f"'{f}' must be a number, got {region[f]!r}")
    if _is_number(region.get("area_ha")) and region["area_ha"] < 0:
        errors.append("'area_ha' must be >= 0")
    if _is_number(region.get("mean_conf")) and not 0 <= region["mean_conf"] <= 1:
        errors.append("'mean_conf' must be in [0, 1]")
    if "location" in region and region["location"] not in LOCATIONS:
        errors.append(f"'location' must be one of {LOCATIONS}, got {region['location']!r}")
    rid = region.get("id", "?")
    return [f"region {rid}: {e}" for e in errors]


def validate_evidence(ev: object) -> list[str]:
    if not isinstance(ev, dict):
        return ["evidence is not an object"]
    errors = [f"evidence: missing field '{f}'" for f in ("change_frac", "regions") if f not in ev]
    if "change_frac" in ev and not (_is_number(ev["change_frac"]) and 0 <= ev["change_frac"] <= 1):
        errors.append("evidence: 'change_frac' must be a number in [0, 1]")
    regions = ev.get("regions", [])
    if not isinstance(regions, list):
        return errors + ["evidence: 'regions' must be a list"]
    for r in regions:
        errors += validate_region(r)
    ids = [r.get("id") for r in regions if isinstance(r, dict)]
    if len(ids) != len(set(ids)):
        errors.append("evidence: region ids are not unique")
    return errors


def validate_claim(claim: object) -> list[str]:
    if not isinstance(claim, dict):
        return ["claim is not an object"]
    errors = [f"missing field '{f}'" for f in ("level", "type", "text") if f not in claim]
    if "level" in claim and claim["level"] not in LEVELS:
        errors.append(f"'level' must be one of {LEVELS}, got {claim['level']!r}")
    if "type" in claim and claim["type"] not in CLAIM_TYPES:
        errors.append(f"'type' must be one of {CLAIM_TYPES}, got {claim['type']!r}")
    refs = claim.get("evidence_ref", [])
    if not isinstance(refs, list):
        errors.append("'evidence_ref' must be a list")
    if claim.get("change_type") is not None and claim["change_type"] not in CHANGE_TYPES:
        errors.append(f"'change_type' must be one of {tuple(CHANGE_TYPES)}, got {claim['change_type']!r}")
    if claim.get("verdict") is not None and claim["verdict"] not in VERDICTS:
        errors.append(f"'verdict' must be one of {VERDICTS}, got {claim['verdict']!r}")
    if claim.get("verdict_reason") is not None and claim["verdict_reason"] not in REASONS:
        errors.append(f"unknown 'verdict_reason' {claim['verdict_reason']!r}")
    return [f"claim {claim.get('claim_id', '?')}: {e}" for e in errors]


def validate_change_regions(fc: object) -> list[str]:
    """The GeoJSON FeatureCollection the map shows and import_geojson.py accepts."""
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        return ["not a GeoJSON FeatureCollection"]
    errors = []
    for i, feature in enumerate(fc.get("features", [])):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon", "Point"):
            errors.append(f"feature {i}: missing or unsupported geometry")
        errors += validate_region(feature.get("properties") if isinstance(feature, dict) else None)
    ids = [f.get("properties", {}).get("id") for f in fc.get("features", []) if isinstance(f, dict)]
    if len(ids) != len(set(ids)):
        errors.append("region ids are not unique")
    return errors


def check(errors: Iterable[str], what: str) -> None:
    errors = list(errors)
    if errors:
        raise SchemaError(f"invalid {what}: " + "; ".join(errors[:10]) + (" ..." if len(errors) > 10 else ""))
