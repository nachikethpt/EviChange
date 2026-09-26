"""Deterministic mock tools. Replace functions marked SWAP-IN with real services."""
from __future__ import annotations

import random
from typing import Optional

T_IDX = 0.10


def query_scenes(aoi: dict, date_before: str, date_after: str, max_cloud_pct: float, rng: random.Random) -> dict:
    """SWAP-IN: query a STAC or Earth Engine catalog for matching scenes."""
    return {
        "scene_before_id": f"S2_{date_before}_mock{rng.randint(1000, 9999)}",
        "scene_after_id": f"S2_{date_after}_mock{rng.randint(1000, 9999)}",
        "cloud_pct_before": round(rng.uniform(2, max_cloud_pct + 15), 1),
        "cloud_pct_after": round(rng.uniform(2, max_cloud_pct + 15), 1),
    }


def run_preprocessing(cloud_pct_before: float, cloud_pct_after: float, max_cloud_pct: float) -> tuple[bool, str]:
    """SWAP-IN: cloud-mask, reproject, and tile imagery."""
    if max(cloud_pct_before, cloud_pct_after) > max_cloud_pct:
        return False, f"cloud cover too high (before={cloud_pct_before}%, after={cloud_pct_after}%, limit={max_cloud_pct}%)"
    return True, "ok"


def run_change_detection(rng: random.Random, n_regions: int = 3) -> tuple[float, list[dict]]:
    """SWAP-IN: run a change-detection model and return detected regions."""
    locations = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west", "centre"]
    regions = []
    for index in range(1, n_regions + 1):
        regions.append({
            "id": f"r{index}", "area_ha": round(rng.uniform(10, 200), 1),
            "mean_conf": round(rng.uniform(0.3, 0.95), 2),
            "dNDVI": round(rng.uniform(-0.5, 0.3), 3),
            "dNDBI": round(rng.uniform(-0.1, 0.4), 3),
            "dMNDWI": round(rng.uniform(-0.2, 0.2), 3),
            "location": rng.choice(locations),
        })
    return round(sum(region["area_ha"] for region in regions) / 24830, 4), regions


def _region_change_types(region: dict) -> list[tuple[str, str]]:
    types = []
    if region["dNDVI"] < -T_IDX: types.append(("vegetation loss", "dNDVI"))
    if region["dNDVI"] > T_IDX: types.append(("vegetation gain", "dNDVI"))
    if region["dNDBI"] > T_IDX: types.append(("increase in built-up or bare surface", "dNDBI"))
    if region["dMNDWI"] > T_IDX: types.append(("increase in surface water", "dMNDWI"))
    if region["dMNDWI"] < -T_IDX: types.append(("decrease in surface water", "dMNDWI"))
    return types


def build_claims(regions: list[dict], condition: str) -> tuple[list[dict], list[dict], Optional[str]]:
    """SWAP-IN: use the Geo-VLM while keeping the same structured return schema."""
    claims: list[dict] = []
    abstain: list[dict] = []

    def add(**claim: object) -> None:
        claim["claim_id"] = f"c{len(claims) + 1}"
        claims.append(claim)

    if condition == "template":
        add(level="L1", type="presence", text="Change detected between the two dates.", region_ref=None, evidence_ref=["change_frac"], stated_conf=1.0)
        for region in regions:
            add(level="L2", type="location", text=f"Region {region['id']}: {region['area_ha']:.0f} ha of change in the {region['location']}.", region_ref=region["id"], evidence_ref=["location", "area_ha"], stated_conf=region["mean_conf"])
    elif condition == "gated":
        add(level="L1", type="presence", text="Change detected between the two dates.", region_ref=None, evidence_ref=["change_frac"], stated_conf=1.0)
        for region in regions:
            for name, field in _region_change_types(region):
                add(level="L3", type="change_type", text=f"In region {region['id']} ({region['location']}, ~{region['area_ha']:.0f} ha) the imagery shows {name} ({field} {region[field]:+.2f}).", region_ref=region["id"], evidence_ref=[field], stated_conf=region["mean_conf"])
        abstain = [{"topic": "cause of change", "reason": "The evidence contains no information about causes."}, {"topic": "legality / licensing", "reason": "Licence data is not part of the evidence."}]
    else:
        add(level="L1", type="presence", text="Land-cover change occurred.", region_ref=None, evidence_ref=[], stated_conf=None)
        add(level="L4", type="cause", text="The change is likely due to illegal mining.", region_ref=None, evidence_ref=[], stated_conf=None)
    return claims, abstain, None
