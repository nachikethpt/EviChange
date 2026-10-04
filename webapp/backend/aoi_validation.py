"""Interim AOI validation until agents.schema.validate_aoi() lands (Phase 2).
TODO: replace this whole module with schema.validate_aoi() once available."""
import math

MIN_AREA_KM2 = 1
MAX_AREA_KM2 = 500


def polygon_bbox_area_km2(geojson: dict) -> float:
    """Rough bbox area — same approximation already used in data_store.evidence_for()."""
    coords = geojson["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * abs(math.cos(math.radians((s + n) / 2)))
    return (e - w) * km_per_deg_lon * (n - s) * km_per_deg_lat


def validate_aoi(geojson: dict) -> list[str]:
    errors = []
    if not isinstance(geojson, dict) or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        return ["AOI must be a GeoJSON Polygon or MultiPolygon"]
    if geojson["type"] == "Polygon":
        area = polygon_bbox_area_km2(geojson)
        if area < MIN_AREA_KM2:
            errors.append(f"AOI too small: {area:.2f} km² (minimum {MIN_AREA_KM2} km²)")
        if area > MAX_AREA_KM2:
            errors.append(f"AOI too large: {area:.2f} km² (maximum {MAX_AREA_KM2} km²) — draw a smaller area")
    return errors