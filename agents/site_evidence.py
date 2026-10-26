"""Evidence for one box (a labelled site, or a development box): the frame every report arm is
verified in (D16 open item 1, option A, decided 2026-10-24).

All arms see the same box (the yellow outline on the chips), so the evidence is cut to it:
- regions overlapping the box, each with its area INSIDE the box (`area_ha`) and its `location`
  relative to the box (where its inside part's centroid falls in a 3 x 3 grid over the box), not
  relative to the whole AOI;
- `change_frac` = detected area inside the box / box area;
- the region's own index deltas, mean_conf and Dynamic World classes, unchanged (they describe the
  region, and the box can't change them).
A box with no region in it gives an empty region list and change_frac 0 (the "random site" case of
the evaluation design: gated should abstain from change claims).
- shoreline transects crossing the box, with their movement between the SAME two windows
  (`transects`, D13 / D16), when scripts/make_shoreline_windows.py has run for those windows.

Plain geometry on a local equirectangular projection (fine at site scale, no shapely needed).
scripts/restratify_sites.py uses the same clipping.
"""
from __future__ import annotations

import math

M_PER_DEG = 111_320
MIN_INSIDE_M2 = 100          # one 10 m pixel: less than this inside the box doesn't count as overlap


# ---------- geometry ----------
def polygons(geom: dict) -> list:
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def bbox(geom: dict) -> tuple[float, float, float, float]:
    xs = [p[0] for poly in polygons(geom) for p in poly[0]]
    ys = [p[1] for poly in polygons(geom) for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def overlaps(a: tuple, b: tuple) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def clip_ring(ring: list, w: float, s: float, e: float, n: float) -> list[tuple]:
    """Sutherland–Hodgman: the part of a ring inside an axis-aligned box (area-correct for any ring)."""
    def clip(points, inside, cross):
        out = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    pts = [tuple(p[:2]) for p in ring[:-1]] if ring[0] == ring[-1] else [tuple(p[:2]) for p in ring]
    for inside, cross in ((lambda p: p[0] >= w, at_x(w)), (lambda p: p[0] <= e, at_x(e)),
                          (lambda p: p[1] >= s, at_y(s)), (lambda p: p[1] <= n, at_y(n))):
        if not pts:
            break
        pts = clip(pts, inside, cross)
    return pts


def _moments(points: list[tuple], lat0: float) -> tuple[float, float, float]:
    """(signed area m², x·area, y·area) in metres of a closed ring, for area and centroid."""
    if len(points) < 3:
        return 0.0, 0.0, 0.0
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    xy = [(x * kx, y * M_PER_DEG) for x, y in points]
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    return a / 2, cx / 6, cy / 6


def area_m2(points: list[tuple], lat0: float) -> float:
    """Shoelace area of lon/lat points on a local equirectangular projection."""
    return abs(_moments(points, lat0)[0])


def inside_part(geom: dict, box: tuple) -> tuple[float, tuple[float, float] | None]:
    """(area m² of the geometry inside the box, centroid lon/lat of that part or None)."""
    lat0 = (box[1] + box[3]) / 2
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    total = mx = my = 0.0
    for poly in polygons(geom):
        for k, ring in enumerate(poly):
            a, x, y = _moments(clip_ring(ring, *box), lat0)
            orient = -1 if a < 0 else 1                 # whichever way the ring winds ...
            sign = orient * (1 if k == 0 else -1)       # ... outer rings add, holes subtract
            total, mx, my = total + sign * a, mx + sign * x, my + sign * y
    if total <= 0:
        return 0.0, None
    return total, (mx / total / kx, my / total / M_PER_DEG)


def where_in_box(lon: float, lat: float, box: tuple) -> str:
    """The 3 x 3 location word for a point in the box (same rule as ee_engine.where_in_aoi)."""
    from .ee_engine import where_in_aoi
    return where_in_aoi(lon, lat, box)


# ---------- evidence ----------
def box_area_m2(box: tuple) -> float:
    w, s, e, n = box
    return area_m2([(w, s), (e, s), (e, n), (w, n)], (s + n) / 2)


_coast_cache: dict = {}


def box_transects(box: tuple, before_window: list[str], after_window: list[str]) -> list[dict] | None:
    """Shoreline transects crossing the box with their statistics between the same two windows
    (scripts/make_shoreline_windows.py, D13 / D16). None when no window run exists for these windows,
    so evidence never mixes in the 24-month (Phase 11) statistics of a different period."""
    from . import shoreline
    try:
        path = shoreline.windows_file(before_window, after_window)
    except (IndexError, TypeError):
        return None
    if path not in _coast_cache:
        stats = shoreline.load(path.name)
        if stats is not None and stats.get("windows") != [list(before_window), list(after_window)]:
            stats = None                                  # same months, other days: not this pair
        _coast_cache[path] = (stats, shoreline.load("transects.geojson")) if stats else None
    hit = _coast_cache[path]
    if not hit or hit[1] is None:
        return None
    return shoreline.evidence_transects(box, hit[1], hit[0]["transects"])


def site_evidence(box: tuple, features: list[dict], before_window: list[str], after_window: list[str],
                  source: str, pair_id: str, coast: bool = True) -> dict:
    """The evidence for `box` from the detector's region features (see the module docstring). With
    coast, the shoreline transects crossing the box (box_transects) join as `transects` when a window
    run exists; a box no transect crosses gets an empty list (no coast in the box)."""
    regions, inside_total = [], 0.0
    for f in features:
        if not overlaps(bbox(f["geometry"]), box):
            continue
        m2, centroid = inside_part(f["geometry"], box)
        if m2 < MIN_INSIDE_M2 or centroid is None:
            continue
        inside_total += m2
        props = {k: v for k, v in f["properties"].items() if not k.startswith("_")}
        regions.append({**props, "area_ha": round(m2 / 10_000, 3), "location": where_in_box(*centroid, box),
                        "area_ha_whole_region": props.get("area_ha")})
    regions.sort(key=lambda r: -r["area_ha"])
    ev = {"pair_id": pair_id, "dates": [before_window, after_window], "source": source,
          "change_frac": round(min(1.0, inside_total / box_area_m2(box)), 4), "regions": regions}
    transects = box_transects(box, before_window, after_window) if coast else None
    if transects is not None:
        ev["transects"] = transects
    return ev
