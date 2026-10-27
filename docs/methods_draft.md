# Methods (draft)

**Status:** draft written 2026-10-25 from `docs/PLAN.md`, `docs/decisions.md` (D1–D18), `docs/eval_audit.md` and
the code. Items marked **[TBD]** depend on decisions still open before the Phase 4 freeze. Citations refer to
`docs/related_work.md` and must be verified there before submission.

## 1. Study area and imagery

The study area is a 1–500 km²-capped box over the coal-mining coast of Quang Ninh, Vietnam (107.22–107.40° E,
20.98–21.10° N, ≈ 250 km², `data/quangninh/study.json`). It covers parts of Ha Long and Cam Pha, where earlier
Landsat studies document open-pit mining, spoil dumped into the sea and urban growth on reclaimed land (Nguyen et
al. 2022; Vu et al. 2024).

We use Sentinel-2 Level-2A surface reflectance from Google Earth Engine. One median composite is made for each of two
dry-season windows: **before**, 1 Nov 2018 – 31 Mar 2019, and **after**, 1 Nov 2022 – 31 Mar 2023. Window ends are
inclusive. Only scenes under 30 % cloud are used, and pixels are masked with the scene classification layer
(SCL cloud, shadow, cirrus and snow classes). The dry season is used because Sentinel-2 has almost no clear scenes over
the area from April to August.

## 2. Change detection (the evidence layer)

The detector is a deliberately simple index-differencing baseline (D6). It is not a contribution of this work and was
not tuned on the labelled sites. For each composite we compute NDVI, NDBI and MNDWI (Rouse et al. 1974; Zha et al.
2003; Xu 2006). Each delta is after minus before.

- **Change mask:** a pixel counts as changed when at least two of the three deltas exceed **T_IDX = 0.10** in absolute
  value. Changed pixels are vectorised into regions.
- **Region attributes:** area (ha), mean deltas (`dNDVI`, `dNDBI`, `dMNDWI`), and location (the cell of a 3 × 3 grid
  over the area that holds the region's centroid).
- **`mean_conf`:** the share of the region's pixels where all three deltas exceed T_IDX. It measures how consistently
  the indices agree; it is **not a probability**. `CONF_MIN = 0.2` (the median over the 504 regions) was fixed before
  any claim existed.

The study area yields 504 regions (`change_regions_quangninh_v3.json`). Each region also gets a Google Dynamic World V1
class per window (Brown et al. 2022): first the per-pixel mode over the window, then the mode over the region's pixels,
plus mean class probabilities (D10). A window without a usable Dynamic World image leaves the class null, so a class is
never guessed. The 0.10 threshold is a project choice; we found no published standard for it. It is reported as a
limitation together with NDBI's known confusion of bare soil with built-up land (§ 9).

*Coastal extension (D11, D13).* From October 2024 to September 2026, the system also maps the shoreline. Each
Sentinel-1 VV scene is split into land and water with an Otsu threshold, and the monthly water masks give a shoreline.
Transects 100 m apart cross a baseline along the October 2024 shoreline. On each transect we compute net shoreline
movement and a linear rate with its 95 % CI from quarterly, tide-averaged positions, as in DSAS (Himmelstoss et al.).
A radar trend counts as confirmed only when the optical dry-season shoreline agrees. Separately, built area from Dynamic
World is measured in strips 0–200 m and 200–500 m inland of the shoreline.

## 3. Sites and box evidence

The test set has **30 sites** (D4):
- 20 detected regions, spread across the range of region sizes;
- 10 random background sites, at least 200 m from any detection.

Sites were shuffled and given anonymous ids before labelling. The unit of analysis is the site's **box**, the yellow
outline drawn on every image chip. Every condition is verified against the same box evidence
(`agents/site_evidence.py`, D16):
- the regions overlapping the box, each with the area that lies inside the box;
- each region's location, taken from the centroid of its inside part in a 3 × 3 grid over the box;
- the region's own deltas, `mean_conf` and classes;
- `change_frac`, the share of the box that was detected as changed.

A background box therefore has an empty region list and `change_frac = 0`.

## 4. Claim generation: the conditions

All conditions see the same before/after chips: true colour and SWIR false colour, with the box outlined (D15). They
differ in what else they get and in how claims are formed.

| Condition | Writer | Input besides the chips | How claims are formed |
|---|---|---|---|
| **template** (reference) | rules | box evidence | one claim per evidence fact: presence, total extent, region location and area, one change type per index delta beyond T_IDX |
| **ungated** (primary comparison) | Qwen2.5-VL-7B-Instruct **[TBD: D15 addendum rule]** | none | free text (3–6 sentences); a separate text-only Qwen pass splits it into claims without judging them (`claim_extract_v1`) |
| **gated** (system) | same model | box evidence as JSON | JSON claims; each must name its level and type, the region it is about and the evidence fields it rests on, and cause, purpose, legality and the future go to an `abstain` list (`gated_report_v0` **[TBD: frozen version]**) |
| **ungated_gpt** (secondary, D16) | GPT **[TBD: model name]** | none | as ungated, with the same Qwen extractor |

Claims follow one schema (`agents/schema.py`). A claim has a level: L1 presence, L2 extent or location, L3 change type
or land cover, L4 cause, intent or forecast. It also has a type and optional structured fields. Model output that breaks
the schema is **dropped and counted as a parse failure, never repaired**.

## 5. The verifier

A deterministic, rule-based verifier (`agents/verifier.py`) gives each claim a verdict: supported, unsupported or
uncertain. Each verdict comes with one of 32 reason codes. The rules run in a fixed order, and the first rule that
decides the claim wins:
1. a malformed claim is uncertain;
2. any L4 claim is unsupported (beyond the evidence);
3. a claim citing an evidence field that does not exist is unsupported;
4. a misquoted index value is unsupported;
5. shoreline and coastal-built claims are checked against the transect statistics and strip areas;
6. L1 presence is checked against the change mask, at the stated location if the claim names one;
7. the region(s) the claim is about are resolved, then L2 claims are checked for extent (± 25 % area, or ± 2 points / 25
   % of the changed share) and location;
8. L3 claims are checked: the change type against the sign and size of the matching index delta, and land cover
   against the Dynamic World classes;
9. a supported claim whose regions all have `mean_conf < CONF_MIN` becomes uncertain.

When a claim carries no structure, as with free text from the ungated arms, the verifier reads location words,
change-type keywords and quoted numbers from the text. This fallback is heuristic. Its errors show up as
verifier–human disagreement, which is measured (§ 7, metric 5).

**The verifier is an instrument, not ground truth (D3).** It shares its thresholds with the gated prompt, so a
condition scored only by the verifier would be graded by its own rules. All headline metrics therefore use human labels.

## 6. Ground truth and adjudication

**Site labels (Phase 3).** Before any claim existed, the 30 sites were labelled from the chips alone, without seeing
index values, detector output or whether a site was detected or random. Each site has `change_occurred` (yes / no /
unsure), its `change_types`, `mining_related` (a visual judgement only; legality is never labelled) and a confidence.
A second labeller labelled 10 sites. Results:

| Measure | Value |
|---|---|
| `change_occurred` agreement | 9 / 10 sites |
| Cohen's κ | 0.63 (bootstrap 95 % CI about [0, 1]) |
| Change-type sets identical | 3 / 10 sites |

**[TBD: second labeller on all 30 sites, and a consensus label.]**

**Claim adjudication (Phase 5).** Every claim from every condition is judged by hand on two independent axes:
- **truth** (true / false / unverifiable) against the site's label and chips;
- **support** (supported / unsupported) against the box evidence.

The adjudication page (`/adjudicate`, `eval/adjudication.py`) blinds the condition as follows:
- claims from all conditions are shown shuffled together within a site, and the sites are in seeded random order;
- region ids and parenthesised index values are removed from the text;
- the condition, the verifier's verdict and the cited evidence fields are never shown;
- truth is judged first, without the evidence; support is judged in a second pass.

A second adjudicator judges a seeded 20 % of sites, and κ is reported on both axes. The adjudication rules (D18,
`docs/adjudication_rules.md`) are frozen with the prompts:
- Claims whose subject is the detector or the evidence ("no change was detected in the box") are judged as statements
  about the detector, tagged `about_detector`, and left out of the hallucination denominator. They are reported as a
  count per condition and stratum.
- `unverifiable` is kept for what no imagery can show: cause, intent, legality, ownership and the future.
- Numbers are judged within set tolerances: area within a factor of 2, share of the box within ±15 points, index values
  by the direction they imply.

## 7. Metrics

Per condition (PLAN, Evaluation):
1. **Hallucination rate:** claims judged false or unverifiable, over all claims emitted. This is the primary metric.
2. **Post-gate hallucination rate:** the same, but only over claims the verifier passes. This is what a user sees and is
   the headline number.
3. **Unsupported rate:** human judgement on the support axis.
4. **Faithful-but-false rate:** claims that are supported by the evidence but false. These are detector errors, not
   generation errors.
5. **Verifier performance:** catch rate (recall on hallucinated claims), precision of what it rejects, and κ against
   the human support axis.
6. **Informativeness:** true claims per site, recall of the labelled change types, abstention rate, and missed
   change at background sites (random sites labelled "change" where the condition made no true change claim, D18).
7. **Detector:** precision (detected sites labelled as change) and background change rate (random sites labelled as
   change).
8. **Parse-failure rate.**

All of these are reported pooled and separately for the detected and background strata. Per claim type, metrics 1–2
are also reported. Under the coastal extension (D13), each extracted quantity is also scored against the Phase 14 blind
labels (`scripts/phase14_report.py`):
- Dynamic World classes, by κ and agreement;
- shoreline position, by RMSE and bias in metres;
- built cells, by accuracy and κ;
- change month, within ± 1 month.

## 8. Statistics

With n = 30 this is a pilot-scale case study. **Pre-specified primary result:** the difference in pooled post-gate
hallucination rate between gated and ungated, with a 95 % CI from a **paired site-level cluster bootstrap**. Sites are
resampled with replacement, both conditions are recomputed on the same resampled sites, and there are 10 000
repetitions with seed 20261023. Its p-value is the exact Wilcoxon signed-rank test on per-site rates, using sites where
both conditions passed at least one claim. The number of excluded sites is reported. The exact sign test and a
comparison of per-site counts on all 30 sites are secondary. The rate, not the count, is primary, because an arm
that says less has fewer hallucinations by construction. The full pre-specified plan, including the sensitivity
analyses, is `docs/analysis_plan.md`.

- Claim-level rates are clustered within sites, so their CIs also come from the site-level cluster bootstrap.
- Wilson intervals are used only for site-level proportions (metric 7, abstention).
- Zero differences are dropped (Wilcoxon's rule), and ties get mid-ranks in the exact null distribution.
- The secondary comparison, gated vs ungated GPT (D16), and gated vs fine-tuned gated (D17) are Holm-adjusted as one
  family. Strata and claim types are descriptive (CIs, no p-values).

At n = 30 the study has about 0.8 power for a post-gate difference of 20 percentage points (40 % vs 20 %), but only
about 0.3 for 10 points (`docs/eval_audit.md`, finding 5). The effect size is reported with its CI, so a
non-significant result is not read as "no effect". All statistics are implemented in pure Python (`eval/metrics.py`),
and the exact tests match SciPy.

## 9. Prompt hygiene, freeze and limitations

**Prompt hygiene.**
- Prompts were developed only on development boxes outside the 30 sites: 60 detected regions and 20 background
  controls (`scripts/report_dev.py`).
- The model and image set were chosen there by rules written before any report output (D15).
- Prompts, adjudication rules and thresholds are frozen by commit **[TBD: commit]** before the 30 sites are run.
- The app blocks any model call on a labelled site until then.

**Limitations to state.**
- The ground truth is self-labelled; the main labeller also built the system.
- The data are 10 m resolution, one study area and one date pair (plus the 24-month coastal series).
- The threshold detector shares its indices with the evidence, so the gate can only be as right as the detector.
  Metric 4 measures this, and 8 of 10 background sites were labelled as changed.
- The 0.10 threshold is not taken from the literature.
- NDBI confuses bare soil with built-up land, and Dynamic World is weakest on its bare, shrub, grass and
  flooded-vegetation classes (Venter et al. 2022).
- Monthly shorelines carry tide noise (Hon Gai tidal range **[TBD: cite]**). Only the 24-month trends are reported.
- The general-AOI app is a tool capability, not validated outside Quang Ninh.
