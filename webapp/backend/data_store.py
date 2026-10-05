"""Where the map's live data comes from.

Two layers:
1. The original global store (REGIONS_PATH/AOI_PATH) — written by
   agents/import_geojson.py or the pipeline's publishing_agent when
   publish_live=True. Unchanged from before Phase 6.
2. The per-run store (Phase 6) — data/runs/{run_id}/... — written by the
   on-demand runs API, so multiple runs can coexist without overwriting
   each other or the global store above.

Falls back to demo_data.py when neither a run id nor the global files exist.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from agents.schema import REGION_FIELDS

from . import demo_data

DATA_DIR = Path(__file__).resolve().parent / "data"
REGIONS_PATH = DATA_DIR / "change_regions.json"
AOI_PATH = DATA_DIR / "aoi.json"


def _run_dir(run_id: str) -> Path:
    return DATA_DIR / "runs" / run_id


def create_run(run_id: str, aoi_geojson: dict, before_window: list[str], after_window: list[str], condition: str, code_version: str) -> None:
    d = _run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "status.json").write_text(json.dumps({
        "run_id": run_id, "status": "queued", "progress": 0.0,
        "created_at": time.time(), "error": None, "cache_key": None,
        "aoi": aoi_geojson, "before_window": before_window, "after_window": after_window,
        "condition": condition, "code_version": code_version,
    }, indent=2))


def get_status(run_id: str) -> Optional[dict]:
    p = _run_dir(run_id) / "status.json"
    return json.loads(p.read_text()) if p.exists() else None


def update_status(run_id: str, **fields) -> None:
    p = _run_dir(run_id) / "status.json"
    current = json.loads(p.read_text())
    current.update(fields)
    p.write_text(json.dumps(current, indent=2))


def write_run_result(run_id: str, aoi_geojson: dict, change_regions_geojson: dict, report: dict) -> None:
    d = _run_dir(run_id)
    (d / "aoi.json").write_text(json.dumps(aoi_geojson, indent=2))
    (d / "change_regions.json").write_text(json.dumps(change_regions_geojson, indent=2))
    (d / "report.json").write_text(json.dumps(report, indent=2))


def cache_key(aoi_geojson: dict, before_window: list[str], after_window: list[str], condition: str, code_version: str) -> str:
    payload = json.dumps(
        {"aoi": aoi_geojson, "before_window": before_window, "after_window": after_window,
         "condition": condition, "code_version": code_version},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def find_cached_run(key: str) -> Optional[str]:
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return None
    for run_dir in runs_dir.iterdir():
        status_path = run_dir / "status.json"
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text())
        if status.get("cache_key") == key and status.get("status") == "done":
            return status["run_id"]
    return None


# --- existing functions, unchanged behavior, now also run-aware ---

def get_aoi(run_id: Optional[str] = None) -> dict:
    if run_id:
        p = _run_dir(run_id) / "aoi.json"
        if p.exists():
            return json.loads(p.read_text())
    if AOI_PATH.exists():
        return json.loads(AOI_PATH.read_text())
    return demo_data.AOI


def get_change_regions(run_id: Optional[str] = None) -> dict:
    if run_id:
        p = _run_dir(run_id) / "change_regions.json"
        if p.exists():
            return json.loads(p.read_text())
    if REGIONS_PATH.exists():
        return json.loads(REGIONS_PATH.read_text())
    return demo_data.CHANGE_REGIONS


def is_live_data(run_id: Optional[str] = None) -> bool:
    if run_id:
        return (_run_dir(run_id) / "change_regions.json").exists()
    return REGIONS_PATH.exists()


def evidence_for(region_ids: list[str], run_id: Optional[str] = None) -> dict:
    fc = get_change_regions(run_id)
    feats = [f["properties"] for f in fc["features"] if f["properties"]["id"] in region_ids]
    total_area = sum(p.get("area_ha", 0) for p in feats)
    coords = get_aoi(run_id)["features"][0]["geometry"]["coordinates"][0]
    lons = [c[0] for c in coords]; lats = [c[1] for c in coords]
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    import math
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * abs(math.cos(math.radians((s + n) / 2)))
    aoi_area_ha = max((e - w) * km_per_deg_lon * (n - s) * km_per_deg_lat * 100, 1)
    return {
        "pair_id": fc["features"][0]["properties"].get("source", "unknown") if fc["features"] else "empty",
        "dates": [feats[0].get("date_before", "?"), feats[0].get("date_after", "?")] if feats else ["?", "?"],
        "source": "live" if is_live_data(run_id) else "demo",
        "change_frac": round(total_area / aoi_area_ha, 4),
        "regions": [{k: p[k] for k in REGION_FIELDS} for p in sorted(feats, key=lambda p: -p["area_ha"])],
    }


DEFAULT_MAX_CLOUD_PCT = 30.0   # same as data/quangninh/study.json


def analysis_params(run_id: Optional[str] = None) -> Optional[dict]:
    """AOI, date windows and cloud limit the shown regions were computed from, or None
    for demo data (which has no Earth Engine analysis behind it)."""
    if run_id:
        s = get_status(run_id)
        if not s:
            return None
        return {"aoi": s["aoi"], "before_window": s["before_window"], "after_window": s["after_window"],
                "max_cloud_pct": DEFAULT_MAX_CLOUD_PCT}
    if not REGIONS_PATH.exists():
        return None
    meta = json.loads(REGIONS_PATH.read_text()).get("metadata") or {}
    if not all(meta.get(k) for k in ("aoi", "before_window", "after_window")):
        return None
    return {"aoi": meta["aoi"], "before_window": meta["before_window"], "after_window": meta["after_window"],
            "max_cloud_pct": float((meta.get("thresholds") or {}).get("max_cloud_pct", DEFAULT_MAX_CLOUD_PCT))}


def known_region_ids(run_id: Optional[str] = None) -> set[str]:
    return {f["properties"]["id"] for f in get_change_regions(run_id)["features"]}