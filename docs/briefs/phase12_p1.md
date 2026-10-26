# Phase 12 brief: buildings near the shoreline (P1)

**Owner:** P1, from 2026-10-26 (moved from P3). **Estimate:** ≈ 8 h.
**Due:** 2026-11-02. If it isn't merged by then, it goes back to P3.
**Spec:** `docs/PLAN.md` row 12 and `docs/decisions.md` D11 ("Buildings near the shoreline") and D13.

## What to build

Built-up area near the Quang Ninh coast from Dynamic World (`GOOGLE/DYNAMICWORLD/V1`, class `built`),
in two strips measured landward from the Oct 2024 shoreline: **0–200 m** and **200–500 m**.

1. **Strips.** Buffer the Phase 11 baseline (`data/quangninh/shoreline/baseline.geojson`, the Oct 2024
   shoreline) landward. Keep land only: drop the sea side using the Phase 11 sea polygons
   (`shoreline.sea_polygons`). Check the strips on the map before going on.
2. **Monthly series.** Built hectares per strip per month, Oct 2024 – Sep 2026, using the month
   windows and the clear-sky rules in `agents/monthly.py` (`month_windows`, `class_image`,
   `class_status`). Months without a clear look are gaps, not zeros. Also give one figure per dry season
   (`monthly.dry_seasons`), because single months are noisy.
3. **New built patches.** Pixels that are built in the last dry season but not the first, inside the
   strips, vectorised as regions with `area_ha`, like the Phase 2 change regions.
4. **Pre-period reference.** Open Buildings temporal (`GOOGLE/Research/open-buildings-temporal/v1`,
   yearly to 2023), built area per strip per year. Reference only; it is not part of the evaluation.
5. **Box evidence between two windows (needed by Phase 15).** The evaluation compares each box's two
   detector windows (QN: Nov 2018 – Mar 2019 vs Nov 2022 – Mar 2023), not 2024–26. For a given pair of
   windows, compute per strip the built area in each window (Dynamic World mode label over the window)
   and save it the way `scripts/make_shoreline_windows.py` does for transects (that script arrives with
   P2's Phase 15 coast-window PR; do steps 1–4 first if it isn't on `team/main` yet). Then add a function that
   returns, for one box, a list in the `coastal_strips[]` format below, clipped to the box. P2 wires it
   into `agents/site_evidence.py`.

## Output format (already fixed, don't change)

`agents/schema.py` (`STRIP_FIELDS`, `validate_strip`) and the verifier (`agents/verifier.py`,
`_check_coastal_built`) already expect:

```json
{"strip": "0-200", "built_ha_before": 3.4, "built_ha_after": 5.1, "location": "north-east"}
```

`strip` is `"0-200"` or `"200-500"`; areas in ha, ≥ 0; `location` optional (one of `schema.LOCATIONS`).
Run `schema.validate_strip` on everything you write.

## Suggested layout

Copy the pattern of the Phase 10 / 11 code:

- `agents/coastal.py`: pure helpers (unit-tested) plus the Earth Engine functions
- `scripts/make_coastal.py` (monthly + patches + Open Buildings), `scripts/make_coastal_windows.py` (step 5)
- outputs in `data/quangninh/coastal/`
- `/api/coastal*` endpoints next to `/api/shoreline*`, so that P3 can draw the strips and charts
- `tests/test_coastal.py`: helpers and the API on a small fixture, no Earth Engine calls

## Rules

- **Blindness (Phase 14 c).** P2 labels 30 coastal cells as built / not built from imagery. Don't share
  per-cell or per-site numbers with P2 before the labels are in. Aggregate strip totals are fine.
- At 10 m single houses don't show up: report **built area**, never building counts (D11).
- Add a short "As implemented (Phase 12)" paragraph to D11 in `docs/decisions.md`, with the
  thresholds you chose.
- Work on a branch from `team/main` and open a PR on the public repo. Run `pytest` before pushing.

## Done when

- strips, monthly / dry-season series, patches and Open Buildings figures exist for Quang Ninh
  in `data/quangninh/coastal/`, with QN totals quoted in the PR;
- the window function returns valid `coastal_strips[]` for the D15 development boxes;
- tests pass and the PR is merged.

Ask P2 about anything in the evidence format or the window logic.
