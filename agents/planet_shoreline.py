"""Phase 13c: independent Planet NDWI positions on the fixed Phase 11 transects.

This supplements the monthly radar series; it never rewrites the published radar / Sentinel-2
statistics or frozen box evidence. Endpoint quarters must match the radar study period.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from . import planet, shoreline
from .study import REPO_ROOT

FILE = "planet.json"
VERSION = "planet-shoreline-v1"
STEP_M = planet.NATIVE_SCALE
MIN_ENDPOINT_MONTHS = 2
MIN_VALID_SHARE = 0.8
METHOD = {
    "source": planet.SOURCE, "attribution": planet.ATTRIBUTION,
    "water": f"Planet green/NIR NDWI > {planet.NDWI_WATER}; UDM2 clear pixels only",
    "position": "fixed Phase 11 transects, sampled at 3 m; sea-connected walk with 30 m of land; "
                "no interpolation across cloud gaps between 100 m landward of the edge and the sea end",
    "confirmation": "median of at least 2 valid monthly positions in each of the first and last radar "
                    "quarters; optical shift >= 20 m in the significant radar trend's direction; "
                    "pending when endpoint coverage is missing; withheld on radar-flagged tidal flats",
    "tide": "Planet mosaics are single-day acquisitions at unknown tide levels. Endpoint medians do not "
            "correct tides. Directional corroboration only, not validated shoreline accuracy or a Planet rate.",
    "blindness": "Phase 14 reference transects and their neighbours are excluded until unlocked",
}


def profile_position(values: list, offsets: list[float]) -> dict:
    valid = sum(v in (0, 1) for v in values) / max(1, len(offsets))
    if valid < MIN_VALID_SHARE:
        return {"pos": None, "status": "insufficient_clear", "valid_share": round(valid, 3)}
    result = shoreline.shoreline_position(values, offsets, land_run=math.ceil(30 / STEP_M))
    if result["pos"] is not None and any(v not in (0, 1) for o, v in zip(offsets, values)
                                         if o >= result["pos"] - shoreline.LANDWARD_CHECK_M):
        result = {"pos": None, "status": "cloud_gap", "agreement": None}
    return {**result, "valid_share": round(valid, 3)}


def confirmation(months: list[str], positions: list[float | None], radar: dict) -> dict:
    groups = shoreline.quarters(months)
    if len(groups) < 2:
        raise ValueError("Planet confirmation requires at least two complete radar quarters")
    epochs = [groups[0], groups[-1]]
    by_month = dict(zip(months, positions))
    samples = [[by_month.get(m) for m in group if by_month.get(m) is not None] for group in epochs]
    medians = [round(statistics.median(p), 1) if len(p) >= MIN_ENDPOINT_MONTHS else None for p in samples]
    trend = radar.get("trend", "too_few")
    conf = shoreline.confirm(trend, *medians)
    if trend not in ("advancing", "retreating"):
        status = "no_significant_radar_trend"
    elif any(p is None for p in medians):
        status = "pending_coverage"
    elif radar.get("tidal"):
        status = "tidal_uncertainty"
    else:
        status = "confirmed" if conf["change"] == trend else "not_confirmed"
    return {"status": status, "radar_trend": trend, "endpoint_months": epochs,
            "n": [len(p) for p in samples], "positions_m": medians, "shift_m": conf["opt_shift"],
            "min_shift_m": shoreline.OPT_MIN_SHIFT_M, "tide_caveat": METHOD["tide"]}


def build(transects: dict, months: list[str], catalog: dict, cache_dir: Path | None = None, log=print) -> dict:
    from .ee_engine import _ee
    hidden = shoreline.hidden_transects(transects)
    visible = [f for f in transects["features"] if f["id"] not in hidden]
    rows = [r for r in catalog["months"] if r["month"] in months]
    offsets = shoreline.profile_offsets(step=STEP_M)
    signature = hashlib.sha256(json.dumps([VERSION, METHOD, rows, visible, months], sort_keys=True).encode()).hexdigest()[:16]
    cache_dir = cache_dir or REPO_ROOT / "data" / "planet" / "shoreline_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    bands = [f"p_{r['month'].replace('-', '_')}" for r in rows]
    ee, stack = None, None
    results = {}
    batch_size = max(1, shoreline.SAMPLE_BATCH // len(offsets))
    for first in range(0, len(visible), batch_size):
        batch = visible[first:first + batch_size]
        path = cache_dir / f"{signature}_{first:04d}.json"
        if path.exists():
            profiles = json.loads(path.read_text(encoding="utf-8"))
        elif rows:
            if ee is None:
                ee = _ee()
                ee.data.setDeadline(180000)
                stack = ee.Image.cat([planet.water_image(ee, r["month"]).unmask(255).rename(b)
                                      for r, b in zip(rows, bands)])
            points = [(f["id"], i, lon, lat) for f in batch
                      for i, (lon, lat) in enumerate(shoreline.transect_points(f, offsets))]
            profiles = shoreline.sample_profiles(ee, stack, points, bands, log=lambda *_: None, scale=STEP_M)
            path.write_text(json.dumps(profiles), encoding="utf-8")
        else:
            profiles = {}
        for f in batch:
            extracted = {}
            for row, band in zip(rows, bands):
                profile = profiles.get(f["id"], {}).get(band, {})
                values = [profile.get(str(i), profile.get(i)) for i in range(len(offsets))]
                extracted[row["month"]] = profile_position(values, offsets)
            quality = [extracted.get(m, {"pos": None, "status": "missing_month"}) for m in months]
            positions = [p["pos"] for p in quality]
            results[f["id"]] = {"positions": positions, "quality": [p["status"] for p in quality],
                                  "confirmation": confirmation(months, positions, f["properties"])}
        log(f"Planet shorelines: {min(first + batch_size, len(visible))}/{len(visible)} transects; {len(rows)} months")
    return {"version": VERSION, "fingerprint": signature, "months": months, "catalog": rows,
            "withheld_transects": len(hidden), "transects": results, "method": METHOD}


def visible_records(data: dict, transects: dict) -> dict:
    """Reapply today's blind lock even to outputs produced while a different lock was active."""
    hidden = shoreline.hidden_transects(transects)
    return {tid: row for tid, row in data["transects"].items() if tid not in hidden}


def summary(data: dict, transects: dict) -> dict:
    records = visible_records(data, transects)
    return {"months": data["months"], "catalog": data["catalog"], "method": data["method"],
            "transects": len(records), "withheld_transects": len(shoreline.hidden_transects(transects)),
            "confirmation_counts": dict(Counter(r["confirmation"]["status"] for r in records.values())),
            "position_counts": {m: sum(r["positions"][i] is not None for r in records.values())
                                for i, m in enumerate(data["months"])}}


def lines(data: dict, transects: dict, month: str | None = None) -> dict:
    records = visible_records(data, transects)
    positions = {tid: row["positions"] for tid, row in records.items()}
    feats = []
    for row in data["catalog"]:
        if month is not None and month != row["month"]:
            continue
        # max_gap=0: never bridge a hidden or cloudy transect.
        runs = shoreline.season_lines(transects["features"], positions, data["months"].index(row["month"]), max_gap=0)
        feats.append({"type": "Feature", "properties": {**row, "source": planet.SOURCE,
                      "scale_m": STEP_M, "attribution": planet.ATTRIBUTION},
                      "geometry": {"type": "MultiLineString", "coordinates": runs}})
    return shoreline.hide_lines({"type": "FeatureCollection", "features": feats}, transects,
                                shoreline.hidden_transects(transects))


def detail(data: dict | None, tid: str) -> dict | None:
    if data is None or tid not in data["transects"]:
        return None
    record = data["transects"][tid]
    meta = {r["month"]: r for r in data["catalog"]}
    return {"series": [{"month": m, "pos": p, "status": q, "date": meta.get(m, {}).get("date")}
                       for m, p, q in zip(data["months"], record["positions"], record["quality"])],
            "confirmation": record["confirmation"], "method": data["method"]}
