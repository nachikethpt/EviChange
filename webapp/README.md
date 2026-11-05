# EviChange GIS — starter web app

A web GIS (in the style of ArcGIS Online's Map Viewer, with our own design) plus the EviChange AI change report.
Without a pipeline run or an import the map shows built-in **demo** regions near the Cam Pha mines; the shoreline,
monthly and coastal panels read the committed Quang Ninh outputs in `data/quangninh/`. Geo-VLM features need the
Colab model server (`VLM_URL`); index and monthly image layers need an Earth Engine login (`EVICHANGE_ENGINE=ee`).
The AI-report panel uses the rule-based stand-ins in `backend/report.py`; the frozen prompts (D19) run on the study
sites with `scripts/report_sites.py`.

## How to start it

Run it from the **repo root** (it imports the shared `agents/schema.py` and
`agents/verifier.py`): double-click `run_webapp_windows.bat`, or

    python -m uvicorn webapp.backend.main:app --reload --port 8000

## What works already

| Tool | What it does |
|---|---|
| Contents (left) | Turn layers on/off, transparency slider, 🔍 zoom to layer, ▲▼ reorder, 🗑 remove added layers |
| ＋ Add data | Load a GeoJSON file or a zipped shapefile |
| ▦ Basemap | Sentinel-2 2022 / 2018 (cloud-free mosaics), streets, topographic, none |
| Click the map | Popup with the feature's attributes (or the coordinates) |
| ☰ Table | Attribute table; click a row to zoom to that feature |
| 📏 Measure | Distance, or area and perimeter |
| ✎ Draw area | Draw a polygon; the change regions inside it go to the AI report |
| ⇆ Swipe | Before/after slider (e.g. Sentinel-2 2018 vs 2022) |
| ◐ Indices | NDVI / NDBI / MNDWI before, after or change, as Earth Engine tile layers over the regions' own AOI and dates (needs live data + an Earth Engine login) |
| ⚙ Tools | Select by attributes (shows the SQL) or location; buffer, clip, intersect, dissolve (run in a background worker; outputs are new layers) |
| Shoreline API (Phase 11) | `/api/shoreline` (summary), `/api/shoreline/transects?change=` (rates, confirmed change), `/api/shoreline/lines?kind=quarter|month`, `/api/shoreline/transects/{id}`; data from `scripts/make_shoreline.py`. The map / chart UI is P3's |
| 🔎 Find changes ⇄ selection | Start a search with *select*, *add* or *remove* to change the map selection (the one ⚙ Tools, charts, the table and the AI report use); every search shows its SQL `WHERE` clause; ☑ Select these / ＋ Add to selection on the results; a **Selection** scope lists and checks whatever is selected; ⚙ Tools → 🔎 Explore in Find changes |
| 📊 Charts | Bar chart (count or sum by a field) or histogram; click a bar to select its features; table view |
| 🖨 Export | Layer → GeoJSON / CSV / KML (all or selected); A4 print layout with legend, north arrow and scale bar → PNG or PDF |
| 🎨 (in Contents) | Symbology: single colour, unique values or graduated colours, with a legend under each layer |
| 🏷 Land cover (D10) | Region cards show the Dynamic World class before → after with class-share bars; list rows show the transition; Find changes understands "trees to built", "from forest", "became water"; ⚙ Symbology → Unique on `class_before` / `class_after` uses Dynamic World's colours. Hidden on regions mostly inside the 30 labelled sites (22 regions) until the Phase 14 labels exist. `python scripts/add_landcover.py` adds the classes to an existing regions file. |
| 🛰 Geo-VLM check (in 🔎 Find changes) | Sends up to 20 regions, one at a time, to Qwen2.5-VL with before/after chips; shows whether the model sees change and how that compares with the detector; flags "no change" regions on the map. Needs `VLM_URL` + `VLM_TOKEN` from `notebooks/EviChange_vlm_server.ipynb` (Colab GPU). An **Images** menu picks the chips sent (true colour / + SWIR / + colour infrared; default from `VLM_CHIPS`, else true colour + SWIR). Every answer is saved to `data/vlm_checks.jsonl` (survives restarts; `python scripts/vlm_compare.py` compares models and image sets). The 30 labelled sites are skipped. |
| ✦ AI report | Template / Ungated / Gated / Compare, confidence threshold slider, verdicts (supported / unsupported / uncertain), abstentions |
| ▶ Run pipeline | Draw, search or use the map view as the AOI, pick the before / after windows, run the analysis on Earth Engine; run list with open / reuse / delete |
| 〰 Shoreline | Yearly (dry seasons 2015-16 … 2025-26) or monthly (2024-10 … 2026-09) shorelines on a slider with Play; transects coloured by confirmed change; click one for its position series (radar, optical, Planet). Phase 14 reference transects stay hidden |
| 🗓 Monthly | Month slider over Dynamic World class, Sentinel-1 water, clear share and Planet 3 m layers; water and clear-share charts; one region's months on click; coastal strips and new built patches |
| /adjudicate | The blinded claim adjudication page (Phase 5, D18): pass 1 truth, pass 2 support, second-adjudicator share |

Map imagery needs internet. Sentinel-2 cloudless mosaics © EOX IT Services (CC BY-NC-SA 4.0 for 2018 and later: fine for research, keep the attribution).

## Folder map — who edits what

```
backend/
  main.py        API endpoints                              → Person 3
  demo_data.py   FAKE change regions + AOI                   → Person 1 replaces with real output
  report.py      claims for 3 conditions + simple verifier   → Person 2 (claims), Person 3 (verify)
frontend/
  index.html, style.css, app.js   the web app               → Person 3
  vendor/        MapLibre, Turf, shpjs (copied here so no internet is needed for them)
```

## The data contract (do not change names without telling the team)

A change region (GeoJSON feature properties):
`id, area_ha, mean_conf, dNDVI, dNDBI, dMNDWI, location, date_before, date_after, source`

A claim (from `/api/report`):
`claim_id, level (L1–L4), type, text, region_ref, evidence_ref[], stated_conf, verdict`
