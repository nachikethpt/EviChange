"""Month of change with CCDC (D14): when a site's lasting change happened, as a window.

CCDC (Zhu & Woodcock 2014, `ee.Algorithms.TemporalSegmentation.Ccdc`) fits a harmonic (seasonal)
model per pixel to Sentinel-2 SR from 2018 on (SCL cloud mask, as ee_engine) on green, red, NIR,
SWIR1, SWIR2 plus NDVI / NDBI / MNDWI, and starts a new segment where clear looks keep leaving the
model. A site's result, from all pixels in its box:

- `share`: the share of pixels with a break in the reporting period (Oct 2024 - Sep 2026);
- `lasting`: share >= LASTING_SHARE. A pixel that only swings with the season fits the harmonic model
  and has no break, so "seasonal" sites get lasting = False;
- `change_window`: [month of the last clear look before the break, month of the break], where the
  break is the most common break month among the breaking pixels. A window, never an invented single
  date, because the monsoon can leave months without a clear look (D11). null when not lasting.

The pure functions below turn Earth Engine's reductions into that result and are unit-tested; the
`ee_*` functions only build Earth Engine calls (no tests without an Earth Engine login). CCDC
parameters are the Earth Engine defaults (D14: any change is recorded there).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

HISTORY_START = "2018-01-01"
PERIOD = ("2024-10-01", "2026-09-30")     # breaks kept (D11 / D14), end inclusive
LASTING_SHARE = 0.5                        # provisional: set before any site result is seen; record changes in D14
CLEAR_SHARE = 0.5                          # a look counts as clear for the site when this share of the box is clear
BANDS = {"B3": "green", "B4": "red", "B8": "nir", "B11": "swir1", "B12": "swir2"}
BREAK_BANDS = ["green", "red", "nir", "swir1", "swir2"]
SCALE_M = 10


# ---------- pure ----------
def month_of(ms: float) -> str:
    """'YYYY-MM' of a Unix time in milliseconds (UTC)."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def ms_of(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def in_period(ms: float, period: tuple[str, str] = PERIOD) -> bool:
    return ms_of(period[0]) <= ms < ms_of(period[1]) + 86_400_000


def break_window(t_break_ms: float, clear_looks_ms: Iterable[float]) -> list[str]:
    """[last month before the break with a clear look, month of the break]. With no clear look before
    the break (shouldn't happen after a 2018 history) the window starts at the history start."""
    before = [t for t in clear_looks_ms if t < t_break_ms]
    start = month_of(max(before)) if before else HISTORY_START[:7]
    end = month_of(t_break_ms)
    return [start, end] if start < end else [month_of(t_break_ms - 31 * 86_400_000), end]


def site_result(break_ms: list[float], n_pixels: int, clear_looks_ms: list[float],
                period: tuple[str, str] = PERIOD, lasting_share: float = LASTING_SHARE) -> dict:
    """The site's CCDC result from the first in-period break time of each breaking pixel (break_ms, one
    entry per pixel), the number of pixels with a model at all, and the site's clear looks."""
    breaks = [t for t in break_ms if t is not None and in_period(t, period)]
    share = len(breaks) / n_pixels if n_pixels else 0.0
    out = {"n_pixels": n_pixels, "n_break": len(breaks), "share": round(share, 3), "lasting": share >= lasting_share and bool(breaks),
           "change_window": None, "break_month": None}
    if out["lasting"]:
        month, _ = Counter(month_of(t) for t in breaks).most_common(1)[0]
        t_break = min(t for t in breaks if month_of(t) == month)
        out["break_month"] = month
        out["change_window"] = break_window(t_break, clear_looks_ms)
    return out


def windows_for_report(results: dict[str, dict]) -> dict[str, list[str]]:
    """{site_id: change_window} for the lasting ones: the --ccdc file scripts/phase14_report.py reads."""
    return {s: r["change_window"] for s, r in results.items() if r.get("lasting") and r.get("change_window")}


# ---------- Earth Engine ----------
def ee_collection(ee: Any, geometry: Any, end: str = PERIOD[1]) -> Any:
    """Cloud-masked Sentinel-2 SR with the CCDC bands, renamed, plus NDVI / NDBI / MNDWI."""
    from .ee_engine import S2_COLLECTION, _cloud_mask

    def prep(img):
        img = _cloud_mask(ee, img)
        refl = img.select(list(BANDS), list(BANDS.values())).divide(10_000)
        idx = ee.Image.cat([refl.normalizedDifference(["nir", "red"]).rename("NDVI"),
                            refl.normalizedDifference(["swir1", "nir"]).rename("NDBI"),
                            refl.normalizedDifference(["green", "swir1"]).rename("MNDWI")])
        return refl.addBands(idx).copyProperties(img, ["system:time_start"])

    return (ee.ImageCollection(S2_COLLECTION).filterBounds(geometry)
            .filterDate(HISTORY_START, end).map(prep))


def ee_site(ee: Any, box: tuple[float, float, float, float]) -> tuple[list[float], int, list[float]]:
    """(first in-period break time per breaking pixel, pixels with a model, clear-look times) for one box."""
    geometry = ee.Geometry.Rectangle(list(box))
    col = ee_collection(ee, geometry)
    ccdc = ee.Algorithms.TemporalSegmentation.Ccdc(collection=col, breakpointBands=BREAK_BANDS, dateFormat=2)
    t_break = ccdc.select("tBreak")
    lo, hi = ms_of(PERIOD[0]), ms_of(PERIOD[1]) + 86_400_000
    in_win = t_break.arrayMask(t_break.gte(lo).And(t_break.lt(hi)))
    first = in_win.arraySlice(0, 0, 1).arrayProject([0]).arrayFlatten([["tbreak"]])
    has_model = ccdc.select("tStart").arrayLength(0).gt(0).rename("model")
    stats = ee.Image.cat([first, has_model]).reduceRegion(
        reducer=ee.Reducer.toList().forEach(["tbreak"]).combine(ee.Reducer.sum().forEach(["model"]), sharedInputs=False),
        geometry=geometry, scale=SCALE_M, maxPixels=1e8).getInfo()
    clear = col.map(lambda img: img.set("clear", img.select("nir").mask().reduceRegion(
        ee.Reducer.mean(), geometry, SCALE_M).get("nir")))
    looks = clear.filter(ee.Filter.gte("clear", CLEAR_SHARE)).aggregate_array("system:time_start").getInfo()
    return list(stats.get("tbreak_list") or stats.get("tbreak") or []), int(stats.get("model_sum") or stats.get("model") or 0), looks


# ---------- change regions (Phase 10b): every detector region, in batches ----------
# Two periods per region. "detection": between the detector's two windows (D6, 2019-04 .. 2023-03 for QN),
# when the region's detected change must have happened, so CCDC can date it. "monitoring": the D14 period
# (Oct 2024 - Sep 2026): did the region change again since. Regions mostly inside a labelled site are
# not run until the Phase 14 (d) change-month labels exist (blind, as --sites above).
EPOCH = "2018-01-01"
MONTH_DAYS = 365.25 / 12
MAG_BANDS = ["NDVI", "NDBI", "MNDWI"]
REGION_BATCH = 25


def month_index(ms: float) -> int:
    """Months since EPOCH (2018-01 = 0) of a Unix time in ms, via the calendar month (exact)."""
    m = month_of(ms)
    return (int(m[:4]) - int(EPOCH[:4])) * 12 + int(m[5:7]) - 1


def month_from_index(i: int) -> str:
    return f"{int(EPOCH[:4]) + i // 12}-{i % 12 + 1:02d}"


def detection_period(date_before: str, date_after: str) -> tuple[str, str]:
    """The detector windows ('2018-11-01/2019-03-31') -> the period between them: from the day after the
    before window to the end of the after window (the change happened somewhere in there)."""
    b_end = date_before.split("/")[1]
    a_end = date_after.split("/")[1]
    nxt = datetime.fromisoformat(b_end).replace(tzinfo=timezone.utc).timestamp() + 86_400
    return datetime.fromtimestamp(nxt, tz=timezone.utc).strftime("%Y-%m-%d"), a_end


def region_result(hist: dict, n_pixels: int, magnitudes: dict | None = None,
                  lasting_share: float = LASTING_SHARE) -> dict:
    """One region and period from a histogram {month index: breaking pixels} (first break in the period
    per pixel), the pixels with a model, and the mean break magnitude per index over breaking pixels."""
    counts = {int(float(k)): int(v) for k, v in (hist or {}).items() if v}
    n_break = sum(counts.values())
    share = n_break / n_pixels if n_pixels else 0.0
    out = {"n_pixels": int(n_pixels), "n_break": n_break, "share": round(share, 3),
           "lasting": bool(n_break) and share >= lasting_share, "break_month": None,
           "magnitude": {k: (round(v, 3) if v is not None else None) for k, v in (magnitudes or {}).items()} or None}
    if n_break:
        top = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]     # most pixels; earliest on a tie
        out["break_month"] = month_from_index(top)
        out["months"] = {month_from_index(k): v for k, v in sorted(counts.items())}
    return out


def ee_ccdc(ee: Any, geometry: Any, end: str) -> Any:
    col = ee_collection(ee, geometry, end)
    return ee.Algorithms.TemporalSegmentation.Ccdc(collection=col, breakpointBands=BREAK_BANDS, dateFormat=2)


def ee_regions(ee: Any, features: list[dict], period: tuple[str, str], scale: float = SCALE_M) -> dict[str, dict]:
    """region_result() for each GeoJSON feature (properties.id) over `period`, in one Earth Engine request."""
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry(f["geometry"]), {"id": f["properties"]["id"]}) for f in features])
    ccdc = ee_ccdc(ee, fc.geometry().bounds(), max(period[1], PERIOD[1]))
    t_break = ccdc.select("tBreak")
    lo, hi = ms_of(period[0]), ms_of(period[1]) + 86_400_000
    sel = t_break.gte(lo).And(t_break.lt(hi))
    has_break = t_break.arrayMask(sel).arrayLength(0).gt(0)       # pixels with no break in the period stay out
    first = lambda band: (ccdc.select(band).arrayMask(sel).arrayPad([1]).arraySlice(0, 0, 1).arrayProject([0])
                          .arrayFlatten([[band]]).updateMask(has_break))
    tb = first("tBreak")
    # month index from ms in mean-length months (30.44 days): matches the calendar month except within
    # about two days of a month boundary, well inside the windows CCDC dates can carry anyway
    midx = tb.subtract(ms_of(EPOCH)).divide(MONTH_DAYS * 86_400_000).floor().toInt().rename("bmonth")
    mags = ee.Image.cat([first(f"{b}_magnitude") for b in MAG_BANDS])
    has_model = ccdc.select("tStart").arrayLength(0).gt(0).rename("model")
    img = ee.Image.cat([midx, has_model, mags])
    red = (ee.Reducer.frequencyHistogram().forEach(["bmonth"])
           .combine(ee.Reducer.sum().forEach(["model"]), sharedInputs=False)
           .combine(ee.Reducer.mean().forEach([f"{b}_magnitude" for b in MAG_BANDS]), sharedInputs=False))
    got = img.reduceRegions(collection=fc, reducer=red, scale=scale, tileScale=8).getInfo()["features"]
    out = {}
    for f in got:
        p = f["properties"]
        out[p["id"]] = region_result(p.get("bmonth") or {}, p.get("model") or 0,
                                     {b: p.get(f"{b}_magnitude") for b in MAG_BANDS})
    return out


# ---------- one region's series (the app chart) ----------
def harmonic_fit(t: list[float], y: list[float]) -> list[float] | None:
    """Least-squares a + b t + c cos 2πt + d sin 2πt (t in years): one season, as CCDC's first harmonic.
    None with fewer than 6 points. Pure Python normal equations (4 x 4)."""
    import math
    if len(t) < 6:
        return None
    rows = [[1.0, ti, math.cos(2 * math.pi * ti), math.sin(2 * math.pi * ti)] for ti in t]
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(4)] for i in range(4)]
    aty = [sum(r[i] * yi for r, yi in zip(rows, y)) for i in range(4)]
    m = [row[:] + [v] for row, v in zip(ata, aty)]                  # Gauss-Jordan with partial pivoting
    for c in range(4):
        p = max(range(c, 4), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(4):
            if r != c:
                k = m[r][c] / m[c][c]
                m[r] = [a - k * b for a, b in zip(m[r], m[c])]
    return [m[i][4] / m[i][i] for i in range(4)]


def harmonic_value(coef: list[float], t: float) -> float:
    import math
    return coef[0] + coef[1] * t + coef[2] * math.cos(2 * math.pi * t) + coef[3] * math.sin(2 * math.pi * t)


def series_result(looks: list[dict], break_month: str | None, index: str = "NDVI") -> dict:
    """The chart for one region: its clear looks [{t: ms, NDVI, NDBI, MNDWI}], the seasonal curve fitted
    separately before and after the break month (one curve with no break), sampled twice a month, and
    the change window [last clear month before the break, break month]."""
    pts = sorted((lk["t"], lk[index]) for lk in looks if lk.get(index) is not None)
    yr = lambda ms: (ms - ms_of(EPOCH)) / (365.25 * 86_400_000)
    split = ms_of(f"{break_month}-01") if break_month else None
    segs = [pts] if split is None else [[p for p in pts if p[0] < split], [p for p in pts if p[0] >= split]]
    curves = []
    for seg in segs:
        coef = harmonic_fit([yr(t) for t, _ in seg], [v for _, v in seg])
        if coef is None or not seg:
            curves.append(None)
            continue
        t0, t1 = seg[0][0], seg[-1][0]
        step = 15 * 86_400_000
        curves.append([[round(t), round(harmonic_value(coef, yr(t)), 4)] for t in range(int(t0), int(t1) + 1, step)])
    window = break_window(split, [t for t, _ in pts]) if split is not None else None
    return {"index": index, "looks": [[t, round(v, 4)] for t, v in pts], "curves": curves,
            "break_month": break_month, "change_window": window}


def ee_series(ee: Any, geometry: dict, end: str = PERIOD[1]) -> list[dict]:
    """A region's mean NDVI / NDBI / MNDWI on every Sentinel-2 look that saw at least CLEAR_SHARE of it."""
    geom = ee.Geometry(geometry)
    col = ee_collection(ee, geom, end)

    def one(img):
        mean = img.select(MAG_BANDS).reduceRegion(ee.Reducer.mean(), geom, SCALE_M * 2, maxPixels=1e8)
        clear = img.select("nir").mask().reduceRegion(ee.Reducer.mean(), geom, SCALE_M * 2, maxPixels=1e8).get("nir")
        return ee.Feature(None, mean).set("t", img.get("system:time_start"), "clear", clear)

    feats = col.map(one).filter(ee.Filter.gte("clear", CLEAR_SHARE)).getInfo()["features"]
    by_day: dict[str, dict] = {}
    for f in feats:                                  # two S2 tiles on one day: keep the first
        p = f["properties"]
        day = datetime.fromtimestamp(p["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day.setdefault(day, {"t": p["t"], **{b: p.get(b) for b in MAG_BANDS}})
    return list(by_day.values())


# ---------- app (Phase 10b) ----------
REGIONS_FILE = "data/quangninh/ccdc_regions.json"
APP_FIELDS = ("ccdc_month", "ccdc_share", "ccdc_lasting", "ccdc_matches", "ccdc_again", "ccdc_again_month", "ccdc_hidden")
DETECTOR_DELTA = 0.1             # the detector's index threshold (D6): smaller index changes say nothing
DETECTOR_FIELDS = {"NDVI": "dNDVI", "NDBI": "dNDBI", "MNDWI": "dMNDWI"}


def matches_detector(region: dict, magnitude: dict | None) -> bool | None:
    """Does the CCDC break go the way the detector saw the region change? True when every index the
    detector counts (|d| > DETECTOR_DELTA) has a break magnitude of the same sign; None when the detector
    counts no index or there is no magnitude. A break the other way is some other event in the period."""
    if not magnitude:
        return None
    used = [(k, region.get(f)) for k, f in DETECTOR_FIELDS.items() if isinstance(region.get(f), (int, float)) and abs(region[f]) > DETECTOR_DELTA]
    if not used or any(magnitude.get(k) is None for k, _ in used):
        return None
    return all((magnitude[k] > 0) == (d > 0) for k, d in used)


def main_index(region: dict) -> str:
    """The index that moved most at the detector (the chart shows it); NDVI when none is known."""
    vals = {k: abs(region.get(f) or 0) for k, f in DETECTOR_FIELDS.items()}
    return max(vals, key=vals.get) if any(vals.values()) else "NDVI"


def attach(fc: dict, data: dict | None) -> dict:
    """Copy of the region FeatureCollection with the CCDC fields on each region the run covers:
    ccdc_month (break month of the detected change, lasting only), ccdc_share, ccdc_lasting, ccdc_again
    (a lasting break again in the monitoring period) and ccdc_again_month; ccdc_hidden on locked regions."""
    if not data or not fc.get("features"):
        return fc
    regions, locked = data.get("regions", {}), set(data.get("locked", []))
    out = []
    for f in fc["features"]:
        p = dict(f.get("properties", {}))
        rid = p.get("id")
        if rid in locked:
            p["ccdc_hidden"] = True
        elif rid in regions:
            det, mon = regions[rid].get("detection") or {}, regions[rid].get("monitoring") or {}
            p.update(ccdc_lasting=bool(det.get("lasting")), ccdc_share=det.get("share"),
                     ccdc_month=det.get("break_month") if det.get("lasting") else None,
                     ccdc_matches=matches_detector(p, det.get("magnitude")) if det.get("lasting") else None,
                     ccdc_again=bool(mon.get("lasting")), ccdc_again_month=mon.get("break_month") if mon.get("lasting") else None)
        out.append({**f, "properties": p})
    return {**fc, "features": out}
