# EviChange build plan (rev 2)

Team of three since 2026-10-05: Person 1 detector + labels, Person 2 VLM (Phases 4, 7c model side),
Person 3 app + verifier (Phases 6, 7, 7b). Before that, solo from the start of week 4 (≈125 h).
Defaults: this repo is canonical; Qwen2.5-VL-7B-Instruct for every reported run.

**Rev 2 changes (2026-09-26):** (1) no OSCD. Imagery comes from Earth Engine for
Quang Ninh, and the ground truth is a self-labelled set of ~30 sites. (2) The app and
backend accept any AOI + date range and run the Earth Engine analysis on demand. Only
Quang Ninh results are validated. See `decisions.md` D4–D5.

## Phases

| # | Phase | Depends on | Est. h | Status |
|---|---|---|---|---|
| 1 | Consolidate repo, one schema, real verifier, EE smoke test | — | 8 | **done** (EE smoke test waits on your project id) |
| 2 | **Earth Engine engine for any AOI.** Phase-1 rework (below); `agents/ee_engine.py` (SCL composites, indices, change mask, vectorised regions, real `mean_conf`); AOI validation + size cap; `tools.py` mock/EE switch; produce the Quang Ninh regions (now `change_regions_quangninh_v3.json`, D6) | 1 | 14 | **done** |
| 3 | **Ground-truth labelling.** `notebooks/EviChange_labeling.ipynb`: 30 blind sites + a second labeller on 10 (inter-rater κ 0.63); `data/quangninh/labels/` | 2 | 4 | **done** (2nd labeller on all 30 recommended) |
| 4 | **Real VLM.** `VLMClient` (hf / http / replay); develop prompts on detected QN regions **outside** the 30 labelled sites; freeze; run 3 conditions on the 30 sites. Also the two prompted-search tasks (D7): prompt → `SearchSpec` (+ schema validation) and candidate check `match`/`no_match`/`unsure`; their prompts are separate and not part of the freeze | 2, 3 (labels done first) | 18 | |
| 5 | **Evaluation.** Claim adjudication page (condition hidden), `eval/metrics.py`, results tables | 3, 4 | 10 | |
| 6 | **On-demand runs API.** `POST /api/runs` (AOI + before/after date windows) → background job running the agent pipeline on Earth Engine; `GET /api/runs/{id}` polling; per-run data store; cache; AOI cap | 2 | 12 | **done** |
| 7 | **App.** Draw/search AOI, date pickers, run + progress state, per-run layers, "not validated outside Quang Ninh" banner, verdict reasons, export, cleanup. **Prompted search (D7):** "Find changes" chat calls the VLM (keyword parser as fallback), confirm-before-run for new dates/AOI/options, candidate-check results with "show rejected" toggle and "VLM-checked, not validated" label | 6 | 24 | |
| 7b | **GIS tools (D8).** (a) Symbology by attribute + legend, scale bar, north arrow; (b) index rasters from Earth Engine (before/after/difference NDVI, NDBI, MNDWI) as tile layers; (c) geoprocessing (buffer, clip, intersect, dissolve) + select by attribute / location; (d) linked charts, layer export (GeoJSON / CSV / KML) + print layout (PNG/PDF). Owners: (b) Person 1 backend + Person 3 layer; the rest Person 3 | 7 (b also 2) | 28 | **done** |
| 7c | **Map assistant (D9).** The "Find changes" chat becomes an ArcGIS Pro-style assistant: typed requests become validated actions that drive the existing tools — style layer (symbology), select / filter by attributes or location, geoprocessing (buffer, clip, intersect, dissolve), add index layer, chart, export, change search and new runs (D7). Each action shows what it ran (query / tool chain) with Undo; runs need confirmation. Keyword parser first, then the Phase 4 VLM produces the same actions. Owners: Person 3 actions + UI, Person 2 VLM side | 7b; VLM side 4 | 12 | |
| 8 | Write-up + advisor demo | 5, 7 | 14 | |

Total remaining ≈ 78 h (Phases 4, 5, 7, 7c, 8), split across three people. If time runs short,
cut the D7 candidate check first, then 7c's VLM side (the keyword assistant still works).
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
1. Now solo: reset milestone dates.
2. Ground truth is self-labelled, 30 sites, pilot framing. Is a second labeler (~1 h) possible?
3. Title says "unlicensed": is concession-boundary data available? Otherwise reframe to "mining-related".
4. The multi-agent pipeline + general-AOI app is a core deliverable (was optional).
5. The detector is an index-threshold baseline (no training data). Confirm that's acceptable.
6. Old schema deprecated (`decisions.md` D1).
7. Prompted change search (D7): the VLM steers search and checks candidates, the detector
   still finds every region. Capability only, not evaluated. Confirm the scope is fine.
8. Map assistant (D9): natural-language actions on the map, like ArcGIS Pro's AI assistant.
   A tool capability, not evaluated. Confirm it's in scope.
