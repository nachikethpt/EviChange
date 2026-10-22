"""Monthly time series for the study AOI (D11, Phase 10).

One set of maps per calendar month, Oct 2024 – Sep 2026 by default (`monthly` in study.json):
- water: Sentinel-1 VV, speckle-smoothed, an Otsu threshold per scene (computed here in Python from
  an Earth Engine histogram, so it is testable without EE); a pixel is water in a month when it is
  water in at least half of that month's radar looks. Steep or high ground is never water (radar
  shadow there is as dark as water). Radar sees through cloud, so every month has a water map.
- class: Google Dynamic World label, the per-pixel mode over the month's images. Dynamic World only
  exists for clear-enough scenes (D10), so from about April to August most pixels have no class:
  those are gaps, never filled or interpolated.
- clear: Sentinel-2 data quality, the number of clear (SCL) looks per pixel in the month.
Change is reported against the previous month and against the first month (the baseline), always
only over pixels observed in both months, with the compared area alongside.

Water is also compared with Sentinel-2 (MNDWI > 0) where a clear look exists (`water_s2_agree`), as a
check on the radar threshold. Monthly positions move with the tide (several metres of range in Ha Long
Bay, D11): treat single months with care, trends over the 24 months are the robust quantity.

Blind labels: the class layers are masked at the labelled sites and region class series hidden there
until the Phase 14 class labels exist (landcover.CLASSES_UNLOCKED_AT_LABELLED_SITES), as in D10.

Earth Engine is imported only inside call sites (see ee_engine).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .ee_engine import S2_COLLECTION, _ee
from .landcover import DW_CLASSES, DW_COLLECTION, _batches
from .study import REPO_ROOT

MONTHLY_DIR = REPO_ROOT / "data" / "quangninh" / "monthly"
SUMMARY_FILE = MONTHLY_DIR / "summary.json"           # scripts/make_monthly.py writes both
REGIONS_FILE = MONTHLY_DIR / "regions_monthly.json"

S1_COLLECTION = "COPERNICUS/S1_GRD"
DEM = "USGS/SRTMGL1_003"
S1_SMOOTH_M = 30                       # focal median radius against speckle
HIST_MIN_DB, HIST_MAX_DB, HIST_BUCKETS = -35.0, 5.0, 160   # 0.25 dB buckets
OTSU_RANGE_DB = (-24.0, -12.0)         # an Otsu threshold outside this is not a land / water split
FALLBACK_DB = -18.0                    # used then (and recorded as such)
MAX_SLOPE_DEG, MAX_ELEV_M = 15, 40     # never water: radar shadow on hills
S2_CLEAR_SCL = [2, 4, 5, 6, 7]         # dark area, vegetation, bare, water, unclassified (not cloud / shadow / cirrus / snow / no data)
STATS_SCALE = 20                       # m, AOI-level areas (10 m pixels at 20 m: areas within ~1 %)
REGION_SCALE = 10
MIN_REGION_CLASS_COVER = 0.5           # a region's monthly class needs Dynamic World on half its area
DRY_SEASON_MONTHS = (10, 3)            # Oct – Mar: the months Dynamic World is usually clear (D11)
TOP_TRANSITIONS = 6

# Map display (Dynamic World's own palette, as in the app's legend).
DW_PALETTE = ["419bdf", "397d49", "88b053", "7a87c6", "e49635", "dfc35a", "c4281b", "a59b8f", "b39fe1"]
LAYERS = ("class", "water", "clear", "water_change", "class_change")
COMPARE = ("base", "prev")
LAYER_VIS = {
    "class": {"min": 0, "max": 8, "palette": DW_PALETTE},
    "water": {"min": 1, "max": 1, "palette": ["1d4ed8"]},
    "clear": {"min": 0, "max": 4, "palette": ["7f1d1d", "dc2626", "f59e0b", "a3e635", "15803d"]},
    "water_change": {"min": 1, "max": 2, "palette": ["2563eb", "ea580c"]},   # 1 gained water, 2 lost water
    "class_change": {"min": 0, "max": 8, "palette": DW_PALETTE},             # coloured by the new class
}


# ---------- months ----------
def month_windows(start: str, end: str) -> list[tuple[str, str, str]]:
    """[(YYYY-MM, first day, first day of next month)] from start to end inclusive ('2024-10', '2026-09')."""
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    if (y, m) > (ey, em):
        raise ValueError(f"start {start} is after end {end}")
    out = []
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((f"{y}-{m:02d}", date(y, m, 1).isoformat(), date(ny, nm, 1).isoformat()))
        y, m = ny, nm
    return out


def previous_month(key: str) -> str:
    y, m = map(int, key.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


# ---------- Otsu ----------
def otsu(counts: list[float], centers: list[float]) -> float | None:
    """Otsu threshold of a histogram: the split between buckets that maximises the between-class
    variance, as the midpoint of the two buckets either side. None for an empty histogram."""
    total = sum(counts)
    if not total or len(counts) < 2:
        return None
    sum_all = sum(c * x for c, x in zip(counts, centers))
    best, threshold, w_b, sum_b = -1.0, None, 0.0, 0.0
    for i in range(len(counts) - 1):
        w_b += counts[i]
        sum_b += counts[i] * centers[i]
        w_f = total - w_b
        if not w_b or not w_f:
            continue
        between = w_b * w_f * (sum_b / w_b - (sum_all - sum_b) / w_f) ** 2
        if between > best:
            best, threshold = between, (centers[i] + centers[i + 1]) / 2
    return threshold


def scene_threshold(hist: list[list[float]] | None) -> dict:
    """{'db': threshold, 'fallback': bool} from an ee.Reducer.fixedHistogram output ([[bucket min, count]])."""
    if hist:
        width = hist[1][0] - hist[0][0] if len(hist) > 1 else 0
        t = otsu([row[1] for row in hist], [row[0] + width / 2 for row in hist])
        if t is not None and OTSU_RANGE_DB[0] <= t <= OTSU_RANGE_DB[1]:
            return {"db": round(t, 2), "fallback": False}
    return {"db": FALLBACK_DB, "fallback": True}


# ---------- reading results ----------
def class_status(cover: float | None) -> str:
    """'none' (no Dynamic World), 'patchy' (under half the AOI) or 'clear'."""
    if not cover:
        return "none"
    return "clear" if cover >= 0.5 else "patchy"


def grouped_ha(groups: Iterable[dict], key: str = "group") -> dict[int, float]:
    """{group code: ha} from a reduceRegion(Reducer.sum().group()) 'groups' list of pixel areas in m²."""
    return {int(g[key]): g["sum"] / 10_000 for g in groups or []}


def class_areas(groups: Iterable[dict]) -> dict[str, float]:
    return {DW_CLASSES[code]: round(ha, 1) for code, ha in sorted(grouped_ha(groups).items()) if 0 <= code < len(DW_CLASSES)}


def transitions(groups: Iterable[dict], top: int = TOP_TRANSITIONS) -> dict:
    """Class change between two months from areas grouped by from*10 + to:
    {'compared_ha', 'changed_ha', 'top': [{'from', 'to', 'ha'}] (largest first)}."""
    areas = grouped_ha(groups)
    compared = sum(areas.values())
    moves = sorted(((ha, code // 10, code % 10) for code, ha in areas.items() if code // 10 != code % 10), reverse=True)
    return {"compared_ha": round(compared, 1), "changed_ha": round(sum(m[0] for m in moves), 1),
            "top": [{"from": DW_CLASSES[a], "to": DW_CLASSES[b], "ha": round(ha, 1)} for ha, a, b in moves[:top]]}


def region_class(mode: float | None, cover: float | None) -> str | None:
    """A region's class in a month: the Dynamic World mode, only when it covers enough of the region."""
    if mode is None or cover is None or cover < MIN_REGION_CLASS_COVER:
        return None
    return DW_CLASSES[int(round(mode))]


def _r(v: float | None, nd: int = 3) -> float | None:
    return None if v is None else round(float(v), nd)


# ---------- Earth Engine images ----------
def _s1(ee: Any, geom: Any, start: str, end: str) -> Any:
    col = (ee.ImageCollection(S1_COLLECTION).filterBounds(geom).filterDate(start, end)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")).select("VV"))
    return col.map(lambda im: im.focalMedian(S1_SMOOTH_M, "circle", "meters").rename("VV")
                   .copyProperties(im, ["system:index", "system:time_start"]))


def s1_thresholds(ee: Any, aoi: dict, start: str, end: str) -> dict[str, dict]:
    """{scene id: {'db', 'fallback'}} for every Sentinel-1 scene of one month (one EE request)."""
    geom = ee.Geometry(aoi)
    col = _s1(ee, geom, start, end)
    feats = col.map(lambda im: ee.Feature(None, {
        "sid": im.get("system:index"),
        "hist": im.reduceRegion(ee.Reducer.fixedHistogram(HIST_MIN_DB, HIST_MAX_DB, HIST_BUCKETS), geom, 30,
                                maxPixels=1e9, bestEffort=True).get("VV")})).getInfo()["features"]
    return {f["properties"]["sid"]: scene_threshold(f["properties"].get("hist")) for f in feats}


def _lowland(ee: Any) -> Any:
    dem = ee.Image(DEM).unmask(0)
    return ee.Terrain.slope(dem).lt(MAX_SLOPE_DEG).And(dem.lt(MAX_ELEV_M))


def water_image(ee: Any, aoi: dict, start: str, end: str, thresholds: dict[str, dict]) -> Any:
    """1 water / 0 land where at least one radar look exists; masked elsewhere."""
    geom = ee.Geometry(aoi)
    col = _s1(ee, geom, start, end).filter(ee.Filter.inList("system:index", list(thresholds)))
    db = ee.Dictionary({k: v["db"] for k, v in thresholds.items()})
    looks = col.map(lambda im: im.lt(ee.Number(db.get(im.get("system:index")))).rename("water"))
    return looks.mean().gte(0.5).And(_lowland(ee)).rename("water").toByte()


def clear_image(ee: Any, aoi: dict, start: str, end: str) -> tuple[Any, Any]:
    """(clear look count per pixel, Sentinel-2 water: median MNDWI of the clear looks > 0)."""
    geom = ee.Geometry(aoi)
    col = ee.ImageCollection(S2_COLLECTION).filterBounds(geom).filterDate(start, end)

    def clear(im: Any) -> Any:
        ok = im.select("SCL").remap(S2_CLEAR_SCL, [1] * len(S2_CLEAR_SCL), 0)
        return im.normalizedDifference(["B3", "B11"]).rename("mndwi").addBands(ok.rename("clear")).updateMask(ok)

    looks = col.map(clear)
    count = looks.select("clear").count().unmask(0).clip(geom).rename("clear")
    s2_water = looks.select("mndwi").median().gt(0).rename("water_s2")
    return count, s2_water


def class_image(ee: Any, aoi: dict, start: str, end: str) -> Any:
    """Dynamic World label, per-pixel mode over the month; masked where no image saw the pixel."""
    col = ee.ImageCollection(DW_COLLECTION).filterBounds(ee.Geometry(aoi)).filterDate(start, end).select("label")
    return col.mode().rename("label")


def _site_mask(ee: Any) -> Any | None:
    """1 outside the labelled sites, while Dynamic World classes are locked there (D10); else None."""
    from . import landcover
    from .vlm_check import labelled_site_boxes
    boxes = labelled_site_boxes()
    if landcover.CLASSES_UNLOCKED_AT_LABELLED_SITES or not boxes:
        return None
    sites = ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle(list(b))) for b in boxes])
    return ee.Image(1).paint(sites, 0)


class Month:
    """Earth Engine images for one month, built lazily (thresholds come from the summary when known)."""

    def __init__(self, ee: Any, aoi: dict, key: str, start: str, end: str, thresholds: dict | None = None):
        self.ee, self.aoi, self.key, self.start, self.end = ee, aoi, key, start, end
        self._thresholds = thresholds
        self._cache: dict[str, Any] = {}

    @property
    def thresholds(self) -> dict:
        if self._thresholds is None:
            self._thresholds = s1_thresholds(self.ee, self.aoi, self.start, self.end)
        return self._thresholds

    def _get(self, name: str, make) -> Any:
        if name not in self._cache:
            self._cache[name] = make()
        return self._cache[name]

    @property
    def water(self) -> Any:
        return self._get("water", lambda: water_image(self.ee, self.aoi, self.start, self.end, self.thresholds))

    @property
    def label(self) -> Any:
        return self._get("label", lambda: class_image(self.ee, self.aoi, self.start, self.end))

    @property
    def clear(self) -> Any:
        return self._get("clear", lambda: clear_image(self.ee, self.aoi, self.start, self.end))


# ---------- AOI summary ----------
def _counts(ee: Any, geom: Any, start: str, end: str) -> Any:
    return ee.Dictionary({
        "s1_scenes": _s1(ee, geom, start, end).size(),
        "s2_scenes": ee.ImageCollection(S2_COLLECTION).filterBounds(geom).filterDate(start, end).size(),
        "dw_images": ee.ImageCollection(DW_COLLECTION).filterBounds(geom).filterDate(start, end).size(),
    })


def month_summary(ee: Any, aoi: dict, cur: Month, prev: Month | None, base: Month | None) -> dict:
    """AOI-level numbers for one month; vs_prev / vs_base null when there is nothing to compare."""
    geom = ee.Geometry(aoi)
    area = ee.Image.pixelArea()
    clear_count, s2_water = cur.clear
    has = {"s1": bool(cur.thresholds)}
    counts = _counts(ee, geom, cur.start, cur.end).getInfo()
    has["dw"] = counts["dw_images"] > 0

    bands = [clear_count.gt(0).rename("seen_clear")]
    if has["dw"]:
        bands.append(cur.label.mask().rename("class_cover"))
    if has["s1"]:
        bands.append(cur.water.eq(s2_water).updateMask(clear_count.gt(0)).rename("water_s2_agree"))
    stats = ee.Image.cat(bands).reduceRegion(ee.Reducer.mean(), geom, STATS_SCALE, maxPixels=1e10, tileScale=4)
    water_m2 = (area.updateMask(cur.water).reduceRegion(ee.Reducer.sum(), geom, STATS_SCALE, maxPixels=1e10, tileScale=4)
                .get("area") if has["s1"] else None)
    out = {"month": cur.key, **counts, "s1_thresholds_db": cur.thresholds}
    got = ee.Dictionary({"stats": stats, "water_m2": water_m2}).getInfo()
    st = got["stats"]
    out["clear_share"] = _r(st.get("seen_clear"))
    out["class_cover"] = _r(st.get("class_cover")) if has["dw"] else 0.0
    out["class_status"] = class_status(out["class_cover"])
    out["water_ha"] = _r(got["water_m2"] / 10_000, 1) if got.get("water_m2") is not None else None
    out["water_s2_agree"] = _r(st.get("water_s2_agree"))

    out["class_ha"] = None
    if has["dw"]:
        groups = area.addBands(cur.label).reduceRegion(ee.Reducer.sum().group(1, "group"), geom, STATS_SCALE,
                                                      maxPixels=1e10, tileScale=4).get("groups")
        out["class_ha"] = class_areas(groups.getInfo())

    for name, ref in (("vs_prev", prev), ("vs_base", base)):
        out[name] = compare(ee, aoi, ref, cur) if ref is not None else None
    return out


def compare(ee: Any, aoi: dict, ref: Month, cur: Month) -> dict | None:
    """Water gained / lost and class transitions from ref to cur, over pixels seen in both."""
    geom = ee.Geometry(aoi)
    area = ee.Image.pixelArea()
    out: dict[str, Any] = {"ref": ref.key, "water": None, "classes": None}
    if ref.thresholds and cur.thresholds:
        gained = cur.water.And(ref.water.Not())
        lost = cur.water.Not().And(ref.water)
        both = cur.water.mask().And(ref.water.mask())
        img = ee.Image.cat([area.updateMask(gained).rename("gained"), area.updateMask(lost).rename("lost"),
                            area.updateMask(both).rename("compared")])
        s = img.reduceRegion(ee.Reducer.sum(), geom, STATS_SCALE, maxPixels=1e10, tileScale=4).getInfo()
        out["water"] = {f"{k}_ha": _r((s.get(k) or 0) / 10_000, 1) for k in ("gained", "lost", "compared")}
    dw = lambda m: ee.ImageCollection(DW_COLLECTION).filterBounds(geom).filterDate(m.start, m.end).size()
    if ee.Number(dw(ref)).min(dw(cur)).getInfo() > 0:
        code = ref.label.multiply(10).add(cur.label).rename("code")
        groups = area.addBands(code).reduceRegion(ee.Reducer.sum().group(1, "group"), geom, STATS_SCALE,
                                                 maxPixels=1e10, tileScale=4).get("groups").getInfo()
        out["classes"] = transitions(groups)
    if out["water"] is None and out["classes"] is None:
        return None
    return out


def dry_seasons(start: str, end: str) -> list[tuple[str, str, str]]:
    """[(label, first day, day after)] for every DRY_SEASON_MONTHS window that lies inside the period,
    e.g. ('2024-25', '2024-10-01', '2025-04-01')."""
    first, last = DRY_SEASON_MONTHS
    keys = [k for k, _, _ in month_windows(start, end)]
    out = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        a, b = f"{y}-{first:02d}", f"{y + 1}-{last:02d}"
        if a in keys and b in keys:
            out.append((f"{y}-{(y + 1) % 100:02d}", f"{a}-01", month_windows(b, b)[0][2]))
    return out


def season_compare(ee: Any, aoi: dict, seasons: list[tuple[str, str, str]]) -> list[dict]:
    """Class transitions between consecutive dry-season composites (per-pixel Dynamic World mode over
    the season). Single months are too noisy for class change (Phase 10: 12-38 % of the AOI 'changes'
    against Oct 2024 every month), the season mode is the comparison D11 asks for."""
    geom = ee.Geometry(aoi)
    area = ee.Image.pixelArea()
    out = []
    for (a, a0, a1), (b, b0, b1) in zip(seasons, seasons[1:]):
        old, new = class_image(ee, aoi, a0, a1), class_image(ee, aoi, b0, b1)
        groups = area.addBands(old.multiply(10).add(new).rename("code")).reduceRegion(
            ee.Reducer.sum().group(1, "group"), geom, STATS_SCALE, maxPixels=1e10, tileScale=4).get("groups").getInfo()
        cover = ee.Image.cat([old.mask().rename("a"), new.mask().rename("b")]).reduceRegion(
            ee.Reducer.mean(), geom, STATS_SCALE, maxPixels=1e10, tileScale=4).getInfo()
        out.append({"from": a, "to": b, "windows": [[a0, a1], [b0, b1]],
                    "cover": {a: _r(cover.get("a")), b: _r(cover.get("b"))}, **transitions(groups, top=10)})
    return out


def build_summary(aoi: dict, start: str, end: str, log=print) -> dict:
    """The AOI's monthly summary: {'period', 'baseline', 'months': [month_summary ...], 'seasons', 'method'}."""
    ee = _ee()
    windows = month_windows(start, end)
    months = {k: Month(ee, aoi, k, s, e) for k, s, e in windows}
    base = months[windows[0][0]]
    rows = []
    for k, _, _ in windows:
        prev = months.get(previous_month(k))
        rows.append(month_summary(ee, aoi, months[k], prev, base if k != base.key else None))
        log(f"{k}: s1 {rows[-1]['s1_scenes']}, s2 {rows[-1]['s2_scenes']}, dw {rows[-1]['dw_images']}, "
            f"clear {rows[-1]['clear_share']}, classes {rows[-1]['class_status']}, water {rows[-1]['water_ha']} ha")
    seasons = season_compare(ee, aoi, dry_seasons(start, end))
    return {"period": [start, end], "baseline": base.key, "months": rows, "seasons": seasons, "method": METHOD}


METHOD = {
    "water": f"Sentinel-1 VV, {S1_SMOOTH_M} m focal median, Otsu per scene in {list(OTSU_RANGE_DB)} dB "
             f"(else {FALLBACK_DB} dB); water in >= half the month's looks; never water at slope >= {MAX_SLOPE_DEG} deg "
             f"or elevation >= {MAX_ELEV_M} m (SRTM)",
    "class": "Dynamic World V1 label, per-pixel mode over the month; gaps where no image (D10, D11)",
    "clear": f"Sentinel-2 SR looks with SCL in {S2_CLEAR_SCL} per pixel; clear_share = AOI share seen clear at least once",
    "compare": "only over pixels observed in both months; vs_prev = previous calendar month, vs_base = first month",
    "seasons": "class change between dry-season (Oct-Mar) Dynamic World modes; single months are too noisy for class change",
    "areas": f"at {STATS_SCALE} m",
    "tide": "monthly water extent includes tide differences (several m range, D11); use trends, not single months",
}


# ---------- per-region series ----------
def region_series(fc: dict, aoi: dict, start: str, end: str, thresholds: dict[str, dict] | None = None, log=print) -> dict:
    """{'months': [...], 'regions': {id: {'class': [...], 'water': [...], 'clear': [...]}}}: per region and
    month the Dynamic World class (null without enough cover), water share and share seen clear."""
    ee = _ee()
    windows = month_windows(start, end)
    regions: dict[str, dict[str, list]] = {f["properties"]["id"]: {"class": [], "water": [], "clear": []} for f in fc["features"]}
    batches = _batches(fc["features"])
    reducer = ee.Reducer.mean().combine(ee.Reducer.mode(), sharedInputs=True)
    for k, s, e in windows:
        m = Month(ee, aoi, k, s, e, (thresholds or {}).get(k))
        clear_count, _ = m.clear
        bands = [clear_count.gt(0).rename("seen")]
        dw = ee.ImageCollection(DW_COLLECTION).filterBounds(ee.Geometry(aoi)).filterDate(s, e).size().getInfo() > 0
        if dw:
            bands += [m.label.rename("label"), m.label.mask().rename("cover")]
        if m.thresholds:
            bands.append(m.water.rename("water"))
        image = ee.Image.cat(bands)
        stats: dict[str, dict] = {}
        for batch in batches:
            col = ee.FeatureCollection([ee.Feature(ee.Geometry(f["geometry"]), {"rid": f["properties"]["id"]}) for f in batch])
            for feat in image.reduceRegions(collection=col, reducer=reducer, scale=REGION_SCALE, tileScale=4).getInfo()["features"]:
                stats[feat["properties"]["rid"]] = feat["properties"]
        for rid, series in regions.items():
            st = stats.get(rid, {})
            series["class"].append(region_class(st.get("label_mode"), st.get("cover_mean")) if dw else None)
            series["water"].append(_r(st.get("water_mean"), 2))
            series["clear"].append(_r(st.get("seen_mean"), 2))
        log(f"{k}: {len(stats)} regions")
    return {"months": [k for k, _, _ in windows], "regions": regions}


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def month_row(summary: dict, key: str) -> dict | None:
    return next((m for m in summary.get("months", []) if m["month"] == key), None)


def hide_classes(series: dict, hidden_ids: set[str]) -> dict:
    """Copy of a region-series file with the class series removed at the given (locked) region ids."""
    regions = {rid: ({**s, "class": None, "class_hidden": True} if rid in hidden_ids else s)
               for rid, s in series.get("regions", {}).items()}
    return {**series, "regions": regions}


# ---------- map tiles ----------
def tile_layer(aoi: dict, month: tuple[str, str, str], layer: str, ref: tuple[str, str, str] | None = None,
               thresholds: dict | None = None, ref_thresholds: dict | None = None) -> dict:
    """XYZ tiles for one monthly layer (LAYERS); the change layers compare with `ref`."""
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {LAYERS}")
    ee = _ee()
    geom = ee.Geometry(aoi)
    cur = Month(ee, aoi, *month, thresholds=thresholds)
    if layer in ("water_change", "class_change"):
        if ref is None:
            raise ValueError(f"{layer} needs a month to compare with")
        old = Month(ee, aoi, *ref, thresholds=ref_thresholds)
    if layer == "class":
        image = cur.label
    elif layer == "water":
        image = cur.water.selfMask()
    elif layer == "clear":
        image = cur.clear[0].min(4)
    elif layer == "water_change":
        image = cur.water.And(old.water.Not()).add(cur.water.Not().And(old.water).multiply(2)).selfMask()
    else:
        image = cur.label.updateMask(cur.label.neq(old.label))
    if layer in ("class", "class_change"):
        sites = _site_mask(ee)
        if sites is not None:
            image = image.updateMask(sites)
    vis = LAYER_VIS[layer]
    map_id = image.clip(geom).getMapId({"min": vis["min"], "max": vis["max"], "palette": vis["palette"]})
    return {"tiles": [map_id["tile_fetcher"].url_format], **vis}
