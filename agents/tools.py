"""Deterministic tool functions each agent calls.

Agents orchestrate; these tools do the deterministic geospatial / DL work.
Every function still has a MOCK implementation so the whole graph runs with no
GPU, Earth Engine login, or API key. Phase 5-6 replace the functions marked
SWAP-IN with real Earth Engine and model calls. Claim generation is NOT here:
it lives only in webapp/backend/report.py (see webapp_bridge.py).
"""
from __future__ import annotations

import random

from .schema import LOCATIONS


def query_scenes(aoi: dict, date_before: str, date_after: str, max_cloud_pct: float, rng: random.Random) -> dict:
    """SWAP-IN (Phase 6): a real Earth Engine catalog query that filters by AOI, date range
    and cloud cover and returns the chosen scene ids + their actual cloud percentages."""
    if not isinstance(aoi, dict) or not aoi.get("type") or not aoi.get("coordinates"):
        raise ValueError("AOI must be a GeoJSON-like dict with a type and coordinates.")
    if not date_before or not date_after:
        raise ValueError("Both date_before and date_after must be provided.")
    if date_after <= date_before:
        raise ValueError("date_after must be later than date_before.")
    return {
        "scene_before_id": f"S2_{date_before}_mock{rng.randint(1000, 9999)}",
        "scene_after_id": f"S2_{date_after}_mock{rng.randint(1000, 9999)}",
        "cloud_pct_before": round(rng.uniform(2, max_cloud_pct + 15), 1),  # sometimes over budget, on purpose
        "cloud_pct_after": round(rng.uniform(2, max_cloud_pct + 15), 1),
    }


def run_preprocessing(cloud_pct_before: float, cloud_pct_after: float, max_cloud_pct: float) -> tuple[bool, str]:
    """SWAP-IN (Phase 6): real cloud masking / compositing. Too cloudy is a recoverable
    failure: the Orchestrator retries Ingestion instead of crashing the pipeline."""
    if max(cloud_pct_before, cloud_pct_after) > max_cloud_pct:
        return False, f"cloud cover too high (before={cloud_pct_before}%, after={cloud_pct_after}%, limit={max_cloud_pct}%)"
    return True, "ok"


def run_change_detection(rng: random.Random, n_regions: int = 3) -> tuple[float, list[dict]]:
    """SWAP-IN (Phase 6): the trained change model's prediction, vectorized into regions."""
    regions = []
    for index in range(1, n_regions + 1):
        regions.append({
            "id": f"r{index}",
            "area_ha": round(rng.uniform(10, 200), 1),
            "mean_conf": round(rng.uniform(0.3, 0.95), 2),
            "dNDVI": round(rng.uniform(-0.5, 0.3), 3),
            "dNDBI": round(rng.uniform(-0.1, 0.4), 3),
            "dMNDWI": round(rng.uniform(-0.2, 0.2), 3),
            "location": rng.choice(LOCATIONS),
        })
    return round(sum(region["area_ha"] for region in regions) / 24830, 4), regions
