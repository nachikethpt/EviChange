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
import urllib.parse
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import ee_engine, landcover, monthly, search_spec, shoreline, ungated, vlm_check
from agents.gpt_client import GPTClient
from agents.vlm_client import VLMClient, VLMUnavailable
from agents.graph import run_pipeline
from agents.study import REPO_ROOT, load_study_config
from agents.schema import CHANGE_TYPES, CONDITIONS, CONF_MIN, REPORT_CONDITIONS, T_IDX, validate_aoi, validate_windows

from . import data_store
from .report import build_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

CODE_VERSION = "phase6-v5"  # bump when pipeline or detector logic changes, invalidates cache (v5: D10 classes)
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
    """Change regions; land-cover classes (D10) are hidden at the labelled sites until Phase 14."""
    _require_valid_run(run_id)
    return landcover.hide_at_labelled_sites(data_store.get_change_regions(run_id))


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


# ---------- Phase 10 (D11): monthly time series of the QN AOI ----------
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_monthly_tiles: dict = {}


def _monthly_summary() -> dict:
    summary = monthly.load(monthly.SUMMARY_FILE)
    if summary is None:
        raise HTTPException(404, "no monthly time series yet: run scripts/make_monthly.py")
    return summary


@app.get("/api/monthly")
def monthly_summary():
    """Per month: scene counts, share seen clear, Dynamic World cover / class areas (gaps as null),
    water area, change vs the previous month and the first month. See agents/monthly.py."""
    return _monthly_summary()


@app.get("/api/monthly/layer")
def monthly_layer(month: str, layer: str, vs: Literal["base", "prev"] = "base"):
    """XYZ tiles for one month: class, water, clear, or water_change / class_change against the first
    month (vs=base) or the previous month (vs=prev). Class layers are masked at the labelled sites (D10)."""
    if not _MONTH_RE.match(month) or layer not in monthly.LAYERS:
        raise HTTPException(400, f"month must be YYYY-MM, layer one of {monthly.LAYERS}")
    summary = _monthly_summary()
    row = monthly.month_row(summary, month)
    if row is None:
        raise HTTPException(404, f"{month} is outside the series {summary['period']}")
    ref_key = None
    if layer.endswith("_change"):
        ref_key = summary["baseline"] if vs == "base" else monthly.previous_month(month)
        if ref_key == month or monthly.month_row(summary, ref_key) is None:
            raise HTTPException(404, f"nothing to compare {month} with (vs={vs})")
    gap = ((layer in ("class", "class_change") and row["dw_images"] == 0)
           or (layer in ("water", "water_change") and not row["s1_thresholds_db"]))
    if gap:
        raise HTTPException(404, f"no {layer.split('_')[0]} data in {month}: shown as a gap")
    key = (month, layer, ref_key)
    hit = _monthly_tiles.get(key)
    if hit and time.time() - hit[0] < INDEX_TILE_TTL_S:
        return hit[1]
    windows = {k: (k, s, e) for k, s, e in monthly.month_windows(*summary["period"])}
    ref_row = monthly.month_row(summary, ref_key) if ref_key else None
    try:
        out = monthly.tile_layer(load_study_config()["aoi"], windows[month], layer, windows.get(ref_key),
                                 row["s1_thresholds_db"], ref_row and ref_row["s1_thresholds_db"])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Earth Engine: {exc}")
    out.update(month=month, layer=layer, ref=ref_key)
    _monthly_tiles[key] = (time.time(), out)
    return out


_hidden_ids: dict = {}


def _class_locked_ids(regions_file: str) -> set:
    """Region ids whose classes are hidden at the labelled sites (D10), for the monthly class series."""
    if regions_file not in _hidden_ids:
        path = REPO_ROOT / regions_file
        fc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"features": []}
        _hidden_ids[regions_file] = {f["properties"]["id"] for f in landcover.hide_at_labelled_sites(fc)["features"]
                                     if f["properties"].get("class_hidden")}
    return _hidden_ids[regions_file]


@app.get("/api/monthly/regions/{region_id}")
def monthly_region(region_id: str):
    """One change region's monthly series: Dynamic World class (null in gaps), water share, share seen clear."""
    series = monthly.load(monthly.REGIONS_FILE)
    if series is None:
        raise HTTPException(404, "no monthly region series yet: run scripts/make_monthly.py")
    if region_id not in series["regions"]:
        raise HTTPException(404, f"unknown region id: {region_id}")
    locked = _class_locked_ids(series.get("regions_file", ""))
    one = monthly.hide_classes({"regions": {region_id: series["regions"][region_id]}}, locked)
    return {"id": region_id, "months": series["months"], **one["regions"][region_id]}



vlm = VLMClient()
gpt = GPTClient()                # ungated GPT arm (D16); off unless EVICHANGE_GPT=http
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
    try:
        result, record = vlm_check.check(vlm, params, feature["properties"], bbox, chip_set, chips, req.run_id, t0)
    except VLMUnavailable as exc:
        raise HTTPException(503, str(exc))
    if vlm.mode != "replay":   # replayed answers are already recorded somewhere
        vlm_check.log_check(record)
    _vlm_checks[key] = result
    return result


class SearchSpecRequest(BaseModel):
    prompt: str


@app.post("/api/search_spec")
def search_spec_endpoint(req: SearchSpecRequest):
    """D7 step 1: a typed request -> a validated SearchSpec from the Geo-VLM (text only, no images).
    503 when no model is reachable and 200 with status "invalid" when the answer is unusable;
    in both cases the app falls back to its keyword parser."""
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    status = vlm.status()
    if not status["available"]:
        raise HTTPException(503, status["detail"])
    try:
        return search_spec.spec_from_prompt(vlm, req.prompt)
    except VLMUnavailable as exc:
        raise HTTPException(503, str(exc))


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


class ReportRequest(BaseModel):
    region_ids: List[str]
    condition: Literal[REPORT_CONDITIONS] = "gated"
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
    if req.condition == "ungated_gpt":
        return _ungated_gpt_report(req, ev)
    return build_report(ev, req.condition)


_ungated_gpt_runs: dict = {}     # (run, selection, prompt versions, models) -> run_ungated() output


def _ungated_gpt_report(req: ReportRequest, ev: dict) -> dict:
    """D16: GPT writes free text from the selection's chips, the Geo-VLM splits it into claims, and the
    verifier checks them against the same evidence as the other arms. Anything missing -> not_run."""
    def not_run(detail: str) -> dict:
        return {**build_report(ev, "ungated_gpt"), "detail": detail}
    fc = data_store.get_change_regions(req.run_id)
    geoms = [f["geometry"] for f in fc["features"] if f["properties"]["id"] in set(req.region_ids)]
    if not geoms:
        return not_run("No regions selected.")
    boxes = [_bbox(g) for g in geoms]
    bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    if vlm_check.touches_labelled_site(bbox):
        return not_run("Overlaps a labelled evaluation site: not sent to any model until the Phase 4 prompts are frozen.")
    params = data_store.analysis_params(req.run_id)
    if params is None:
        return not_run("These change regions have no Earth Engine analysis behind them (demo data).")
    for name, client in (("GPT", gpt), ("Geo-VLM (claim extractor)", vlm)):
        status = client.status()
        if not status["available"]:
            return not_run(f"{name} unavailable: {status['detail']}")
    chip_set = vlm_check.DEFAULT_CHIP_SET
    sel = ",".join(sorted(req.region_ids))
    key = (req.run_id, sel, ungated.REPORT_PROMPT_VERSION, ungated.EXTRACT_PROMPT_VERSION, chip_set,
           gpt.status()["model"], vlm.status()["model"])
    if key not in _ungated_gpt_runs:
        try:
            chips = ee_engine.region_chips(params["aoi"], params["before_window"], params["after_window"],
                                           params["max_cloud_pct"], bbox, kinds=vlm_check.chip_kinds(chip_set))
        except Exception as exc:
            return not_run(f"Earth Engine: {exc}")
        try:
            _ungated_gpt_runs[key] = ungated.run_ungated(
                gpt, vlm, "ungated_gpt", sel, params["before_window"], params["after_window"],
                [chips[k] for k in vlm_check.chip_keys(chip_set)], chip_set)
        except VLMUnavailable as exc:
            return not_run(str(exc))
    return build_report(ev, "ungated_gpt", ungated=_ungated_gpt_runs[key])


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


@app.get("/api/runs")
def list_runs():
    """All stored runs, newest first, so the app can reopen or delete an earlier one."""
    return data_store.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    _require_valid_run(run_id)
    return data_store.get_status(run_id)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    """Delete a finished or failed run. A queued or running run is refused (409): the background
    worker still holds it and would crash writing its status into a missing folder."""
    _require_valid_run(run_id)
    if data_store.get_status(run_id)["status"] in ("queued", "running"):
        raise HTTPException(409, "run is still in progress; wait for it to finish before deleting it")
    data_store.delete_run(run_id)
    return {"deleted": run_id}


@app.get("/api/geocode")
def geocode(q: str):
    """Place-name search for the AOI picker (OpenStreetMap Nominatim, proxied so the request carries the
    User-Agent its usage policy asks for). Returns [{name, lon, lat, bbox: [w, s, e, n]}]."""
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(400, "type at least 2 characters")
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 6})
    req = urllib.request.Request(url, headers={"User-Agent": "EviChange-GIS/0.1 (research project)"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            hits = json.load(resp)
    except Exception as exc:
        raise HTTPException(502, f"place search is unavailable: {exc}")
    out = []
    for h in hits:
        try:
            s, n, w, e = (float(v) for v in h["boundingbox"])     # Nominatim order: south, north, west, east
            out.append({"name": h["display_name"], "lon": float(h["lon"]), "lat": float(h["lat"]), "bbox": [w, s, e, n]})
        except (KeyError, ValueError, TypeError):
            continue
    return out


# ---------- Phase 11 (D11): shoreline change ----------
def _shoreline(name: str) -> Any:
    data = shoreline.load(name)
    if data is None:
        raise HTTPException(404, "no shoreline analysis yet: run scripts/make_shoreline.py")
    return data


@app.get("/api/shoreline")
def shoreline_summary():
    """Transect counts by trend (advancing / retreating / stable), baseline length, fastest rates and
    the method. See agents/shoreline.py."""
    return _shoreline("summary.json")


@app.get("/api/shoreline/transects")
def shoreline_transects(change: Optional[str] = None, trend: Optional[str] = None):
    """Transects as GeoJSON lines with their rate (lrr m/yr, seaward +), 95 % CI, net movement, the radar
    `trend` and the reported `change` (radar trend confirmed by the optical dry-season shoreline, else
    "unconfirmed"). Filter with ?change= or ?trend=."""
    fc = _shoreline("transects.geojson")
    fc = shoreline.hide_transects(fc, shoreline.hidden_transects(fc))
    feats = fc["features"]
    if change:
        feats = [f for f in feats if f["properties"].get("change") == change]
    if trend:
        feats = [f for f in feats if f["properties"]["trend"] == trend]
    return {**fc, "features": feats}


@app.get("/api/shoreline/baseline")
def shoreline_baseline():
    return _shoreline("baseline.geojson")


@app.get("/api/shoreline/lines")
def shoreline_lines(month: Optional[str] = None, kind: Optional[Literal["month", "quarter"]] = None):
    """Extracted shorelines: one MultiLineString per month (kind=month; move with the tide) and per
    quarter (kind=quarter; tide-averaged, the lines the rates come from). ?month=YYYY-MM picks one month."""
    transects = _shoreline("transects.geojson")
    fc = shoreline.hide_lines(_shoreline("shorelines.geojson"), transects, shoreline.hidden_transects(transects))
    feats = fc["features"]
    if kind:
        feats = [f for f in feats if f["properties"].get("kind", "month") == kind]
    if month:
        if not _MONTH_RE.match(month):
            raise HTTPException(400, "month must be YYYY-MM")
        feats = [f for f in feats if f["properties"].get("month") == month]
        if not feats:
            raise HTTPException(404, f"no shoreline for {month}")
    return {**fc, "features": feats}


@app.get("/api/shoreline/transects/{tid}")
def shoreline_transect(tid: str):
    """One transect's positions (m from the baseline, seaward +; null = none): monthly (tide-affected)
    and quarterly (tide-averaged, the rate is fitted to these)."""
    pos = _shoreline("positions.json")
    if tid not in pos["positions"]:
        raise HTTPException(404, f"unknown transect {tid}")
    transects = _shoreline("transects.geojson")
    feat = next(f for f in transects["features"] if f["id"] == tid)
    if tid in shoreline.hidden_transects(transects):          # Phase 14 reference transect: blind until digitised
        return {**shoreline.hide_transects({"features": [feat]}, {tid})["features"][0]["properties"],
                "geometry": feat["geometry"], "series": None, "quarterly": None}
    return {**feat["properties"], "geometry": feat["geometry"],
            "series": [{"month": m, "pos": p} for m, p in zip(pos["months"], pos["positions"][tid])],
            "quarterly": [{"quarter": q, "pos": p} for q, p in zip(pos.get("quarters", []), pos.get("quarter_positions", {}).get(tid, []))]}


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")