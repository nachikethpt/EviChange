# EviChange

Evidence-gated interpretation of satellite change, validated on a self-labelled Quang Ninh (Vietnam)
case study; the app runs on any AOI (unvalidated there). Two strands, sharing one data contract:

- **Evidence-gated claims.** A Geo-VLM (Qwen2.5-VL-7B) describes detected land-cover change. Four arms
  (template, ungated, evidence-gated, ungated GPT; a fine-tuned gated arm if Phase 4b lands) are compared on
  30 blind-labelled sites by how many false or unsupported claims reach the user (`docs/analysis_plan.md`).
- **Coast and time series** (teacher feedback, D10–D14): Dynamic World classes, monthly maps,
  shoreline change on 735 transects (yearly 2015–2026 and monthly 2024–2026, Sentinel-1 tide-averaged with
  optical and Planet 3 m checks), buildings near the shore, CCDC month of change.

Where things stand: `docs/PLAN.md`. Why things are the way they are: `docs/decisions.md` (D1–D19).

```
agents/        pipeline, Earth Engine analyses and the shared contract
  schema.py      regions, evidence, claims, verdicts, thresholds (the ONE definition)
  verifier.py    deterministic claim verifier with reason codes (nli_verifier.py: learned one, for the ablation)
  gated.py, ungated.py, gpt_client.py, vlm_client.py   report arms and model clients (prompts frozen, D19)
  site_evidence.py   the box evidence every arm is verified against
  ee_engine.py, landcover.py, monthly.py, shoreline.py, coastal.py, ccdc.py, planet.py   Earth Engine analyses
  labels14.py    Phase 14 ground-truth samples and the blind-labelling locks
  nodes.py, graph.py, state.py, tools.py   6-agent LangGraph pipeline
eval/          adjudication.py (blinded claim queue, agreement, join), metrics.py (all evaluation statistics)
webapp/        FastAPI + MapLibre web GIS (map tools, shoreline / monthly panels, AI report, adjudication page)
scripts/       make_*.py rebuild the analyses; report_sites.py runs the 30-site evaluation;
               results_tables.py writes the paper tables; phase14_report.py scores the Phase 14 labels
notebooks/     Colab: labelling (Phase 3, Phase 14), Geo-VLM server, Planet → Earth Engine, fine-tuning
docs/          PLAN.md, decisions.md, analysis_plan.md, adjudication_rules.md, paper drafts
               (paper_draft.md: evidence gating; paper_shoreline_draft.md: shoreline), related_work.md, briefs/
data/          study outputs (regions, monthly, shoreline, coastal), labels, report runs
legacy/        deprecated old-schema files, not imported
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
| Adjudication page | web app running → http://localhost:8000/adjudicate |
| Adjudicated claims → metrics files | `python -m eval.adjudication data/reports_sites.jsonl judgements.jsonl claims.jsonl runs.jsonl` |
| Paper tables and figure | `python scripts/results_tables.py claims.jsonl runs.jsonl --out docs/results` |

Delete `webapp/backend/data/` to return the map to the built-in demo data.

Place search in the run panel sends the typed name to OpenStreetMap Nominatim (`/api/geocode`, on click only);
nothing else leaves the machine except Earth Engine requests and, when connected, the Geo-VLM server.

The pipeline defaults to a deterministic offline detector. Set
`EVICHANGE_ENGINE=ee` and `EE_PROJECT=<project-id>` after running
`earthengine authenticate` to use `agents/ee_engine.py` with Sentinel-2 SR.
The real Quang Ninh export is created after Earth Engine access is verified.
