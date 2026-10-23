# Design decisions

Short records of decisions the report needs to cite. Newest last.

## D1 — Deprecate the prototype claim schema (Phase 1)

**Decision.** The early prototype's schema (`claim_type`, `estimated_change_direction`,
patch-level evidence card) is deprecated. Its code is not migrated. Three ideas from it
are carried into `agents/verifier.py`: categorical reason codes, the rule that rejects
claims denying or understating detected change, and the risk-among-accepted metric.

**Paragraph for the report.**
> An early prototype represented each image pair with a single patch-level claim
> (`claim_type`, `estimated_change_direction`) checked against a 4-band evidence card
> that used a Red/NIR proxy for NDBI. We deprecated it in favour of the region-level
> schema used throughout the final system. Change in mining landscapes is spatially
> heterogeneous: one scene can contain vegetation loss, new bare surface, and new water
> bodies at once. A single direction label per patch cannot represent that, so it cannot
> be verified claim by claim. The final schema ties every claim to a region and a named
> evidence field (`region_ref`, `evidence_ref`), which makes claim-level verification and
> the hallucination metrics possible. Three elements of the prototype were kept:
> categorical reason codes on verdicts, a rule that rejects claims denying change the
> evidence shows, and the risk-among-accepted metric.

## D2 — One repo, one schema module, one verifier (Phase 1)

- The full system (previously `E:\claude\evichange-system`, not under version control)
  now lives in this repo: `agents/`, `webapp/`, `notebooks/`, all run from the repo root.
- `agents/schema.py` is the only definition of regions, evidence, claims, verdicts and
  thresholds (`T_IDX = 0.10`, `CONF_MIN = 0.5`). The pipeline validates at the DL-analysis
  and publishing handoffs; `import_geojson.py` validates imports; tests check the demo data.
- `agents/verifier.py` replaces the placeholder `verify()` in `report.py`. Every verdict
  now carries a reason code (`schema.REASONS`).
- Claims gained two optional fields: `change_type` (one of `schema.CHANGE_TYPES`, set by
  producers that know it) and `verdict_reason`. Free-text claims without them are
  handled by the verifier's text fallback.

## D3 — The verifier is an instrument, not ground truth (Phase 1)

The gated prompt and the verifier share thresholds, so scoring the gated condition with
the verifier alone would be circular. The evaluation (Phase 4) uses human reference labels
as ground truth and reports the verifier's agreement with them (Cohen's κ), its catch rate
and its precision.

**Known limitation to report.** The verifier's text fallback (location words and
change-type keywords) is heuristic. It is used only when a claim lacks `region_ref` or
`change_type`. Its errors show up as verifier–human disagreement and are measured, not hidden.

**Known limitation, fixed in Phase 2 (see D6).** `mean_conf` was a placeholder
(`min(1, area_ha/50)` in the Earth Engine notebook; random in the mock pipeline), so the
`low_detection_confidence` rule and the web app's threshold slider did not mean anything.

## D4 — Self-labelled Quang Ninh ground truth instead of OSCD (rev 2)

**Decision.** No public benchmark. Imagery is Sentinel-2 from Earth Engine for the
Quang Ninh AOI. The ground truth is ~30 sites labelled visually by the author
(`notebooks/EviChange_labeling.ipynb`): 20 detected regions + 10 random background
sites, shuffled and anonymised, labelled from image chips only, before any claims exist.

**Why it isn't circular.** The detector, the evidence, the gated prompt and the verifier
all derive from the same spectral-index deltas. The labels are the only element that
doesn't: the labeller sees imagery, not indices or detector output, and doesn't know
which sites were detected. Claims are then scored on two separate axes: truth (vs labels)
and evidence support. That lets the report separate generation errors (hallucination)
from evidence errors (faithful-but-false).

**Cost.** n ≈ 30 is pilot scale. Results are reported as a case study with Wilson CIs and
exact paired tests, and nothing is generalised beyond the AOI and period.

## D5 — General-AOI app, validated only in Quang Ninh (rev 2)

**Decision.** The web app and API accept any user-drawn or searched AOI + date range, and
run the Earth Engine composite → indices → change mask → region extraction on demand,
through the same agent pipeline. This is a **tool capability, not a scientific claim**:
thresholds were not tuned or validated outside Quang Ninh, and the app shows that on
every non-QN run.

**Constraints.**
- Earth Engine calls take tens of seconds, so runs are background jobs
  (`POST /api/runs` → `202` + run id → poll `GET /api/runs/{id}`), never a blocking request.
- AOI area is capped (1–500 km²; the QN box is ≈250 km²) to stay inside interactive
  Earth Engine limits.
- One Earth Engine job at a time; results are cached by (AOI, dates, parameters, code version).
- The backend uses the local user's Earth Engine credentials: it's a local tool, not
  a public deployment.
- Ungated/gated claims need the VLM (GPU in Colab). Without a reachable `VLMClient`
  backend, non-QN runs offer the template condition only, and the app says so.

## D6 — `mean_conf` for the threshold detector (rev 3, 2026-10-06)

No trained model means no probability. `mean_conf` is the **index-agreement fraction**:
the share of the region's pixels where **all 3** index deltas exceed `T_IDX`. The change
mask counts a pixel as changed when **at least 2 of 3** deltas exceed `T_IDX` (unchanged
from the original detector). Agreement must be stricter than the mask, or every region
averages to exactly 1.0. It's in [0, 1], has a plain meaning ("how consistently the indices agree
this is change"), and is computed server-side in Earth Engine.

**History.** v1 used a 2-of-3 mask and 2-of-3 agreement, so every region was 1.0. v2 kept
2-of-3 agreement but loosened the mask to any one index: on Quang Ninh that flagged 58% of
the AOI (v1: 38%), merged it into one 10,106 ha region, and put all 10 labelled background
sites within 200 m of detected change. v3 (`ee-threshold-v3`) restores the v1 mask, so its
regions are identical to v1 (`change_regions_quangninh_v3.json`: 504 regions, same ids,
areas and deltas) and the labelled sites keep their strata (20 detected, 10 background;
`scripts/restratify_sites.py`). Only `mean_conf` differs: 0.00–0.83, median 0.21.

**`CONF_MIN = 0.2`** (2026-10-06, set before any Phase-4 claims exist). The old 0.5 was set when
`mean_conf` was a placeholder: under v3 only 46 of 504 QN regions (2 of the 20 labelled detected
sites) reach it, so the verifier would rate almost every gated claim `uncertain`. 0.2 is about
the median of the v3 QN regions (0.21), so roughly half the detections count as confident.
It is pinned from here on: changing it after claims exist would be tuning on the test set.
`change_regions_quangninh_v3.json` still records `mean_conf_min: 0.5` in its metadata (the
`study.json` value when it was generated); the detector never reads it. The field name stays for
schema compatibility; the report defines it explicitly and never calls it a probability.

## D7 — Prompted change search: the VLM steers, the detector finds (2026-10-05, proposed)

**Decision.** The Geo-VLM does more than write the change report: the user can prompt it to
find changes ("forest cleared for mining near the coast, bigger than 5 ha, 2019 vs 2023").
It does this in three steps, and **every region outline still comes from the Earth Engine
detector**. The VLM never draws, invents or deletes a region.

1. **Prompt → search spec.** The VLM turns the prompt into a JSON `SearchSpec`, validated
   in `schema.py`: change types, gain/loss, min/max ha, locations, scope (all / view /
   drawn), top N, and optionally `before_window`/`after_window` and detector options
   (index subset, `MIN_AREA_HA` within fixed bounds). `T_IDX` is not prompt-tunable.
   Invalid or unparseable output falls back to the keyword parser (`explore.js`
   `parseQuery()`), which also stays the only path when no `VLMClient` backend is reachable.
2. **Search or run.** If the spec fits the loaded run, it filters those regions. If it
   needs other dates, another AOI or other detector options, the app shows the proposed run
   and the user confirms it before `POST /api/runs` (Earth Engine cost, D5 cap and cache
   apply). The AOI comes from the drawn/searched area, never from coordinates the VLM
   writes.
3. **Candidate check.** For up to 20 matching regions (largest first), the VLM sees the
   before/after chips plus the prompt and answers `match` / `no_match` / `unsure` with a
   one-line reason. `no_match` regions are hidden, not removed ("show rejected" toggle),
   and the map labels the result "VLM-checked, not validated".
   **Built (2026-10-06)** as the standalone "🛰 Check with Geo-VLM" button in Find changes, before
   step 1 exists: `agents/vlm_check.py` (prompt `vlmcheck_v1`, parsing, comparison with the detector),
   `agents/vlm_client.py` (http / replay / off), `POST /api/vlm/check` (one region per call, chips
   rendered by `ee_engine.region_chips()` from the detector's composites, results cached), and
   `notebooks/EviChange_vlm_server.ipynb` (Qwen2.5-VL on a Colab GPU behind a token-protected
   cloudflared tunnel). The model sees images only, not the detector's numbers or types, so its
   answer is an independent second look. Regions whose box overlaps any of the 30 labelled sites
   are not sent to the model until the Phase-4 prompts are frozen (`LABELLED_SITES_UNLOCKED`):
   45 of the 504 QN regions.

The change report for the found regions is then produced and verified exactly as before.

**Why not let the VLM scan imagery itself.** Hundreds to thousands of chips per AOI on a
7B model is slow, its free detections are the hallucination this project measures, and
they would need their own ground truth. Out of scope.

**Evaluation.** Unchanged. Prompted search is a tool capability, like D5, not a reported
result. Its prompts are separate from the frozen report prompts and are never run on the
30 labelled sites before the Phase-4 freeze. If time allows, the write-up gives a small
qualitative example of the candidate check against labels, clearly marked as anecdotal.

## D8 — ArcGIS Pro-style GIS tools in the web app (2026-10-05, proposed)

**Decision.** Add the ArcGIS Pro features that help someone inspect and use change results,
not a general GIS: symbology + legend, Earth Engine index rasters, geoprocessing + selection,
charts, export and a print layout (PLAN Phase 7b). Out of scope: editing, labelling engine,
3D, time slider (needs multi-date runs).

**Constraints.**
- Everything runs in the browser on GeoJSON (MapLibre + the bundled Turf), except the index
  rasters, which the backend serves as Earth Engine tile URLs for a run's AOI and windows,
  using the same composites as `ee_engine.py` so the map shows the detector's actual inputs.
- Geoprocessing outputs are new user layers. They never change a run's change regions and
  never reach the AI report (only the change layer does). Clipped, intersected and buffered
  polygons get their own `area_ha` (the source value is kept as `area_ha_src`); other source
  attributes, such as `mean_conf`, are copied unchanged and describe the original region.
- Geometry runs in a Web Worker: Earth Engine regions are pixel-edged (one QN region has ~100k
  vertices), so buffer / clip / intersect / dissolve take 5–15 s on the full QN layer. Geometry
  is never simplified to speed this up: removing the pixel steps would move outlines by more
  than half a pixel.
- Export formats: GeoJSON, CSV (attributes + centroid) and KML. Shapefile export is left out:
  it needs a vendored writer library, and GeoJSON opens in ArcGIS Pro and QGIS.
- Exports keep attribution (EOX for the Sentinel-2 mosaics, Copernicus for Earth Engine data)
  and the "not validated outside Quang Ninh" note for non-QN runs.

## D9 — Map assistant: typed requests become tool actions (2026-10-06, proposed)

**Decision.** Like ArcGIS Pro's AI assistant, the "Find changes" chat takes requests such as
"make the AOI purple, 95% transparent", "select regions bigger than 10 ha found after April" or
"buffer the river layer by 500 m and clip the change regions to it", and runs them with the
app's own tools (D8). D7's prompted change search becomes one action among several.

1. **One action schema** (`schema.py`), e.g. `{action: "style_layer", layer, color, opacity}`,
   `select_by_attributes`, `select_by_location`, `buffer`, `clip`, `intersect`, `dissolve`,
   `add_index_layer`, `chart`, `export`, `search_changes`, `start_run`. Every action is
   validated before it runs; an invalid one is rejected with a message, never run blind.
2. **Two producers of actions.** The keyword parser (extending `explore.js` `parseQuery()`)
   works without a model. In Phase 4 the VLM produces the same JSON from free text; its output
   falls back to the keyword parser when invalid or when no `VLMClient` is reachable.
3. **Show, then undo.** Each action shows what it ran (the SQL `WHERE` clause, the tool chain,
   the style applied) and offers Undo. `start_run` (Earth Engine cost) and anything that
   replaces a layer need confirmation first. Multi-step requests show the whole chain first.

**Constraints.** Actions only call existing app tools: the assistant never edits a run's change
regions, and geoprocessing outputs stay new layers (D8). The AOI for new runs comes from a drawn
or searched area, never from coordinates the model writes (D7).

**Evaluation.** None. Like D5 and D7, the assistant is a tool capability, not a reported result.
Its prompts are separate from the frozen Phase-4 report prompts.

## D10 — Specific land-cover classes from Dynamic World (2026-10-08; implemented 2026-10-20)

**Decision.** Change regions get land-cover classes from Google Dynamic World V1
(`GOOGLE/DYNAMICWORLD/V1`, 10 m, one classification per Sentinel-2 scene): water, trees, grass,
flooded vegetation, crops, shrub and scrub, built, bare, snow and ice. For each region and window,
the mode of the per-pixel most-likely class gives `class_before` / `class_after`, and the mean class
probabilities give `class_frac_<class>`. A region then reads "trees → bare" (likely mining or
clearing), "water → built" (reclamation), "bare → built" (construction).

**Why not our own classifier.** Training data for a custom classifier (e.g. aquaculture ponds, coastal
sand, mangrove) doesn't exist yet; Dynamic World is documented, peer-reviewed and needs none. Custom
coastal classes can be added later on top of Dynamic World, once Planet data and labels exist.

**What doesn't change.** The detector (D6) still decides *where* change is; classes describe *what*
it is. Index types (`dNDVI` …) stay as evidence. Dynamic World only exists for scenes with ≤ 35 %
cloud, so a window with no usable scene gets `class_* = null`, never a guess.

**As implemented (Phase 9, `agents/landcover.py`).** Fields: `class_before`, `class_after` (a class
name or null) and `class_frac_before`, `class_frac_after` ({class: mean probability}). Each pixel's
class is its mode over the window's Dynamic World images; the region's class is the mode of those
over its pixels. New detector runs add the fields (a Dynamic World failure is recorded in the
metadata, never loses the detection); `scripts/add_landcover.py` adds them to an existing regions
file without touching ids or geometry. QN v3 (Nov 2018 – Mar 2019 vs Nov 2022 – Mar 2023): all 504
regions got both classes; 105 change class, most often built → trees (15), shrub → trees (10),
shrub → bare (9), trees → bare / trees → built / water → built (7 each). "Built → trees" being most
common is a flag for Phase 14 to check (bare spoil labelled built in 2018?).

**Blind labels.** Phase 14 labels the from / to class at the 30 sites without seeing Dynamic World,
so the app hides the class fields of regions with at least 10 % of their area inside a labelled site
(22 of 504 regions, 93 ha) until those labels exist (`CLASSES_UNLOCKED_AT_LABELLED_SITES`), like the
Geo-VLM lock (D7). A first version locked every region whose bounding box touched a site: 45 regions
and 66 % of the changed area, mostly huge regions with 0–0.5 % of their area in a site, whose class
says nothing about the site.

**First reading of the QN classes.** The largest "type unclear" regions (r239 3,275 ha, r280, r390,
r108) keep the same class with near-identical shares, so they are probably not land change: r239
alone is 41 % of all changed area, which is a detector issue to report. Real changes stand out:
r363 water → built (coastal reclamation, south), r289 bare → trees (revegetation). Some coastal
regions keep "water" as their class while its share falls (r435: 47 % → 28 %), so the shares carry
information the class alone hides.

## D11 — Monthly change, shoreline and coastal buildings (2026-10-08; monthly maps implemented 2026-10-22)

**Period.** Oct 2024 – Sep 2026 (24 months: two full monsoon cycles, so seasonal swings can be
told apart from lasting change).

**Data availability over the QN AOI (checked 2026-10-08).** Sentinel-2 scenes with < 40 % cloud /
Dynamic World images per month: 1–6 from October to March, but **0 in most of April–August**
(monsoon). Sentinel-1 radar: 1–4 IW scenes in every month. Therefore:
- **Water and shoreline are monthly all year**, from Sentinel-1 (VV backscatter, Otsu threshold per
  scene, monthly median), with Sentinel-2 MNDWI used where a clear scene exists.
- **Land-cover class maps are monthly only where clear** (about Oct–Mar); other months are shown as
  gaps, never interpolated. Seasonal (dry-season) composites are the fallback for comparisons.

**Shoreline method.** Monthly water mask → land / water boundary as a line; a fixed baseline along
the Oct 2024 shoreline with transects every 100 m; per transect the shoreline position each month,
net movement and a linear rate (m/yr) over 24 months, as in standard shoreline-change analysis.

**Tide.** The tidal range around Ha Long Bay is several metres, so one month's shoreline can differ
from the next mostly because of the tide at acquisition time. Monthly positions are therefore
shown with a tide caveat, and the reported quantity is the **24-month trend**, which averages out
tide noise. Correcting each scene to a common tide (a tide model) is optional future work.

**Buildings near the shoreline.** Dynamic World `built` inside 0–200 m and 200–500 m strips from
the Oct 2024 shoreline, per month (where clear) and per dry season; new built patches as regions.
Google Open Buildings temporal (`GOOGLE/Research/open-buildings-temporal/v1`, available over the
AOI, yearly to 2023) is a pre-period reference only. At 10 m, single houses are below resolution:
"built area" is reported, not building counts, until Planet (3 m) is integrated.

**As implemented (Phase 10, `agents/monthly.py`, `scripts/make_monthly.py`).** Months come from
`monthly` in `study.json`; the baseline is the first month (Oct 2024).
- *Water:* Sentinel-1 IW VV, 30 m focal median against speckle, one Otsu threshold per scene from a
  0.25 dB histogram over the AOI (computed in Python, so it is unit-tested). A threshold outside
  −24 … −12 dB means the scene has no land / water split and −18 dB is used instead, recorded as
  `fallback`. A pixel is water in a month when at least half of that month's looks call it water.
  Slopes ≥ 15° or ground ≥ 40 m (SRTM) are never water, because radar shadow on the karst hills is as
  dark as water. Where Sentinel-2 has a clear look, the radar water is compared with MNDWI > 0
  (`water_s2_agree`).
- *Classes:* the Dynamic World label, as the per-pixel mode over the month. Pixels with no image stay
  gaps. A month's `class_status` is `none`, `patchy` (under half the AOI) or `clear`.
- *Data quality:* clear Sentinel-2 looks per pixel (SCL 2, 4–7). `clear_share` is the share of the AOI
  seen clear at least once.
- *Change:* compared with the previous calendar month and with the baseline. Only pixels observed in
  both months count, and `compared_ha` always goes with the gained / lost / changed areas. A month with
  no data gives `null`, never a guess.
- *Per region:* for each change region and month, the class (null under 50 % Dynamic World cover),
  the water share and the share seen clear.
- *API:*
  - `GET /api/monthly`: the summary.
  - `GET /api/monthly/layer?month=YYYY-MM&layer=class|water|clear|water_change|class_change&vs=base|prev`:
    tiles. A gap month gives 404.
  - `GET /api/monthly/regions/{id}`: one region's series.

  The class layers are masked at the labelled sites and the region class series hidden there until
  Phase 14 (D10).

**First QN run (2026-10-22, Oct 2024 – Sep 2026).**
- *Radar:* every month has 1–4 Sentinel-1 scenes; 3 of 59 scenes needed the −18 dB fallback.
- *Water:* 4,780–5,610 ha per month. That ±8 % swing is mostly tide and speckle along the shore, so
  use trends, not single months. The radar water agrees with Sentinel-2 MNDWI on 92–97 % of
  clear-look pixels, except in months with almost no clear look (May 2025: 72 % on 0.3 % of the AOI).
- *Class gaps:* Dynamic World covers Oct–Mar (Feb 2025 and Feb–Mar 2026 only partly). There are no
  images from Apr to Aug 2025. 2026 is kinder: May and Aug are usable.
- *Single months are too noisy for class change:* against Oct 2024, 12–38 % of the compared area
  "changes class" every month, far more than real change. The summary therefore also compares
  **dry-season modes** (`seasons`).
- *Dry season 2024-25 → 2025-26:* 4,815 of 24,861 ha change class. The largest move is
  shrub → trees (1,850 ha), Dynamic World's known shrub / tree confusion. The plausible real changes
  are smaller: water → bare 301 ha, bare → built 244 ha. Phase 14's class labels will say how much of
  this is real; until then report class change from the seasons, never from single months.

## D12 — Planet-ready imagery source (2026-10-08, proposed)

**Decision.** `ee_engine` gets an imagery `source` (`sentinel2` now, `planet` when the data arrives)
with a per-source band map, scale and cloud mask, so every phase above can run on either.
PlanetScope has **no SWIR band**: NDBI and MNDWI can't be computed from it. On Planet, water uses
NDWI (green / NIR), and built / bare come from classification rather than an index. Request
**8-band surface reflectance** (SuperDove) for the AOI and the 24-month window; deliveries outside
Earth Engine are uploaded as an Earth Engine image collection so the same code reads them.

**Access (2026-10-11 update).** Planet's Education and Research program accepted the project on
2026-10-08: two years, **3,000 km² per month** (reset on the 1st), non-commercial, 30-day delay on
PlanetScope. Published work must cite *Planet Team (2026). Planet Application Program Interface: In
Space for Life on Earth. San Francisco, CA. https://api.planet.com.*

**What Planet is used for.** Not as the time series source (D14): PlanetScope has no SWIR, its
history for this AOI would cost quota, and its sensor generations differ radiometrically. Planet is
used for (1) **monsoon months**: daily revisits give clear looks in April–August, when Sentinel-2
has almost none; (2) **3 m detail**: buildings near the shore (Phase 12), the shoreline (Phase 11),
and labelling (Phase 14); (3) sharper **Geo-VLM chips**.

**Ordering.** `scripts/planet_order.py` searches PSScene 8-band surface reflectance per month, picks
the acquisition day whose scenes cover the AOI best with the most clear sky, and orders it clipped
to the AOI and harmonised to Sentinel-2 (Planet's `harmonize` tool). The AOI is ≈ 250 km², so one
day per month for 24 months is ≈ 6,000 km²: Oct 2024 – Sep 2025 on the October 2026 quota, Oct
2025 – Sep 2026 on November's. Nothing is ordered without an explicit `--confirm` after the km²
total is shown. Extra monsoon days are ordered only from leftover quota.

**Quota counting (2026-10-19).** The quota is not the clipped AOI area: the first 11 orders covered
2,567 km² of AOI but used 3,131 km², and the 12th (Feb 2025) was refused as over quota. Overlapping
scenes are charged more than once (October 2024's 9 scenes added up to 932 km² inside the AOI).
The script now keeps only the scenes needed to cover the AOI (year 1 would have been 3,460 instead
of 4,275 km² of per-scene area), prefers the cheaper of two near-equal days, and checks the quota
against the per-scene sum, an upper bound. Year 2 may therefore need two quota months; Feb 2025
goes into November's order.

**Into Earth Engine (Phase 13b, 2026-10-22).** The project PC can't run rasterio (Windows Smart App
Control blocks its GDAL DLLs), so `notebooks/EviChange_planet_to_ee.ipynb` does the raster work on
Colab (CPU runtime): per month, every scene is masked with Planet's UDM2 clear band, scenes are
merged clearest first into one 3 m mosaic, and the mosaic goes into the private Earth Engine
collection `projects/space-510615/assets/planet_qn` as image `m<YYYY>_<MM>` with 9 bands (8 × surface
reflectance × 10 000, plus `clear`), no-data 0, the acquisition date as start time, and `month`,
`date`, `item_ids`, `clear_share` and the Planet attribution as properties. Upload is automatic with a
Cloud Storage bucket, otherwise by hand in the Code Editor (exact asset ids printed); the notebook
then sets dates and properties. `agents/planet.py` reads the collection, selecting bands by position
so either upload path works, and gives `month_image()` (reflectance, clear-masked), `indices()`
(NDVI, NDWI), `water_image()` (NDWI > 0) and `region_chips()` (true colour + NIR false colour).
Rather than an `ee_engine` `source` switch, Planet gets its own module: its bands, missing SWIR and
monthly single-day images differ enough from the Sentinel-2 composites that one code path would
hide the differences. Wiring it into the monthly maps, the shoreline and the Geo-VLM check follows
once the mosaics are in Earth Engine. **Feb 2025 is skipped for now** (refused over quota): the 11
delivered months go in first, and rerunning the notebook in November adds February alone.
Neither the scenes nor the mosaics are committed to either repository (licence).

## D13 — Extended evaluation: classes, shoreline and coastal buildings (2026-10-08, proposed)

**Decision.** The new outputs are also evaluated, not only shown, using the same two-axis design
(truth vs labels, support vs evidence) and the same gated / ungated / template conditions:
- **New claim types:** `land_cover` (L3, "trees were replaced by bare ground"), `shoreline` (L2,
  "the shoreline moved ~40 m seaward in the north-east") and `coastal_built` (L2, "built area
  within 200 m of the shore grew by ~3 ha"). Evidence fields: the D10 class fields, transect
  statistics, coastal-strip built areas. The verifier gets rules for each.
- **New ground truth (Phase 14), labelled blind like Phase 3:** from / to class at the existing 30
  sites (labellers don't see Dynamic World); reference shorelines digitised on high-resolution
  imagery for 2 dates on 30 transects; 30 coastal cells labelled built / not built at both ends of
  the window. The existing `labels_v1` files are not changed; new labels go in new files.
- **Extra metrics:** shoreline extraction RMSE (m) against the reference lines, class-transition
  agreement (κ) between Dynamic World and the labels, coastal-built accuracy, and hallucination
  rates per claim type.
- **Freeze order:** Phase 4 prompts are frozen only after the new claim types exist (PLAN).

## D14 — Time series analysis with CCDC (2026-10-11, proposed)

**Why.** The teacher asked for time series analysis. Two-date comparison (D6) says *what* changed
but not *when*, and it can't tell a monsoon greening that comes back every year from a lasting
change. Phase 10's monthly maps show the series; this decision adds an analysis of it.

**Decision.** Continuous Change Detection and Classification (CCDC, Zhu & Woodcock 2014), built
into Earth Engine as `ee.Algorithms.TemporalSegmentation.Ccdc`, on Sentinel-2 surface reflectance
(SCL cloud mask): green, red, NIR, SWIR1, SWIR2 plus NDVI / NDBI / MNDWI. Each pixel gets a harmonic
(seasonal) model learned from **2018 onwards**; a break is a run of clear observations that leave
the model. Breaks in **Oct 2024 – Sep 2026** are kept.

**Outputs per change region.** `change_month`: the window between the last clear look before the
break and the first after it, reported as a window because monsoon gaps can be months long, never
as a single invented date. `break_magnitude` per index. `lasting`: true when the post-break model
differs from the pre-break one, false when the region only swings with the season. App: a chart of
monthly values with the fitted curve and the break; Find changes can filter by date.

**Why Sentinel-2, not Planet.** CCDC needs years of consistent history to learn the season.
Sentinel-2 has it for free from 2018, with SWIR. Planet's history would use months of quota, has no
SWIR, and mixes sensor generations whose colours differ (D12). Planet's monthly images are still
used to *see* the monsoon months and to label the month of change (Phase 14d).

**Limits to state.** Few clear Sentinel-2 looks from April to August (D11), so a break there is
dated to a window spanning the monsoon. Sentinel-1 water series (Phase 11) are not run through CCDC;
they use the monthly series and trend directly. CCDC parameters are the Earth Engine defaults unless
the labelled data show a reason to change them, and any change is recorded here.

**Evaluation.** Break-month agreement with the Phase 14d labels (share within ± 1 month and within
the reported window), and the share of detector regions CCDC calls seasonal rather than lasting.

## D16 — Ungated GPT as a secondary comparison arm (2026-10-23, proposed)

**Why.** The obvious question about the Geo-VLM is "why not just ask GPT?". The three conditions
only use Qwen, so they can show that gating helps a 7B open model, not how that compares with a
frontier model used the usual way: free text from the images, no evidence, no checks.

**Decision.** A fourth report arm, `ungated_gpt`, run on the same 30 sites with the same chips and
scored by the same verifier and labels. It is a **pre-specified secondary comparison**: gated Qwen
vs ungated GPT. The primary comparison (gated vs ungated Qwen) is unchanged, and template stays a
reference.
- **Same input and prompt as ungated Qwen.** Both ungated arms use `agents/ungated.py`
  (`ungated_report_v0`): the before/after chips with the box outlined, the dates, nothing from the
  evidence. The arms differ only in the model that writes, so the difference is the model's.
- **One extractor for both ungated arms.** Free text is split into claims by the Geo-VLM (Qwen,
  text only, `claim_extract_v0`), which copies statements and never judges them. Using the same
  extractor for GPT and Qwen keeps extraction errors from favouring either arm. Items that break the
  claim schema are dropped and counted as parse failures (metric 8), never repaired.
- **Report arm, not a pipeline condition.** `schema.REPORT_CONDITIONS` adds `ungated_gpt`;
  `CONDITIONS` (pipeline runs) stays at three, since the pipeline has no chips.
- **Off unless asked for.** `GPTClient` is off by default; an `OPENAI_API_KEY` alone never turns it
  on. Running it needs `EVICHANGE_GPT=http` and an explicit `OPENAI_MODEL`, and the model name is
  reported. It sends the chips to OpenAI, so it costs money and moves imagery off our own GPU. The
  labelled-site lock (D7) applies to it too. Answers can be replayed (`GPT_REPLAY_FILE`).
- **Prompt hygiene.** The ungated report prompt and the extractor prompt are drafts (v0). They are
  developed outside the 30 sites and frozen with the other Phase 4 prompts.

**Open before freezing.**
1. *Location frame.* A region's `location` is relative to the whole AOI, but the ungated prompt asks
   where change is *in the box*. For both ungated arms, the verifier's location checks would then
   compare different frames. Options: recompute locations relative to the site box for every arm,
   or drop location wording from the ungated prompt.
2. *Extractor validation.* Check the extractor on a sample of reports outside the 30 sites (claims
   missed, invented or mis-levelled) and report that rate; it is part of the measurement.

**Limits to state.** One GPT model at one point in time (the API model can change behind a name;
record the dated model name the API returns). GPT sees PNG chips at its own image resolution, not
the 10 m pixels. A better GPT result would not say the Geo-VLM is worse at describing imagery; the
claim tested is about unsupported claims reaching the user.
