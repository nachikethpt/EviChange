"""The six independent nodes in the EviChange pipeline."""
from __future__ import annotations

import random

from . import tools
from .state import PipelineState, log


def orchestrator(state: PipelineState) -> dict:
    attempt = state.get("attempt", 0) + 1
    updates = {"attempt": attempt, "status": "running", "step": "orchestrator"}
    if state["task"] != "change_detection":
        return {**updates, "status": "failed", "error": "unapproved task", "log": log(state, "orchestrator", "error", "unapproved task")}
    if state["condition"] not in {"template", "ungated", "gated"}:
        return {**updates, "status": "failed", "error": "unapproved claim condition", "log": log(state, "orchestrator", "error", "unapproved claim condition")}
    return {**updates, "log": log(state, "orchestrator", "ok", f"attempt {attempt}/{state['max_attempts']}")}


def ingestion_agent(state: PipelineState) -> dict:
    rng = random.Random(f"{state['aoi_name']}-{state['attempt']}")
    scenes = tools.query_scenes(state["aoi"], state["date_before"], state["date_after"], 30, rng)
    return {**scenes, "step": "ingestion", "log": log(state, "ingestion_agent", "ok", f"{scenes['scene_before_id']}; {scenes['scene_after_id']}")}


def preprocessing_agent(state: PipelineState) -> dict:
    ok, detail = tools.run_preprocessing(state["cloud_pct_before"], state["cloud_pct_after"], 30)
    if not ok:
        return {"tiles_ready": False, "step": "preprocessing", "log": log(state, "preprocessing_agent", "error", detail)}
    return {"tiles_ready": True, "preprocessing_version": "v1-cloudmask-normalize-tile", "step": "preprocessing", "log": log(state, "preprocessing_agent", "ok", detail)}


def dl_analysis_agent(state: PipelineState) -> dict:
    change_frac, regions = tools.run_change_detection(random.Random(f"{state['scene_before_id']}-{state['scene_after_id']}"))
    return {"change_frac": change_frac, "regions": regions, "model_version": "threshold-baseline-v1", "step": "dl_analysis", "log": log(state, "dl_analysis_agent", "ok", f"{len(regions)} regions")}


def geovlm_agent(state: PipelineState) -> dict:
    claims, abstain, raw_output = tools.build_claims(state["regions"], state["condition"])
    return {"claims": claims, "abstain": abstain, "raw_output": raw_output, "prompt_version": f"{state['condition']}_v1", "step": "geovlm", "log": log(state, "geovlm_agent", "ok", f"{len(claims)} claims")}


def publishing_agent(state: PipelineState) -> dict:
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": index, "properties": {**region, "date_before": state["date_before"], "date_after": state["date_after"], "source": state["model_version"]}, "geometry": {"type": "Point", "coordinates": [0, 0]}} for index, region in enumerate(state["regions"])]}
    report = {key: state[key] for key in ("condition", "model_version", "prompt_version", "scene_before_id", "scene_after_id", "preprocessing_version", "change_frac", "claims", "abstain")}
    report["model"] = report.pop("model_version")
    return {"published_geojson": geojson, "published_report": report, "status": "done", "step": "publishing", "log": log(state, "publishing_agent", "ok", "packaged GeoJSON + report")}
