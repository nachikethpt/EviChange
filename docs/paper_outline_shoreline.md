# Paper outline: shoreline change in Quang Ninh (draft, 2026-10-28)

**Why this outline.** On 2026-10-28 the professor asked for the paper to focus on the shoreline. This outline
centres it there. The existing `docs/paper_draft.md` (evidence-gated VLM claims) is not changed. Its
comparison becomes Section 6 here, or a second paper; that is decided with the professor.

Numbers marked *(first run)* come from the 2026-10-28 yearly run (D11) and change if the method changes.
**[TBD]** = not measured yet.

## Working title

*Ten years of shoreline change on a reclaimed coal-mining coast: tide-averaged Sentinel-1 shorelines,
optical confirmation and a reference check, Quang Ninh, Vietnam (2015–2026)*

## 1. Introduction

- Quang Ninh's coast: coal ports, land reclamation, aquaculture, mangroves, wide tidal flats; Ha Long Bay nearby.
- Why shoreline change matters there: reclamation for ports and towns, erosion, loss of mangroves and flats.
- Problems with satellite shorelines on such a coast: clouds (optical), tides (several metres of range, wide
  flats), and short records.
- Research questions:
  1. How did the shoreline move from 2015-16 to 2025-26, and where?
  2. How accurate are tide-averaged Sentinel-1 shorelines against shorelines traced on high-resolution imagery?
  3. How much does optical confirmation (Sentinel-2) change which transects are called advancing or retreating?
  4. How does a short monthly record (24 months) compare with ten dry seasons for detecting change?

## 2. Study area and data

- Area of interest: the Quang Ninh study area, coastline 2024–26 baseline, 735 transects every 100 m.
- Sentinel-1 VV (all seasons), Sentinel-2 SR (from 2016-17 over the area), Dynamic World for coastal land cover.
- Reference: Google Earth Pro historical imagery (looked at only), Planet 3 m for 2024–26 when delivered (D12).

## 3. Methods (from `agents/shoreline.py`; details in D11, D13)

1. Sea mask and baseline from monthly radar water occurrence; transects 300 m landward, 500 m seaward.
2. Shoreline position per transect: the landward edge of sea-connected water, sampled every 10 m.
3. **Yearly mode:** one tide-averaged radar shoreline per dry season (water in ≥ half of the season's looks),
   2015-16 to 2025-26, plus the season's optical (MNDWI) shoreline.
4. Rate: linear regression over the seasons with a 95 % CI; advancing / retreating only when the CI excludes 0.
5. Confirmation: the optical shoreline must move the same way by ≥ 20 m.
6. Monthly mode (24 months) for comparison: tidal spread, quarterly rates.
7. **Accuracy:** 30 reference transects (seeded, spread along the coast), traced blind on Google Earth for 4 dry
   seasons (2016-17, 2019-20, 2022-23, 2025-26). Metrics: bias, RMSE, MAE, share within 20 / 30 m. A second
   labeller for agreement **[TBD: P1?]**. Planet 3 m check for 2024–26 **[TBD]**.
8. Coastal buildings: built-up area in the 0–200 m and 200–500 m strips (Phase 12) as context for reclamation.

## 4. Results

- 4.1 Shoreline change 2015–2026 *(first run)*: 34 transects advancing (up to +41 m/yr), 4 retreating (to
  −46 m/yr), 446 stable, 45 unconfirmed, 206 with too few positions. Map figure: the slider's yearly lines and
  coloured transects. **[TBD: lengths of coast per class, rates per stretch.]**
- 4.2 Case studies: transect t0133, about 290 m seaward around 2019-20 with radar and optical agreeing
  (likely port reclamation) **[TBD: confirm on Google Earth / Planet; 1–2 more cases, one retreating]**.
- 4.3 Accuracy against the reference shorelines **[TBD: bias, RMSE per season]**.
- 4.4 Effect of optical confirmation: 45 radar trends not confirmed *(first run)*; why (clouds, flats, aquaculture).
- 4.5 Monthly vs yearly: 24 months found 5 advancing, 0 retreating; tidal spread per transect.
- 4.6 Built-up change near the shore **[TBD from Phase 12]**.

## 5. Discussion

- What drives the changes (reclamation, ports, aquaculture, erosion) — stated as interpretation, not measured.
- Tide-averaging versus single images; limits on wide flats.
- Transects laid on the 2024–26 coast: positions missing where the coast moved beyond their reach (`too_few`).
- Reference limits: Google Earth image dates and tides vary; one labeller built the method.

## 6. (Optional) Making shoreline claims checkable

The EviChange evidence-gated report (D16, D19) as an application: shoreline statements a VLM makes, checked
against the transect statistics. Either a short section here or the separate paper in `docs/paper_draft.md`.

## 7. Conclusion

## Figures and tables (planned)

1. Study area with transects coloured by change (2015–2026).
2. Yearly shorelines at 2–3 sites (the slider's lines) with Google Earth / Planet backdrops.
3. Position series for t0133 and a retreating transect (radar and optical).
4. Accuracy: scatter of extracted vs traced positions, per season.
5. Table: change counts and rates; monthly vs yearly.

## Next steps

1. Trace the 30 reference transects on Google Earth (`shoreline_ge_p2.html` + `.kml`), then
   `scripts/shoreline_reference_ge.py --score`.
2. Show this outline to the professor; decide Section 6.
3. Planet months for the 3 m check (`notebooks/EviChange_planet_to_ee.ipynb`).
