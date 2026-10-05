"""EviChange GIS — backend (FastAPI).

Run from the repo root:
    python -m uvicorn webapp.backend.main:app --reload
then open http://localhost:8000

Data comes from data_store.py: demo data until the multi-agent pipeline (../agents)
or Person 1's real Earth Engine export has written backend/data/change_regions.json,
then automatically switches to that — no code change needed.

Phase 6: POST /api/runs and GET /api/runs/{id} run the agent pipeline on demand,
as a background job, against an arbitrary AOI + before/after date windows
([start, end] each, validated by schema.validate_windows). Existing /api/data/*,
/api/layers and /api/report endpoints now accept an optional run_id so they can
serve a specific run's results instead of only the demo/global data.

Validation, per review: condition is checked against schema.CONDITIONS before
queueing (not left to fail inside the background job); any run_id coming from
a request is checked against the 12-char hex format the server generates
(rejects path-traversal-shaped input) and checked to actually exist (a typo'd
run_id returns 404, not a silent fall-through to demo data).
"""
import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import ee_engine
from agents.graph import run_pipeline
from agents.schema import CHANGE_TYPES, CONDITIONS, CONF_MIN, T_IDX, validate_aoi, validate_windows

from . import data_store
from .report import build_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

CODE_VERSION = "phase6-v2"  # bump when pipeline logic changes, invalidates cache
run_queue: asyncio.Queue = asyncio.Queue()

_RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _require_valid_run(run_id: Optional[str]) -> None:
    """Reject malformed run ids (path-traversal shaped) and unknown ones (would
    otherwise silently fall back to demo data instead of erroring)."""
    if run_id is None:
        return
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(400, "run_id must be a 12-character hex id")
    if data_store.get_status(run_id) is None:
        raise HTTPException(404, f"unknown run id: {run_id}")


async def _worker():
    while True:
        run_id, aoi, before_window, after_window, condition = await run_queue.get()
        data_store.update_status(run_id, status="running", progress=0.1)
        try:
            state = await asyncio.to_thread(
                run_pipeline, run_id, aoi, before_window, after_window, condition, 3, False
            )
            if state.get("status") == "failed":
                last_log = state.get("log", [])[-1] if state.get("log") else {}
                reason = state.get("error") or last_log.get("detail") or "pipeline failed"
                data_store.update_status(run_id, status="error", error=reason)
            else:
                data_store.write_run_result(run_id, {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {"name": "on-demand AOI"}, "geometry": aoi}],
                }, state["published_geojson"], state["published_report"])
                data_store.update_status(run_id, status="done", progress=1.0)
        except Exception as exc:
            data_store.update_status(run_id, status="error", error=str(exc))
        run_queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_worker())
    yield


app = FastAPI(title="EviChange GIS API", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "live_data": data_store.is_live_data()}


@app.get("/api/layers")
def layers(run_id: Optional[str] = None):
    """The operational layers the map loads on start. Pass run_id to point at a specific run's results."""
    _require_valid_run(run_id)
    label = "Detected change regions" if data_store.is_live_data(run_id) else "Detected change regions (DEMO)"
    suffix = f"?run_id={run_id}" if run_id else ""
    return [
        {"id": "aoi", "name": "Study area (AOI)", "kind": "geojson", "url": f"/api/data/aoi{suffix}", "style": "outline"},
        {"id": "change", "name": label, "kind": "geojson", "url": f"/api/data/change_regions{suffix}", "style": "confidence"},
    ]


@app.get("/api/change_types")
def change_types():
    """The change-type rules from agents/schema.py, so the map colours regions exactly as the verifier reads them."""
    return {"t_idx": T_IDX, "conf_min": CONF_MIN,
            "types": {k: {"field": field, "sign": sign, "label": label} for k, (field, sign, label) in CHANGE_TYPES.items()}}


@app.get("/api/data/aoi")
def aoi(run_id: Optional[str] = None):
    _require_valid_run(run_id)
    return data_store.get_aoi(run_id)


@app.get("/api/data/change_regions")
def change_regions(run_id: Optional[str] = None):
    _require_valid_run(run_id)
    return data_store.get_change_regions(run_id)


INDEX_TILE_TTL_S = 3600   # Earth Engine map ids expire after a few hours
_index_tiles: dict = {}


@app.get("/api/index_layer")
def index_layer(index: str, kind: str, run_id: Optional[str] = None):
    """Phase 7b (D8): XYZ tiles for an index raster (NDVI / NDBI / MNDWI; before / after / change)
    over the AOI and windows the shown regions were computed from."""
    _require_valid_run(run_id)
    if index not in ee_engine.INDEX_NAMES or kind not in ee_engine.INDEX_KINDS:
        raise HTTPException(400, f"index must be one of {ee_engine.INDEX_NAMES}, kind one of {ee_engine.INDEX_KINDS}")
    params = data_store.analysis_params(run_id)
    if params is None:
        raise HTTPException(404, "these change regions have no Earth Engine analysis behind them (demo data)")
    key = (json.dumps(params, sort_keys=True), index, kind)
    hit = _index_tiles.get(key)
    if hit and time.time() - hit[0] < INDEX_TILE_TTL_S:
        return hit[1]
    try:
        layer = ee_engine.index_tile_layer(params["aoi"], params["before_window"], params["after_window"],
                                           index, kind, params["max_cloud_pct"])
    except RuntimeError as exc:       # earthengine-api missing
        raise HTTPException(503, str(exc))
    except Exception as exc:          # auth, quota, no scenes, ...
        raise HTTPException(502, f"Earth Engine: {exc}")
    layer.update(index=index, kind=kind, before_window=params["before_window"], after_window=params["after_window"])
    _index_tiles[key] = (time.time(), layer)
    return layer


class ReportRequest(BaseModel):
    region_ids: List[str]
    condition: Literal["template", "ungated", "gated"] = "gated"
    run_id: Optional[str] = None


@app.post("/api/report")
def report(req: ReportRequest):
    """Person 2's endpoint: selected change regions -> claims with verdicts and abstentions."""
    _require_valid_run(req.run_id)
    known = data_store.known_region_ids(req.run_id)
    unknown = [r for r in req.region_ids if r not in known]
    if unknown:
        raise HTTPException(400, f"unknown region ids: {unknown}")
    ev = data_store.evidence_for(req.region_ids, req.run_id)
    return build_report(ev, req.condition)


class RunRequest(BaseModel):
    aoi: dict
    before_window: List[str]   # [start, end], ISO dates
    after_window: List[str]
    condition: str = "gated"


@app.post("/api/runs", status_code=202)
def create_run(req: RunRequest):
    if req.condition not in CONDITIONS:
        raise HTTPException(400, f"condition must be one of {CONDITIONS}, got {req.condition!r}")

    # Same checks the pipeline applies, so a bad request fails here with a clear message
    # instead of inside the background job.
    errors = validate_aoi(req.aoi) + validate_windows(req.before_window, req.after_window)
    if errors:
        raise HTTPException(400, "; ".join(errors))

    key = data_store.cache_key(req.aoi, req.before_window, req.after_window, req.condition, CODE_VERSION)
    cached = data_store.find_cached_run(key)
    if cached:
        return {"run_id": cached, "status": "done", "cached": True}

    run_id = uuid.uuid4().hex[:12]
    data_store.create_run(run_id, req.aoi, req.before_window, req.after_window, req.condition, CODE_VERSION)
    data_store.update_status(run_id, cache_key=key)
    run_queue.put_nowait((run_id, req.aoi, req.before_window, req.after_window, req.condition))
    return {"run_id": run_id, "status": "queued", "cached": False}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    _require_valid_run(run_id)
    return data_store.get_status(run_id)


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")