"""The six agents as LangGraph nodes.

Each function takes the current PipelineState and returns only the fields it
changed (LangGraph merges partial updates into state). Data crossing agent
boundaries is checked against agents/schema.py.
"""
from __future__ import annotations

import random

from . import schema, tools, webapp_bridge
from .state import PipelineState, log

AOI_BOUNDS = (107.22, 20.98, 107.40, 21.10)  # matches webapp/backend/demo_data.py's demo AOI


def orchestrator(state: PipelineState) -> dict:
    """01 Orchestrator — validates the request and records state."""
    attempt = state.get("attempt", 0) + 1
    updates = {"attempt": attempt, "status": "running", "step": "orchestrator"}
    if state["task"] != "change_detection":
        return {**updates, "status": "failed", "error": "unapproved task", "log": log(state, "orchestrator", "error", "unapproved task")}
    if state["condition"] not in schema.CONDITIONS:
        return {**updates, "status": "failed", "error": "unapproved claim condition", "log": log(state, "orchestrator", "error", "unapproved claim condition")}
    return {**updates, "log": log(state, "orchestrator", "ok", f"attempt {attempt}/{state['max_attempts']}")}


def ingestion_agent(state: PipelineState) -> dict:
    """02 Ingestion Agent — query catalogs by area/time/sensor."""
    rng = random.Random(f"{state['aoi_name']}-{state['attempt']}")  # deterministic but different per retry
    scenes = tools.query_scenes(state["aoi"], state["date_before"], state["date_after"], 30, rng)
    return {**scenes, "step": "ingestion",
            "log": log(state, "ingestion_agent", "ok",
                       f"{scenes['scene_before_id']} (cloud {scenes['cloud_pct_before']}%), "
                       f"{scenes['scene_after_id']} (cloud {scenes['cloud_pct_after']}%)")}


def preprocessing_agent(state: PipelineState) -> dict:
    """03 Preprocessing Agent — approved optical pipeline -> analysis-ready tiles."""
    ok, detail = tools.run_preprocessing(state["cloud_pct_before"], state["cloud_pct_after"], 30)
    if not ok:
        return {"tiles_ready": False, "step": "preprocessing", "log": log(state, "preprocessing_agent", "error", detail)}
    return {"tiles_ready": True, "preprocessing_version": "v1-cloudmask-normalize-tile", "step": "preprocessing",
            "log": log(state, "preprocessing_agent", "ok", detail)}


def dl_analysis_agent(state: PipelineState) -> dict:
    """04 DL Analysis Agent — runs the change model, outputs regions + metadata."""
    change_frac, regions = tools.run_change_detection(random.Random(f"{state['scene_before_id']}-{state['scene_after_id']}"))
    schema.check(schema.validate_evidence({"change_frac": change_frac, "regions": regions}), "DL analysis output")
    return {"change_frac": change_frac, "regions": regions, "model_version": "threshold-baseline-v1", "step": "dl_analysis",
            "log": log(state, "dl_analysis_agent", "ok", f"{len(regions)} regions, change_frac={change_frac}")}


def geovlm_agent(state: PipelineState) -> dict:
    """05 Geo-VLM Agent — grounded claims over prepared evidence.

    Calls webapp/backend/report.py (via webapp_bridge), the same function that answers
    the web app's AI-report panel, so the two can never drift apart."""
    ev = {"pair_id": f"{state['scene_before_id']}__{state['scene_after_id']}",
          "dates": [state["date_before"], state["date_after"]], "source": state["model_version"],
          "change_frac": state["change_frac"], "regions": state["regions"]}
    rep = webapp_bridge.build_report(ev, state["condition"])
    return {"claims": rep["claims"], "abstain": rep["abstain"], "raw_output": rep.get("raw_output"),
            "prompt_version": f"{state['condition']}_v1", "step": "geovlm",
            "log": log(state, "geovlm_agent", "ok", f"{len(rep['claims'])} claims {rep['counts']}, {len(rep['abstain'])} abstentions")}


def _region_polygon(r: dict, seed_key: str) -> dict:
    """MOCK geometry: a small square inside the AOI so the map has something to draw.
    Phase 6 replaces this with the real vectorized polygon from the change model."""
    w, s, e, n = AOI_BOUNDS
    rng = random.Random(seed_key)
    cx, cy = rng.uniform(w + 0.02, e - 0.02), rng.uniform(s + 0.02, n - 0.02)
    half = min(0.015, max(0.004, (r["area_ha"] / 24830) ** 0.5 * 0.1))
    ring = [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half]]
    return {"type": "Polygon", "coordinates": [ring]}


def publishing_agent(state: PipelineState) -> dict:
    """06 Publishing Agent — package GeoJSON + metadata + report for the WebGIS.

    With publish_live=True it also writes into the web app's live data store
    (webapp/backend/data/); refresh the browser to see the run."""
    schema.check([e for r in state["regions"] for e in schema.validate_region(r)], "published change regions")
    geojson ={"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": index,
        "properties": {**region, "date_before": state["date_before"], "date_after": state["date_after"], "source": state["model_version"]},
        "geometry": _region_polygon(region, f"{state['scene_before_id']}-{region['id']}"),
    } for index, region in enumerate(state["regions"])]}
    schema.check(schema.validate_change_regions(geojson), "published change regions")
    w, s, e, n = AOI_BOUNDS
    aoi_geojson = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": f"{state['aoi_name']} (agent pipeline run)", "source": "agents"},
        "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
    }]}
    report = {key: state[key] for key in ("condition", "model_version", "prompt_version", "scene_before_id", "scene_after_id",
                                          "preprocessing_version", "change_frac", "claims", "abstain")}
    report["model"] = report.pop("model_version")
    detail = "packaged GeoJSON + report"
    if state.get("publish_live"):
        webapp_bridge.write_live_data(aoi_geojson, geojson)
        detail += f" and wrote to {webapp_bridge.DATA_DIR} (refresh the web app to see it)"
    return {"published_geojson": geojson, "published_report": report, "status": "done", "step": "publishing",
            "log": log(state, "publishing_agent", "ok", detail)}
