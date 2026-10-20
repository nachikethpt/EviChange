"""Land-cover classes for change regions from Google Dynamic World (D10, Phase 9).

For each region and each window (before / after): the most common Dynamic World class over the
region's pixels gives `class_before` / `class_after`, and the region's mean class probabilities give
`class_frac_before` / `class_frac_after` ({class: share}). Each pixel's class is its mode over the
window's Dynamic World images. A window without any Dynamic World image (≤ 35 % cloud scenes only)
leaves the fields null: a class is never guessed.

The detector (D6) still decides *where* change is; these classes describe *what* it is.

Labelled sites: Phase 14 labels the from / to class at the 30 QN sites blind to Dynamic World. Until
those labels exist (CLASSES_UNLOCKED_AT_LABELLED_SITES), the app hides the class fields of regions
that overlap a labelled site (hide_at_labelled_sites), the same way the Geo-VLM check is locked.

Earth Engine is imported only inside call sites (see ee_engine).
"""
from __future__ import annotations

import json
from typing import Any

from .schema import LANDCOVER_CLASSES as DW_CLASSES

DW_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"
CLASS_FIELDS = ("class_before", "class_after", "class_frac_before", "class_frac_after")
CLASSES_UNLOCKED_AT_LABELLED_SITES = False     # set True in the commit that adds the Phase 14 class labels
BATCH_BYTES = 2_000_000                        # GeoJSON per Earth Engine request (the QN regions are 13 MB)


# ---------- reading the fields ----------
def transition(region: dict) -> str | None:
    """'trees → bare', 'water' (no class change), or None when either class is unknown."""
    before, after = region.get("class_before"), region.get("class_after")
    if not before or not after:
        return None
    return before if before == after else f"{before} → {after}"


def label(name: str | None) -> str:
    return (name or "unknown").replace("_", " ")


# ---------- labelled-site guard ----------
def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


MIN_SITE_SHARE = 0.10    # hide a region's classes when at least this share of its area lies in a site
_share_cache: dict[tuple, float] = {}


def _rings(geometry: dict) -> list[list]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [ring for poly in polys for ring in poly]          # holes too: even-odd ray casting handles them


def site_share(geometry: dict, area_ha: float, boxes: list[tuple[float, float, float, float]], n: int = 12) -> float:
    """Approximate share of a region's area that lies inside the labelled-site boxes: an n x n grid
    of points over each box ∩ region bbox, tested against the region outline (even-odd rule; only
    edges spanning the box's latitudes are scanned, so huge outlines stay fast)."""
    import math
    w, s, e, nn = _bbox(geometry)
    edges = [(a, b) for ring in _rings(geometry) for a, b in zip(ring, ring[1:])]
    inside_m2 = 0.0
    for bw, bs, be, bn in boxes:
        x0, y0, x1, y1 = max(w, bw), max(s, bs), min(e, be), min(nn, bn)
        if x0 >= x1 or y0 >= y1:
            continue
        near = [(a, b) for a, b in edges if min(a[1], b[1]) <= y1 and max(a[1], b[1]) >= y0]
        hits = 0
        for i in range(n):
            for j in range(n):
                px, py = x0 + (i + 0.5) * (x1 - x0) / n, y0 + (j + 0.5) * (y1 - y0) / n
                crossings = sum(1 for a, b in near if (a[1] > py) != (b[1] > py)
                                and px < a[0] + (py - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
                hits += crossings % 2
        cell_m2 = (x1 - x0) * 111_320 * math.cos(math.radians((y0 + y1) / 2)) * (y1 - y0) * 110_574
        inside_m2 += cell_m2 * hits / (n * n)
    return min(1.0, inside_m2 / (area_ha * 10_000)) if area_ha else 0.0


def hide_at_labelled_sites(fc: dict) -> dict:
    """Copy of fc with the class fields removed (and class_hidden: true) on regions with at least
    MIN_SITE_SHARE of their area inside a labelled site, until the Phase 14 class labels exist.
    A region that only grazes a site (the big QN regions: < 1 %) says nothing about the site's class,
    so it keeps its classes. Other regions are unchanged."""
    if CLASSES_UNLOCKED_AT_LABELLED_SITES or not fc.get("features"):
        return fc
    from .vlm_check import labelled_site_boxes
    boxes = labelled_site_boxes()
    out = []
    for f in fc["features"]:
        props = f.get("properties", {})
        if any(k in props for k in CLASS_FIELDS):
            geom = f["geometry"]
            key = (props.get("id"), json.dumps(geom["coordinates"][0][:3]), sum(len(r) for r in _rings(geom)))
            if key not in _share_cache:
                _share_cache[key] = site_share(geom, props.get("area_ha", 0), boxes)
            if _share_cache[key] >= MIN_SITE_SHARE:
                props = {k: v for k, v in props.items() if k not in CLASS_FIELDS}
                props["class_hidden"] = True
                f = {**f, "properties": props}
        out.append(f)
    return {**fc, "features": out}


# ---------- Earth Engine ----------
def _inclusive_end(window: list[str]) -> str:
    from .ee_engine import _inclusive_end as end
    return end(window)


def dw_window(ee: Any, aoi: dict, window: list[str]) -> Any | None:
    """[label (per-pixel mode), <class> mean probabilities] for one window, or None without images."""
    col = (ee.ImageCollection(DW_COLLECTION).filterBounds(ee.Geometry(aoi))
           .filterDate(window[0], _inclusive_end(window)))
    if col.size().getInfo() == 0:
        return None
    return ee.Image.cat([col.select("label").mode().rename("label"), col.select(list(DW_CLASSES)).mean()])


def _batches(features: list[dict], max_bytes: int = BATCH_BYTES) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for f in features:
        n = len(json.dumps(f["geometry"]))
        if cur and size + n > max_bytes:
            out.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    return out + ([cur] if cur else [])


def _props(stats: dict, prefix: str) -> dict:
    """Region fields for one window from reduceRegions output (mode of label, mean of probabilities)."""
    code = stats.get(f"{prefix}_label_mode")
    fracs = {c: stats.get(f"{prefix}_{c}_mean") for c in DW_CLASSES}
    if code is None or any(v is None for v in fracs.values()):
        return {"class": None, "frac": None}
    return {"class": DW_CLASSES[int(round(code))], "frac": {c: round(float(v), 3) for c, v in fracs.items()}}


def add_landcover(fc: dict, aoi: dict, before_window: list[str], after_window: list[str]) -> dict:
    """fc with class_before / class_after / class_frac_before / class_frac_after on every region.
    Geometry and the other fields are unchanged. Metadata gets a `landcover` note."""
    from .ee_engine import _ee
    ee = _ee()
    windows = {"b": dw_window(ee, aoi, before_window), "a": dw_window(ee, aoi, after_window)}
    bands = [img.rename([f"{k}_{n}" for n in ("label", *DW_CLASSES)]) for k, img in windows.items() if img is not None]
    stats_by_id: dict[str, dict] = {}
    if bands:
        image = ee.Image.cat(bands)
        reducer = ee.Reducer.mean().combine(ee.Reducer.mode(), sharedInputs=True)
        for batch in _batches(fc["features"]):
            col = ee.FeatureCollection([ee.Feature(ee.Geometry(f["geometry"]), {"rid": f["properties"]["id"]}) for f in batch])
            result = image.reduceRegions(collection=col, reducer=reducer, scale=10, tileScale=4).getInfo()
            for feat in result["features"]:
                stats_by_id[feat["properties"]["rid"]] = feat["properties"]
    features = []
    for f in fc["features"]:
        stats = stats_by_id.get(f["properties"]["id"], {})
        before, after = _props(stats, "b"), _props(stats, "a")
        props = {**f["properties"], "class_before": before["class"], "class_after": after["class"],
                 "class_frac_before": before["frac"], "class_frac_after": after["frac"]}
        features.append({**f, "properties": props})
    note = {"source": DW_COLLECTION, "method": "per-pixel mode of label per window; region mode + mean probabilities (D10)",
            "before_images": windows["b"] is not None, "after_images": windows["a"] is not None}
    return {**fc, "features": features, "metadata": {**fc.get("metadata", {}), "landcover": note}}
