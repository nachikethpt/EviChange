"""Deterministic tool functions each agent calls.

Agents orchestrate; these tools do the deterministic geospatial work.
Every function still has a MOCK implementation so the whole graph runs with no
GPU, Earth Engine login, or API key. Claim generation is NOT here:
it lives only in webapp/backend/report.py (see webapp_bridge.py).
"""
from __future__ import annotations

import os
import random

from . import schema


def query_scenes(aoi: dict, before_window: list[str], after_window: list[str], max_cloud_pct: float, rng: random.Random) -> dict:
    """Query the configured mock catalog or Earth Engine Sentinel-2 catalog."""
    schema.check(schema.validate_aoi(aoi), "AOI")
    schema.check(schema.validate_windows(before_window, after_window), "date windows")
    mode = os.environ.get("EVICHANGE_ENGINE", "mock").strip().lower()
    if mode not in ("mock", "ee"):
        raise ValueError("EVICHANGE_ENGINE must be 'mock' or 'ee'")
    if mode == "ee":
        from .ee_engine import query_scenes_ee
        return query_scenes_ee(aoi, before_window, after_window, max_cloud_pct)
    return {
        "scene_before_id": f"S2_{before_window[0]}_{before_window[1]}_mock{rng.randint(1000, 9999)}",
        "scene_after_id": f"S2_{after_window[0]}_{after_window[1]}_mock{rng.randint(1000, 9999)}",
        "cloud_pct_before": round(rng.uniform(2, max_cloud_pct + 15), 1),  # sometimes over budget, on purpose
        "cloud_pct_after": round(rng.uniform(2, max_cloud_pct + 15), 1),
    }


def run_preprocessing(cloud_pct_before: float, cloud_pct_after: float, max_cloud_pct: float) -> tuple[bool, str]:
    """Apply the pipeline's cloud-budget gate. EE masking happens in ee_engine."""
    if max(cloud_pct_before, cloud_pct_after) > max_cloud_pct:
        return False, f"cloud cover too high (before={cloud_pct_before}%, after={cloud_pct_after}%, limit={max_cloud_pct}%)"
    return True, "ok"


def run_change_detection(rng: random.Random, aoi: dict, before_window: list[str], after_window: list[str], thresholds: dict, n_regions: int = 3) -> tuple[float, list[dict], dict]:
    """Run the configured EE detector or deterministic offline detector."""
    if os.environ.get("EVICHANGE_ENGINE", "mock").strip().lower() == "ee":
        from .ee_engine import run_engine
        output = run_engine(aoi, before_window, after_window, thresholds)
        regions = []
        for feature in output["features"]:
            region = dict(feature["properties"])
            region["_geometry"] = feature["geometry"]
            regions.append(region)
        return output["metadata"]["change_frac"], regions, output["metadata"]

    regions = []
    for index in range(1, n_regions + 1):
        regions.append({
            "id": f"r{index}",
            "area_ha": round(rng.uniform(10, 200), 1),
            "mean_conf": round(rng.uniform(0.3, 0.95), 2),
            "dNDVI": round(rng.uniform(-0.5, 0.3), 3),
            "dNDBI": round(rng.uniform(-0.1, 0.4), 3),
            "dMNDWI": round(rng.uniform(-0.2, 0.2), 3),
            "location": rng.choice(schema.LOCATIONS),
        })
    metadata = {"before_window": before_window, "after_window": after_window, "thresholds": thresholds, "code_version": "mock-threshold-v1", "aoi": aoi}
    return round(sum(region["area_ha"] for region in regions) / schema.aoi_area_ha(aoi), 4), regions, metadata
