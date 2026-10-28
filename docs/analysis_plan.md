# Analysis plan (pre-specified)

**Status:** draft, 2026-10-26. It becomes binding when it is committed together with the Phase 4 freeze (prompts,
adjudication rules and thresholds pinned by the same commit), **before any claim on the 30 sites exists**. The
commit hash and date are the timestamp. A change after that commit goes in § 10 with its date and reason. It never
silently rewrites an earlier section.

Sources: PLAN "Evaluation", `docs/decisions.md` (D3, D4, D13, D15–D18), `docs/eval_audit.md`,
`docs/adjudication_rules.md` and `eval/metrics.py`. Where this plan and those differ, this plan wins once committed.

## 1. Question and hypothesis

Does gating a VLM's change claims on structured detector evidence, with a deterministic verifier, reduce the share
of claims a user sees that are false or unverifiable?

- **H1 (primary):** the post-gate hallucination rate of **gated** is lower than that of **ungated**. Both use the same
  base model (Qwen2.5-VL-7B-Instruct, D15) on the same 30 sites. The test is two-sided at α = 0.05.
- The result is reported as an effect size with a CI. A CI that includes 0 is "inconclusive at this sample size", not
  "no effect" (§ 7).

## 2. Data

- **Area and imagery:** the Quang Ninh study box (`data/quangninh/study.json`) and the Sentinel-2 L2A dry-season
  composites 2018-11-01 – 2019-03-31 and 2022-11-01 – 2023-03-31 (methods § 1).
- **Sites:** the 30 Phase 3 sites (`data/quangninh/labels/sites_key.json`). 20 are **detected** (detector regions spread
  across the size range) and 10 are **random**: boxes at least 200 m from any detection. The random stratum is
  described as "outside the detector's regions", **never as "no change"**: 8 of its 10 sites are labelled as changed
  (audit finding 1).
- **Site sampling:** the 20 detected sites were chosen purposively across the size range, not drawn at random. The 10
  random sites were drawn at random. The paper says so.
- **Ground truth:** `labels_v1.jsonl` (labeller 1, all 30 sites). If a second labeller covers all 30 sites before the
  freeze, a consensus label made by discussing the disagreements replaces it, and that is recorded in § 10. The labels
  are never changed after a claim exists.

## 3. Conditions

| Condition | Role | Writer |
|---|---|---|
| `gated` | system | base model with box evidence, verified |
| `ungated` | **primary comparator** | base model, chips only, the same Qwen extractor |
| `template` | reference only, no test | rules from the box evidence |
| `ungated_gpt` | secondary comparator (D16) | GPT, chips only, the same Qwen extractor |
| `gated_ft` | secondary comparator (D17), only if fine-tuning reaches the 30 sites | fine-tuned base model with box evidence |

Every condition runs once per site with the frozen prompts. A failed model call is retried; a reply that breaks the
claim schema is never retried or repaired. It is dropped and counted (metric 8). Any condition that runs on fewer than
30 sites reports which sites are missing and why.

## 4. Unit, claims and adjudication

- **Unit:** the site's box (D16). Claims are clustered within sites.
- **Adjudication:** by the D18 rules (`docs/adjudication_rules.md`), on two axes, with the condition hidden:
  **truth** (true / false / unverifiable) against the label and chips, and **support** (supported / unsupported)
  against the box evidence.
- **`about_detector` claims** (subject is the detector, the evidence or the analysis) are left out of the denominators
  of metrics 1–5. They are reported as counts per condition and stratum.
- **Second adjudicator:** a seeded 20 % of sites (`eval/adjudication.py`, `SECOND_SHARE = 0.20`, `SEED = 20261023`;
  the sites are drawn before adjudication starts). Disagreements are resolved to one final record; the first-pass
  records are kept for κ (§ 8).

## 5. Metrics

Per condition, pooled over all sites and separately for each stratum (detected, random). Claim-level metrics count
only claims that are not `about_detector`.

| # | Metric | Definition |
|---|---|---|
| 1 | Hallucination rate | (false + unverifiable) / claims emitted |
| 2 | **Post-gate hallucination rate** | the same, over claims the verifier passes (`verdict = supported`). **Primary metric** |
| 3 | Unsupported rate | support = unsupported / claims emitted |
| 4 | Faithful-but-false rate | (support = supported and truth = false) / claims emitted |
| 5 | Verifier | catch rate (rejected / hallucinated), precision (hallucinated / rejected), κ of passed vs human support |
| 6 | Informativeness | true claims per site; change-type recall per site (sites whose label has types); abstention (sites with no parsed claim); `about_detector` count; **missed change at random sites** (random sites labelled "change" where the condition made no true change claim) |
| 7 | Detector | precision (detected sites labelled change); background change rate (random sites labelled change); `unsure` sites left out and counted |
| 8 | Parse failures | items that broke the schema / all items produced |

Pooled rates are **unweighted pooled sample rates** over the 30 sites, not population estimates. The strata are not
weighted by their share of the area, and the paper uses that name for them.

Coastal extension (D13): Dynamic World class κ and agreement, shoreline RMSE and bias, built-cell accuracy and κ, and
change-month agreement against the Phase 14 labels (`eval/metrics.py`, `scripts/phase14_report.py`). These are
descriptive and have no hypothesis test.

## 6. Primary analysis

**The primary result:** the difference in pooled post-gate hallucination rate, gated minus ungated, on the sites both
conditions ran. Its 95 % CI comes from a **paired site-level cluster bootstrap**: resample sites with replacement,
recompute both conditions on the same resampled sites, 10 000 reps, seed 20261023, percentile interval
(`eval.metrics.paired_cluster_bootstrap`, `pooled_rate_diff`). Resamples where either condition has no passed claims
are skipped and their number is reported.

**Its p-value:** the exact Wilcoxon signed-rank test on per-site post-gate rates, over sites where both conditions
passed at least one claim. Zero differences are dropped (Wilcoxon's rule), and ties get mid-ranks in the exact null
distribution (`eval.metrics.wilcoxon_signed_rank`). The number of sites without a rate is reported, pooled and per
stratum.

The rate, not the count, is primary. A condition that says less has fewer hallucinations by construction (audit
finding 3).

## 7. Secondary, sensitivity and descriptive analyses

**Pre-specified secondary comparisons** (one family, **Holm-adjusted**; same estimator and test as § 6):
- S1 (D16): gated vs `ungated_gpt`, post-gate hallucination rate;
- S2 (D17): `gated_ft` vs gated, post-gate hallucination rate (only if `gated_ft` exists; otherwise the family is S1
  alone).

**Supporting tests for the primary comparison** (reported, not used to decide H1):
- the exact sign test on per-site rates;
- per-site hallucination **counts** on all sites (exact Wilcoxon and sign test), with improvements / ties /
  worsenings;
- metric 1 (pre-gate hallucination rate), gated minus ungated, with the same bootstrap CI.

**Sensitivity analyses** (decided now, reported whatever they show):
- **Zero handling:** Pratt's rule (zeros ranked, then their ranks dropped) for the primary Wilcoxon test.
- **`about_detector` included:** metrics 1–2 and the primary difference recomputed with those claims judged as
  statements about the ground (`to_metric_records(..., drop_about_detector=False)`). This shows how much the D18
  choice moves the result.
- **Strata:** the primary difference within the detected stratum alone. The random stratum has 10 sites, too few for
  a stable bootstrap.

**Descriptive only** (CIs, no p-values): every stratum, claim type (`by_claim_type`) and claim level; template
against anything; metrics 3–8.

**What the primary result is read with.** Gating can lower metric 2 by deleting claims. Next to the primary result
the paper always shows, for gated and ungated:
- claims passed per site;
- true claims per site;
- change-type recall;
- missed change at random sites;
- the verifier's wrong rejections (true claims it rejected).

No composite score combines these with the hallucination rate.

## 8. Reliability

- **Labels:** Cohen's κ between labellers on `change_occurred`, with a site-bootstrap 95 % CI, plus raw agreement and
  per-type agreement on `change_types`. The current 10 double-labelled sites (κ = 0.63) are a **pilot-scale check**:
  their CI is about [0, 1] (audit finding 7).
- **Adjudication:** on the second adjudicator's sites, for the truth and support axes separately: raw agreement, κ
  with a site-bootstrap CI, and Gwet's AC1 as a sensitivity check (κ is unstable under skewed prevalence).
- **Extractor (D16):** claims missed, invented or mis-levelled by `claim_extract_v1` on a sample of development
  reports outside the 30 sites. This is measured before the freeze and reported as part of the measurement.
- L3 truth and change-type recall are flagged as low-reliability: the labellers' change-type sets matched on 3 of
  10 sites.

## 9. Power, missing data and stopping

- **Power** (audit finding 5): about 0.83 for 40 % vs 20 % post-gate and about 0.29 for 40 % vs 30 % at n = 30. The
  smallest effect this study can reliably detect is about 20 percentage points. This is stated in the paper before
  the results.
- **Missing data:** a site where a condition emits nothing stays in that condition's clusters as an empty cluster
  (bootstrap) and counts as abstention. It is never imputed.
- **No early look, no extra sites:** the 30 sites are fixed. Claims are not scored before every condition has run on
  every site, and no site is added or dropped after seeing results. A site can only be dropped for a reason recorded
  in § 10 that does not depend on any claim (for example, the imagery is missing).
- **Code:** all numbers come from `eval/metrics.py` and `scripts/results_tables.py` at the frozen commit. A bug fix
  after the freeze goes in § 10, and the paper reports both the before and after numbers if they differ.

### To implement before the freeze

These are named above but are not yet in the code:
- the `about_detector` count per condition and stratum, and "missed change at random sites" (metric 6).
  `to_metric_records` currently drops `about_detector` claims, so nothing downstream counts them;
- `sites_without_rates` per stratum;
- Pratt's zero handling, as an option of `wilcoxon_signed_rank`;
- the site-bootstrap CI for κ, and Gwet's AC1;
- Holm adjustment across S1 and S2 in `report()` / Table 6;
- the true claims the verifier wrongly rejected, per condition.

## 10. Deviations

Every change after the freeze commit: date, what changed, why, and whether any claim or result had been seen.

| Date | Change | Reason | Results seen? |
|---|---|---|---|
| 2026-10-28 | Implemented the items listed under "To implement before the freeze" in `eval/metrics.py`, `eval/adjudication.py` and `scripts/results_tables.py`: about_detector claims counted apart (metrics 1–5 exclude them; sensitivity comparison includes them), wrong rejections, missed change at random sites, Pratt zero handling next to Wilcoxon, Holm adjustment for the D16 secondary, pre-gate and detected-only comparisons, labeller and adjudicator reliability (κ with site-bootstrap CI, Gwet AC1). No change to what is measured or how it is decided; code only, with synthetic tests. | The plan specified these but they were not coded; doing it before any claims exist keeps the analysis fixed in advance. Touches P2's `eval/metrics.py`: P2 to review. | No: no claims or results existed |
