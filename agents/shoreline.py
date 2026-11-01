"""Shoreline change over the monthly series (D11, Phase 11).

Method, as in standard shoreline-change analysis (baseline + transects + rates):
1. Water occurrence: the share of the months (Phase 10's Sentinel-1 water maps, monthly.water_image)
   in which a pixel is water.
2. Sea: water polygons (occurrence >= 0.5) that touch the AOI edge and cover >= SEA_MIN_HA. Inland
   ponds and rivers don't touch the edge, so they are not sea.
3. Baseline: the sea polygons' boundary (coast + islands), without stretches that only follow the
   AOI edge, cut into lines, lines shorter than MIN_LINE_M dropped. The sea mask is first opened by
   OPEN_M (water narrower than ~2 x OPEN_M: docks, inlets, channels, leaves the sea), and the line is
   resampled and smoothed over +-SMOOTH_WINDOW_M, so transects stay near-parallel instead of
   following every inlet (an unsmoothed first run had crossing transects and false ~300 m/yr rates
   where an inlet flipped between water and land).
4. Transects every TRANSECT_SPACING_M, perpendicular to the baseline, LAND_M landward and SEA_M
   seaward, sampled every STEP_M.
5. Each month: the water mask along every transect; the shoreline is the landward edge of the water
   connected to the sea: from the seaward end, walk landward through water until LAND_RUN land samples
   in a row. Inland ponds behind the coast are never reached (a first run that took the best overall
   land / water split jumped between the coast and settling ponds ~300 m inland, month to month, which
   made false trends). No position when the seaward end isn't water, the water reaches the landward
   end, or fewer than MIN_AGREEMENT of the samples around the position agree.
6. Rates come from QUARTERLY shorelines: water in at least half of all the radar looks in each 3-month
   window (~6-12 looks), which averages the tide out to about the mid-tide line. Per transect:
   positions in metres from the baseline, seaward positive; net movement (mean of the last 2
   quarters minus mean of the first 2); linear regression rate (m/yr) with its 95 % confidence
   interval; "advancing" / "retreating" only when the interval excludes 0, else "stable".
7. Monthly positions are kept for display, with their spread: a transect whose monthly positions
   spread (IQR) more than TIDAL_IQR_M is flagged `tidal` (a wide intertidal flat).
8. Optical confirmation: the same shoreline from Sentinel-2 (median MNDWI of the clear looks > 0)
   for each dry season (Oct-Mar). `change` is "advancing" / "retreating" only when the radar trend
   is significant AND the optical shoreline moved the same way by at least OPT_MIN_SHIFT_M between
   the first and last dry season; a radar trend without that is "unconfirmed". On the QN coast, radar
   alone also "advanced" where wind-roughened water or moored barges read as land (Jul-Sep 2026,
   coal-port channel) while the imagery showed an unchanged coast. Change after the last dry season
   can't be confirmed optically until Planet's monsoon months are in (Phase 13c).

Tide: single Sentinel-1 looks are at different tide levels, and Ha Long Bay's range is several
metres (D11). On tidal flats a monthly shoreline jumps by hundreds of metres between low and high
tide; a run that fitted rates to monthly positions called such transects "advancing" or
"retreating" at 150-340 m/yr wherever low-tide months happened to cluster. Hence the quarterly
composites for rates, and never a single month.

The geometry and statistics here are pure Python (shapely can't load on the project PC); only
build() and sample_profiles() use Earth Engine.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from .study import REPO_ROOT

SHORELINE_DIR = REPO_ROOT / "data" / "quangninh" / "shoreline"
SEA_MIN_HA = 100
OCCURRENCE = 0.5
VECTOR_SCALE = 20              # m, baseline polygons (positions are measured at STEP_M along transects)
EDGE_M = 60                    # boundary within this of the AOI edge is the AOI cut, not a shoreline
SMOOTH_M = 40                  # Douglas–Peucker tolerance for the baseline
OPEN_M = 50                    # sea mask opening radius: removes water features narrower than ~100 m
RESAMPLE_M = 20
SMOOTH_WINDOW_M = 250          # moving-average half-window along the baseline
MIN_LINE_M = 500
TRANSECT_SPACING_M = 100
NORMAL_SPAN_M = 100            # transect direction from the baseline +- this far along it
LAND_M, SEA_M, STEP_M = 300, 500, 10
MIN_AGREEMENT = 0.8
LAND_RUN = 3                   # land samples in a row that end the sea (30 m at STEP_M)
LANDWARD_CHECK_M = 100         # agreement looks this far landward of the shoreline
MIN_MONTHS = 6                 # (monthly series) points needed for a rate
MIN_QUARTERS = 5               # quarters with a position needed for the reported rate
TIDAL_IQR_M = 100              # monthly positions spreading more than this: tidal flat
OPT_MIN_SHIFT_M = 20           # optical (dry-season) shoreline shift that confirms a radar trend: 2 pixels
SAMPLE_BATCH = 4000            # points per Earth Engine request
M_PER_DEG = 111_320


# ---------- local metric coordinates ----------
class LocalFrame:
    """Equirectangular metres around a reference latitude; fine at the AOI's ~20 km scale."""

    def __init__(self, lon0: float, lat0: float):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = M_PER_DEG * math.cos(math.radians(lat0))

    def to_m(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * M_PER_DEG

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self.lon0 + x / self.kx, self.lat0 + y / M_PER_DEG


def line_length(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def douglas_peucker(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return list(pts)
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm else math.dist(pts[i], pts[0])
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return douglas_peucker(pts[: idx + 1], tol)[:-1] + douglas_peucker(pts[idx:], tol)


def split_off_edge(ring: list[tuple[float, float]], box: tuple[float, float, float, float], edge: float) -> list[list[tuple[float, float]]]:
    """Pieces of a closed ring (metres) that stay more than `edge` inside the box (w, s, e, n).
    A ring that never comes near the edge (an island) is returned whole, still closed."""
    w, s, e, n = box
    keep = [min(x - w, e - x, y - s, n - y) > edge for x, y in ring]
    if all(keep):
        return [list(ring)]
    pts = ring[:-1] if ring[0] == ring[-1] else list(ring)
    keep = keep[: len(pts)]
    start = keep.index(False)                     # rotate so a dropped vertex comes first: no piece wraps around
    pts, keep = pts[start:] + pts[:start], keep[start:] + keep[:start]
    pieces, cur = [], []
    for p, k in zip(pts, keep):
        if k:
            cur.append(p)
        elif cur:
            pieces.append(cur); cur = []
    if cur:
        pieces.append(cur)
    return [p for p in pieces if len(p) >= 2]


def point_in_polygons(pt: tuple[float, float], polygons: list[list[list[tuple[float, float]]]]) -> bool:
    """Even-odd test over polygons given as [outer ring, hole rings...] in the same coordinates."""
    x, y = pt
    inside = False
    for rings in polygons:
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


def resample(pts: list[tuple[float, float]], step: float = RESAMPLE_M) -> list[tuple[float, float]]:
    """Points every `step` metres along a polyline (plus its end)."""
    length = line_length(pts)
    n = max(1, int(length // step))
    return [point_at(pts, i * step) for i in range(n + 1)] + ([pts[-1]] if n * step < length else [])


def smooth(pts: list[tuple[float, float]], window: float = SMOOTH_WINDOW_M, step: float = RESAMPLE_M) -> list[tuple[float, float]]:
    """Moving average over +-window along a resampled polyline; the window shrinks near the ends,
    so the ends stay put."""
    r = resample(pts, step)
    k = max(1, int(window // step))
    out = []
    for i in range(len(r)):
        h = min(k, i, len(r) - 1 - i)
        seg = r[i - h: i + h + 1]
        out.append((sum(x for x, _ in seg) / len(seg), sum(y for _, y in seg) / len(seg)))
    return out


def point_at(pts: list[tuple[float, float]], dist: float) -> tuple[float, float]:
    """Point `dist` metres along a polyline (clamped to its ends)."""
    if dist <= 0:
        return pts[0]
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if dist <= seg and seg:
            t = dist / seg
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        dist -= seg
    return pts[-1]


def make_transects(lines: list[list[tuple[float, float]]], sea: list[list[list[tuple[float, float]]]],
                   spacing: float = TRANSECT_SPACING_M, span: float = NORMAL_SPAN_M) -> list[dict]:
    """Transects (metres) along baseline lines: {'line', 'chainage', 'origin', 'normal'}, where
    normal is a unit vector pointing to the sea (decided by which side lies inside a sea polygon)."""
    out = []
    for li, pts in enumerate(lines):
        length = line_length(pts)
        n = int(length // spacing)
        for k in range(n + 1):
            c = k * spacing if n else length / 2
            if c > length:
                break
            o = point_at(pts, c)
            a, b = point_at(pts, max(0.0, c - span)), point_at(pts, min(length, c + span))
            tx, ty = b[0] - a[0], b[1] - a[1]
            norm = math.hypot(tx, ty)
            if not norm:
                continue
            nx, ny = -ty / norm, tx / norm
            probe = (o[0] + nx * 3 * STEP_M, o[1] + ny * 3 * STEP_M)
            if not point_in_polygons(probe, sea):
                nx, ny = -nx, -ny
                if not point_in_polygons((o[0] + nx * 3 * STEP_M, o[1] + ny * 3 * STEP_M), sea):
                    continue           # no clear sea side here (e.g. a narrow spit): skip
            out.append({"line": li, "chainage": round(c, 1), "origin": o, "normal": (nx, ny)})
    return out


def profile_offsets(land: float = LAND_M, sea: float = SEA_M, step: float = STEP_M) -> list[float]:
    """Sample positions along a transect, metres from the baseline, landward negative."""
    n_land, n_sea = int(land // step), int(sea // step)
    return [i * step for i in range(-n_land, n_sea + 1)]


# ---------- positions and rates ----------
def shoreline_position(values: list[int | None], offsets: list[float], min_agreement: float = MIN_AGREEMENT,
                       land_run: int = LAND_RUN, check_m: float = LANDWARD_CHECK_M) -> dict:
    """Edge of the sea-connected water on one profile. values: 1 water, 0 land, None no data,
    landward first. Starting at the seaward end (which must be water), walk landward through the
    water until `land_run` land samples in a row: the shoreline is midway between the last water
    sample and that run. Inland ponds behind the coast are never reached, and a single land pixel in
    the sea (speckle, a boat) doesn't stop the walk.
    {'pos': metres from the baseline or None, 'agreement': water share seaward of pos + land share in
     the check_m landward of it, 'status'}"""
    pts = [(o, v) for o, v in zip(offsets, values) if v in (0, 1)]
    if len(pts) < 5:
        return {"pos": None, "agreement": None, "status": "no_data"}
    tail = [v for _, v in pts[-5:]]
    if sum(tail) < 3:                                                      # no sea at the seaward end
        land = sum(1 - v for _, v in pts) / len(pts)
        return {"pos": None, "agreement": round(land, 3),                  # shore beyond the transect, or a pier
                "status": "all_land" if land >= min_agreement else "unclear"}
    i, run, last_water = len(pts) - 1, 0, None
    while i >= 0:
        if pts[i][1] == 1:
            run, last_water = 0, i
        else:
            run += 1
            if run >= land_run:
                break
        i -= 1
    if i < 0:                                                              # water to the landward end
        share = sum(v for _, v in pts) / len(pts)
        return {"pos": None, "agreement": round(share, 3), "status": "all_water" if share >= min_agreement else "unclear"}
    first_land = i + land_run - 1                                          # seaward-most sample of the land run
    pos = (pts[first_land][0] + pts[last_water][0]) / 2
    sea = [v for o, v in pts if o > pos]
    land = [v for o, v in pts if pos - check_m <= o < pos]
    agreement = (sum(sea) + sum(1 - v for v in land)) / max(1, len(sea) + len(land))
    if agreement < min_agreement:
        return {"pos": None, "agreement": round(agreement, 3), "status": "unclear"}
    return {"pos": round(pos, 1), "agreement": round(agreement, 3), "status": "ok"}


_T95 = [(1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571), (6, 2.447), (7, 2.365), (8, 2.306),
        (9, 2.262), (10, 2.228), (12, 2.179), (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042), (60, 2.000)]


def t95(df: int) -> float:
    """Two-sided 95 % Student-t critical value (table, conservative between rows)."""
    if df < 1:
        return float("inf")
    val = 1.96
    for d, t in reversed(_T95):
        if df >= d:
            return t if df < 120 else val
    return _T95[0][1]


def rate_stats(series: list[tuple[float, float | None]], min_months: int = MIN_MONTHS) -> dict:
    """Linear regression rate of positions over time. series: [(years since start, pos or None)].
    {'n', 'lrr' m/yr, 'ci95', 'r2', 'nsm' m, 'trend': advancing / retreating / stable / too_few}"""
    pts = [(t, p) for t, p in series if p is not None]
    n = len(pts)
    out = {"n": n, "lrr": None, "ci95": None, "r2": None, "nsm": None, "trend": "too_few"}
    if n < min_months:
        return out
    k = min(3 if n > 12 else 2, n // 2)
    out["nsm"] = round(sum(p for _, p in pts[-k:]) / k - sum(p for _, p in pts[:k]) / k, 1)
    tm = sum(t for t, _ in pts) / n
    pm = sum(p for _, p in pts) / n
    sxx = sum((t - tm) ** 2 for t, _ in pts)
    if not sxx:
        return out
    slope = sum((t - tm) * (p - pm) for t, p in pts) / sxx
    resid = [p - (pm + slope * (t - tm)) for t, p in pts]
    sse = sum(r * r for r in resid)
    sst = sum((p - pm) ** 2 for _, p in pts)
    se = math.sqrt(sse / (n - 2) / sxx) if n > 2 else float("inf")
    ci = t95(n - 2) * se
    out.update(lrr=round(slope, 2), ci95=round(ci, 2) if math.isfinite(ci) else None,
               r2=round(1 - sse / sst, 3) if sst else None)
    if math.isfinite(ci) and slope - ci > 0:
        out["trend"] = "advancing"           # land moves seaward: accretion or reclamation
    elif math.isfinite(ci) and slope + ci < 0:
        out["trend"] = "retreating"          # sea moves landward: erosion
    else:
        out["trend"] = "stable"
    return out


def quarters(keys: list[str]) -> list[list[str]]:
    """Consecutive 3-month windows from the first month; a trailing window shorter than 2 months is dropped."""
    out = [keys[i: i + 3] for i in range(0, len(keys), 3)]
    return [q for q in out if len(q) >= 2]


def iqr(values: list[float]) -> float | None:
    v = sorted(values)
    if len(v) < 4:
        return None
    q = lambda f: v[min(len(v) - 1, max(0, round(f * (len(v) - 1))))]
    return round(q(0.75) - q(0.25), 1)


def confirm(radar_trend: str, opt_first: float | None, opt_last: float | None, min_shift: float = OPT_MIN_SHIFT_M) -> dict:
    """{'opt_shift': m or None, 'change': advancing / retreating / unconfirmed / stable / too_few}."""
    shift = None if opt_first is None or opt_last is None else round(opt_last - opt_first, 1)
    if radar_trend not in ("advancing", "retreating"):
        return {"opt_shift": shift, "change": radar_trend}
    sign = 1 if radar_trend == "advancing" else -1
    ok = shift is not None and sign * shift >= min_shift
    return {"opt_shift": shift, "change": radar_trend if ok else "unconfirmed"}


def years_since(month: str, start: str) -> float:
    y0, m0 = map(int, start.split("-"))
    y, m = map(int, month.split("-"))
    return ((y - y0) * 12 + (m - m0)) / 12


def monthly_lines(transects: list[dict], positions: dict[str, list[float | None]], month_idx: int,
                  frame: LocalFrame, max_gap: int = 1) -> list[list[tuple[float, float]]]:
    """The month's shoreline as polylines (lon/lat) through consecutive transects' positions. A run
    breaks where a transect has no position or the next one is more than max_gap transects away."""
    runs, cur, prev = [], [], None
    for tr in transects:
        p = positions[tr["id"]][month_idx]
        key = (tr["line"], tr["index"])
        if p is None:
            continue
        if prev is not None and (key[0] != prev[0] or key[1] - prev[1] > max_gap + 1):
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
        ox, oy = tr["origin_m"]
        nx, ny = tr["normal"]
        cur.append(frame.to_lonlat(ox + nx * p, oy + ny * p))
        prev = key
    if len(cur) >= 2:
        runs.append(cur)
    return [[(round(x, 6), round(y, 6)) for x, y in run] for run in runs]


# ---------- Earth Engine ----------
def water_stack(ee: Any, aoi: dict, months: list[dict]) -> Any:
    """One band per month (w_YYYY_MM) and per quarter (q_YYYY_MM, named by its first month):
    1 water, 0 land, 255 no radar look. A quarter is water where at least half of all its looks are."""
    from .monthly import month_windows, water_image
    bands = []
    for row in months:
        key = row["month"]
        _, s, e = month_windows(key, key)[0]
        bands.append(water_image(ee, aoi, s, e, row["s1_thresholds_db"]).unmask(255).rename(f"w_{key.replace('-', '_')}"))
    by_key = {r["month"]: r for r in months}
    for q in quarters([r["month"] for r in months]):
        thresholds = {k: v for m in q for k, v in by_key[m]["s1_thresholds_db"].items()}
        _, s, _ = month_windows(q[0], q[0])[0]
        _, _, e = month_windows(q[-1], q[-1])[0]
        bands.append(water_image(ee, aoi, s, e, thresholds).unmask(255).rename(f"q_{q[0].replace('-', '_')}"))
    for label, s, e in dry_season_windows([r["month"] for r in months]):
        bands.append(optical_water(ee, aoi, s, e).rename(f"o_{label.replace('-', '_')}"))
    return ee.Image.cat(bands)


def dry_season_windows(keys: list[str]) -> list[tuple[str, str, str]]:
    from .monthly import dry_seasons
    return dry_seasons(keys[0], keys[-1])


def optical_water(ee: Any, aoi: dict, start: str, end: str) -> Any:
    """Sentinel-2 water for a season: median MNDWI of the clear (SCL) looks > 0; 255 where never clear."""
    from .ee_engine import S2_COLLECTION
    from .monthly import S2_CLEAR_SCL

    def clear(im: Any) -> Any:
        ok = im.select("SCL").remap(S2_CLEAR_SCL, [1] * len(S2_CLEAR_SCL), 0)
        return im.normalizedDifference(["B3", "B11"]).rename("mndwi").updateMask(ok)

    col = ee.ImageCollection(S2_COLLECTION).filterBounds(ee.Geometry(aoi)).filterDate(start, end).map(clear)
    water = col.median().gt(0).unmask(255).toByte()
    # a season before Sentinel-2 SR covers the area has no images: all 255 (no optical position)
    return ee.Image(ee.Algorithms.If(col.size().gt(0), water, ee.Image.constant(255).toByte().rename("mndwi")))


def sea_polygons(ee: Any, aoi: dict, stack: Any) -> list[dict]:
    """GeoJSON sea polygons from water occurrence (touching the AOI edge, >= SEA_MIN_HA)."""
    geom = ee.Geometry(aoi)
    monthly_bands = stack.select("w_.*")
    occ = monthly_bands.updateMask(monthly_bands.neq(255)).reduce(ee.Reducer.mean())
    water = occ.gte(OCCURRENCE).unmask(0)
    opened = water.focalMin(OPEN_M, "circle", "meters").focalMax(OPEN_M, "circle", "meters")
    vec = opened.selfMask().reduceToVectors(
        geometry=geom, scale=VECTOR_SCALE, geometryType="polygon", eightConnected=True, maxPixels=1e10, tileScale=4)
    edge = geom.buffer(-EDGE_M, 1)
    vec = vec.map(lambda f: f.set("area_ha", f.geometry().area(1).divide(1e4),
                                  "touches_edge", f.geometry().difference(edge, 1).area(1).gt(0)))
    return vec.filter(ee.Filter.gte("area_ha", SEA_MIN_HA)).filter(ee.Filter.eq("touches_edge", 1)).getInfo()["features"]


def sample_profiles(ee: Any, stack: Any, points: list[tuple[str, int, float, float]], bands: list[str], log=print,
                    scale: float = STEP_M) -> dict:
    """{transect id: {band: [value per offset]}}, each point read at `scale` m. points: [(tid, i, lon, lat)]."""
    out: dict[str, dict[str, list]] = {}
    for b0 in range(0, len(points), SAMPLE_BATCH):
        batch = points[b0: b0 + SAMPLE_BATCH]
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([lon, lat]), {"t": t, "i": i}) for t, i, lon, lat in batch])
        got = stack.reduceRegions(collection=fc, reducer=ee.Reducer.first(), scale=scale, tileScale=4).getInfo()["features"]
        for f in got:
            p = f["properties"]
            rec = out.setdefault(p["t"], {b: {} for b in bands})
            for b in bands:
                v = p.get(b)
                rec[b][p["i"]] = None if v is None or v == 255 else int(v)
        log(f"  sampled {min(b0 + SAMPLE_BATCH, len(points))} / {len(points)} points")
    return out


def build(aoi: dict, summary: dict, log=print) -> dict:
    """The full shoreline analysis for the monthly period in summary (Phase 10's summary.json)."""
    from .ee_engine import _ee
    ee = _ee()
    months = summary["months"]
    keys = [r["month"] for r in months]
    qs = quarters(keys)
    bands = [f"w_{k.replace('-', '_')}" for k in keys]
    qbands = [f"q_{q[0].replace('-', '_')}" for q in qs]
    seasons = dry_season_windows(keys)
    obands = [f"o_{label.replace('-', '_')}" for label, _, _ in seasons]
    stack = water_stack(ee, aoi, months)

    ring = aoi["coordinates"][0]
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    frame = LocalFrame((min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2)
    bw, bs = frame.to_m(min(lons), min(lats))
    be, bn = frame.to_m(max(lons), max(lats))

    sea_feats = sea_polygons(ee, aoi, stack)
    sea_m, lines = [], []
    for f in sea_feats:
        g = f["geometry"]
        for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            rings = [[frame.to_m(x, y) for x, y in r] for r in poly]
            sea_m.append(rings)
            for r in rings:
                for piece in split_off_edge(r, (bw, bs, be, bn), EDGE_M):
                    simple = douglas_peucker(piece, SMOOTH_M)
                    if line_length(simple) >= MIN_LINE_M:
                        lines.append(smooth(simple))
    log(f"sea: {len(sea_feats)} polygons, baseline {len(lines)} lines, {sum(map(line_length, lines)) / 1000:.1f} km")

    raw = make_transects(lines, sea_m)
    offsets = profile_offsets()
    transects, points, per_line = [], [], {}
    for tr in raw:
        idx = per_line.get(tr["line"], 0); per_line[tr["line"]] = idx + 1
        tid = f"t{len(transects) + 1:04d}"
        (ox, oy), (nx, ny) = tr["origin"], tr["normal"]
        transects.append({"id": tid, "line": tr["line"], "index": idx, "chainage": tr["chainage"],
                          "origin_m": (ox, oy), "normal": (nx, ny)})
        for i, o in enumerate(offsets):
            lon, lat = frame.to_lonlat(ox + nx * o, oy + ny * o)
            points.append((tid, i, lon, lat))
    log(f"{len(transects)} transects, {len(points)} sample points")

    profiles = sample_profiles(ee, stack, points, bands + qbands + obands, log)
    positions: dict[str, list[float | None]] = {}
    qpositions: dict[str, list[float | None]] = {}
    status_counts: dict[str, int] = {}
    q_times = [sum(years_since(m, keys[0]) for m in q) / len(q) for q in qs]
    for tr in transects:
        prof = profiles.get(tr["id"], {})
        rows = {}
        for group, names in (("month", bands), ("quarter", qbands), ("optical", obands)):
            row = []
            for b in names:
                res = shoreline_position([prof.get(b, {}).get(i) for i in range(len(offsets))], offsets)
                if group == "month":
                    status_counts[res["status"]] = status_counts.get(res["status"], 0) + 1
                row.append(res["pos"])
            rows[group] = row
        positions[tr["id"]], qpositions[tr["id"]] = rows["month"], rows["quarter"]
        st = rate_stats(list(zip(q_times, rows["quarter"])), min_months=MIN_QUARTERS)
        spread = iqr([p for p in rows["month"] if p is not None])
        opt = rows["optical"]
        conf = confirm(st["trend"], opt[0] if opt else None, opt[-1] if len(opt) > 1 else None)
        tr["stats"] = {**st, "monthly_iqr": spread, "tidal": bool(spread is not None and spread > TIDAL_IQR_M),
                       "opt_first": opt[0] if opt else None, "opt_last": opt[-1] if len(opt) > 1 else None, **conf}

    return {"frame": frame, "keys": keys, "quarters": qs, "seasons": [label for label, _, _ in seasons], "lines": lines, "transects": transects,
            "positions": positions, "qpositions": qpositions, "status_counts": status_counts, "offsets": offsets}


# ---------- output ----------
METHOD = {
    "water": "Phase 10 monthly Sentinel-1 water maps (monthly.water_image)",
    "sea": f"water occurrence >= {OCCURRENCE} of the months, polygons at {VECTOR_SCALE} m touching the AOI edge, >= {SEA_MIN_HA} ha",
    "baseline": f"sea mask opened by {OPEN_M} m, boundary minus the AOI cut ({EDGE_M} m), Douglas-Peucker {SMOOTH_M} m, "
                f"smoothed over +-{SMOOTH_WINDOW_M} m, lines >= {MIN_LINE_M} m",
    "transects": f"every {TRANSECT_SPACING_M} m, perpendicular over +-{NORMAL_SPAN_M} m, {LAND_M} m landward to {SEA_M} m seaward, samples every {STEP_M} m",
    "position": f"landward edge of the sea-connected water: walk from the seaward end until {LAND_RUN} land samples in a row; none if < {MIN_AGREEMENT:.0%} agreement, no sea at the seaward end, or water to the landward end",
    "rate": f"from quarterly shorelines (water in >= half of a quarter's radar looks, tide-averaged): linear regression rate "
            f"(m/yr, seaward +) with a 95 % CI, >= {MIN_QUARTERS} quarters; advancing / retreating only when the CI excludes 0",
    "nsm": "net shoreline movement: mean of the last 2 quarterly positions minus mean of the first 2",
    "tidal": f"monthly positions with an IQR > {TIDAL_IQR_M} m: a wide intertidal flat; monthly lines there move with the tide",
    "confirmation": f"change = radar trend confirmed by the Sentinel-2 dry-season shoreline (median MNDWI > 0) moving the same way by >= {OPT_MIN_SHIFT_M} m "
                    "between the first and last dry season; otherwise unconfirmed",
    "tide": "monthly positions include tide differences (several m range, D11); the 24-month rate is the reported quantity",
}


def write_outputs(result: dict, out_dir: Path | None = None) -> dict:
    out_dir = out_dir or SHORELINE_DIR
    frame, keys = result["frame"], result["keys"]
    out_dir.mkdir(parents=True, exist_ok=True)
    trend_counts: dict[str, int] = {}
    change_counts: dict[str, int] = {}
    tr_feats = []
    for tr in result["transects"]:
        (ox, oy), (nx, ny) = tr["origin_m"], tr["normal"]
        a = frame.to_lonlat(ox - nx * LAND_M, oy - ny * LAND_M)
        b = frame.to_lonlat(ox + nx * SEA_M, oy + ny * SEA_M)
        st = tr["stats"]
        trend_counts[st["trend"]] = trend_counts.get(st["trend"], 0) + 1
        change_counts[st.get("change", st["trend"])] = change_counts.get(st.get("change", st["trend"]), 0) + 1
        tr_feats.append({"type": "Feature", "id": tr["id"],
                         "geometry": {"type": "LineString", "coordinates": [[round(a[0], 6), round(a[1], 6)], [round(b[0], 6), round(b[1], 6)]]},
                         "properties": {"id": tr["id"], "line": tr["line"], "chainage_m": tr["chainage"], **st}})
    base_feats = [{"type": "Feature", "properties": {"line": i, "length_m": round(line_length(pts), 1)},
                   "geometry": {"type": "LineString", "coordinates": [[round(x, 6), round(y, 6)] for x, y in (frame.to_lonlat(*p) for p in pts)]}}
                  for i, pts in enumerate(result["lines"])]
    month_feats = []
    for mi, k in enumerate(keys):
        runs = monthly_lines(result["transects"], result["positions"], mi, frame)
        if runs:
            month_feats.append({"type": "Feature", "properties": {"month": k, "kind": "month"},
                                "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in r] for r in runs]}})
    for qi, q in enumerate(result["quarters"]):
        runs = monthly_lines(result["transects"], result["qpositions"], qi, frame)
        if runs:
            month_feats.append({"type": "Feature", "properties": {"quarter": f"{q[0]}/{q[-1]}", "kind": "quarter"},
                                "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in r] for r in runs]}})
    fc = lambda feats: {"type": "FeatureCollection", "features": feats}
    (out_dir / "transects.geojson").write_text(json.dumps(fc(tr_feats)))
    (out_dir / "baseline.geojson").write_text(json.dumps(fc(base_feats)))
    (out_dir / "shorelines.geojson").write_text(json.dumps(fc(month_feats)))
    (out_dir / "positions.json").write_text(json.dumps({"months": keys, "positions": result["positions"],
                                                        "quarters": [f"{q[0]}/{q[-1]}" for q in result["quarters"]],
                                                        "quarter_positions": result["qpositions"]}))
    rate = lambda kind: [t["stats"]["lrr"] for t in result["transects"] if t["stats"].get("change", t["stats"]["trend"]) == kind]
    summary = {"period": [keys[0], keys[-1]], "months": keys, "transects": len(tr_feats),
               "baseline_km": round(sum(map(line_length, result["lines"])) / 1000, 2),
               "changes": change_counts, "radar_trends": trend_counts, "dry_seasons": result.get("seasons", []), "tidal_transects": sum(t["stats"]["tidal"] for t in result["transects"]),
               "quarters": [f"{q[0]}/{q[-1]}" for q in result["quarters"]], "month_status": result["status_counts"],
               "fastest_advance_m_yr": max(rate("advancing"), default=None), "fastest_retreat_m_yr": min(rate("retreating"), default=None),
               "method": METHOD}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


# ---------- two-window mode (box evidence, D13 / D16) ----------
# The box reports compare two dry-season windows (2018-19 vs 2022-23 for QN), not the 24-month period,
# so their shoreline evidence is measured in those windows: on the same transects, one tide-averaged
# radar water map per window (water in >= half of its looks) and the optical (MNDWI) water of the window.
WINDOW_MIN_SHIFT_M = 30        # radar shift below this is "stable": 3 samples, the noise of a 10 m sample walk


def window_stats(pos_before: float | None, pos_after: float | None, opt_before: float | None,
                 opt_after: float | None, years: float, min_shift: float = WINDOW_MIN_SHIFT_M) -> dict:
    """Transect statistics between two windows, in the evidence's transect format (schema.TRANSECT_FIELDS
    minus id / location): nsm = after - before (m, seaward +), lrr = nsm / years, ci95 None (two
    points), change = radar direction confirmed by the optical shift (confirm()), else unconfirmed."""
    out = {"pos_before": pos_before, "pos_after": pos_after, "opt_before": opt_before, "opt_after": opt_after,
           "nsm": None, "lrr": None, "ci95": None}
    if pos_before is None or pos_after is None:
        return {**out, "opt_shift": None, "change": "too_few"}
    nsm = round(pos_after - pos_before, 1)
    trend = "stable" if abs(nsm) < min_shift else ("advancing" if nsm > 0 else "retreating")
    return {**out, "nsm": nsm, "lrr": round(nsm / years, 2) if years > 0 else None,
            **confirm(trend, opt_before, opt_after)}


def window_years(before_window: list[str], after_window: list[str]) -> float:
    """Years between the middles of two [start, end] date windows."""
    from datetime import date
    mid = lambda w: date.fromisoformat(w[0]).toordinal() / 2 + date.fromisoformat(w[1]).toordinal() / 2
    return (mid(after_window) - mid(before_window)) / 365.25


def transect_points(feature: dict, offsets: list[float] | None = None) -> list[tuple[float, float]]:
    """Lon/lat of the sample points of a transects.geojson line (landward end -> seaward end)."""
    offsets = offsets if offsets is not None else profile_offsets()
    (lon_a, lat_a), (lon_b, lat_b) = feature["geometry"]["coordinates"]
    span = LAND_M + SEA_M
    return [(lon_a + (o + LAND_M) / span * (lon_b - lon_a), lat_a + (o + LAND_M) / span * (lat_b - lat_a)) for o in offsets]


def build_windows(aoi: dict, transects: dict, before_window: list[str], after_window: list[str], log=print) -> dict:
    """Two-window shoreline statistics on the Phase 11 transects. {'windows', 'years', 'transects':
    {id: window_stats()}, 'status_counts', 'method'}."""
    from .ee_engine import _ee
    from .monthly import s1_thresholds, water_image
    ee = _ee()
    bands, imgs = [], []
    for name, (s, e) in (("before", before_window), ("after", after_window)):
        th = s1_thresholds(ee, aoi, s, e)
        log(f"{name} {s} - {e}: {len(th)} radar scenes ({sum(1 for v in th.values() if v.get('fallback'))} on the fallback threshold)")
        imgs += [water_image(ee, aoi, s, e, th).unmask(255).rename(f"r_{name}"), optical_water(ee, aoi, s, e).rename(f"o_{name}")]
        bands += [f"r_{name}", f"o_{name}"]
    stack = ee.Image.cat(imgs)
    offsets = profile_offsets()
    points = [(f["id"], i, lon, lat) for f in transects["features"] for i, (lon, lat) in enumerate(transect_points(f, offsets))]
    log(f"{len(transects['features'])} transects, {len(points)} sample points")
    profiles = sample_profiles(ee, stack, points, bands, log)
    years = window_years(before_window, after_window)
    out, counts = {}, {}
    for f in transects["features"]:
        prof = profiles.get(f["id"], {})
        pos = {b: shoreline_position([prof.get(b, {}).get(i) for i in range(len(offsets))], offsets)["pos"] for b in bands}
        st = window_stats(pos["r_before"], pos["r_after"], pos["o_before"], pos["o_after"], years)
        counts[st["change"]] = counts.get(st["change"], 0) + 1
        out[f["id"]] = st
    return {"windows": [list(before_window), list(after_window)], "years": round(years, 2), "transects": out,
            "status_counts": counts, "method": WINDOW_METHOD}


WINDOW_METHOD = {
    "transects": "the Phase 11 transects (transects.geojson), unchanged",
    "radar": "Sentinel-1 VV water over each whole window (per-scene Otsu thresholds, water in >= half of the looks: tide-averaged)",
    "optical": "Sentinel-2 median MNDWI > 0 over each window's clear looks",
    "position": "as Phase 11 (landward edge of the sea-connected water); none where the line lies outside the transect",
    "change": f"radar shift >= {WINDOW_MIN_SHIFT_M} m, confirmed by the optical shift (>= {OPT_MIN_SHIFT_M} m the same way), else unconfirmed; "
              "below that stable; lrr = nsm / years between the window middles, no CI (two points)",
}


def windows_file(before_window: list[str], after_window: list[str], out_dir: Path | None = None) -> Path:
    tag = f"{before_window[0][:7]}_{after_window[0][:7]}"
    return (out_dir or SHORELINE_DIR) / f"windows_{tag}.json"


def evidence_transects(box: tuple, transects: dict, stats: dict) -> list[dict]:
    """Evidence transects (schema.TRANSECT_FIELDS) for a box: every transect whose line crosses the box,
    its location = where its inside part's middle falls in the box's 3 x 3 grid. A transect the
    window run has no statistics for is left out."""
    from .site_evidence import where_in_box
    w, s, e, n = box
    out = []
    for f in transects["features"]:
        st = stats.get(f["id"])
        if st is None:
            continue
        (x0, y0), (x1, y1) = f["geometry"]["coordinates"]
        inside = [(x0 + (x1 - x0) * k / 50, y0 + (y1 - y0) * k / 50) for k in range(51)]
        inside = [p for p in inside if w <= p[0] <= e and s <= p[1] <= n]
        if not inside:
            continue
        mid = inside[len(inside) // 2]
        out.append({"id": f["id"], "location": where_in_box(*mid, box), "change": st["change"],
                    "nsm": st["nsm"], "lrr": st["lrr"], "ci95": st["ci95"]})
    return out


# ---------- yearly mode (map time slider) ----------
# One shoreline per dry season (Oct-Mar, as D11) from 2015-16 to 2025-26 on the same transects, each from
# a tide-averaged radar water map over the whole season (as the two-window mode) plus the season's optical
# water. The 24-month monthly series shows tides more than change; ten seasons show the change.
YEARS_FIRST, YEARS_LAST = "2015-10", "2026-03"
MIN_SEASONS = 5                # seasons with a position needed for a rate


def year_seasons(first: str = YEARS_FIRST, last: str = YEARS_LAST) -> list[tuple[str, str, str]]:
    """[(label, first day, day after)], e.g. ('2015-16', '2015-10-01', '2016-04-01')."""
    from .monthly import dry_seasons
    return dry_seasons(first, last)


def position_point(feature: dict, pos: float) -> tuple[float, float]:
    """Lon/lat of a position (m from the baseline, seaward +) on a transects.geojson line."""
    (lon_a, lat_a), (lon_b, lat_b) = feature["geometry"]["coordinates"]
    f = (pos + LAND_M) / (LAND_M + SEA_M)
    return round(lon_a + f * (lon_b - lon_a), 6), round(lat_a + f * (lat_b - lat_a), 6)


def season_lines(features: list[dict], positions: dict[str, list[float | None]], idx: int,
                 max_gap: int = 1) -> list[list[tuple[float, float]]]:
    """A season's shoreline as polylines through consecutive transects' positions (as monthly_lines, from
    transects.geojson: neighbours are consecutive features of the same baseline line)."""
    runs, cur, prev = [], [], None
    for k, f in enumerate(features):
        p = (positions.get(f["id"]) or [None] * (idx + 1))[idx]
        if p is None:
            continue
        line = f["properties"]["line"]
        if prev is not None and (line != prev[0] or k - prev[1] > max_gap + 1):
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
        cur.append(position_point(f, p))
        prev = (line, k)
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def years_stats(labels: list[str], radar: list[float | None], optical: list[float | None]) -> dict:
    """A transect's rate over the seasons (rate_stats, years from the first season) with the change
    confirmed by the optical shift between its first and last season with an optical position."""
    t = [int(lb[:4]) - int(labels[0][:4]) for lb in labels]
    st = rate_stats(list(zip(t, radar)), min_months=MIN_SEASONS)
    opt = [p for p in optical if p is not None]
    return {**st, "opt_first": opt[0] if opt else None, "opt_last": opt[-1] if len(opt) > 1 else None,
            **confirm(st["trend"], opt[0] if opt else None, opt[-1] if len(opt) > 1 else None)}


def build_years(aoi: dict, transects: dict, seasons: list[tuple[str, str, str]] | None = None, log=print) -> dict:
    """Yearly shoreline positions and rates on the Phase 11 transects. {'seasons', 'positions': {id: [m]},
    'optical': {id: [m]}, 'transects': {id: years_stats()}, 'status_counts', 'method'}."""
    from .ee_engine import _ee
    from .monthly import s1_thresholds, water_image
    ee = _ee()
    seasons = seasons or year_seasons()
    bands, imgs = [], []
    for label, s, e in seasons:
        th = s1_thresholds(ee, aoi, s, e)
        tag = label.replace("-", "_")
        log(f"{label} {s} - {e}: {len(th)} radar scenes ({sum(1 for v in th.values() if v.get('fallback'))} on the fallback threshold)")
        if th:
            imgs.append(water_image(ee, aoi, s, e, th).unmask(255).rename(f"r_{tag}"))
            bands.append(f"r_{tag}")
        imgs.append(optical_water(ee, aoi, s, e).rename(f"o_{tag}"))
        bands.append(f"o_{tag}")
    stack = ee.Image.cat(imgs)
    offsets = profile_offsets()
    points = [(f["id"], i, lon, lat) for f in transects["features"] for i, (lon, lat) in enumerate(transect_points(f, offsets))]
    log(f"{len(transects['features'])} transects, {len(points)} sample points, {len(bands)} bands")
    profiles = sample_profiles(ee, stack, points, bands, log)
    labels = [lb for lb, _, _ in seasons]
    radar, optical, stats, counts = {}, {}, {}, {}
    for f in transects["features"]:
        prof = profiles.get(f["id"], {})
        pos = lambda b: (shoreline_position([prof.get(b, {}).get(i) for i in range(len(offsets))], offsets)["pos"]
                         if b in bands else None)
        radar[f["id"]] = [pos(f"r_{lb.replace('-', '_')}") for lb in labels]
        optical[f["id"]] = [pos(f"o_{lb.replace('-', '_')}") for lb in labels]
        st = years_stats(labels, radar[f["id"]], optical[f["id"]])
        counts[st["change"]] = counts.get(st["change"], 0) + 1
        stats[f["id"]] = st
    return {"seasons": [[lb, s, e] for lb, s, e in seasons], "positions": radar, "optical": optical,
            "transects": stats, "status_counts": counts, "method": YEARS_METHOD}


YEARS_METHOD = {
    "transects": "the Phase 11 transects (transects.geojson), unchanged",
    "seasons": "dry seasons Oct-Mar, 2015-16 to 2025-26 (D11's dry-season months)",
    "radar": "Sentinel-1 VV water over each whole season (per-scene Otsu thresholds, water in >= half of the looks: tide-averaged)",
    "optical": "Sentinel-2 SR median MNDWI > 0 over each season's clear looks (none before Sentinel-2 SR covers the area)",
    "position": "as Phase 11 (landward edge of the sea-connected water); none where the line lies outside the transect",
    "rate": f"linear regression of the radar positions over the seasons (m/yr, seaward +) with a 95 % CI, >= {MIN_SEASONS} seasons; "
            "advancing / retreating only when the CI excludes 0",
    "change": f"radar trend confirmed by the optical shoreline moving the same way by >= {OPT_MIN_SHIFT_M} m between its first and "
              "last season with an optical position, else unconfirmed",
}


def years_outputs(result: dict, transects: dict, out_dir: Path | None = None) -> dict:
    """Write years.json (seasons, positions, stats) and years_lines.geojson (one MultiLineString per season)."""
    out_dir = out_dir or SHORELINE_DIR
    labels = [s[0] for s in result["seasons"]]
    feats = []
    for i, lb in enumerate(labels):
        runs = season_lines(transects["features"], result["positions"], i)
        if runs:
            feats.append({"type": "Feature", "properties": {"season": lb, "kind": "season"},
                          "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in r] for r in runs]}})
    (out_dir / "years.json").write_text(json.dumps(result))
    (out_dir / "years_lines.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return {"seasons": labels, "lines": len(feats), "status_counts": result["status_counts"]}


# ---------- Planet 3 m shoreline (D12, Phase 13c) ----------
# One PlanetScope day per month (Oct 2024 - Sep 2025, Feb 2025 missing; agents/planet.py), water = NDWI > 0
# on Planet's clear pixels, read on the same transects every PLANET_STEP_M at Planet's 3 m. A single day is
# at one tide, like a single radar look, so these positions are compared with the radar, never fitted for
# rates. They give: (1) a 3 m check of the radar shorelines month by month, dry and monsoon months apart
# (the monsoon months have no clear Sentinel-2, so this is their only optical check), and (2) a 3 m check
# of the tide-averaged yearly 2024-25 shoreline against the median of the Planet dry-season months.
PLANET_STEP_M = 5               # m between samples (Planet pixels are 3 m)
PLANET_YEAR = "2024-25"         # the yearly (dry-season) shoreline the Planet dry months are compared with
CHECK_WITHIN_M = (20, 30)       # report the share of differences within these


def planet_offsets() -> list[float]:
    return profile_offsets(step=PLANET_STEP_M)


def is_dry_month(month: str) -> bool:
    return int(month[5:7]) in (10, 11, 12, 1, 2, 3)


def diff_stats(diffs: list[float]) -> dict:
    """Agreement of two shorelines from their position differences (a - b, m, seaward +)."""
    if not diffs:
        return {"n": 0, "bias_m": None, "mae_m": None, "rmse_m": None, "median_abs_m": None,
                **{f"within_{w}m": None for w in CHECK_WITHIN_M}}
    n = len(diffs)
    absd = sorted(abs(d) for d in diffs)
    return {"n": n, "bias_m": round(sum(diffs) / n, 1), "mae_m": round(sum(absd) / n, 1),
            "rmse_m": round(math.sqrt(sum(d * d for d in diffs) / n), 1), "median_abs_m": round(median(absd), 1),
            **{f"within_{w}m": round(sum(1 for d in absd if d <= w) / n, 3) for w in CHECK_WITHIN_M}}


def median(values: list[float]) -> float | None:
    v = sorted(values)
    if not v:
        return None
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2


def planet_compare(months: list[str], planet: dict[str, list[float | None]], radar_months: list[str],
                   radar: dict[str, list[float | None]], yearly: dict[str, float | None] | None = None,
                   skip: set[str] = frozenset()) -> dict:
    """Planet vs radar positions. planet / radar: {transect id: [position per month]}; yearly: {transect id:
    the PLANET_YEAR yearly radar position}. Transects in `skip` (Phase 14 reference transects, blind) are left out.
    {'per_month': [{month, dry, n_planet, ...diff_stats}], 'dry': diff_stats, 'monsoon': diff_stats,
     'yearly': diff_stats of (median Planet dry-season position - yearly position)}."""
    ridx = {m: i for i, m in enumerate(radar_months)}
    per_month, dry, wet, yr = [], [], [], []
    for mi, m in enumerate(months):
        diffs, n_planet = [], 0
        for tid, row in planet.items():
            p = row[mi] if mi < len(row) else None
            if tid in skip or p is None:
                continue
            n_planet += 1
            rrow = radar.get(tid) or []
            r = rrow[ridx[m]] if m in ridx and ridx[m] < len(rrow) else None
            if r is not None:
                diffs.append(p - r)
        (dry if is_dry_month(m) else wet).extend(diffs)
        per_month.append({"month": m, "dry": is_dry_month(m), "n_planet": n_planet, **diff_stats(diffs)})
    if yearly:
        dry_idx = [i for i, m in enumerate(months) if is_dry_month(m)]
        for tid, row in planet.items():
            y = yearly.get(tid)
            pm = median([row[i] for i in dry_idx if i < len(row) and row[i] is not None])
            if tid not in skip and y is not None and pm is not None:
                yr.append(pm - y)
    return {"per_month": per_month, "dry": diff_stats(dry), "monsoon": diff_stats(wet), "yearly": diff_stats(yr)}


def build_planet(transects: dict, months: list[str] | None = None, log=print) -> dict:
    """Planet shoreline positions on the Phase 11 transects. {'months', 'dates', 'positions': {id: [m]},
    'status_counts', 'method'}."""
    from . import planet as pl
    from .ee_engine import _ee
    ee = _ee()
    months = months or pl.available_months(ee)
    if not months:
        raise RuntimeError(f"no Planet months in {pl.PLANET_COLLECTION}")
    by_month = {d[:7]: d for d in pl.collection(ee).aggregate_array("date").getInfo()}
    bands = [f"p_{m.replace('-', '_')}" for m in months]
    stack = ee.Image.cat([pl.water_image(ee, m).unmask(255).toByte().rename(b) for m, b in zip(months, bands)])
    offsets = planet_offsets()
    points = [(f["id"], i, lon, lat) for f in transects["features"] for i, (lon, lat) in enumerate(transect_points(f, offsets))]
    log(f"{len(months)} Planet months, {len(transects['features'])} transects, {len(points)} sample points")
    profiles = sample_profiles(ee, stack, points, bands, log, scale=pl.NATIVE_SCALE)
    positions, counts = {}, {}
    for f in transects["features"]:
        prof = profiles.get(f["id"], {})
        row = []
        for b in bands:
            res = shoreline_position([prof.get(b, {}).get(i) for i in range(len(offsets))], offsets)
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            row.append(res["pos"])
        positions[f["id"]] = row
    return {"months": months, "dates": [by_month.get(m) for m in months], "positions": positions,
            "status_counts": counts, "method": PLANET_METHOD}


PLANET_METHOD = {
    "imagery": "PlanetScope 8-band surface reflectance harmonised to Sentinel-2, one clear day per month, 3 m (agents/planet.py, D12)",
    "water": "NDWI (green, NIR) > 0 on Planet's UDM2 clear pixels; cloud / haze / no data is no data",
    "position": f"as Phase 11 on the same transects, samples every {PLANET_STEP_M} m read at 3 m: landward edge of the "
                f"sea-connected water ({LAND_RUN} land samples in a row)",
    "tide": "one day per month is one tide level (several m range, D11): positions are compared, not fitted for rates",
    "compare_month": "Planet minus the Phase 11 monthly radar position, same transect and month (seaward +); dry months "
                     "(Oct-Mar) and monsoon months (Apr-Sep) apart",
    "compare_yearly": f"median Planet position over the dry-season months minus the {PLANET_YEAR} yearly (tide-averaged) radar position",
    "blind": "the Phase 14 reference transects and their neighbours are left out of the comparison and hidden in the app",
}


def planet_outputs(result: dict, transects: dict, out_dir: Path | None = None) -> dict:
    """Write planet.json (months, dates, positions, comparison with the radar) and planet_lines.geojson."""
    out_dir = out_dir or SHORELINE_DIR
    pos = load("positions.json", out_dir) or {"months": [], "positions": {}}
    years = load("years.json", out_dir)
    yearly = None
    if years:
        labels = [s[0] for s in years["seasons"]]
        if PLANET_YEAR in labels:
            yi = labels.index(PLANET_YEAR)
            yearly = {tid: row[yi] for tid, row in years["positions"].items()}
    skip = hidden_transects(transects)
    compare = planet_compare(result["months"], result["positions"], pos["months"], pos["positions"], yearly, skip)
    feats = []
    for i, m in enumerate(result["months"]):
        runs = season_lines(transects["features"], result["positions"], i)
        if runs:
            feats.append({"type": "Feature", "properties": {"month": m, "date": result["dates"][i], "kind": "planet"},
                          "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in r] for r in runs]}})
    out = {**result, "compare": compare, "attribution": "Imagery © Planet Labs PBC"}
    (out_dir / "planet.json").write_text(json.dumps(out))
    (out_dir / "planet_lines.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return {"months": result["months"], "lines": len(feats), "status_counts": result["status_counts"],
            "dry": compare["dry"], "monsoon": compare["monsoon"], "yearly": compare["yearly"]}


# ---------- Phase 14 blind lock ----------
REFERENCE_TRANSECTS_UNLOCKED = False     # set True in the commit that adds the Phase 14 reference shorelines
HIDDEN_FIELDS = ("n", "lrr", "ci95", "r2", "nsm", "trend", "monthly_iqr", "tidal", "opt_first", "opt_last", "opt_shift", "change")
_HIDE_NEAR_M = 30                        # a shoreline vertex this close to a hidden transect belongs to it


def hidden_transects(transects: dict | None = None) -> set[str]:
    """Ids hidden until the Phase 14 reference shorelines exist: the 30 reference transects and
    their neighbours (labels14.hidden_transect_ids). Empty when unlocked or not sampled yet."""
    if REFERENCE_TRANSECTS_UNLOCKED:
        return set()
    from . import labels14
    refs = labels14.load_samples(labels14.TRANSECTS_FILE)
    transects = transects if transects is not None else load("transects.geojson")
    if not refs or not transects:
        return set()
    return labels14.hidden_transect_ids(transects, refs)


def hide_transects(fc: dict, hidden: set[str]) -> dict:
    """Copy of the transects with the extracted statistics removed (and hidden: true) on hidden ones."""
    feats = [f if f["id"] not in hidden else
             {**f, "properties": {**{k: v for k, v in f["properties"].items() if k not in HIDDEN_FIELDS}, "hidden": True}}
             for f in fc["features"]]
    return {**fc, "features": feats}


def _near_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float], frame: "LocalFrame", tol: float) -> bool:
    (px, py), (ax, ay), (bx, by) = frame.to_m(*p), frame.to_m(*a), frame.to_m(*b)
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy) <= tol


def hide_lines(fc: dict, transects: dict, hidden: set[str], tol: float = _HIDE_NEAR_M) -> dict:
    """Copy of the extracted shorelines with the vertices on hidden transects removed: each line is
    split there, so no line passes through (or interpolates across) a reference transect."""
    if not hidden:
        return fc
    segs = [tuple(map(tuple, f["geometry"]["coordinates"])) for f in transects["features"] if f["id"] in hidden]
    feats = []
    for f in fc["features"]:
        lines = []
        for line in f["geometry"]["coordinates"]:
            cur = []
            for p in line:
                frame = LocalFrame(p[0], p[1])
                if any(_near_segment(tuple(p), a, b, frame, tol) for a, b in segs
                       if abs(a[0] - p[0]) < 0.01 and abs(a[1] - p[1]) < 0.01):
                    if len(cur) >= 2:
                        lines.append(cur)
                    cur = []
                else:
                    cur.append(p)
            if len(cur) >= 2:
                lines.append(cur)
        if lines:
            feats.append({**f, "geometry": {"type": "MultiLineString", "coordinates": lines}})
    return {**fc, "features": feats}


def load(name: str, out_dir: Path | None = None) -> Any:
    path = (out_dir or SHORELINE_DIR) / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
