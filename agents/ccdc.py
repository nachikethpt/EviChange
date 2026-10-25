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
