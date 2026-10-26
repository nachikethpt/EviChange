# Evaluation plan audit (2026-10-25)

An audit of PLAN.md "Evaluation" and `eval/metrics.py` against the Phase 3 labels that exist now. It was done before
any claim on the 30 sites exists and before the Phase 4 freeze, so every change below can still be pre-specified.
The numbers come from `data/quangninh/labels/` (`labels_v1.jsonl`, `labels_v1_labeler2.jsonl`, `sites_key.json`).

## Summary

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| 1 | 8 of 10 random sites are labelled "change" | **high**: decides how the random stratum reads | Decide now how "no change was detected" claims are adjudicated (truth axis), and stop describing random sites as "no change" sites |
| 2 | "Unverifiable" mixes "beyond imagery" with "too precise to check" | **high**: can penalise gated, which quotes exact numbers | Written adjudication rules for numeric claims, frozen with the prompts |
| 3 | The count comparison favours the arm that says less | medium | Make the rate difference with its CI the one primary result; counts secondary |
| 4 | The effect size had no CI in code | medium, **fixed** | `paired_comparison` now returns `pooled_rate_diff` with a paired site bootstrap CI |
| 5 | Power: only large effects are detectable | medium | State the minimum detectable effect in the write-up, before the results |
| 6 | Change-type labels agree exactly on 3 of 10 sites | medium | Report L3 claims and change-type recall as low-reliability; second labeller on all 30 |
| 7 | κ = 0.63 on 10 sites has a 95 % CI of about [0, 1] | low | Report the CI; label more sites with two labellers |
| 8 | Blinding of the condition is weak | medium | Normalise claim text before adjudication; second adjudicator on a subsample |
| 9 | Many tests, no multiplicity plan | low | Name one primary test; Holm or descriptive-only for the rest |
| 10 | Rates are compared only on sites where both arms passed a claim | low | Report the excluded sites per stratum; add the pooled-rate difference (4) on all sites |

## 1. The random sites mostly changed

| Stratum | yes | no | unsure |
|---|---|---|---|
| detected (20) | 16 | 3 | 1 |
| random (10) | **8** | 2 | 0 |

The background change rate is 80 % (Wilson 95 % CI 49–94 %). The plan says a random site "tests hallucinated change
where none was detected: gated should abstain, while ungated can still invent change." By the labels, though, change
did happen at 8 of those 10 boxes. The detector missed it, which is metric 7's "rough miss estimate."

What this does to the study:
- At a random site, gated's prompt (rule 4) and the template produce one claim: no change was detected in the box.
  The verifier passes it, because the evidence is empty. Whether that claim is **true** depends on how it is read:
  - as a statement about the **detector** ("the detector found nothing"), it is true at all 10 sites;
  - as a statement about the **ground** ("nothing changed"), it is false at 8 of 10. It then counts as a
    faithful-but-false hallucination (metric 4) that passes the gate (metric 2).
- Ungated Qwen2.5-VL said "change" on 20 of 20 D15 negative controls (`docs/vlm_compare_d15.md`). With an 80 %
  base rate, that habit makes ungated *right* at most random sites.

So under the second reading, the random stratum can favour ungated on the headline metric. Under the first, it
favours gated. Both readings are defensible, and they give opposite results, so the choice has to be made before the
claims exist.

Recommendation:
- Pre-specify the reading in the adjudication rules. Our suggestion is the ground reading, because the label is
  about the ground. In that case, word gated's rule-4 claim as what it is ("The detector found no change in the box"),
  and adjudicate claims about the detector as true or false about the detector. The other option: drop presence
  claims that only restate the evidence from the hallucination denominator.
- Describe the random stratum in the write-up as "outside the detector's regions," not "no change." Report
  per stratum, as the plan already says.

## 2. "Unverifiable" needs rules for numbers

Metric 1 counts `false` **and** `unverifiable` as hallucinations. The plan's example of unverifiable is legality
and the future. But gated and template claims quote exact values ("182.4 ha", "dNDVI −0.34"), which the truth axis
cannot check from chips either. If an adjudicator marks those unverifiable, gated is penalised for being precise.
That's the opposite of the study's intent.

Recommendation: write adjudication rules for the truth axis and freeze them with the prompts. For example:
- extent: true if the visible changed area is within a factor of 2 of the stated figure; false if clearly not;
- index values: judged on the support axis only, and on the truth axis only through the change they imply;
- `unverifiable` is reserved for things no imagery can show (cause, intent, legality, ownership, the future).

## 3. Counts favour the terse arm

The paired test compares per-site hallucination **counts** on all 30 sites. An arm that emits fewer claims has
fewer hallucinations by construction. Informativeness (metric 6) is meant to catch this, but it is a separate
metric, and the count test doesn't adjust for it. Rates don't have this problem.

Recommendation: pre-specify one primary result, **the difference of pooled post-gate hallucination rates, gated
minus ungated, with its paired site-bootstrap 95 % CI** (finding 4). Report the Wilcoxon / sign tests on per-site
rates as its p-value and the count tests as secondary.

## 4. Effect-size CI (fixed in this change)

PLAN: "Report the effect size with its CI, not only p." `paired_comparison` returned p-values and an unweighted mean
of per-site differences only. It now also returns `pooled_rate_diff = (diff, lo, hi)`: the difference of pooled rates
on the common sites, from resampling sites jointly for both conditions (`paired_cluster_bootstrap`), so the pairing
is kept. The statistics were cross-checked against SciPy and statsmodels: the sign test and exact Wilcoxon match;
Wilson differs only past the 5th decimal (z = 1.96).

## 5. Power

The minimum number of sites going one way for a two-sided sign test with p < 0.05:

| sites with a difference | needed in one direction |
|---|---|
| 20 | 15 (75 %) |
| 25 | 18 (72 %), the plan's example, p = 0.043 |
| 30 | 21 (70 %) |

Simulated power of the Wilcoxon test on per-site post-gate rates (about 4 passed claims per site for ungated and 3 for
gated, binomial errors):

| ungated vs gated rate | n = 30 | n = 20 |
|---|---|---|
| 40 % vs 30 % | 0.29 | 0.21 |
| 40 % vs 20 % | 0.83 | 0.66 |
| 50 % vs 25 % | 0.93 | 0.79 |

The study can detect differences of about 20 percentage points or more. A 10-point difference would most likely be
"not significant", which is not evidence of no effect. Say this in the write-up before the results, and lead with
the CI (finding 3).

## 6–7. Label reliability

On the 10 double-labelled sites:
- `change_occurred`: 9 of 10 agree, κ = 0.63, but the bootstrap 95 % CI is about [0, 1] (κ is also undefined in 11
  % of resamples). Ten sites cannot pin κ down.
- `change_types`: the two labellers give the **same set on only 3 of 10** sites (s03, s04, s11, s12, s13, s25, s28
  differ, often vegetation vs built-up).

The truth axis for L3 change-type claims and metric 6's change-type recall both rest on these types. Recall currently
uses labeller 1 only.

Recommendation: report κ with its CI, and per-type agreement. Treat L3 truth and change-type recall as
low-reliability. Have the second labeller do all 30 sites, as PLAN Phase 3 already recommends (≈ 1 h). If that's
possible, adjudicate disagreements to one consensus label before Phase 5.

## 8. Blinding

The condition is hidden on the adjudication page, but the text gives it away: template claims are formulaic, and
gated claims cite region ids and index values. The adjudicator is on the team that built the system.

Recommendation: before adjudication, strip region ids, `evidence_ref` and parenthesised index values from the shown
text, and randomise claim order across conditions within a site. A second person adjudicates a random 20 % of claims,
and κ is reported on both axes.

## 9. Multiplicity

Two pre-specified comparisons (primary; D16 GPT) and `gated_ft` (D17) are planned. Each gives count and rate × Wilcoxon
and sign, pooled and per stratum and per claim type: well over 30 p-values on 30 sites.

Recommendation: one primary test (finding 3). Holm-adjust the pre-specified secondaries (D16, D17) as a family. Strata
and claim types are descriptive, with CIs and no p-values.

## 10. Sites without a defined rate

The rate tests use only sites where both arms passed at least one claim. Post-gate, that excludes sites based on an
outcome of the gate itself, and the random sites (one claim each) are the most likely to drop out. `sites_without_rates`
is reported; report it per stratum too. The pooled-rate difference (finding 4) uses every site with claims in either
arm's pool, so it is less affected.

## What was checked and is fine

- Cluster bootstrap over sites for claim-level rates, with Wilson only for site-level proportions: correct, and
  implemented as specified (`eval/metrics.py`).
- Exact Wilcoxon with mid-ranks over doubled ranks: correct, and matches SciPy's exact test.
- Prompt hygiene (development boxes outside the 30 sites, freeze by commit) and the labelled-site locks in code.
- Two independent adjudication axes (truth, support): a good design. Findings 1 and 2 are about writing its rules
  down, not about changing it.
