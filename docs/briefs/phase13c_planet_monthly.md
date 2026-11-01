# Phase 13c: Planet maps, shoreline corroboration and Geo-VLM chips

Implemented 2026-11-01 (D12). Monthly maps, shoreline corroboration and the app's
Planet Geo-VLM chip workflow are wired. Actual corroboration of changes through
2026 still requires the undelivered 2026 mosaics. Qwen inference requires a
running Geo-VLM server; none was configured on this machine during validation.

## Repository review

- `main` contains 90 reports in `data/reports_sites.jsonl`: 30 template, 30 gated,
  30 ungated. The Phase 4/5 runner is already implemented. Human adjudication and
  Phase 14 reference labels remain on the evaluation's critical path; this change
  does not produce those judgements or change the frozen report inputs.
- The monthly/coast panel and shoreline slider have landed. Planet mosaics were
  readable by `agents/planet.py` but were not selectable on the monthly map.
- A live read of the Earth Engine collection confirmed 11 mosaics, October 2024
  through September 2025, excluding February 2025. An order in `orders.json` is
  not treated as proof of delivery.

## Delivered

The Monthly & coast layer selector now offers Planet true colour, NIR false
colour, NDVI and NDWI on the existing calendar-month slider. Images are masked
to UDM2 clear pixels, clipped to the study AOI, and carry Planet attribution.
The panel shows the actual acquisition date, 3 m resolution and mosaic-wide
clear share. Missing months remain explicit gaps; changing the date removes
the previous image immediately, and stale requests cannot replace a newer one.

- `GET /api/planet/months`: live collection metadata (month, acquisition date,
  clear share, asset id), source, resolution and attribution. Access errors are
  reported as errors, rather than a successful empty inventory.
- `GET /api/planet/layer?month=2025-06&layer=rgb`: tiles plus the same metadata.
  Layers: `rgb`, `nir`, `ndvi`, `ndwi`. Missing months return 404.
- Catalog and tile responses are cached for one hour, matching the existing
  Earth Engine tile expiry policy. Failed requests are not cached.

Planet supplies imagery for visual inspection during Sentinel-2's cloudy months.
It does not infer Dynamic World classes in those gaps, replace Sentinel-1 water
statistics, or modify report evidence or prompts. Planet has no SWIR, so NDBI
and MNDWI are not offered.

## Validation

- Full Python/node-backed suite: 553 tests passed (527 before the shoreline / chip continuation).
- JavaScript syntax checks for the changed app, monthly, shoreline and Geo-VLM
  scripts and `git diff --check` passed.
- Live Earth Engine/API check: all four June 2025 visualisations returned HTTP
  200 and PNG tile bytes; acquisition date 2025-06-01, clear share 0.8671.
  February 2025 returned 404.
- Browser check: selecting Planet true colour displayed October 2024 imagery,
  acquisition date and attribution. Moving the slider to February 2025 removed
  that image and displayed the explicit missing-mosaic gap.
- Browser continuation check: the separate October 2024 Planet shoreline overlay
  showed 411 valid positions and its acquisition date; September 2026 showed an
  optical gap. Geo-VLM displayed the delivered acquisition dates and RGB/NIR
  options while clearly reporting the disconnected model server.

## Shoreline corroboration

Run `.venv/Scripts/python.exe scripts/make_planet_shoreline.py` after adding any
new delivered mosaics. It saves resumable, fingerprinted batches under the
gitignored `data/planet/shoreline_cache/`, then writes separate derived results
to `data/quangninh/shoreline/planet.json`.

Planet NDWI > 0 is sampled at 3 m on the fixed Phase 11 transects. The existing
sea-connected walk keeps a physical 30 m land run; the sampled profile needs
80% clear coverage, with no cloud gap from 100 m landward of the edge to the
seaward end. This is sampling resolution, not a measured accuracy claim.
The 81 Phase 14 reference transects and neighbours are excluded before sampling;
API summaries, lines and details reapply the current lock as well.

Corroboration compares the median of at least two valid monthly positions in
each of the **first and last radar quarters** (Oct–Dec 2024 and Jul–Sep 2026).
The optical shift must be at least 20 m in the significant radar trend's
direction. Missing endpoint positions stay `pending_coverage`; tidal flats stay
`tidal_uncertainty`. Single-day Planet waterlines are not tide-corrected, and
the median is not treated as tide correction or an independent validation.
Published radar / Sentinel-2 classes and frozen box evidence are unchanged.

The live run produced **2,872 usable positions across 654 visible transects**
and 11 delivered months. The 26 visible significant radar trends all remain
pending because the 2026 endpoint is missing; the other 628 visible transects
have no significant radar trend. No Planet-confirmed trend is claimed.

`GET /api/shoreline/planet` serves coverage and status counts;
`GET /api/shoreline/planet/lines?month=YYYY-MM` serves guarded optical lines.
Existing transect details add a separate `planet` series and confirmation.
The Monthly shoreline panel shows an orange Planet line and acquisition dates,
alongside the original radar series, with explicit missing-month gaps.

## Planet Geo-VLM workflow

In Find changes, choose **Planet** as source, then two delivered acquisition
dates and true colour or true colour + NIR. Requests use `/api/vlm/check` with
`source=planet`, `before_month`, `after_month`, and `chips=planet_rgb` or
`planet_rgb_nir`. Missing / reversed pairs and SWIR chip requests are rejected.
At least half the requested box must be clear on each date; otherwise no model
judgement is requested. Locked evaluation sites and Phase 14 shoreline references
are blocked before rendering or sending chips.

`agents/planet_vlm.py` has its own `planetcheck_v1` prompt and replay identity.
Cache / log identities include the source, collection, acquisition metadata,
framing, image set and model. Sentinel-2 prompt bytes and report evaluation
inputs stay unchanged. When acquisition dates are outside the detector's windows,
the result is `different_period`, is not compared with the detector, and never
hides a detection. Source/date changes and switching runs clear old UI results;
late replies cannot populate the new context.

Real January / September 2025 RGB and NIR chips rendered as PNGs, and the sample
box was fully clear on both dates. API tests use a local model server; no actual
Qwen inference is claimed without a configured server.

## Remaining data and operational steps

1. Deliver and upload the missing months, including the 2026 endpoint, then
   rerun the resumable shoreline command. Ordering remains a separate,
   quota-confirmed operation under D12.
2. Start the existing Colab Geo-VLM server, set `VLM_URL` / `VLM_TOKEN`, restart
   the app and run checks with the chosen Planet dates. These app checks remain
   unvalidated and separate from the frozen report comparison.
3. Finish human adjudication and Phase 14 reference labels before claiming
   validated shoreline accuracy or changing the blind locks.
