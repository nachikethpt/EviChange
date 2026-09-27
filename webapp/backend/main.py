"""EviChange GIS — backend (FastAPI).

Run from the repo root:
    python -m uvicorn webapp.backend.main:app --reload
then open http://localhost:8000

Data comes from data_store.py: demo data until the multi-agent pipeline (../agents)
or Person 1's real Earth Engine export has written backend/data/change_regions.json,
then automatically switches to that — no code change needed.
"""
from pathlib import Path
from typing import List, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import data_store
from .report import build_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="EviChange GIS API", version="0.1.0")


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


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
