# EviChange

Evidence-gated interpretation of bi-temporal Sentinel-2 imagery. Validated on a
self-labelled Quang Ninh (Vietnam) case study; the app runs on any AOI (unvalidated there).
It compares three ways of generating claims about detected land-cover change
(template / ungated VLM / evidence-gated VLM) by how many unsupported claims reach the user.

```
agents/      6-agent LangGraph pipeline + the shared contract
  schema.py    regions, evidence, claims, verdicts, thresholds (the ONE definition)
  verifier.py  deterministic claim verifier with reason codes
webapp/      FastAPI + MapLibre web GIS; backend/report.py = the ONE claim generator
notebooks/   Colab: Earth Engine acquisition, ground-truth labeling, Qwen2.5-VL claims
             (the Person2 notebook's OSCD cells are obsolete; its Qwen cells are reused in Phase 4)
scripts/     ee_smoke_test.py
docs/        PLAN.md (phases, evaluation plan), decisions.md (design records)
legacy/      deprecated old-schema files, not imported
```

The pipeline's Geo-VLM Agent and the web app's AI-report panel call the same
`report.build_report()` (via `agents/webapp_bridge.py`), so they cannot drift apart.

## Setup (Windows)

Double-click `setup_windows.bat` once. Or manually:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

## Run (always from the repo root)

| What | Command |
|---|---|
| Tests | `.venv\Scripts\python.exe -m pytest -q` |
| Pipeline demo (prints every handoff) | `.venv\Scripts\python.exe run_demo.py` |
| Pipeline → live map | `run_pipeline_windows.bat` (or `python run_and_publish.py --condition gated`) |
| Web app | `run_webapp_windows.bat` → http://localhost:8000 |
| Import a real Earth Engine export | `python import_geojson.py path\to\change_regions.json` |
| Earth Engine check | `pip install -r requirements-ee.txt`, then `python scripts/ee_smoke_test.py --project <id>` |

Delete `webapp/backend/data/` to return the map to the built-in demo data.

The pipeline defaults to a deterministic offline detector. Set
`EVICHANGE_ENGINE=ee` and `EE_PROJECT=<project-id>` after running
`earthengine authenticate` to use `agents/ee_engine.py` with Sentinel-2 SR.
The real Quang Ninh export is created after Earth Engine access is verified.
