"""The one EviChange data contract: change regions, evidence, claims, verdicts.

Every producer and consumer (the Earth Engine and labeling notebooks, the agent
pipeline, the web app, the evaluation scripts) validates against this module
instead of keeping its own list of field names. If a field changes, it changes
here and the tests catch every place that disagrees.

    region   {id, area_ha, mean_conf, dNDVI, dNDBI, dMNDWI, location,
              [date_before, date_after, source],
              [class_before, class_after, class_frac_before, class_frac_after] (D10)}
    evidence {pair_id, dates, source, change_frac, regions[],
              [transects[]], [coastal_strips[]] (D13)}
    transect {id, location, change, nsm, lrr, ci95}   shoreline statistics per transect (D11)
    strip    {strip, built_ha_before, built_ha_after, [location]}   built area in a coastal strip (D11)
    claim    {claim_id, level, type, text, region_ref, evidence_ref[], stated_conf,
              [change_type], [class_before, class_after] (land_cover claims, D13),
              [transect_ref, shoreline_change] (shoreline claims, D13), [strip] (coastal_built claims, D13),
              [verdict, verdict_reason]}
"""
from __future__ import annotations

from datetime import date, timedelta
from math import cos, pi
from typing import Iterable

T_IDX = 0.10      # |index change| at or below this is "no clear change" (notebooks, report, verifier)
CONF_MIN = 0.2    # detections with mean_conf below this only support "uncertain" claims (D6: ~median of v3 QN regions)

CONDITIONS = ("template", "ungated", "gated")
REPORT_CONDITIONS = (*CONDITIONS, "ungated_gpt")   # D16: GPT is a report-only comparison arm, not a pipeline run
LEVELS = ("L1", "L2", "L3", "L4")
CLAIM_TYPES = ("presence", "extent", "location", "change_type", "land_cover", "shoreline", "coastal_built", "cause", "other")
VERDICTS = ("supported", "unsupported", "uncertain")
LOCATIONS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west", "centre")
INDEX_FIELDS = ("dNDVI", "dNDBI", "dMNDWI")

REGION_FIELDS = ("id", "area_ha", "mean_conf", "dNDVI", "dNDBI", "dMNDWI", "location")
LANDCOVER_CLASSES = ("water", "trees", "grass", "flooded_vegetation", "crops", "shrub_and_scrub", "built", "bare",
                     "snow_and_ice")   # Dynamic World V1 (D10); optional region fields, null when unknown
REGION_PROVENANCE_FIELDS = ("date_before", "date_after", "source")
# Shoreline transects (D11, agents/shoreline.py): `change` is the optically confirmed trend; nsm is net
# movement in m and lrr the rate in m/yr, both seaward positive; null when the transect has too few quarters
SHORELINE_CHANGES = ("advancing", "retreating", "stable", "unconfirmed", "too_few")
TRANSECT_FIELDS = ("id", "location", "change", "nsm", "lrr", "ci95")
# Coastal strips (D11, Phase 12): distance from the Oct 2024 shoreline in m
COASTAL_STRIPS = ("0-200", "200-500")
STRIP_FIELDS = ("strip", "built_ha_before", "built_ha_after")
EVIDENCE_REF_FIELDS = frozenset({"change_frac", "area_ha", "location", "mean_conf", *INDEX_FIELDS,
                                 "class_before", "class_after", "class_frac_before", "class_frac_after",
                                 "change", "nsm", "lrr", "ci95", "built_ha_before", "built_ha_after"})

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
    "class_transition_matches": "The land-cover classes before and after match the evidence.",
    "class_transition_mismatch": "The stated land-cover change disagrees with the evidence classes.",
    "class_not_in_evidence": "The region has no land-cover classes in the evidence, so this cannot be checked.",
    "unknown_transect": "Refers to a transect id that is not in the evidence.",
    "no_transect_at_location": "No shoreline transect at the stated location.",
    "shoreline_not_in_evidence": "The evidence has no shoreline transects, so this cannot be checked.",
    "shoreline_matches": "The stated shoreline movement matches the transect statistics.",
    "shoreline_mismatch": "The stated shoreline movement disagrees with the transect statistics.",
    "shoreline_unconfirmed": "The radar trend here is not confirmed by the imagery, so the movement cannot be checked.",
    "coastal_not_in_evidence": "The evidence has no coastal-strip built areas for this, so it cannot be checked.",
    "coastal_built_matches": "The stated built-area change near the shore matches the evidence.",
    "coastal_built_mismatch": "The built area near the shore changed the other way, or not by enough.",
}


class SchemaError(ValueError):
    """Raised by check() when data does not match the contract."""


def _ring_area_km2(ring: list[list[float]]) -> float:
    lat0 = sum(point[1] for point in ring[:-1]) / max(len(ring) - 1, 1)
    scale_x = 111.32 * cos(lat0 * pi / 180)
    scale_y = 111.32
    return abs(sum(
        ring[index][0] * scale_x * ring[(index + 1) % (len(ring) - 1)][1] * scale_y
        - ring[(index + 1) % (len(ring) - 1)][0] * scale_x * ring[index][1] * scale_y
        for index in range(len(ring) - 1)
    ) / 2)


def _valid_ring(ring: object) -> tuple[bool, float]:
    if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
        return False, 0.0
    if any(not isinstance(point, list) or len(point) < 2 for point in ring):
        return False, 0.0
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for point in ring for value in point[:2]):
        return False, 0.0
    if len({(point[0], point[1]) for point in ring[:-1]}) < 3:
        return False, 0.0
    area = _ring_area_km2(ring)
    return area > 0, area


def _polygon_area_km2(coordinates: object) -> tuple[bool, float]:
    if not isinstance(coordinates, list) or not coordinates:
        return False, 0.0
    valid, area = _valid_ring(coordinates[0])
    if not valid:
        return False, 0.0
    for hole in coordinates[1:]:
        hole_valid, hole_area = _valid_ring(hole)
        if not hole_valid:
            return False, 0.0
        area -= hole_area
    return area > 0, max(area, 0.0)


def validate_aoi(aoi: object) -> list[str]:
    """Validate a GeoJSON Polygon/MultiPolygon in longitude/latitude."""
    if not isinstance(aoi, dict):
        return ["AOI must be a GeoJSON object"]
    if aoi.get("type") not in ("Polygon", "MultiPolygon"):
        return ["AOI type must be Polygon or MultiPolygon"]
    coordinates = aoi.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return ["AOI coordinates must be a non-empty list"]
    if aoi["type"] == "Polygon":
        polygons = [coordinates]
    else:
        polygons = coordinates
    if not all(isinstance(polygon, list) and all(isinstance(ring, list) for ring in polygon) for polygon in polygons):
        return ["AOI coordinates must be lists of rings"]
    results = [_polygon_area_km2(polygon) for polygon in polygons]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    errors = []
    if not results or not all(result[0] for result in results):
        errors.append("AOI contains an invalid or zero-area ring")
    if any(not isinstance(point, list) or len(point) < 2 for point in points):
        errors.append("AOI coordinates must contain longitude/latitude pairs")
    elif any(not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90 for point in points):
        errors.append("AOI longitude/latitude is out of range")
    area = sum(result[1] for result in results)
    if area < 1 or area > 500:
        errors.append(f"AOI area must be between 1 and 500 km², got {area:.3f} km²")
    return errors


def validate_windows(before_window: object, after_window: object) -> list[str]:
    errors = []
    parsed = []
    for name, window in (("before_window", before_window), ("after_window", after_window)):
        if not isinstance(window, list) or len(window) != 2:
            errors.append(f"{name} must be [start, end]")
            continue
        try:
            start, end = date.fromisoformat(window[0]), date.fromisoformat(window[1])
        except (TypeError, ValueError):
            errors.append(f"{name} must contain ISO dates")
            continue
        if start >= end:
            errors.append(f"{name} start must be earlier than end")
        if end > start + timedelta(days=366):
            errors.append(f"{name} must be at most 12 months")
        parsed.append((start, end))
    # end dates are inclusive (ee_engine._inclusive_end), so a shared day is an overlap
    if len(parsed) == 2 and parsed[0][1] >= parsed[1][0] and parsed[1][1] >= parsed[0][0]:
        errors.append("before_window and after_window must not overlap")
    if len(parsed) == 2 and parsed[0][0] >= parsed[1][0]:
        errors.append("before_window must precede after_window")
    return errors


def aoi_bounds(aoi: dict) -> tuple[float, float, float, float]:
    polygons = [aoi["coordinates"]] if aoi["type"] == "Polygon" else aoi["coordinates"]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def aoi_area_ha(aoi: dict) -> float:
    polygons = [aoi["coordinates"]] if aoi["type"] == "Polygon" else aoi["coordinates"]
    return sum(_polygon_area_km2(polygon)[1] for polygon in polygons) * 100


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
    for f in ("class_before", "class_after"):
        if region.get(f) is not None and region[f] not in LANDCOVER_CLASSES:
            errors.append(f"'{f}' must be one of {LANDCOVER_CLASSES} or null, got {region[f]!r}")
    for f in ("class_frac_before", "class_frac_after"):
        frac = region.get(f)
        if frac is None:
            continue
        if not isinstance(frac, dict) or set(frac) - set(LANDCOVER_CLASSES):
            errors.append(f"'{f}' must map Dynamic World classes to shares")
        elif not all(_is_number(v) and 0 <= v <= 1 for v in frac.values()):
            errors.append(f"'{f}' shares must be numbers in [0, 1]")
    rid = region.get("id", "?")
    return [f"region {rid}: {e}" for e in errors]


def validate_transect(tr: object) -> list[str]:
    if not isinstance(tr, dict):
        return ["transect is not an object"]
    errors = [f"missing field '{f}'" for f in TRANSECT_FIELDS if f not in tr]
    if "location" in tr and tr["location"] not in LOCATIONS:
        errors.append(f"'location' must be one of {LOCATIONS}, got {tr['location']!r}")
    if "change" in tr and tr["change"] not in SHORELINE_CHANGES:
        errors.append(f"'change' must be one of {SHORELINE_CHANGES}, got {tr['change']!r}")
    for f in ("nsm", "lrr", "ci95"):
        if tr.get(f) is not None and not _is_number(tr[f]):
            errors.append(f"'{f}' must be a number or null, got {tr[f]!r}")
    return [f"transect {tr.get('id', '?')}: {e}" for e in errors]


def validate_strip(st: object) -> list[str]:
    if not isinstance(st, dict):
        return ["coastal strip is not an object"]
    errors = [f"missing field '{f}'" for f in STRIP_FIELDS if f not in st]
    if "strip" in st and st["strip"] not in COASTAL_STRIPS:
        errors.append(f"'strip' must be one of {COASTAL_STRIPS}, got {st['strip']!r}")
    for f in ("built_ha_before", "built_ha_after"):
        if f in st and not (_is_number(st[f]) and st[f] >= 0):
            errors.append(f"'{f}' must be a number >= 0, got {st[f]!r}")
    if st.get("location") is not None and st["location"] not in LOCATIONS:
        errors.append(f"'location' must be one of {LOCATIONS} or null, got {st['location']!r}")
    return [f"coastal strip {st.get('strip', '?')}: {e}" for e in errors]


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
    for name, check_item in (("transects", validate_transect), ("coastal_strips", validate_strip)):
        items = ev.get(name, [])
        if not isinstance(items, list):
            errors.append(f"evidence: '{name}' must be a list")
            continue
        for item in items:
            errors += check_item(item)
    tids = [t.get("id") for t in ev.get("transects", []) if isinstance(t, dict)] if isinstance(ev.get("transects", []), list) else []
    if len(tids) != len(set(tids)):
        errors.append("evidence: transect ids are not unique")
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
    for f in ("class_before", "class_after"):
        if claim.get(f) is not None and claim[f] not in LANDCOVER_CLASSES:
            errors.append(f"'{f}' must be one of {LANDCOVER_CLASSES} or null, got {claim[f]!r}")
    if claim.get("shoreline_change") is not None and claim["shoreline_change"] not in ("advancing", "retreating", "stable"):
        errors.append(f"'shoreline_change' must be advancing, retreating, stable or null, got {claim['shoreline_change']!r}")
    if claim.get("strip") is not None and claim["strip"] not in (*COASTAL_STRIPS, "0-500"):
        errors.append(f"'strip' must be one of {(*COASTAL_STRIPS, '0-500')} or null, got {claim['strip']!r}")
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
    ids = [f["properties"].get("id") for f in fc.get("features", []) if isinstance(f, dict) and isinstance(f.get("properties"), dict)]
    if len(ids) != len(set(ids)):
        errors.append("region ids are not unique")
    return errors


def check(errors: Iterable[str], what: str) -> None:
    errors = list(errors)
    if errors:
        raise SchemaError(f"invalid {what}: " + "; ".join(errors[:10]) + (" ..." if len(errors) > 10 else ""))