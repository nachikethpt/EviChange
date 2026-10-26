"""Buildings near the shoreline (D11, Phase 12).

Built area from Dynamic World (`built`, class 6) inside two strips landward of the Oct 2024 shoreline:
0-200 m and 200-500 m. Built area is reported, never building counts: at 10 m single houses are below
resolution (D11).

1. Strips. The Phase 11 baseline (data/quangninh/shoreline/baseline.geojson, the Oct 2024 shoreline) gives
   the distance of every pixel to the coast; the sea (Phase 11 sea polygons, shoreline.sea_polygons)
   is removed, so a strip is land only and islands count from their own coast. Distance 0-200 m is
   strip "0-200", over 200 up to 500 m is "200-500" (the 200 m line belongs to the inner strip).
   The strips are rasters at COASTAL_SCALE (10 m = Dynamic World's pixel), not buffered polygons:
   no polygon boolean operations, and areas are sums of pixel areas.
2. Monthly series, Oct 2024 - Sep 2026 (`monthly` in study.json): per strip the built hectares of the
   month's Dynamic World label mode (monthly.class_image), the hectares observed at all and the cover
   (observed / strip land). A month whose cover is under 50 % (monthly.class_status: "patchy" or "none",
   the monsoon months) is a gap: built_ha is null, never 0. Also one figure per dry season
   (monthly.dry_seasons), because single months are noisy (Phase 10).
3. New built patches: pixels built in the last dry season and not in the first, observed in both,
   at least PATCH_MIN_HA (connected, 8-neighbour), vectorised as regions with area_ha, like the
   Phase 2 change regions. A patch that crosses the 200 m line is split in two.
4. Open Buildings Temporal (GOOGLE/Research/open-buildings-temporal/v1, `building_presence`, yearly to
   2023): built area per strip per year where the confidence is at least a threshold. Reference only:
   the confidence is uncalibrated (the dataset says it is good for ranking / thresholding only), so
   three thresholds are reported; and it measures building footprints, Dynamic World `built` also
   takes roads, ports and yards, so the two are different quantities and are never compared as one.
5. Box evidence between two windows (D13 / D16, Phase 15): the strips are tiled into ~100 m cells
   (CELL_DEG), per window pair the built area of each cell is saved (scripts/make_coastal_windows.py),
   and evidence_strips() clips them to a box and returns `coastal_strips[]` (schema.STRIP_FIELDS).

Blindness (Phase 14 c): P2 labels 30 coastal cells from imagery; per-cell and per-site numbers stay
out of the API until those labels exist (hide_patches, COASTAL_CELLS_UNLOCKED). Strip totals are fine.

The pure helpers here are unit-tested (tests/test_coastal.py); only the *_ee functions use Earth Engine,
imported lazily as in agents/monthly.py.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from . import monthly, shoreline
from .landcover import DW_CLASSES
from .schema import COASTAL_STRIPS, validate_strip
from .study import REPO_ROOT

COASTAL_DIR = REPO_ROOT / "data" / "quangninh" / "coastal"
SUMMARY = "summary.json"

# ---------- strips ----------
STRIP_BOUNDS_M = {"0-200": (0, 200), "200-500": (200, 500)}     # (from, to] metres landward of the baseline
STRIP_CODES = {"0-200": 1, "200-500": 2}
STRIP_NAMES = {v: k for k, v in STRIP_CODES.items()}
STRIP_MAX_M = 500
BUILT = DW_CLASSES.index("built")
COASTAL_SCALE = 10             # m: Dynamic World's pixel. Strips are thin, 20 m (Phase 10's AOI scale) is too coarse
VECTOR_SCALE = 20              # m: strips drawn as polygons for the map (areas come from the 10 m sums)
MIN_COVER = 0.5                # a strip-month needs Dynamic World on half its land, else it is a gap (class_status)

# ---------- patches ----------
PATCH_MIN_HA = 0.5             # connected new-built pixels; the verifier's COASTAL_MIN_HA is the same size
PATCH_MIN_PIXELS = math.ceil(PATCH_MIN_HA * 10_000 / COASTAL_SCALE ** 2)   # 50
PATCH_MAX_SIZE = 128           # connectedPixelCount cap (>= PATCH_MIN_PIXELS)

# ---------- Open Buildings Temporal ----------
OB_COLLECTION = "GOOGLE/Research/open-buildings-temporal/v1"
OB_BAND = "building_presence"
OB_YEARS = (2016, 2023)
OB_THRESHOLDS = (0.3, 0.5, 0.7)    # uncalibrated confidence: report a few cut-offs
OB_HEADLINE = 0.5
OB_SCALE = 4                       # m: the dataset's effective resolution

# ---------- box evidence (windows) ----------
CELL_DEG = 0.001               # ~104 m x 111 m at 21 N
CELL_BASE = 1000               # cell code = strip * CELL_BASE**2 + cx * CELL_BASE + cy
BOX_MIN_STRIP_HA = 0.5         # a strip with less land than this inside the box gets no entry
BOX_MIN_COVER = 0.5            # ... nor one Dynamic World saw (in both windows) on under half of its land

# ---------- Phase 14 (c) blind lock ----------
COASTAL_CELLS_UNLOCKED = False     # set True in the commit that adds the Phase 14 coastal-cell labels
HIDE_MARGIN_M = 30


def r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(float(v), nd)


# ---------- strip rule ----------
def strip_for_distance(d_m: float | None) -> str | None:
    """The strip of a land pixel d_m from the baseline: (0, 200] -> "0-200", (200, 500] -> "200-500".
    strip_image() builds the same rule on distance rasters; this pins the boundary convention."""
    if d_m is None or d_m < 0 or d_m > STRIP_MAX_M:
        return None
    return "0-200" if d_m <= STRIP_BOUNDS_M["0-200"][1] else "200-500"


# ---------- reading Earth Engine results ----------
def strip_areas(groups: Iterable[dict] | None) -> dict[str, float]:
    """{strip: ha} from a reduceRegion(Reducer.sum().group()) 'groups' list of pixel areas in m² grouped by strip code."""
    return {STRIP_NAMES[code]: ha for code, ha in monthly.grouped_ha(groups or []).items() if code in STRIP_NAMES}


def strip_row(land_ha: float, observed_ha: float, built_ha: float, min_cover: float = MIN_COVER) -> dict:
    """One strip in one period. built_ha (and built_share = built / observed) is null when Dynamic World saw
    under min_cover of the strip's land: a gap, not a zero."""
    cover = observed_ha / land_ha if land_ha else 0.0
    status = "none" if not cover else "clear" if cover >= min_cover else "patchy"   # as monthly.class_status, with our cut-off
    clear = status == "clear"
    return {"land_ha": r(land_ha, 1), "observed_ha": r(observed_ha, 1), "cover": r(cover, 3), "status": status,
            "built_ha": r(built_ha, 2) if clear else None,
            "built_share": r(built_ha / observed_ha, 4) if clear and observed_ha else None}


def period_row(land: dict[str, float], observed_groups: Iterable[dict] | None, built_groups: Iterable[dict] | None) -> dict[str, dict]:
    obs, built = strip_areas(observed_groups), strip_areas(built_groups)
    return {n: strip_row(land.get(n, 0.0), obs.get(n, 0.0), built.get(n, 0.0)) for n in COASTAL_STRIPS}


def series(summary: dict, strip: str | None = None) -> list[dict]:
    """The monthly series for charts: [{month, built_ha, observed_ha, cover, status, built_share}] (gaps have
    built_ha null), for one strip; without `strip`, [{month, strips: {...}}]."""
    if strip is None:
        return [{"month": m["month"], "strips": m["strips"]} for m in summary.get("months", [])]
    if strip not in COASTAL_STRIPS:
        raise ValueError(f"strip must be one of {COASTAL_STRIPS}")
    return [{"month": m["month"], **{k: m["strips"][strip][k] for k in ("built_ha", "built_share", "observed_ha", "cover", "status")}}
            for m in summary.get("months", [])]


def change_row(land: dict[str, float], compared: Iterable[dict] | None, gained: Iterable[dict] | None, lost: Iterable[dict] | None) -> dict[str, dict]:
    """Built-area change between two seasons over the pixels observed in both: compared / gained / lost hectares."""
    c, g, l = strip_areas(compared), strip_areas(gained), strip_areas(lost)
    out = {}
    for n in COASTAL_STRIPS:
        comp = c.get(n, 0.0)
        cover = comp / land[n] if land.get(n) else 0.0
        out[n] = {"compared_ha": r(comp, 1), "cover": r(cover, 3), "gained_ha": r(g.get(n, 0.0), 2), "lost_ha": r(l.get(n, 0.0), 2),
                  "net_ha": r(g.get(n, 0.0) - l.get(n, 0.0), 2)}
    return out


# ---------- polygons (pure) ----------
def _ring_area_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    """(signed area, cx, cy) of a closed ring in metres (shoelace)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if a == 0:
        return 0.0, ring[0][0], ring[0][1]
    return a / 2, cx / (6 * (a / 2)), cy / (6 * (a / 2))


def polygons_of(geometry: dict) -> list[list[list[list[float]]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError(f"not a polygon: {geometry['type']}")


def polygon_stats(geometry: dict, frame: shoreline.LocalFrame) -> dict:
    """{'area_ha', 'lon', 'lat'}: area of the polygon(s) minus holes, and the area-weighted centroid."""
    total = sx = sy = 0.0
    for poly in polygons_of(geometry):
        for i, ring in enumerate(poly):
            area, cx, cy = _ring_area_centroid([frame.to_m(x, y) for x, y in ring])
            sign = 1 if i == 0 else -1
            a = sign * abs(area)
            total += a
            sx += a * cx
            sy += a * cy
    if total <= 0:
        raise ValueError("polygon without area")
    lon, lat = frame.to_lonlat(sx / total, sy / total)
    return {"area_ha": total / 10_000, "lon": lon, "lat": lat}


def aoi_bounds(aoi: dict) -> tuple[float, float, float, float]:
    ring = aoi["coordinates"][0]
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    return min(lons), min(lats), max(lons), max(lats)


def _frame(aoi: dict) -> shoreline.LocalFrame:
    w, s, e, n = aoi_bounds(aoi)
    return shoreline.LocalFrame((w + e) / 2, (s + n) / 2)


def finalise_patches(features: list[dict], aoi: dict, min_ha: float = PATCH_MIN_HA) -> dict:
    """Patch regions from raw Earth Engine vectors (property `strip` = the strip code): area_ha (computed here, in
    metres), strip name, centroid, `location` in the AOI's 3 x 3 grid (as the Phase 2 regions), ids p0001.. by
    descending area. Patches under min_ha are dropped."""
    from .ee_engine import where_in_aoi
    frame, bounds = _frame(aoi), aoi_bounds(aoi)
    kept = []
    for f in features:
        code = int(round(f["properties"]["strip"]))
        if code not in STRIP_NAMES:
            continue
        st = polygon_stats(f["geometry"], frame)
        if st["area_ha"] < min_ha:
            continue
        kept.append((st, code, f["geometry"]))
    kept.sort(key=lambda k: -k[0]["area_ha"])
    feats = [{"type": "Feature", "id": f"p{i:04d}", "geometry": g,
              "properties": {"id": f"p{i:04d}", "strip": STRIP_NAMES[code], "area_ha": round(st["area_ha"], 3),
                             "lon": round(st["lon"], 6), "lat": round(st["lat"], 6),
                             "location": where_in_aoi(st["lon"], st["lat"], bounds)}}
             for i, (st, code, g) in enumerate(kept, 1)]
    return {"type": "FeatureCollection", "features": feats}


def finalise_strips(features: list[dict]) -> dict:
    """Strip polygons for the map: property `strip` = the strip name."""
    feats = [{"type": "Feature", "geometry": f["geometry"], "properties": {"strip": STRIP_NAMES[int(round(f["properties"]["strip"]))]}}
             for f in features if int(round(f["properties"]["strip"])) in STRIP_NAMES]
    feats.sort(key=lambda f: f["properties"]["strip"])
    return {"type": "FeatureCollection", "features": feats}


def patch_summary(patches: dict) -> dict:
    out: dict[str, Any] = {"count": len(patches["features"]), "min_ha": PATCH_MIN_HA, "by_strip": {}}
    for n in COASTAL_STRIPS:
        ha = [f["properties"]["area_ha"] for f in patches["features"] if f["properties"]["strip"] == n]
        out["by_strip"][n] = {"count": len(ha), "area_ha": round(sum(ha), 2), "largest_ha": max(ha, default=None)}
    return out


# ---------- Phase 14 (c) blind lock ----------
def hidden_cells() -> list[tuple[float, float, float, float]]:
    """Bounding boxes (w, s, e, n) of the 30 Phase 14 coastal cells, grown by HIDE_MARGIN_M."""
    from . import labels14
    path = labels14.CELLS_FILE
    if not Path(path).exists():
        return []
    margin = HIDE_MARGIN_M / shoreline.M_PER_DEG
    out = []
    for c in json.loads(Path(path).read_text(encoding="utf-8")):
        ring = c["outline"]["coordinates"][0]
        lons, lats = [p[0] for p in ring], [p[1] for p in ring]
        out.append((min(lons) - margin, min(lats) - margin, max(lons) + margin, max(lats) + margin))
    return out


def hide_patches(fc: dict, boxes: list[tuple] | None = None, unlocked: bool | None = None) -> dict:
    """Drop the new-built patches that touch a Phase 14 coastal cell (they show built / not built there) until the
    cell labels exist."""
    if COASTAL_CELLS_UNLOCKED if unlocked is None else unlocked:
        return fc
    boxes = hidden_cells() if boxes is None else boxes

    def touches(f: dict) -> bool:
        pts = [p for poly in polygons_of(f["geometry"]) for ring in poly for p in ring]
        w, e = min(p[0] for p in pts), max(p[0] for p in pts)
        s, n = min(p[1] for p in pts), max(p[1] for p in pts)
        return any(w <= be and e >= bw and s <= bn and n >= bs for bw, bs, be, bn in boxes)

    return {**fc, "features": [f for f in fc["features"] if not touches(f)]}


# ---------- Open Buildings (pure) ----------
def ob_row(year: int, tiles: int, observed: Iterable[dict] | None, by_threshold: dict[float, Iterable[dict] | None]) -> dict:
    """Open Buildings for one year: per strip the hectares the dataset covers and the built hectares at each threshold."""
    obs = strip_areas(observed)
    built = {t: strip_areas(g) for t, g in by_threshold.items()}
    return {"year": year, "tiles": tiles,
            "strips": {n: {"observed_ha": r(obs.get(n, 0.0), 1),
                           "built_ha": {f"{t:g}": r(built[t].get(n, 0.0), 2) for t in by_threshold}} for n in COASTAL_STRIPS}}


# ---------- box evidence between two windows (pure) ----------
def cell_grid(aoi: dict, step: float = CELL_DEG) -> dict:
    west, south, east, north = aoi_bounds(aoi)
    nx, ny = math.ceil(round((east - west) / step, 6)), math.ceil(round((north - south) / step, 6))   # round: 0.18 / 0.001 is 180.00000000000003
    if max(nx, ny) >= CELL_BASE:
        raise ValueError(f"the AOI needs {nx} x {ny} cells, the cell code holds under {CELL_BASE} per side: raise CELL_DEG")
    return {"lon0": west, "lat0": south, "step": step, "nx": nx, "ny": ny}


def decode_cell(code: int) -> tuple[int, int, int]:
    """(strip code, cx, cy) of a cell code strip * CELL_BASE² + cx * CELL_BASE + cy."""
    strip, rest = divmod(int(round(code)), CELL_BASE * CELL_BASE)
    cx, cy = divmod(rest, CELL_BASE)
    return strip, cx, cy


def cell_rect(cx: int, cy: int, grid: dict) -> tuple[float, float, float, float]:
    w, s = grid["lon0"] + cx * grid["step"], grid["lat0"] + cy * grid["step"]
    return w, s, w + grid["step"], s + grid["step"]


def cells_from_groups(grid: dict, land: Iterable[dict], observed: Iterable[dict], before: Iterable[dict], after: Iterable[dict]) -> list[list]:
    """Rows [strip code, cx, cy, land_ha, observed_ha, built_ha_before, built_ha_after] from the four group lists
    (cell code -> m²). `observed` is the area Dynamic World saw in BOTH windows, and both built areas are over
    those pixels, as in Phase 10's comparisons."""
    L, O, B, A = (monthly.grouped_ha(g or []) for g in (land, observed, before, after))
    rows = []
    for code in sorted(L):
        strip, cx, cy = decode_cell(code)
        if strip not in STRIP_NAMES or not (0 <= cx < grid["nx"] and 0 <= cy < grid["ny"]):
            continue
        rows.append([strip, cx, cy, round(L[code], 4), round(O.get(code, 0.0), 4), round(B.get(code, 0.0), 4), round(A.get(code, 0.0), 4)])
    return rows


WINDOW_COLUMNS = ["strip", "cx", "cy", "land_ha", "observed_ha", "built_ha_before", "built_ha_after"]


def windows_file(before_window: list[str], after_window: list[str], out_dir: Path | None = None) -> Path:
    tag = f"{before_window[0][:7]}_{after_window[0][:7]}"
    return (out_dir or COASTAL_DIR) / f"windows_{tag}.json"


def _overlap(rect: tuple, box: tuple) -> tuple[float, tuple[float, float, float, float] | None]:
    """(share of the rect inside the box, the intersection)."""
    w, s = max(rect[0], box[0]), max(rect[1], box[1])
    e, n = min(rect[2], box[2]), min(rect[3], box[3])
    if e <= w or n <= s:
        return 0.0, None
    return (e - w) * (n - s) / ((rect[2] - rect[0]) * (rect[3] - rect[1])), (w, s, e, n)


def evidence_strips(box: tuple, windows: dict, min_ha: float = BOX_MIN_STRIP_HA, min_cover: float = BOX_MIN_COVER) -> list[dict]:
    """`coastal_strips[]` (schema.STRIP_FIELDS + location) for a box (w, s, e, n) from a windows file
    (scripts/make_coastal_windows.py).

    Cells are clipped to the box by the share of each cell inside it (the built area is taken as spread evenly over
    the cell: ~100 m, so the clip is good to about one cell on the box edge). The entries are per strip AND per
    location in the box's 3 x 3 grid (where the clipped cell's middle falls), so "built-up growth in the north"
    can be checked against the north part only; the verifier sums entries of a strip when no location is claimed.
    A (strip, location) with under min_ha of land in the box, or whose land Dynamic World saw in both windows on
    under min_cover, gets no entry (the claim is then `coastal_not_in_evidence`: uncertain, never guessed).
    [] when no strip crosses the box."""
    from .site_evidence import where_in_box
    grid, cols = windows["grid"], windows["columns"]
    ix = {c: cols.index(c) for c in WINDOW_COLUMNS}
    acc: dict[tuple[str, str], list[float]] = {}
    for row in windows["cells"]:
        strip = STRIP_NAMES.get(row[ix["strip"]])
        share, inter = _overlap(cell_rect(row[ix["cx"]], row[ix["cy"]], grid), box)
        if strip is None or not share or inter is None:
            continue
        loc = where_in_box((inter[0] + inter[2]) / 2, (inter[1] + inter[3]) / 2, box)
        a = acc.setdefault((strip, loc), [0.0, 0.0, 0.0, 0.0])
        for k, col in enumerate(("land_ha", "observed_ha", "built_ha_before", "built_ha_after")):
            a[k] += row[ix[col]] * share
    out = []
    for (strip, loc), (land, obs, before, after) in sorted(acc.items()):
        if land < min_ha or obs / land < min_cover:
            continue
        entry = {"strip": strip, "built_ha_before": round(before, 3), "built_ha_after": round(after, 3), "location": loc}
        errors = validate_strip(entry)
        if errors:
            raise ValueError("; ".join(errors))
        out.append(entry)
    return out


_cache: dict = {}


def box_strips(box: tuple, before_window: list[str], after_window: list[str]) -> list[dict] | None:
    """evidence_strips() for the window pair a box was detected in. None when no window run exists for exactly these
    windows (so evidence never mixes in another period), as site_evidence.box_transects does for the transects.
    The file name only carries the months, so the dates are compared on every call, not only when it is first read."""
    try:
        path = windows_file(before_window, after_window)
    except (IndexError, TypeError):
        return None
    if path not in _cache:
        _cache[path] = load(path.name)
    data = _cache[path]
    if not data or data.get("windows") != [list(before_window), list(after_window)]:
        return None                                     # no run, or same months but other days: not this pair
    return evidence_strips(box, data)


# ---------- files ----------
def load(name: str, out_dir: Path | None = None) -> Any:
    path = (out_dir or COASTAL_DIR) / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


METHOD = {
    "strips": f"land within 0-200 m and 200-500 m of the Oct 2024 shoreline (Phase 11 baseline), the sea (Phase 11 sea polygons) removed; "
              f"rasters at {COASTAL_SCALE} m, areas are sums of pixel areas; a pixel 200 m away is in the inner strip",
    "built": "Dynamic World V1 `built` (label 6): the per-pixel mode of the label over the month / dry season (monthly.class_image)",
    "gaps": f"a strip-month with Dynamic World on under {MIN_COVER:.0%} of its land is a gap (built_ha null): the monsoon months, not zeros",
    "seasons": "dry-season (Oct-Mar) modes (monthly.dry_seasons); change over the pixels observed in both seasons",
    "patches": f"built in the last dry season, not in the first, observed in both; >= {PATCH_MIN_HA} ha connected (8-neighbour); "
               "split where they cross the 200 m line; area_ha computed from the polygon",
    "open_buildings": f"{OB_COLLECTION} `{OB_BAND}` yearly mosaic, area where the confidence >= {list(OB_THRESHOLDS)} (headline {OB_HEADLINE}) at {OB_SCALE} m; "
                      "uncalibrated confidence, footprints only (Dynamic World also counts roads, ports, yards): reference only, not part of the evaluation",
    "units": "hectares of built area, never building counts (10 m, D11)",
    "caveats": "Dynamic World labels bare ground, coal yards and port apron as built in places and the mode flickers between built / bare "
               "from month to month: trust the dry-season figures and the trend over the single months; the strips follow the 2024 coast, "
               "so for earlier windows the strip is where the coast is now",
}


def write_outputs(result: dict, out_dir: Path | None = None) -> dict:
    """Write summary.json, strips.geojson, patches.geojson and sea.geojson; returns the summary."""
    out_dir = out_dir or COASTAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fc = lambda feats: {"type": "FeatureCollection", "features": feats}
    summary = {"period": result["period"], "strips": result["strips"], "months": result["months"], "seasons": result["seasons"],
               "season_change": result["season_change"], "patches": patch_summary(result["patches"]),
               "open_buildings": result["open_buildings"], "method": METHOD}
    (out_dir / SUMMARY).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out_dir / "strips.geojson").write_text(json.dumps(result["strip_polygons"]), encoding="utf-8")
    (out_dir / "patches.geojson").write_text(json.dumps(result["patches"]), encoding="utf-8")
    if result.get("sea") is not None:
        (out_dir / "sea.geojson").write_text(json.dumps(fc(result["sea"])), encoding="utf-8")
    return summary


# =====================================================================================================
# Earth Engine (not unit-tested; mirrors agents/monthly.py)
# =====================================================================================================
def sea_features(ee: Any, aoi: dict, monthly_summary: dict) -> list[dict]:
    """The Phase 11 sea polygons (shoreline.sea_polygons), recomputed from the monthly water maps: they are not
    saved by Phase 11, so make_coastal.py keeps a copy in coastal/sea.geojson."""
    stack = shoreline.water_stack(ee, aoi, monthly_summary["months"])
    return shoreline.sea_polygons(ee, aoi, stack)


def strip_image(ee: Any, baseline: dict, sea: list[dict]) -> Any:
    """Band `strip`: 1 (0-200 m) / 2 (200-500 m) on land within 500 m of the baseline, masked elsewhere."""
    lines = ee.FeatureCollection([ee.Feature(ee.Geometry(f["geometry"])) for f in baseline["features"]])
    d = lines.distance(searchRadius=STRIP_MAX_M, maxError=COASTAL_SCALE).unmask(STRIP_MAX_M + 1)
    inner, outer = STRIP_BOUNDS_M["0-200"][1], STRIP_BOUNDS_M["200-500"][1]
    code = d.lte(inner).multiply(STRIP_CODES["0-200"]).add(d.gt(inner).And(d.lte(outer)).multiply(STRIP_CODES["200-500"]))
    sea_img = ee.Image(0).paint(ee.FeatureCollection([ee.Feature(ee.Geometry(g["geometry"] if "geometry" in g else g)) for g in sea]), 1)
    return code.updateMask(code.gt(0)).updateMask(sea_img.eq(0)).rename("strip").toByte()


def _groups(ee: Any, aoi: dict, mask: Any, group: Any, scale: float = COASTAL_SCALE, tile_scale: int = 4) -> Any:
    """Pixel area where `mask`, summed by the `group` band (an ee.Dictionary-friendly 'groups' list)."""
    return (ee.Image.pixelArea().updateMask(mask).addBands(group)
            .reduceRegion(ee.Reducer.sum().group(1, "group"), ee.Geometry(aoi), scale, maxPixels=1e10, tileScale=tile_scale).get("groups"))


def land_areas(ee: Any, aoi: dict, strip: Any, log=print) -> dict[str, float]:
    got = monthly.get_info(ee.Dictionary({"land": _groups(ee, aoi, strip, strip)}), "strip land area", log=log)
    return strip_areas(got["land"])


def period_stats(ee: Any, aoi: dict, strip: Any, label: Any, land: dict[str, float], what: str, log=print) -> dict[str, dict]:
    """Per strip observed and built hectares for one Dynamic World label image (a month or a season)."""
    got = monthly.get_info(ee.Dictionary({"observed": _groups(ee, aoi, label.mask(), strip),
                                          "built": _groups(ee, aoi, label.eq(BUILT), strip)}), what, log=log)
    return period_row(land, got["observed"], got["built"])


def dw_images(ee: Any, aoi: dict, start: str, end: str) -> int:
    from .landcover import DW_COLLECTION
    return monthly.get_info(ee.ImageCollection(DW_COLLECTION).filterBounds(ee.Geometry(aoi)).filterDate(start, end).size(), f"{start} Dynamic World count")


def month_series(ee: Any, aoi: dict, strip: Any, land: dict[str, float], start: str, end: str, log=print) -> list[dict]:
    rows = []
    for key, s, e in monthly.month_windows(start, end):
        if dw_images(ee, aoi, s, e) == 0:
            strips = period_row(land, None, None)
        else:
            strips = period_stats(ee, aoi, strip, monthly.class_image(ee, aoi, s, e), land, f"{key} built area", log)
        rows.append({"month": key, "strips": strips})
        log(f"{key}: " + ", ".join(f"{n} {v['built_ha']} ha ({v['status']}, cover {v['cover']})" for n, v in strips.items()))
    return rows


def season_series(ee: Any, aoi: dict, strip: Any, land: dict[str, float], seasons: list[tuple[str, str, str]], log=print) -> list[dict]:
    rows = []
    for label, s, e in seasons:
        strips = period_stats(ee, aoi, strip, monthly.class_image(ee, aoi, s, e), land, f"{label} built area", log)
        rows.append({"season": label, "window": [s, e], "strips": strips})
        log(f"season {label}: " + ", ".join(f"{n} {v['built_ha']} ha (cover {v['cover']})" for n, v in strips.items()))
    return rows


def _gain_lost(old: Any, new: Any) -> tuple[Any, Any, Any]:
    both = old.mask().And(new.mask())
    gained = new.eq(BUILT).And(old.neq(BUILT)).And(both)
    lost = old.eq(BUILT).And(new.neq(BUILT)).And(both)
    return both, gained, lost


def season_change(ee: Any, aoi: dict, strip: Any, land: dict[str, float], first: tuple, last: tuple, log=print) -> dict:
    """Built-area change from the first to the last dry season over pixels observed in both."""
    old, new = monthly.class_image(ee, aoi, first[1], first[2]), monthly.class_image(ee, aoi, last[1], last[2])
    both, gained, lost = _gain_lost(old, new)
    got = monthly.get_info(ee.Dictionary({"compared": _groups(ee, aoi, both, strip), "gained": _groups(ee, aoi, gained, strip),
                                          "lost": _groups(ee, aoi, lost, strip)}), "season change", log=log)
    return {"from": first[0], "to": last[0], "strips": change_row(land, got["compared"], got["gained"], got["lost"])}


def new_patches(ee: Any, aoi: dict, strip: Any, first: tuple, last: tuple, log=print) -> dict:
    """Regions of pixels built in the last dry season and not in the first (observed in both), >= PATCH_MIN_HA."""
    old, new = monthly.class_image(ee, aoi, first[1], first[2]), monthly.class_image(ee, aoi, last[1], last[2])
    _, gained, _ = _gain_lost(old, new)
    gained = gained.selfMask().updateMask(strip.mask())
    big = gained.connectedPixelCount(PATCH_MAX_SIZE, True).gte(PATCH_MIN_PIXELS)
    vec = strip.updateMask(gained).updateMask(big).reduceToVectors(
        geometry=ee.Geometry(aoi), scale=COASTAL_SCALE, geometryType="polygon", eightConnected=True, labelProperty="strip",
        maxPixels=1e10, tileScale=4)
    feats = monthly.get_info(vec, "new built patches", log=log)["features"]
    fc = finalise_patches(feats, aoi)
    log(f"{len(feats)} raw patches -> {len(fc['features'])} of >= {PATCH_MIN_HA} ha")
    return fc


def strip_polygons(ee: Any, aoi: dict, strip: Any, log=print) -> dict:
    vec = strip.reduceToVectors(geometry=ee.Geometry(aoi), scale=VECTOR_SCALE, geometryType="polygon", eightConnected=True,
                                labelProperty="strip", maxPixels=1e10, tileScale=4)
    return finalise_strips(monthly.get_info(vec, "strip polygons", log=log)["features"])


def open_buildings(ee: Any, aoi: dict, strip: Any, years: tuple[int, int] = OB_YEARS, log=print) -> list[dict]:
    geom = ee.Geometry(aoi)
    rows = []
    for year in range(years[0], years[1] + 1):
        col = ee.ImageCollection(OB_COLLECTION).filterBounds(geom).filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        pres = col.select(OB_BAND).mosaic()
        asked = {"tiles": col.size(), "observed": _groups(ee, aoi, pres.mask(), strip, OB_SCALE, 8)}
        asked.update({f"t{i}": _groups(ee, aoi, pres.gte(t), strip, OB_SCALE, 8) for i, t in enumerate(OB_THRESHOLDS)})
        got = monthly.get_info(ee.Dictionary(asked), f"Open Buildings {year}", log=log)
        rows.append(ob_row(year, got["tiles"], got["observed"], {t: got[f"t{i}"] for i, t in enumerate(OB_THRESHOLDS)}))
        log(f"Open Buildings {year}: {got['tiles']} tiles, " + ", ".join(f"{n} {v['built_ha'][f'{OB_HEADLINE:g}']} ha" for n, v in rows[-1]["strips"].items()))
    return rows


def cell_image(ee: Any, strip: Any, grid: dict) -> Any:
    """Band `cell`: strip * CELL_BASE² + cx * CELL_BASE + cy for the ~100 m grid cell of every strip pixel."""
    ll = ee.Image.pixelLonLat()
    cx = ll.select("longitude").subtract(grid["lon0"]).divide(grid["step"]).floor()
    cy = ll.select("latitude").subtract(grid["lat0"]).divide(grid["step"]).floor()
    return strip.toInt32().multiply(CELL_BASE * CELL_BASE).add(cx.multiply(CELL_BASE)).add(cy).rename("cell")


def build_windows(ee: Any, aoi: dict, strip: Any, before_window: list[str], after_window: list[str], log=print) -> dict:
    """Built area per ~100 m strip cell in the detector's two windows (D13 / D16). Windows are passed to
    Earth Engine as given, as in shoreline.build_windows."""
    grid = cell_grid(aoi)
    cell = cell_image(ee, strip, grid)
    old = monthly.class_image(ee, aoi, *before_window)
    new = monthly.class_image(ee, aoi, *after_window)
    both = old.mask().And(new.mask())
    got = monthly.get_info(ee.Dictionary({
        "land": _groups(ee, aoi, strip, cell), "observed": _groups(ee, aoi, both, cell),
        "before": _groups(ee, aoi, old.eq(BUILT).And(both), cell), "after": _groups(ee, aoi, new.eq(BUILT).And(both), cell)}),
        "window cells", log=log)
    cells = cells_from_groups(grid, got["land"], got["observed"], got["before"], got["after"])
    totals = {}
    for n in COASTAL_STRIPS:
        rows = [c for c in cells if STRIP_NAMES[c[0]] == n]
        totals[n] = {"cells": len(rows), "land_ha": round(sum(c[3] for c in rows), 1), "observed_ha": round(sum(c[4] for c in rows), 1),
                     "built_ha_before": round(sum(c[5] for c in rows), 2), "built_ha_after": round(sum(c[6] for c in rows), 2)}
    return {"windows": [list(before_window), list(after_window)], "grid": grid, "columns": WINDOW_COLUMNS, "strip_codes": STRIP_CODES,
            "cells": cells, "totals": totals,
            "method": {"cells": f"strip pixels grouped into a {CELL_DEG}° grid ({CELL_DEG * shoreline.M_PER_DEG:.0f} m); per cell the strip land, the area "
                                "Dynamic World saw in both windows, and the built area (label mode over each window) before and after, over those pixels",
                       "strips": METHOD["strips"], "clip": "evidence_strips(): cells weighted by the share inside the box, per strip and 3 x 3 location",
                       "caveat": "the strips follow the Oct 2024 coast; where the coast moved since the windows, the strip is where the coast is now"}}


def build(aoi: dict, monthly_summary: dict, baseline: dict, sea: list[dict] | None = None, with_open_buildings: bool = True, log=print) -> dict:
    """The full Phase 12 analysis for the study AOI and its monthly period."""
    from .ee_engine import _ee
    ee = _ee()
    ee.data.setDeadline(monthly.REQUEST_TIMEOUT_S * 1000)
    start, end = monthly_summary["period"]
    if sea is None:
        sea = sea_features(ee, aoi, monthly_summary)
        log(f"sea: {len(sea)} polygons")
    strip = strip_image(ee, baseline, sea)
    land = land_areas(ee, aoi, strip, log)
    log("strip land: " + ", ".join(f"{n} {v:.1f} ha" for n, v in land.items()))
    months = month_series(ee, aoi, strip, land, start, end, log)
    seasons = monthly.dry_seasons(start, end)
    rows = season_series(ee, aoi, strip, land, seasons, log)
    change, patches = [], {"type": "FeatureCollection", "features": []}
    if len(seasons) >= 2:
        change = [season_change(ee, aoi, strip, land, seasons[0], seasons[-1], log)]
        patches = new_patches(ee, aoi, strip, seasons[0], seasons[-1], log)
    ob = open_buildings(ee, aoi, strip, log=log) if with_open_buildings else []
    return {"period": [start, end], "strips": {n: {"land_ha": r(v, 1)} for n, v in land.items()}, "months": months, "seasons": rows,
            "season_change": change, "patches": patches, "open_buildings": ob,
            "strip_polygons": strip_polygons(ee, aoi, strip, log), "sea": sea}
