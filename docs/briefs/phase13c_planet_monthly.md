# Phase 13c: Planet monthly map integration

Started 2026-11-01. This is the first deliverable of Phase 13c (D12); shoreline
confirmation and Geo-VLM chip integration remain to be done.

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

- Full Python/node-backed suite: 527 tests passed (513 existing + 14 new).
- `node --check webapp/frontend/monthly.js` and `git diff --check` passed.
- Live Earth Engine/API check: all four June 2025 visualisations returned HTTP
  200 and PNG tile bytes; acquisition date 2025-06-01, clear share 0.8671.
  February 2025 returned 404.
- Browser check: selecting Planet true colour displayed October 2024 imagery,
  acquisition date and attribution. Moving the slider to February 2025 removed
  that image and displayed the explicit missing-mosaic gap.

## Remaining Phase 13c work

1. Add Planet-derived shoreline positions as an independent optical check,
   preserving Phase 14 transect guards, per-sensor provenance and tide caveats.
   Confirmation after March 2026 requires the undelivered 2026 months.
2. Add Planet before/after chips to the app's Geo-VLM workflow with explicit
   acquisition dates and a separate source/prompt identity. Keep the frozen
   Sentinel-2 evaluation separate.
3. Add newly delivered mosaics as they arrive. Ordering remains a separate,
   quota-confirmed operation under D12.
