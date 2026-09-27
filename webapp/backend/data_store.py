"""Where the map's live data comes from — this is what makes the multi-agent
pipeline and Person 1's real Earth Engine output actually show up on the map,
instead of staying separate demo data forever.

Priority order, checked on every request (so a fresh pipeline run shows up
immediately on browser refresh, no server restart needed):
  1. backend/data/change_regions.json + backend/data/aoi.json — written by
     agents/import_geojson.py (Person 1's real export) or by the multi-agent
     pipeline's publishing_agent (agents/agents/nodes.py).
  2. demo_data.py — the original hand-made fake data, used until either of
     the above exists.
"""
import json
from pathlib import Path

from agents.schema import REGION_FIELDS

from . import demo_data

DATA_DIR = Path(__file__).resolve().parent / "data"
REGIONS_PATH = DATA_DIR / "change_regions.json"
AOI_PATH = DATA_DIR / "aoi.json"


def get_aoi() -> dict:
    if AOI_PATH.exists():
        return json.loads(AOI_PATH.read_text())
    return demo_data.AOI


def get_change_regions() -> dict:
    if REGIONS_PATH.exists():
        return json.loads(REGIONS_PATH.read_text())
    return demo_data.CHANGE_REGIONS


def is_live_data() -> bool:
    """True once real (agent/Person-1) data has been written — the frontend
    banner and /api/health use this so nobody mistakes demo data for real results."""
    return REGIONS_PATH.exists()


def evidence_for(region_ids: list[str]) -> dict:
    """Same shape build_report() expects, computed from whichever region set is live."""
    fc = get_change_regions()
    feats = [f["properties"] for f in fc["features"] if f["properties"]["id"] in region_ids]
    total_area = sum(p.get("area_ha", 0) for p in feats)
    # AOI area in hectares, from the AOI polygon's bounding box (rough, consistent either way)
    coords = get_aoi()["features"][0]["geometry"]["coordinates"][0]
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * abs(__import__("math").cos(__import__("math").radians((s + n) / 2)))
    aoi_area_ha = max((e - w) * km_per_deg_lon * (n - s) * km_per_deg_lat * 100, 1)
    return {
        "pair_id": fc["features"][0]["properties"].get("source", "unknown") if fc["features"] else "empty",
        "dates": [feats[0].get("date_before", "?"), feats[0].get("date_after", "?")] if feats else ["?", "?"],
        "source": "live" if is_live_data() else "demo",
        "change_frac": round(total_area / aoi_area_ha, 4),
        "regions": [
            {k: p[k] for k in REGION_FIELDS}
            for p in sorted(feats, key=lambda p: -p["area_ha"])
        ],
    }


def known_region_ids() -> set[str]:
    return {f["properties"]["id"] for f in get_change_regions()["features"]}
