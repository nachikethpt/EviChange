# EviChange build plan (rev 2)

Team of three (again since 2026-10-19; one member worked solo 2026-10-06 → 10-19 in a private repo,
synced to this one): **P1** Earth Engine + labels, **P2** VLM + Planet, **P3** app + verifier. The
Owner column says who does each phase (updated 2026-10-23). P1 did Phases 2 and 3; the Phase 14 labelling
moved to P2 on 2026-10-23, with P3 as second labeller (blindness: see Phase 14). The critical path
(9 → 10 → freeze → 4 / 5) is with P2; P3 has work that blocks no one (5 page, 7, 7c, 10b, 12, UI). Before 2026-10-05, solo from the start of
week 4 (≈125 h).
Defaults: this repo is canonical; Qwen2.5-VL-7B-Instruct for every reported run.

**Rev 2 changes (2026-09-26):** (1) no OSCD. Imagery comes from Earth Engine for
Quang Ninh, and the ground truth is a self-labelled set of ~30 sites. (2) The app and
backend accept any AOI + date range and run the Earth Engine analysis on demand. Only
Quang Ninh results are validated. See `decisions.md` D4–D5.

## Phases

| # | Phase | Depends on | Est. h | Owner | Status |
|---|---|---|---|---|---|
| 1 | Consolidate repo, one schema, real verifier, EE smoke test | — | 8 | P2 | **done** (EE smoke test waits on your project id) |
| 2 | **Earth Engine engine for any AOI.** Phase-1 rework (below); `agents/ee_engine.py` (SCL composites, indices, change mask, vectorised regions, real `mean_conf`); AOI validation + size cap; `tools.py` mock/EE switch; produce the Quang Ninh regions (now `change_regions_quangninh_v3.json`, D6) | 1 | 14 | P1 | **done** |
| 3 | **Ground-truth labelling.** `notebooks/EviChange_labeling.ipynb`: 30 blind sites + a second labeller on 10 (inter-rater κ 0.63); `data/quangninh/labels/` | 2 | 4 | P1 | **done** (2nd labeller on all 30 recommended) |
| 4 | **Real VLM.** `VLMClient` (hf / http / replay) — http + replay done 2026-10-06 with the Geo-VLM region check (D7), served from Colab; develop prompts on detected QN regions **outside** the 30 labelled sites; freeze; run 3 conditions on the 30 sites. Also the two prompted-search tasks (D7): prompt → `SearchSpec` (+ schema validation) and candidate check `match`/`no_match`/`unsure`; their prompts are separate and not part of the freeze | 2, 3 (labels done first) | 18 | P2 | **in progress**: VLMClient (http / replay), Colab server (works end to end since 2026-10-08), region check, image sets, model setting, answer log + `scripts/vlm_compare.py` done. Ungated report path + ungated GPT arm (D16) built 2026-10-23 (replay-tested, API never called). Next: Qwen2.5-VL-7B vs Qwen3-VL-8B and image-set comparison (D15), report prompts (incl. the D16 open items), freeze (after 9 and the 15 schema), 3 conditions + ungated GPT on the 30 sites |
| 5 | **Evaluation.** Claim adjudication page (condition hidden), `eval/metrics.py`, results tables | 3, 4 | 10 | P3 (page) + P2 (metrics) | |
| 6 | **On-demand runs API.** `POST /api/runs` (AOI + before/after date windows) → background job running the agent pipeline on Earth Engine; `GET /api/runs/{id}` polling; per-run data store; cache; AOI cap | 2 | 12 | P2 | **done** |
| 7 | **App.** Draw/search AOI, date pickers, run + progress state, per-run layers, "not validated outside Quang Ninh" banner, verdict reasons, export, cleanup. **Prompted search (D7):** "Find changes" chat calls the VLM (keyword parser as fallback), confirm-before-run for new dates/AOI/options, candidate-check results with "show rejected" toggle and "VLM-checked, not validated" label | 6 | 24 | P3 | **in progress**: Find changes, shared selection, Geo-VLM check done (by P2); the rest is P3's |
| 7b | **GIS tools (D8).** (a) Symbology by attribute + legend, scale bar, north arrow; (b) index rasters from Earth Engine (before/after/difference NDVI, NDBI, MNDWI) as tile layers; (c) geoprocessing (buffer, clip, intersect, dissolve) + select by attribute / location; (d) linked charts, layer export (GeoJSON / CSV / KML) + print layout (PNG/PDF). Owner: Person 2 | 7 (b also 2) | 28 | P2 | **done** |
| 7c | **Map assistant (D9).** The "Find changes" chat becomes an ArcGIS Pro-style assistant: typed requests become validated actions that drive the existing tools — style layer (symbology), select / filter by attributes or location, geoprocessing (buffer, clip, intersect, dissolve), add index layer, chart, export, change search and new runs (D7). Each action shows what it ran (query / tool chain) with Undo; runs need confirmation. Keyword parser first, then the Phase 4 VLM produces the same actions. Owners: Person 3 actions + UI, Person 2 VLM side | 7b; VLM side 4 | 12 | P3 (actions, UI) + P2 (VLM side) | |
| 8 | Write-up + advisor demo | 5, 7, 14 | 14 | all | |

### Coastal + land-cover extension (teacher feedback, 2026-10-08; D10–D14)

The teacher asked for (1) specific land-cover classes, (2) change over **months**, including
shorelines and buildings near the shoreline, and (3) the same analysis on **Planet** data, which
arrives later (access granted 2026-10-08, D12). Later the teacher also asked for **time series
analysis** (D14): when a change happened and whether it lasts, not only before vs after. These are
both new app capabilities and new evaluated claim types (D13).
Study period for the monthly work: the last 24 months, **Oct 2024 – Sep 2026**.

| # | Phase | Depends on | Est. h | Owner | Status |
|---|---|---|---|---|---|
| 9 | **Land-cover classes (D10).** Dynamic World for each change region: dominant class before / after and class shares, so a region reads "trees → bare" instead of "vegetation loss + more bare ground". New optional region fields `class_before`, `class_after`, `class_frac_*`; app legend, cards and Find changes search by class / transition ("trees to built") | 2 | 10 | P2 | **done** 2026-10-20 (public #14): all 504 QN regions classed, 105 change class; classes locked on the 22 regions mostly inside labelled sites until Phase 14 |
| 10 | **Monthly time series (D11).** One map per month for the AOI: Dynamic World class map (only where clear: about Oct–Mar, see D11), Sentinel-1 water mask (every month), and a per-month data-quality layer (clear-sky share). Monthly change vs the previous month and vs Oct 2024. App: time slider over months with gaps shown as gaps, a monthly chart per region / transect | 2, 9 | 16 | P2 (+ P3 slider, charts) || **in progress**: data + API done 2026-10-22 (`agents/monthly.py`, `scripts/make_monthly.py`, `/api/monthly*`, D11 "as implemented"); class change from dry-season modes, single months too noisy. Next: P3 time slider + region charts on the API |
| 10b | **Time series analysis (D14).** CCDC (`ee.Algorithms.TemporalSegmentation.Ccdc`) on Sentinel-2 per pixel: a seasonal model learned from 2018 onwards, breaks detected in Oct 2024 – Sep 2026. Per region: `change_month` (date window between the last clear look before and the first after the break), break magnitude per index, lasting vs seasonal. Planet monthly images (Phase 13) fill the monsoon months visually. App: region chart with monthly values, the fitted seasonal curve and the break; Find changes by date ("forest loss after June 2025") | 10 | 12 | P3 | |
| 11 | **Shoreline change (D11).** Monthly land / water line from Sentinel-1 (VV, Otsu threshold) with Sentinel-2 MNDWI where clear; baseline + transects every 100 m; per transect: position each month, net movement and linear rate (m/yr) over the 24 months; tide caveat on every number (D11). App: shoreline per month on the map, transect chart, "advancing / retreating" colouring | 10 | 14 | P2 (+ P3 map, chart) | **in progress**: P2's part **done** 2026-10-23: `agents/shoreline.py`, `scripts/make_shoreline.py`, `/api/shoreline*`; 735 transects on 90 km, quarterly tide-averaged rates, optical confirmation (D11). QN: 483 stable, 5 confirmed advancing, 0 retreating, 30 unconfirmed. Left: P3's map and transect chart |
| 12 | **Buildings near the shoreline (D11).** Built area inside coastal strips (0–200 m, 200–500 m from the Oct 2024 shoreline) per month from Dynamic World `built`; new built patches; Open Buildings temporal (to 2023) as a pre-period reference | 10, 11 | 8 | P3 | |
| 13 | **Planet imagery (D12).** (a) `scripts/planet_order.py`: best clear 8-band scene set per month over the AOI, clipped and harmonised to Sentinel-2, km² shown before ordering; Oct 2024 – Sep 2025 on the October 2026 quota, the rest in November; (b) `ee_engine` gets a `source` setting (sentinel2 / planet) with a per-source band map and resolution; indices that need SWIR (NDBI, MNDWI) are replaced by NDWI + classes for Planet; (c) integration: monsoon gap fill for Phase 10, 3 m detail for Phases 11–12, Geo-VLM chips | 9, 10 (a: none) | 6 (+8) | P2 | **in progress**: (a) **done**: ordering script; year 1 delivered (11 of 12 months; Feb 2025 refused over quota, re-order in November). (b) Planet → Earth Engine **ready** 2026-10-22: `notebooks/EviChange_planet_to_ee.ipynb` (Colab) + `agents/planet.py`; the 11 delivered months first, February skipped for now. Next: run the notebook, then (c) wiring into Phases 10, 11 and the Geo-VLM chips |
| 14 | **Ground truth for classes, shoreline and coastal buildings (D13).** (a) From / to land-cover class at the existing 30 sites (blind to Dynamic World); (b) reference shorelines digitised on high-resolution imagery at 2 dates on 30 transects; (c) 30 coastal cells labelled built / not built at Oct 2024 and Sep 2026; (d) month of change at the 30 sites where the Planet monthly images show it (D14) | 9, 11, 12, 13 | 9 | P2 (moved from P1 2026-10-23); 2nd labeller on 10 sites: P3 | Blindness: P2 builds the class and shoreline outputs, so (a) classes stay hidden at the labelled sites (already locked, D10), (b) the 30 reference transects are drawn at random and their extracted shorelines hidden in the app until digitised, (c) each site is labelled from imagery before any output for it is opened; the write-up states the labeller built the classifier. |
| 15 | **Evaluation extension (D13).** Claim types `land_cover` (L3), `shoreline` (L2) and `coastal_built` (L2) in `schema.py`, verifier rules, gated / ungated prompts cover them; metrics per claim type; extraction accuracy (shoreline RMSE in m, class-transition agreement κ with the labels) | 4, 14 | 10 | P2 (prompts) + P3 (schema, verifier rules) | **in progress**: `land_cover` claim type + verifier rule **done** by P3 2026-10-22 (public #16). Left: `shoreline`, `coastal_built`, and P2's prompts |

**Order matters for the evaluation.** Phase 4's report prompts must be frozen **after** Phase 9 and
the Phase 15 schema exist, because the frozen prompts have to cover the new claim types. Phase 4
work that doesn't depend on them (VLMClient, server notebook, the region check) carries on.

Total remaining ≈ 150 h on 2026-10-19 (179 h planned on 2026-10-11, minus Phase 4 / 7 / 13a work done since):
roughly P2 ≈ 77 h (including Phase 14, moved from P1 on 2026-10-23) and P3 ≈ 55 h, plus the write-up together. If P3 slips, the core results
still happen; the cut order below applies (7c, then 10b and 12 are the first extras to go). Decided 2026-10-08: add the hours rather than
cut scope. If something must give later, cut the D7 candidate check first, then 7c's VLM side.
Labelling is done; a second labeller on the remaining 20 sites is optional (≈40 min).
Re-plan trigger: Phase 4 not finished by end of week 6.

### Phase-1 rework (implemented in Phase 2)
- `agents/nodes.py`: `AOI_BOUNDS` is hardcoded to Quang Ninh. Derive bounds, the published
  AOI and mock geometry from `state["aoi"]`.
- `agents/tools.py`: mock `change_frac` divides by `24830` ha (the Quang Ninh box area).
  Use the requested AOI's area.
- `agents/graph.py`: AOI check accepts any `type` + `coordinates`, including a Point.
  Replace it with `schema.validate_aoi()`: Polygon/MultiPolygon, valid ring, lon/lat
  range, area 1–500 km².
- `tests/test_pipeline.py`, `tests/test_webapp.py`: test AOI is a Point. Change it to a Polygon.
- `webapp/backend/data_store.py` + `main.py`: one global `change_regions.json` and
  global region ids. Becomes a per-run store in Phase 6. `evidence_for()` AOI area from
  a lat/lon bbox → geodesic area of the run's AOI.
- `docs/decisions.md` D3: `mean_conf` note referred to a trained model. It's now defined by D6.
- `README.md`, `schema.py` docstring: mention OSCD. Remove. (Done.)

Found in the rev-2 audit (2026-09-27), not in the list above:
- **Dates vs windows.** `state.py`/`graph.py`/`tools.py`/`run_pipeline()` and the tests take one
  `date_before`/`date_after` string. Earth Engine composites need windows. Change the
  pipeline input and the API to `before_window`/`after_window` (`[start, end]`) and validate them
  (start < end, windows don't overlap, ≤ 12 months each).
- **One Quang Ninh study config.** The windows disagree today: Person1 notebook = calendar 2018
  vs 2022 with QA60 masking; labeling notebook = dry-season Nov–Mar with SCL; `run_demo.py`/tests =
  2018-01-01 → 2022-06-01. Put the QN AOI + windows + thresholds in one file
  (`data/quangninh/study.json`). `ee_engine.py`, the CLI scripts and the tests read it. The
  labeling notebook copies it and checks it against the regions file's `metadata`.
- **No region cap in the extraction.** The Person1 notebook keeps `MAX_REGIONS = 5`. Labeling
  needs ≥ 20 detected regions spread over sizes, so `ee_engine.py` writes **all** regions ≥
  `MIN_AREA_HA`. The FeatureCollection gets a top-level
  `metadata: {before_window, after_window, thresholds, code_version, aoi}`. The app can cap what it
  *displays*, but not what is written.
- **`location` relative to the run's AOI.** The Person1 notebook's `where_in_aoi()` uses the
  QN bounds. Move it into `ee_engine.py` and pass it the run's AOI bbox.
- `agents/tools.py` `query_scenes()` has its own AOI check that also accepts a Point, and
  `nodes._region_polygon()` also divides by `24830`. Both go when the EE path lands.
- `import_geojson.py` writes the single global store. In Phase 6 it becomes "import as the QN
  run".
- `notebooks/EviChange_Person1_starter.ipynb`: the placeholder `mean_conf` is obsolete
  (the "train a model on the old dataset" steps are removed). `ee_engine.py` replaces the
  notebook's extraction. Mark the notebook superseded rather than maintaining two extractors.
- `notebooks/EviChange_Person2_starter.ipynb`: now pulls practice chips from Earth Engine
  (5 sites near Cam Pha, threshold evidence). Switch its sites/evidence to `ee_engine.py`
  regions once Phase 2 lands. (Done: no dataset download left.)
- Phase 7 cleanup: `app.js` `HOME` view and `demo_data.py` are QN-specific. That's fine as a
  default view, but the map should fit to the run's AOI.
- Unchanged and still valid: `schema.py` contract, `verifier.py`, `report.py`, the bridge,
  the tests' verifier cases.

## Evaluation (rev 2: self-labelled Quang Ninh, n ≈ 30 sites)

**Ground truth (Phase 3, before any claims exist).** 30 sites = 20 detected regions
(spread across the size range) + 10 random background sites (≥200 m from any detection).
They are shuffled with anonymous ids. For each site you label, from before/after
true-colour and SWIR chips only:
- `change_occurred`: yes / no / unsure
- `change_types`: multi-select from `schema.CHANGE_TYPES` + other
- `mining_related`: yes / no / unsure (visual only; legality is never labelled)
- your confidence

You don't see index values, detector output, or whether a site is detected or random.
Relabel 10 sites after ≥7 days to get self-agreement κ. If a second labeler is available,
they label all 30 (≈1 h) to get inter-rater κ, which is stronger.

**Claim adjudication (Phase 5, after the claims exist).** Every claim from all 3
conditions is shuffled, with the condition hidden, and judged against that site's
ground-truth label and chips:
- **truth:** `true` / `false` / `unverifiable-from-imagery` (e.g. legality, future)
- **evidence support:** `supported` / `unsupported`, judged against the evidence JSON
  the system had

That gives two independent axes, so nothing is scored by the same rules that produced it.

**Metrics (per condition, with Wilson 95% CIs for pooled proportions):**
1. **Hallucination rate** = claims false or unverifiable (per ground truth) / claims
   emitted. **Primary metric.**
2. **Post-gate hallucination rate**: the same, restricted to claims the verifier passes.
   This is what a user actually sees. **Headline number.**
3. **Unsupported-by-evidence rate** (human judgement on the support axis).
4. **Faithful-but-false rate**: claims supported by the evidence but false per ground
   truth. These are detector/evidence errors, not generation errors. Gated can only
   be as right as its evidence, so this separates the two error sources.
5. **Verifier:** catch rate (recall on false + unverifiable), precision, and κ against
   human support labels.
6. **Informativeness:** true claims per site; ground-truth change-type recall per site;
   abstention rate. This stops "gated wins by saying nothing".
7. **Detector:** precision = share of detected sites labelled as change; background
   change rate = share of random sites labelled as change (a rough miss estimate).
8. Parse-failure rate; self-agreement (and inter-rater) κ.

**What each condition sees at a site.** At a detected site, all 3 conditions get the same
before/after chips. The template and gated conditions also get that region's evidence JSON.
At a random site, the evidence is an empty region list (`change_frac` = 0 inside the box). A
random site therefore tests hallucinated change where none was detected: gated should abstain,
while ungated can still invent change. Report the detected and random strata separately, as
well as pooled.

**Statistics.** n = 30 is a pilot-scale sample.
- **Pre-specified primary comparison:** post-gate hallucination rate, gated vs ungated.
  Template is a reference, and its comparisons are secondary.
- **Pre-specified secondary comparison (D16):** post-gate hallucination rate, gated (Qwen) vs
  ungated GPT, with the same site-level bootstrap and paired tests as the primary comparison.
- Claims are clustered within sites (several per site). Pooled claim-level rates get a
  **site-level cluster bootstrap 95% CI** (resample sites, 10 000 reps), not Wilson. Wilson
  is only for site-level proportions (detector precision, background change rate).
- Paired per-site test: per-site hallucination *count* and rate, gated vs ungated, with exact
  Wilcoxon signed-rank + sign test. Sites where a condition emits 0 claims have no defined
  rate. Report how many there are, compare counts on all 30, and compare rates only on sites
  where both conditions emitted claims.
- Only large effects are detectable (for example, gated better on ≥ 18 of 25 sites with
  differences for p < 0.05). Report the effect size with its CI, not only p.
- The label's unit is the site's **box**. A claim is adjudicated against what's inside the
  box.
- Full per-site table in the appendix.

**Prompt hygiene.** Prompts are developed only on detected Quang Ninh regions outside
the 30 labelled sites. They are frozen (pinned by commit) before the 30 sites are run.

**Reporting.**
- Frame it as "a Quang Ninh case study with self-labelled ground truth (30 sites)",
  with no generalisation beyond the AOI and period.
- The general-AOI app is described as a tool capability, with no validation outside
  Quang Ninh.
- Limitations to state: single labeller (unless a second one joins), 10 m resolution,
  one date pair, a threshold detector that shares indices with the evidence.

## Advisor items (raise now)
1. Team of three again (2026-10-19): reset milestone dates. With the extension (Phases 9–15), Phase 4
   will miss the week-6 re-plan trigger; agree new dates and the owners above.
2. Ground truth is self-labelled, 30 sites, pilot framing. Is a second labeler (~1 h) possible?
3. Title says "unlicensed": is concession-boundary data available? Otherwise reframe to "mining-related".
4. The multi-agent pipeline + general-AOI app is a core deliverable (was optional).
5. The detector is an index-threshold baseline (no training data). Confirm that's acceptable.
6. Old schema deprecated (`decisions.md` D1).
7. Prompted change search (D7): the VLM steers search and checks candidates, the detector
   still finds every region. Capability only, not evaluated. Confirm the scope is fine.
8. Map assistant (D9): natural-language actions on the map, like ArcGIS Pro's AI assistant.
   A tool capability, not evaluated. Confirm it's in scope.
9. Teacher feedback (2026-10-08) is in Phases 9–15: Dynamic World classes, monthly change,
   shoreline + coastal buildings, Planet later, and an extended evaluation. Confirm (a) the 24-month
   window, (b) that monthly land-cover maps may only cover the dry season (D11), and (c) that tide
   is reported as an uncertainty rather than corrected (D11).
10. Time series analysis (D14): CCDC on Sentinel-2, with Planet for monsoon months and detail rather
   than as the time series source (short history, no SWIR, sensor mix). Confirm (a) CCDC is the
   method wanted (vs LandTrendr / BFAST or a general monthly series), and (b) that this Planet role
   is acceptable.
