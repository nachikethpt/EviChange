"""PlanetScope imagery in Earth Engine (D12, Phase 13b).

The monthly PlanetScope mosaics are made and uploaded by notebooks/EviChange_planet_to_ee.ipynb
(rasterio can't run on the project PC under Windows Smart App Control). Each month is one image in
the collection PLANET_COLLECTION, id `m<YYYY>_<MM>`, with 9 bands in this order:

  1-8  PlanetScope 8-band surface reflectance, harmonised to Sentinel-2, reflectance x 10 000
       (coastal blue, blue, green I, green, yellow, red, red edge, NIR)
  9    clear: 1 where Planet's UDM2 says clear, 0 elsewhere (cloud, shadow, haze, no data)

Bands are selected by position, so the names Earth Engine gave them at upload don't matter (an
upload through the Code Editor names them b1..b9). PlanetScope has no SWIR: NDBI and MNDWI can't be
computed; water uses NDWI (green / NIR) and built / bare need a classification (D12).

Earth Engine is imported only inside call sites, as in ee_engine.py.
"""
from __future__ import annotations

import os
import re
from typing import Any

PLANET_COLLECTION = os.environ.get("EVICHANGE_PLANET_COLLECTION", "projects/space-510615/assets/planet_qn")
SR_BANDS = ("coastal_blue", "blue", "green_i", "green", "yellow", "red", "rededge", "nir")
BANDS = (*SR_BANDS, "clear")
SR_SCALE = 1e-4                    # stored reflectance x 10 000
NATIVE_SCALE = 3                   # m
NDWI_WATER = 0.0                   # NDWI above this is water (McFeeters); the shoreline phase may refine it per month
SOURCE = "planetscope_8b_sr_harmonized"
ATTRIBUTION = "Imagery © Planet Labs PBC (PlanetScope, Education and Research programme)"
CHIP_VIS = {"rgb": (["red", "green", "blue"], 0, 0.3), "nir": (["nir", "red", "green"], 0, 0.45)}   # no SWIR on Planet

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


# ---------- names (no Earth Engine needed) ----------
def check_month(month: str) -> str:
    if not _MONTH.match(month or ""):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    return month


def asset_id(month: str, collection: str = PLANET_COLLECTION) -> str:
    """Earth Engine asset id of one month's mosaic, e.g. .../planet_qn/m2024_10."""
    y, m = check_month(month).split("-")
    return f"{collection}/m{y}_{m}"


def month_of_asset(asset: str) -> str | None:
    match = re.search(r"/m(\d{4})_(\d{2})$", asset or "")
    return f"{match.group(1)}-{match.group(2)}" if match else None


def asset_properties(month: str, date: str, item_ids: list[str], clear_share: float) -> dict:
    """Properties every monthly mosaic carries (set by the notebook, read by available_months())."""
    check_month(month)
    if not date.startswith(month):
        raise ValueError(f"acquisition date {date} is not in {month}")
    return {"month": month, "date": date, "source": SOURCE, "scene_count": len(item_ids),
            "item_ids": ",".join(item_ids), "clear_share": round(float(clear_share), 4), "attribution": ATTRIBUTION}


def ingestion_manifest(month: str, date: str, gcs_uri: str, properties: dict, collection: str = PLANET_COLLECTION) -> dict:
    """Earth Engine ingestion manifest for one monthly mosaic in Cloud Storage (ee.data.startIngestion)."""
    return {
        "name": asset_id(month, collection),
        "tilesets": [{"id": "0", "sources": [{"uris": [gcs_uri]}]}],
        "bands": [{"id": name, "tilesetId": "0", "tilesetBandIndex": i, "missingData": {"values": [0]}}
                  for i, name in enumerate(BANDS)],
        "startTime": f"{date}T00:00:00Z",
        "properties": properties,
    }


def missing_months(expected: list[str], available: list[str]) -> list[str]:
    have = set(available)
    return [m for m in expected if m not in have]


# ---------- Earth Engine ----------
def collection(ee: Any) -> Any:
    return ee.ImageCollection(PLANET_COLLECTION)


def available_months(ee: Any) -> list[str]:
    """Months with a mosaic in the collection, sorted. [] when the collection doesn't exist yet."""
    try:
        months = collection(ee).aggregate_array("month").getInfo() or []
    except Exception:          # collection not created / not shared with this project yet
        return []
    return sorted(set(months))


def month_image(ee: Any, month: str) -> Any:
    """One month as reflectance (0-1) with named bands, masked to clear pixels."""
    img = ee.Image(asset_id(month)).select(list(range(len(BANDS))), list(BANDS))
    sr = img.select(list(SR_BANDS)).multiply(SR_SCALE)
    return sr.updateMask(img.select("clear").eq(1)).set("month", month)


def indices(ee: Any, img: Any) -> Any:
    """NDVI and NDWI; the SWIR indices (NDBI, MNDWI) don't exist for PlanetScope (D12)."""
    return ee.Image.cat([img.normalizedDifference(["nir", "red"]).rename("NDVI"),
                         img.normalizedDifference(["green", "nir"]).rename("NDWI")])


def water_image(ee: Any, month: str, threshold: float = NDWI_WATER) -> Any:
    """1 = water, 0 = land, masked where the month isn't clear."""
    return indices(ee, month_image(ee, month)).select("NDWI").gt(threshold).rename("water")


TILE_KINDS = ("rgb", "nir", "water")


def tile_layer(month: str, kind: str, aoi: dict | None = None) -> dict:
    """XYZ tiles of one Planet month for the map: true colour (rgb), NIR false colour (nir) or NDWI water
    (water, blue; land transparent). Cloud and no data are transparent, so a gap shows as a gap."""
    from .ee_engine import _ee
    if kind not in TILE_KINDS:
        raise ValueError(f"kind must be one of {TILE_KINDS}")
    ee = _ee()
    img = month_image(ee, month)
    if kind == "water":
        vis_img = water_image(ee, month).selfMask().visualize(palette=["2563eb"])
    else:
        bands, lo, hi = CHIP_VIS[kind]
        vis_img = img.visualize(bands=bands, min=lo, max=hi)
    if aoi:
        vis_img = vis_img.clip(ee.Geometry(aoi))
    map_id = vis_img.getMapId({})
    return {"tiles": [map_id["tile_fetcher"].url_format], "month": month, "kind": kind, "attribution": ATTRIBUTION}


def region_chips(month: str, bbox: tuple[float, float, float, float]) -> dict[str, bytes]:
    """Planet chips around a region for the Geo-VLM check: true colour + NIR false colour (no SWIR),
    same framing as ee_engine.region_chips(). Keys: rgb, nir."""
    import urllib.request

    from .ee_engine import CHIP_PX, _ee, chip_box
    ee = _ee()
    img = month_image(ee, month)
    region = ee.Geometry.Rectangle(chip_box(bbox))
    edge = (ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle(list(bbox)))]), 1, 2)
            .visualize(palette=["ffff00"]))
    chips = {}
    for kind, (bands, lo, hi) in CHIP_VIS.items():
        url = img.visualize(bands=bands, min=lo, max=hi).unmask(0).blend(edge).getThumbURL(
            {"region": region, "dimensions": CHIP_PX, "format": "png"})
        with urllib.request.urlopen(url, timeout=120) as resp:
            chips[kind] = resp.read()
    return chips


def window_month(window: list[str], months: list[str]) -> str | None:
    """The last Planet month starting inside a date window [start, end) (ISO dates), or None."""
    start, end = window
    inside = [m for m in months if start[:7] <= m and f"{m}-01" < end]
    return inside[-1] if inside else None


def pair_chips(before_month: str, after_month: str, bbox: tuple[float, float, float, float]) -> dict[str, bytes]:
    """Before / after Planet chips for the Geo-VLM check, keyed like ee_engine.region_chips():
    before_rgb, after_rgb, before_nir, after_nir."""
    out = {}
    for when, month in (("before", before_month), ("after", after_month)):
        out.update({f"{when}_{kind}": png for kind, png in region_chips(month, bbox).items()})
    return out
