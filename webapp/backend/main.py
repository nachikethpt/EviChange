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

from agents import ee_engine, vlm_check
from agents.vlm_client import VLMClient, VLMUnavailable
from agents.graph import run_pipeline
from agents.schema import CHANGE_TYPES, CONDITIONS, CONF_MIN, T_IDX, validate_aoi, validate_windows

from . import data_store
from .report import build_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

CODE_VERSION = "phase6-v4"  # bump when pipeline or detector logic changes, invalidates cache
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


vlm = VLMClient()
_vlm_checks: dict = {}           # check key -> result; filled from the answer log on first use
_vlm_log_loaded = False
LOG_ONLY_FIELDS = ("key", "time", "run_id", "bbox", "seconds")


def _cached_check(key: str) -> Optional[dict]:
    """A result for this check key from this session or, after a restart, from the answer log."""
    global _vlm_log_loaded
    if not _vlm_log_loaded:
        for rec in vlm_check.read_log():
            result = {k: v for k, v in rec.items() if k not in LOG_ONLY_FIELDS}
            result["raw"] = (result.get("raw") or "")[:1000]
            _vlm_checks[rec["key"]] = {**result, "from_log": True}
        _vlm_log_loaded = True
    return _vlm_checks.get(key)


@app.get("/api/vlm/status")
def vlm_status():
    """Whether a Geo-VLM server is reachable (see notebooks/EviChange_vlm_server.ipynb).
    Always asks the server afresh: the app calls this on start-up and on "Retry connection"."""
    vlm._status = None
    return {**vlm.status(), "labelled_sites_locked": not vlm_check.LABELLED_SITES_UNLOCKED,
            "prompt_version": vlm_check.prompt_version(vlm_check.DEFAULT_CHIP_SET),
            "chip_sets": list(vlm_check.CHIP_SETS), "default_chips": vlm_check.DEFAULT_CHIP_SET}


class VLMCheckRequest(BaseModel):
    region_id: str
    run_id: Optional[str] = None
    chips: Optional[str] = None          # a vlm_check.CHIP_SETS key; default VLM_CHIPS / rgb_swir


@app.post("/api/vlm/check")
def vlm_check_region(req: VLMCheckRequest):
    """D7 candidate check for one region: before/after chips -> Geo-VLM -> verdict, compared with
    the detector. One region per request so the app can show progress; results are cached."""
    _require_valid_run(req.run_id)
    chip_set = req.chips or vlm_check.DEFAULT_CHIP_SET
    if chip_set not in vlm_check.CHIP_SETS:
        raise HTTPException(400, f"chips must be one of {list(vlm_check.CHIP_SETS)}")
    version = vlm_check.prompt_version(chip_set)
    fc = data_store.get_change_regions(req.run_id)
    feature = next((f for f in fc["features"] if f["properties"]["id"] == req.region_id), None)
    if feature is None:
        raise HTTPException(404, f"unknown region id: {req.region_id}")
    bbox = _bbox(feature["geometry"])
    if vlm_check.touches_labelled_site(bbox):
        return {"region_id": req.region_id, "status": "blocked",
                "detail": "Overlaps a labelled evaluation site: not sent to the model until the Phase 4 prompts are frozen."}
    params = data_store.analysis_params(req.run_id)
    if params is None:
        raise HTTPException(404, "these change regions have no Earth Engine analysis behind them (demo data)")
    status = vlm.status()
    if not status["available"]:
        raise HTTPException(503, status["detail"])
    key = vlm_check.check_key(params, req.region_id, version, status["model"])
    cached = _cached_check(key)
    if cached:
        return cached
    t0 = time.time()
    try:
        chips = ee_engine.region_chips(params["aoi"], params["before_window"], params["after_window"],
                                       params["max_cloud_pct"], bbox, kinds=vlm_check.chip_kinds(chip_set))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Earth Engine: {exc}")
    prompt = vlm_check.build_prompt(params["before_window"], params["after_window"], chip_set)
    images = [chips[k] for k in vlm_check.chip_keys(chip_set)]
    try:
        out = vlm.generate(prompt, images, replay_key=f"{version}:{req.region_id}")
    except VLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    answer = vlm_check.parse_answer(out["text"])
    result = {"region_id": req.region_id, "status": "checked", **answer,
              **vlm_check.compare(answer, feature["properties"]),
              "model": out["model"], "prompt_version": version, "chips": chip_set, "raw": out["text"][:1000],
              "before_window": params["before_window"], "after_window": params["after_window"]}
    if vlm.mode != "replay":   # replayed answers are already recorded somewhere
        vlm_check.log_check({"key": key, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run_id": req.run_id,
                             "bbox": [round(v, 6) for v in bbox], "seconds": round(time.time() - t0, 1),
                             **result, "raw": out["text"]})   # full text in the log, for replays
    _vlm_checks[key] = result
    return result


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


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