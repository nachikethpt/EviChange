"""Earth Engine change-detection engine for the Person 1 Phase 2 contract.

Earth Engine is imported only inside call sites so the mock pipeline and unit tests
remain usable on machines without the EE client or credentials.
"""
from __future__ import annotations

from datetime import date, timedelta
import os
from typing import Any

from . import schema


S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
CODE_VERSION = "ee-threshold-v1"
SCL_CLOUD_CLASSES = [3, 8, 9, 10, 11]


def _ee():
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError("earthengine-api is required for EVICHANGE_ENGINE=ee") from exc
    try:
        ee.Initialize(project=os.environ.get("EE_PROJECT", "ariel-509507"))
    except Exception:
        # A second initialize is harmless when another caller initialized EE.
        ee.Initialize()
    return ee


def _geometry(ee: Any, aoi: dict) -> Any:
    return ee.Geometry(aoi)


def _inclusive_end(window: list[str]) -> str:
    return (date.fromisoformat(window[1]) + timedelta(days=1)).isoformat()


def _cloud_mask(ee: Any, image: Any) -> Any:
    scl = image.select("SCL")
    return image.updateMask(scl.remap(SCL_CLOUD_CLASSES, [0] * len(SCL_CLOUD_CLASSES), 1).eq(1))


def _composite(ee: Any, aoi: dict, window: list[str], max_cloud_pct: float) -> tuple[Any, Any]:
    geometry = _geometry(ee, aoi)
    collection = (ee.ImageCollection(S2_COLLECTION)
                  .filterBounds(geometry)
                  .filterDate(window[0], _inclusive_end(window))
                  .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud_pct))
                  .map(lambda image: _cloud_mask(ee, image)))
    count = collection.size()
    if count.getInfo() == 0:
        raise ValueError(f"No Sentinel-2 SR scenes found for window {window} under {max_cloud_pct}% cloud")
    return collection.median().select(["B2", "B3", "B4", "B8", "B11"]), collection


def query_scenes_ee(aoi: dict, before_window: list[str], after_window: list[str], max_cloud_pct: float) -> dict:
    ee = _ee()
    schema.check(schema.validate_aoi(aoi), "AOI")
    schema.check(schema.validate_windows(before_window, after_window), "date windows")
    geometry = _geometry(ee, aoi)
    selected = {}
    for label, window in (("before", before_window), ("after", after_window)):
        collection = (ee.ImageCollection(S2_COLLECTION)
                      .filterBounds(geometry)
                      .filterDate(window[0], _inclusive_end(window))
                      .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud_pct))
                      .sort("CLOUDY_PIXEL_PERCENTAGE"))
        first = ee.Image(collection.first())
        info = first.getInfo()
        if not info:
            raise ValueError(f"No Sentinel-2 scene found for {label} window {window}")
        selected[f"scene_{label}_id"] = info.get("id", "unknown")
        selected[f"cloud_pct_{label}"] = float(info.get("properties", {}).get("CLOUDY_PIXEL_PERCENTAGE", 0.0))
    return selected


def _indices(ee: Any, image: Any) -> Any:
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndbi = image.normalizedDifference(["B11", "B8"]).rename("NDBI")
    mndwi = image.normalizedDifference(["B3", "B11"]).rename("MNDWI")
    return ee.Image.cat([ndvi, ndbi, mndwi])


def where_in_aoi(lon: float, lat: float, bounds: tuple[float, float, float, float]) -> str:
    west, south, east, north = bounds
    col = ["west", "centre", "east"][min(max(int(3 * (lon - west) / (east - west)), 0), 2)]
    row = ["south", "centre", "north"][min(max(int(3 * (lat - south) / (north - south)), 0), 2)]
    if row == "centre" and col == "centre":
        return "centre"
    if row == "centre":
        return col
    if col == "centre":
        return row
    return f"{row}-{col}"


def run_engine(aoi: dict, before_window: list[str], after_window: list[str], thresholds: dict, code_version: str = CODE_VERSION) -> dict:
    """Run the EE detector and return the shared GeoJSON FeatureCollection contract."""
    ee = _ee()
    schema.check(schema.validate_aoi(aoi), "AOI")
    schema.check(schema.validate_windows(before_window, after_window), "date windows")
    geometry = _geometry(ee, aoi)
    max_cloud = float(thresholds["max_cloud_pct"])
    index_delta = float(thresholds["index_delta"])
    min_area_ha = float(thresholds["min_area_ha"])

    before, _ = _composite(ee, aoi, before_window, max_cloud)
    after, _ = _composite(ee, aoi, after_window, max_cloud)
    before_idx, after_idx = _indices(ee, before), _indices(ee, after)
    d_ndvi = after_idx.select("NDVI").subtract(before_idx.select("NDVI")).rename("dNDVI")
    d_ndbi = after_idx.select("NDBI").subtract(before_idx.select("NDBI")).rename("dNDBI")
    d_mndwi = after_idx.select("MNDWI").subtract(before_idx.select("MNDWI")).rename("dMNDWI")
    deltas = ee.Image.cat([d_ndvi, d_ndbi, d_mndwi])
    votes = (d_ndvi.abs().gt(index_delta).add(d_ndbi.abs().gt(index_delta)).add(d_mndwi.abs().gt(index_delta)))
    agreement = votes.gte(2).rename("agreement")
    change_mask = agreement.selfMask().rename("change")

    stats = ee.Image.cat([change_mask, deltas, agreement, ee.Image.pixelArea().rename("area_m2")])
    vectors = stats.reduceToVectors(
        geometry=geometry,
        scale=10,
        geometryType="polygon",
        labelProperty="change",
        reducer=ee.Reducer.mean().combine(ee.Reducer.sum(), "", True),
        maxPixels=1e10,
        tileScale=4,
    )

    def add_properties(feature: Any) -> Any:
        area_ha = ee.Number(feature.get("area_m2_sum")).divide(10000)
        return feature.set({
            "area_ha": area_ha,
            "dNDVI": feature.get("dNDVI_mean"),
            "dNDBI": feature.get("dNDBI_mean"),
            "dMNDWI": feature.get("dMNDWI_mean"),
            "mean_conf": feature.get("agreement_mean"),
            "centroid": feature.geometry().centroid(1).coordinates(),
        })

    vectors = vectors.map(add_properties).filter(ee.Filter.gte("area_ha", min_area_ha))
    info = vectors.getInfo()
    bounds = schema.aoi_bounds(aoi)
    features = []
    for index, feature in enumerate(info.get("features", []), 1):
        props = feature.get("properties", {})
        centroid = props.pop("centroid", None) or [sum(point[0] for point in feature["geometry"]["coordinates"][0]) / len(feature["geometry"]["coordinates"][0]), sum(point[1] for point in feature["geometry"]["coordinates"][0]) / len(feature["geometry"]["coordinates"][0])]
        region = {
            "id": f"r{index}",
            "area_ha": round(float(props.get("area_ha", 0)), 3),
            "mean_conf": round(float(props.get("mean_conf", 0)), 4),
            "dNDVI": round(float(props.get("dNDVI", 0)), 6),
            "dNDBI": round(float(props.get("dNDBI", 0)), 6),
            "dMNDWI": round(float(props.get("dMNDWI", 0)), 6),
            "location": where_in_aoi(float(centroid[0]), float(centroid[1]), bounds),
        }
        properties = {**region, "date_before": "/".join(before_window), "date_after": "/".join(after_window), "source": code_version}
        feature["id"] = index
        feature["properties"] = properties
        features.append(feature)

    change_area = change_mask.multiply(ee.Image.pixelArea()).reduceRegion(ee.Reducer.sum(), geometry, 10, maxPixels=1e10).get("change")
    aoi_area = ee.Image.pixelArea().reduceRegion(ee.Reducer.sum(), geometry, 10, maxPixels=1e10).get("area")
    change_frac = float(ee.Number(change_area).divide(aoi_area).getInfo() or 0.0)
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "before_window": before_window,
            "after_window": after_window,
            "thresholds": thresholds,
            "code_version": code_version,
            "aoi": aoi,
            "change_frac": change_frac,
        },
    }
