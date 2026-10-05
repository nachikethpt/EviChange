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

## D6 — `mean_conf` for the threshold detector (rev 2, proposed)

No trained model means no probability. `mean_conf` becomes the **index-agreement
fraction**: the share of the region's pixels where at least 2 of the 3 index deltas
exceed `T_IDX`. It's in [0, 1], has a plain meaning ("how consistently the indices agree
this is change"), and is computed server-side in Earth Engine. The field name stays for
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
- Geoprocessing outputs are new user layers. They never change a run's change regions, and
  regions derived from them carry no `mean_conf` and don't go to the AI report as evidence.
- Exports keep attribution (EOX for the Sentinel-2 mosaics, Copernicus for Earth Engine data)
  and the "not validated outside Quang Ninh" note for non-QN runs.
