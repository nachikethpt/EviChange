"""EviChange GIS — backend (FastAPI).

Run from the repo root:
    python -m uvicorn webapp.backend.main:app --reload
then open http://localhost:8000

Data comes from data_store.py: demo data until the multi-agent pipeline (../agents)
or Person 1's real Earth Engine export has written backend/data/change_regions.json,
then automatically switches to that — no code change needed.

Phase 6: POST /api/runs and GET /api/runs/{id} run the agent pipeline on demand,
as a background job, against an arbitrary AOI + date range.
"""
import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.graph import run_pipeline

from . import data_store
from .aoi_validation import validate_aoi
from .report import build_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

CODE_VERSION = "phase6-v1"  # bump when pipeline logic changes, invalidates cache
run_queue: asyncio.Queue = asyncio.Queue()


async def _worker():
    while True:
        run_id, aoi, date_before, date_after, condition = await run_queue.get()
        data_store.update_status(run_id, status="running", progress=0.1)
        try:
            state = await asyncio.to_thread(
                run_pipeline, "on-demand", aoi, date_before, date_after, condition, 3, False
            )
            if state.get("status") == "failed":
                data_store.update_status(run_id, status="error", error=state.get("error", "pipeline failed"))
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
def layers():
    """The operational layers the map loads on start. Person 1/3: add real layers here."""
    label = "Detected change regions" if data_store.is_live_data() else "Detected change regions (DEMO)"
    return [
        {"id": "aoi", "name": "Study area (AOI)", "kind": "geojson", "url": "/api/data/aoi", "style": "outline"},
        {"id": "change", "name": label, "kind": "geojson", "url": "/api/data/change_regions", "style": "confidence"},
    ]


@app.get("/api/data/aoi")
def aoi():
    return data_store.get_aoi()


@app.get("/api/data/change_regions")
def change_regions():
    return data_store.get_change_regions()


class ReportRequest(BaseModel):
    region_ids: List[str]
    condition: Literal["template", "ungated", "gated"] = "gated"


@app.post("/api/report")
def report(req: ReportRequest):
    """Person 2's endpoint: selected change regions -> claims with verdicts and abstentions."""
    known = data_store.known_region_ids()
    unknown = [r for r in req.region_ids if r not in known]
    if unknown:
        raise HTTPException(400, f"unknown region ids: {unknown}")
    ev = data_store.evidence_for(req.region_ids)
    return build_report(ev, req.condition)


class RunRequest(BaseModel):
    aoi: dict
    date_before: str
    date_after: str
    condition: str = "gated"


@app.post("/api/runs", status_code=202)
def create_run(req: RunRequest):
    errors = validate_aoi(req.aoi)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    if req.date_after <= req.date_before:
        raise HTTPException(400, "date_after must be later than date_before")

    key = data_store.cache_key(req.aoi, req.date_before, req.date_after, req.condition, CODE_VERSION)
    cached = data_store.find_cached_run(key)
    if cached:
        return {"run_id": cached, "status": "done", "cached": True}

    run_id = uuid.uuid4().hex[:12]
    data_store.create_run(run_id, req.aoi, req.date_before, req.date_after, req.condition, CODE_VERSION)
    data_store.update_status(run_id, cache_key=key)
    run_queue.put_nowait((run_id, req.aoi, req.date_before, req.date_after, req.condition))
    return {"run_id": run_id, "status": "queued", "cached": False}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    status = data_store.get_status(run_id)
    if status is None:
        raise HTTPException(404, "unknown run id")
    return status


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")