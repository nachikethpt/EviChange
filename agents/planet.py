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
LAYERS = ("rgb", "nir", "ndvi", "ndwi")
INDEX_VIS = {
    "ndvi": {"min": -1, "max": 1, "palette": ["8c510a", "f6e8c3", "01665e"]},
    "ndwi": {"min": -1, "max": 1, "palette": ["a6611a", "f5f5f5", "018571"]},
}

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


# ---------- names (no Earth Engine needed) ----------
def check_month(month: str) -> str:
    if not _MONTH.fullmatch(month or ""):
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


def month_catalog(ee: Any) -> dict:
    """Delivered mosaics and acquisition metadata, read from EE, never inferred from orders.

    Unlike available_months(), access/authentication errors propagate: an unavailable collection
    must not be presented as a successful query with no delivered imagery.
    """
    col = collection(ee)
    # toList(0) is invalid in EE, so handle an empty (but accessible) collection explicitly.
    count = col.size().getInfo()
    rows = (col.toList(count).map(lambda im: ee.Image(im).toDictionary(
        ["month", "date", "clear_share"])).getInfo() if count else [])
    months = []
    for row in rows:
        month = check_month(row.get("month"))
        months.append({"month": month, "date": row.get("date"), "clear_share": row.get("clear_share"),
                       "asset_id": asset_id(month)})
    return {"months": sorted(months, key=lambda r: r["month"]), "collection": PLANET_COLLECTION,
            "source": SOURCE, "scale_m": NATIVE_SCALE, "attribution": ATTRIBUTION}


def tile_layer(aoi: dict, month: str, layer: str) -> dict:
    """Clear-masked Planet monthly imagery / indices as XYZ tiles, clipped to the study AOI.

    Planet is an additional visual source. It does not fill Dynamic World class labels or alter
    the frozen Sentinel-2 evidence used in the report evaluation.
    """
    check_month(month)
    if layer not in LAYERS:
        raise ValueError(f"layer must be one of {LAYERS}")
    from .ee_engine import _ee
    ee = _ee()
    image = month_image(ee, month)
    if layer in CHIP_VIS:
        bands, lo, hi = CHIP_VIS[layer]
        vis = {"bands": bands, "min": lo, "max": hi}
    else:
        image = indices(ee, image).select(layer.upper())
        vis = INDEX_VIS[layer]
    map_id = image.clip(ee.Geometry(aoi)).getMapId(vis)
    return {"tiles": [map_id["tile_fetcher"].url_format], **vis,
            "source": SOURCE, "scale_m": NATIVE_SCALE, "attribution": ATTRIBUTION}


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


def box_clear_share(ee: Any, month: str, bbox: tuple) -> float:
    """Observed clear share of the requested box, including uncovered pixels as not clear."""
    image = month_image(ee, month)
    value = image.select("red").mask().unmask(0, False).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=ee.Geometry.Rectangle(list(bbox)), scale=NATIVE_SCALE,
        maxPixels=1e8, tileScale=4).get("red").getInfo()
    return float(value or 0)


def region_chips(month: str, bbox: tuple[float, float, float, float],
                 kinds: tuple[str, ...] = ("rgb", "nir")) -> dict[str, bytes]:
    """Planet chips around a region for the Geo-VLM check: true colour + NIR false colour (no SWIR),
    same framing as ee_engine.region_chips(). Keys: rgb, nir."""
    import urllib.request

    if any(kind not in CHIP_VIS for kind in kinds):
        raise ValueError(f"Planet chips must be one of {tuple(CHIP_VIS)} (no SWIR)")
    from .ee_engine import CHIP_PX, _ee, chip_box
    ee = _ee()
    img = month_image(ee, month)
    region = ee.Geometry.Rectangle(chip_box(bbox))
    edge = (ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle(list(bbox)))]), 1, 2)
            .visualize(palette=["ffff00"]))
    chips = {}
    for kind in kinds:
        bands, lo, hi = CHIP_VIS[kind]
        url = img.visualize(bands=bands, min=lo, max=hi).unmask(0).blend(edge).getThumbURL(
            {"region": region, "dimensions": CHIP_PX, "format": "png"})
        with urllib.request.urlopen(url, timeout=120) as resp:
            chips[kind] = resp.read()
    return chips
