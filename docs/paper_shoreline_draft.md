# Ten years of shoreline change on a reclaimed coal-mining coast: tide-averaged Sentinel-1 shorelines, optical confirmation and a reference check, Quang Ninh, Vietnam (2015–2026) (draft)

**Status:** first full draft, 2026-11-04, written from `docs/paper_outline_shoreline.md`. Methods and the
results that already exist are written out. **[TBD]** marks what waits on the Phase 14 (b) reference
shorelines, which stay blind until all labellers have finished (D13), or on a decision with the professor.

**Sources of numbers.** Every number comes from a committed output: the yearly run (`data/quangninh/shoreline/years.json`,
D11 "Yearly shorelines"), the monthly run (`summary.json`, D11), the Planet comparison (`planet.json`, D12
"Year-2 rerun", 2026-11-02) and the coastal strips (`data/quangninh/coastal/`, D11, Phase 12). Rerunning a
script changes them; quote them from the file at the paper's commit.

**Citations** carry the verification tags of `docs/related_work.md`: **[V]** checked, **[PK]** from memory and
**to be checked before submission**, **[U]** do not cite until checked. The shoreline literature review (P1,
`docs/briefs/shoreline_literature_p1.md`) replaces these as it lands.

**Blindness.** The 30 reference transects and their same-line neighbours (81 transects) are hidden in the app
and left out of the Planet comparison until the reference tracings are in. The counts below are over all 735
transects and were computed by the scripts, not read transect by transect. No statement here about a single
transect concerns a reference transect.

---

## Abstract (skeleton)

Quang Ninh's coast mixes coal ports, spoil dumped into the sea, reclaimed town land, aquaculture ponds,
mangroves and wide tidal flats, and the published record of how it moved is Landsat-scale and mostly ends
before 2020. We map ten dry seasons of shoreline (2015-16 to 2025-26) on 735 shore-normal transects along
90 km of coast, from **tide-averaged Sentinel-1 radar shorelines** (water in at least half of a season's looks),
and call a transect advancing or retreating only when (i) the linear-regression rate's 95 % confidence
interval excludes zero and (ii) the season's Sentinel-2 optical shoreline moved the same way by at least
20 m. Of 529 transects with enough seasons, 34 advance (median +12 m/yr, up to +41 m/yr), 4 retreat and 446
are stable; 45 radar trends are not confirmed by the optical shoreline. A 24-month monthly series on the
same transects finds only 5 confirmed changes, mostly tide. Against PlanetScope 3 m shorelines (23 months,
2024–26) the tide-averaged yearly line lies a median 22.5 m away (48 % within 20 m). Against shorelines
traced blind on high-resolution imagery at 30 random transects for 4 seasons, the yearly shorelines have a
bias of **[TBD]** m and RMSE of **[TBD]** m. **[TBD: one-sentence takeaway once the accuracy is known.]**

## 1. Introduction

Quang Ninh, in north-east Vietnam, holds most of the country's coal. Its coast between Ha Long and Cam Pha
carries the infrastructure of that industry, coal ports, conveyors and stockyards, next to towns that have
grown onto land taken from the bay. Landsat studies document the pattern: waste rock dumped into the sea
replaced water at Cam Trung and Cam Thinh (Nguyen et al. 2022, [V]), and Ha Long's urban area in 2023 was more
than four times its 2000 extent, with land reclaimed from the bay a significant part of the growth (Vu et al.
2024, [V]). Across Vietnam, about half the coast showed no significant change over 1986–2021, with the
fastest accretion, up to +47 m/yr, mostly on artificial coasts (Lappe et al. 2022, [V]). Globally, land
gained from the sea exceeds land lost, largely through reclamation in East Asia (Mentaschi et al. 2018, [PK]).

Quang Ninh's own shoreline record is thin. The only Cam Pha shoreline study compares a 2018 Sentinel-2
coastline with a 1999 map and finds accretion-dominated change (Duong Thi Loi et al. 2021, [V]). No
Sentinel-1 shoreline series for any Quang Ninh coast, and no transect-based (DSAS-style) analysis of Ha Long
or Cam Pha after 2018, was found in the literature review (`docs/related_work.md`).

Three properties of this coast make satellite shorelines hard:
1. **Clouds.** The monsoon (about April to September) leaves few clear optical looks, so optical series
   have gaps of months (D11).
2. **Tides.** The tidal range is several metres **[TBD: sourced figure; the review's 3–4 m spring range at
   Hon Gai is unsourced]** and the flats are wide, so a single image's waterline can sit hundreds of metres
   from another's at a different tide. Tide-correcting or tide-averaging is standard practice for this
   reason (Boak & Turner 2005, [PK]; Bishop-Taylor et al. 2021, [PK]).
3. **Short, dense records versus long, sparse ones.** Monthly series show the tide more than change; ten
   years of one line per season show change but say little about when within a year it happened.

Radar sees through cloud, and averaging many radar looks over a season averages the tide out to roughly
a mid-tide line. This paper asks:
- **RQ1.** How did the shoreline move from 2015-16 to 2025-26, and where?
- **RQ2.** How accurate are tide-averaged Sentinel-1 shorelines against shorelines traced on
  high-resolution imagery?
- **RQ3.** How much does optical confirmation change which transects are called advancing or retreating?
- **RQ4.** How does a 24-month monthly record compare with ten dry seasons for detecting change?

**[TBD with the professor: whether Section 6 (checkable shoreline claims) stays here or is the separate
paper in `docs/paper_draft.md`.]**

## 2. Study area and data

**Area.** The Quang Ninh study area of EviChange (`agents/study.py`), about 250 km² covering the coast from
Ha Long to Cam Pha. The baseline (§ 3.1) is 90.2 km long, coast and islands.

**Sentinel-1.** C-band SAR, VV polarisation, interferometric wide swath, every look over the area from
October 2015 (Earth Engine `COPERNICUS/S1_GRD`). Radar is the only source with looks in every month.

**Sentinel-2.** Surface reflectance with the scene classification cloud mask (`COPERNICUS/S2_SR_HARMONIZED`),
dry seasons from 2016-17 (surface reflectance doesn't cover 2015-16 over the area). Used for the optical
shoreline that confirms radar trends.

**PlanetScope.** 8-band surface reflectance harmonised to Sentinel-2, one clear day per month, 3 m, for
October 2024 to September 2026 (23 months; July 2026 not ordered) (D12). Used only as a check of where the
radar line sits, since one day is one tide level. Imagery © Planet Labs PBC; neither scenes nor mosaics are
redistributed.

**Reference imagery.** Google Earth Pro's historical high-resolution imagery, looked at only, to trace
reference shorelines (§ 3.6).

**Dynamic World** (10 m, near-real-time land cover) for the built-up area in coastal strips (§ 3.7).

## 3. Methods

All steps are in `agents/shoreline.py` (radar and optical shorelines, transects, rates), `agents/planet.py`
and `scripts/make_shoreline_planet.py` (Planet), `scripts/shoreline_reference_ge.py` (reference tracing and
scoring) and `agents/coastal.py` (coastal strips). The geometry and statistics are plain Python; only the
image sampling runs in Earth Engine.

### 3.1 Sea mask, baseline and transects

1. **Water maps.** Each Sentinel-1 scene's VV backscatter, speckle-smoothed with a focal median, is split
   into water and land by an Otsu threshold computed for that scene (kept only between −24 and −12 dB) (D11).
2. **Sea.** Water occurrence is the share of months a pixel is water. Sea is the water polygons with
   occurrence ≥ 0.5 that touch the area's edge and cover ≥ 100 ha, so inland ponds and rivers are not sea.
3. **Baseline.** The sea mask is opened by 50 m, removing water narrower than about 100 m (docks, inlets,
   channels). Its boundary, minus stretches within 60 m of the area's edge, is simplified (Douglas–Peucker,
   40 m), resampled every 20 m and smoothed over ±250 m. Lines shorter than 500 m are dropped. A first run
   without the smoothing had crossing transects and false rates of about 300 m/yr where an inlet flipped
   between water and land.
4. **Transects.** Every 100 m along the baseline, perpendicular to it (direction from ±100 m along the line),
   300 m landward and 500 m seaward, sampled every 10 m: 735 transects.

### 3.2 Shoreline position on a transect

From the seaward end, walk landward through water until three land samples in a row (30 m): the shoreline is
the landward edge of the water connected to the sea. A position is recorded only when the seaward end is
water, the water does not reach the landward end, and at least 80 % of the samples around the position agree.
Positions are in metres from the baseline, seaward positive. A first run that took the best overall
land / water split along the transect jumped between the coast and settling ponds about 300 m inland from
month to month, which produced false trends; walking from the sea never reaches ponds behind the coast.

### 3.3 Tide-averaged shorelines

A single radar look is one tide level. Over a period, a pixel is water when it is water in **at least half of
the period's looks**, which places the line near the mid-tide position:
- **Yearly mode (main analysis):** one shoreline per dry season (October to March), 2015-16 to 2025-26,
  eleven seasons.
- **Monthly mode (comparison, RQ4):** one shoreline per month, October 2024 to September 2026, with rates from
  quarterly composites (about 6 to 12 looks each). A transect whose monthly positions spread (IQR) more than
  100 m is flagged *tidal*: a wide intertidal flat.

### 3.4 Rates and the change call

Per transect, the positions over the seasons are fitted by ordinary least squares: the linear regression rate
(LRR, m/yr) with its 95 % confidence interval (Student t), and the net shoreline movement (NSM: the mean of the
last two or three positions minus the mean of the first two or three). These are the DSAS statistics
(Himmelstoss et al. 2021, [PK]). A rate needs at least 5 seasons with a position (in the monthly mode, 5
quarters); with fewer, the transect is *too few*. The radar trend is *advancing* (land moved seaward) or
*retreating* (the sea moved landward) only when the 95 % CI excludes zero, otherwise *stable*.

### 3.5 Optical confirmation

The radar trend is a **change** only when the Sentinel-2 shoreline agrees: the same position rule on the median
MNDWI of the season's clear looks (water where MNDWI > 0), and the optical position must move the radar
trend's way by at least 20 m (two Sentinel-2 pixels) between the first and last dry season. A significant
radar trend without that is *unconfirmed*. The rule exists because radar alone also "advanced" where
wind-roughened water or moored barges read as land, as on the coal-port channel in July to September 2026,
while the imagery showed an unchanged coast (D11).

### 3.6 Accuracy: reference shorelines (RQ2)

**Planet check (2024–26).** On the same transects, each Planet month's water (NDWI > 0 on clear pixels) gives a
position by the same rule, sampled every 5 m. A position needs at least 80 % of its profile clear and no cloud
between 100 m landward of the edge and the sea end. Planet positions are compared with the radar line of the
same transect and month (monthly mode) and, as the median of the Planet dry-season months, with the
tide-averaged 2024-25 yearly line. Planet also corroborates the monthly mode's significant radar trends: its
median position in the radar series' first and last quarters must move the trend's way by at least 20 m.

**Reference tracings (2016–2026).** 30 transects drawn at random, one from each of 30 equal runs of the usable
transects in coast order, so the sample spans the coast (`agents/labels14.py`, seeded). On Google Earth Pro's
historical imagery a labeller marks the land / water edge on each transect for 4 dry seasons (2016-17,
2019-20, 2022-23, 2025-26) and records the image month. The page shows each transect extended by a random
0 to 200 m at both ends, numbered, with ticks every 25 m and no ids or baseline, so the extracted line's
position can't be read off the drawing. Each tracing is scored against the yearly shoreline of the dry season
its image is from (labellers sometimes use the nearest image, in the season before). Metrics: bias
(extracted minus reference, seaward positive), RMSE, MAE, and the share within 20 m and 30 m, overall and per
season. **[TBD: second labeller (P3) on the same page for agreement, D13 / labelling split 2026-11-01.]**

### 3.7 Built-up area near the shore

Built area per Dynamic World in two strips landward of the October 2024 shoreline, 0–200 m and 200–500 m, per
dry season, with the strips' land area and new built patches (Phase 12, D11). Open Buildings Temporal
(2016–2023) is a pre-period reference only. At 10 m, single houses are below resolution, so this is context
for reclamation, not a building count.

## 4. Results

### 4.1 Shoreline change 2015-16 to 2025-26 (RQ1)

Of the 735 transects, 529 have a position in at least 5 of the 11 seasons (Table 1).

**Table 1.** Change call on the 735 transects, yearly mode (`years.json`).

| Change | Transects | LRR, median (range), m/yr |
|---|---:|---|
| Advancing (confirmed) | 34 | +12.1 (+0.8 to +41.1) |
| Retreating (confirmed) | 4 | −4.7 (−46.4 to −2.7) |
| Stable | 446 | |
| Unconfirmed (radar trend, optical disagrees) | 45 | |
| Too few seasons | 206 | |

Accretion dominates: 34 confirmed advancing transects against 4 retreating, which agrees with the
accretion-dominated change reported for Cam Pha (Duong Thi Loi et al. 2021, [V]) and with artificial coasts
being Vietnam's fastest-accreting (Lappe et al. 2022, [V]). **[TBD: length of coast per class (transects ×
100 m) and rates per stretch: Ha Long, Hon Gai, Cam Pha port, Cam Pha town; a map figure (Fig. 1) with the
transects coloured by change.]**

The 206 *too few* transects are mostly where the coast moved beyond a transect's reach or where the seaward
end is not open water (§ 5.3). **[TBD: break the 206 down by reason from `years.json` status counts.]**

### 4.2 Case studies

**[TBD: 2–3 transects, none of them a reference transect or a neighbour.]** Candidates: the fastest advancing
stretch (up to +41 m/yr), with radar and optical position series (Fig. 3) and Google Earth / Planet images
before and after; one of the 4 retreating transects; one *unconfirmed* transect where radar and optical
disagree, to show why the confirmation matters. Interpretations (port reclamation, spoil, aquaculture) are
stated as interpretation of the imagery, not measured.

### 4.3 Accuracy against reference shorelines (RQ2)

**Planet, 2024–26 (Table 2).** The tide-averaged 2024-25 yearly line lies a median 22.5 m from the median
Planet dry-season position (48 % within 20 m, 391 transects). Against the monthly radar lines, single Planet
days differ by a median 32.5 m in both the dry months (40 % within 20 m, 3,134 transect-months) and the
monsoon months (38 %, 1,895). The distribution has a long tail: RMSE is 92 m against the yearly line and
123–134 m against the monthly lines, far above the medians. The monthly bias swings with the tide of the
Planet day (from −85.8 m on 12 May 2025 to +80.6 m on 5 Jul 2025, Planet minus radar, months with at least 30
pairs), which is the case for tide-averaging: single days, even at 3 m, do not give a sharper line.

**Table 2.** Planet minus radar position, same transect (`planet.json`, `compare`). Seaward positive.

| Comparison | n | Bias, m | Median \|d\|, m | MAE, m | RMSE, m | Within 20 m | Within 30 m |
|---|---:|---:|---:|---:|---:|---:|---:|
| Planet dry-season median vs yearly 2024-25 | 391 transects | −21.7 | 22.5 | 49.3 | 92.1 | 48 % | 58 % |
| Planet day vs monthly radar, dry months | 3,134 | −19.4 | 32.5 | 70.9 | 123.0 | 40 % | 49 % |
| Planet day vs monthly radar, monsoon months | 1,895 | +3.4 | 32.5 | 74.9 | 133.5 | 38 % | 50 % |

**[TBD: why the tail. Expected sources: wide flats (78 transects are *tidal* in the monthly mode), aquaculture
pond walls, moored barges. Break the error down by the tidal flag and by stretch.]**

**Reference tracings, 2016–2026.** **[TBD: bias, RMSE, MAE and within 20 / 30 m, overall and per season, from
`scripts/shoreline_reference_ge.py --score`; how many tracings were scored in another season than entered;
agreement of the two labellers.]** Compare the RMSE with CoastSat's roughly 10 m on sandy beaches (Vos et al.
2019, [PK]): on this coast the reference itself carries tide error (§ 5.2).

### 4.4 What optical confirmation changes (RQ3)

Of the 83 significant radar trends in the yearly mode, 38 are confirmed by the optical shoreline (34 advancing,
4 retreating) and 45 are not, so without the confirmation more than half the reported changes would rest on
radar alone. **[TBD: why the 45 fail: optical moved less than 20 m, optical moved the other way, or no clear
optical look in the first or last season; split by tidal flag.]** In the monthly mode, Planet corroborated 3 of
the 26 significant radar trends it could test (all advancing, 20 to 123 m), did not corroborate 9 (8 advancing
with Planet shifts of −15 to +3 m, and one retreating while Planet moved 145 m seaward), withheld 3 on tidal
flats, and leaves 11 pending, with a cloud or no position in an end quarter (D12).

### 4.5 Monthly versus yearly (RQ4)

The 24-month monthly series on the same transects finds 35 significant radar trends from quarterly
composites, of which **5 are confirmed** (all advancing, up to +73 m/yr) and 30 are unconfirmed; 217 transects
have too few quarters, and 78 are tidal flats whose monthly positions spread more than 100 m (`summary.json`).
Ten dry seasons find 38 confirmed changes. Two years are too short against the tide on this coast: the
monthly record is the one to see *when* a change happened (with the Planet months filling the monsoon), the
yearly one to say *whether* the coast moved.

### 4.6 Built-up area near the shore

Between the dry seasons 2024-25 and 2025-26, the built area changed by −21.1 ha in the 0–200 m strip and
−16.6 ha in the 200–500 m strip, with 20 and 17 new built patches (25.6 ha and 33.2 ha). Over the detector's
windows, 2018-19 to 2022-23, built area grew from 130.2 to 219.6 ha (0–200 m) and from 339.7 to 477.4 ha
(200–500 m) (Phase 12). **[TBD: reconcile the year-on-year decrease with the new patches (Dynamic World class
noise between seasons, cover threshold); relate the 2018–2023 growth to the advancing stretches.]**

## 5. Discussion

### 5.1 What moves this coast

The confirmed changes are almost all seaward, at rates up to about 40 m/yr, which on this coast points to
reclamation, port works and spoil rather than natural accretion. That is an interpretation of the imagery and
the literature (Nguyen et al. 2022, [V]; Vu et al. 2024, [V]), not something the method measures. Retreat is
rare (4 transects) and slow except at one stretch. **[TBD after § 4.2.]**

### 5.2 Tide-averaging and its limits

Averaging a season's radar looks removes most of the tide, as the Planet comparison shows (single Planet days
swing by about ±80 m with the tide; the tide-averaged yearly line is a median 22.5 m from the Planet dry-season
median). It does not remove the flats: a mid-tide line on a 500 m flat is not where anyone would draw the
shoreline, and the reference tracings, at the unknown tide of each Google Earth image, carry the same
problem. Accuracy on this coast is therefore partly a property of the reference. A tide model
(Bishop-Taylor et al. 2021, [PK]) would let images be filtered or corrected by tide height. **[TBD: is a
tide model available for Ha Long Bay at useful accuracy?]**

### 5.3 Transects on a moving coast

The transects are laid on the 2024–26 coast. Where the coast moved more than 300 m landward or 500 m
seaward of it over the decade, or where reclaimed land closed off the sea at the seaward end, a transect has
no position for those seasons and drops to *too few*. Large reclamations are therefore under-counted,
not over-counted.

### 5.4 The optical confirmation rule

Requiring Sentinel-2 to agree costs sensitivity (45 radar trends set aside) and buys protection against radar
artefacts on this coast (barges, rough water). The 20 m threshold is two pixels; a transect whose optical
shoreline moved 15 m is unconfirmed even if the radar trend is real. **[TBD: sensitivity of the counts to 10 /
30 m.]**

### 5.5 Limitations

- One area, one period; nothing is claimed beyond it.
- The labeller of the reference tracings may have built the shoreline method (P2 built it; the 2026-11-01
  split moves the tracings to P1 and P3). The blind layout guards against reading the extracted line off the
  drawing; the paper states who traced.
- Google Earth image dates and sources vary, and their tide is unknown.
- Sentinel-2 surface reflectance starts in 2016-17, so the 2015-16 season has radar only.
- The tidal range is not yet sourced **[TBD]**.

## 6. (Optional) Making shoreline claims checkable

**[TBD with the professor.]** The EviChange evidence gate (D16, D19) turns transect statistics into evidence a
vision-language model must cite: a statement like "the shoreline moved about 40 m seaward in the north-east"
is checked against the transect's confirmed change, NSM and LRR (verifier rules 4b, D13), and a radar trend
the imagery doesn't confirm can only give *uncertain*. If kept, this section reports the shoreline claims
from the 30-site evaluation (`docs/paper_draft.md` § 4.7); otherwise it is one paragraph pointing to that paper.

## 7. Conclusion

**[TBD after § 4.3.]**

## Figures and tables

1. Study area with the 735 transects coloured by change, 2015–2026 (the app's Shoreline panel, exported).
2. Yearly shorelines at 2–3 stretches (the slider's lines) over Google Earth / Planet imagery.
3. Radar and optical position series for the case-study transects.
4. Accuracy: extracted versus traced position, per season (scatter, 1:1 line).
5. Table 1 (change counts and rates), Table 2 (Planet comparison), Table 3 (reference accuracy **[TBD]**),
   Table 4 (monthly vs yearly).

## References (to be completed from the literature review)

Tags as in `docs/related_work.md`. **[PK] and [U] entries must be checked before submission.**

- Bishop-Taylor, R. et al. 2021. Remote Sensing of Environment. https://doi.org/10.1016/j.rse.2021.112734 [PK]
- Boak, E. H. & Turner, I. L. 2005. Journal of Coastal Research. https://doi.org/10.2112/03-0071.1 [PK]
- Duong Thi Loi et al. 2021. Vietnam Journal of Earth Sciences. https://doi.org/10.15625/2615-9783/16066 [V]
- Himmelstoss, E. A. et al. 2021. Digital Shoreline Analysis System (DSAS) v5.1 user guide. USGS OFR 2021-1091. https://doi.org/10.3133/ofr20211091 [PK]
- Lappe, R. et al. 2022. Remote Sensing 14, 2476. https://doi.org/10.3390/rs14102476 [V; exact title PK]
- Mentaschi, L. et al. 2018. Scientific Reports. https://doi.org/10.1038/s41598-018-30904-w [PK]
- Nguyen et al. 2022. Remote Sensing 14, 1241. https://doi.org/10.3390/rs14051241 [V]
- Vos, K. et al. 2019. Environmental Modelling & Software. https://doi.org/10.1016/j.envsoft.2019.104528 [PK]
- Vu et al. 2024. European Journal of Remote Sensing. https://doi.org/10.1080/22797254.2024.2398108 [V]
