# Claim adjudication rules (D18)

**Status: decided 2026-10-26** (`docs/decisions.md`, D18): the **(proposed)** options below are the rules,
and the alternatives are not taken. They answer findings 1 and 2 of `docs/eval_audit.md`. The rules are
frozen with the prompts (pinned by commit), and the adjudication page (`/adjudicate`) shows them beside
every claim.

Each claim gets two independent judgements (PLAN, "Claim adjudication"):
- **truth**: `true` / `false` / `unverifiable`, judged against the site's ground-truth label and the chips;
- **support**: `supported` / `unsupported`, judged against the evidence JSON the system had.

The adjudicator never sees the condition, the verifier's verdict, the claim's `region_ref` / `evidence_ref`,
or parenthesised index values. The page strips them (audit finding 8).

## 1. What a claim is about: the box

Everything is judged inside the site's box (the yellow outline), at the box's dates. A claim about something
outside the box is `unverifiable` on the truth axis, unless it is clearly about the box as a whole.

## 2. Claims that restate the detector (audit finding 1)

Some claims are about **the detector's output**, not the ground: "No change was detected in the box",
"The detector found two regions", "Detection confidence is low".

- **(proposed) Judge them as statements about the detector.** On the truth axis they are `true` when they
  correctly describe the evidence. Tag them `about_detector: true`. They are **left out of the hallucination
  denominator** (metrics 1 and 2) and reported separately as a count per condition and stratum.
  - Why: the label is about the ground, so a sentence about the detector can't be true or false against it.
    Counting it either way decides the random stratum by wording alone. 8 of the 10 random sites are labelled
    "change" (audit finding 1).
  - Reported instead: **missed change at random sites** = random sites labelled "change" where the condition
    made no true change claim. This is the honest cost of gated's abstention, and it belongs with
    informativeness (metric 6).
- *Alternative:* judge every presence claim as a statement about the ground ("no change was detected" read
  as "nothing changed"). It is then `false` at the 8 changed random sites, which counts heavily against gated
  and template. If the team prefers this, gated's rule-4 sentence should be reworded *before the freeze* to
  "The detector found no change in the box", so that the claim says what it means.

A claim is `about_detector` only when its subject is the detector, the evidence or the analysis ("detected",
"the detector", "the analysis found", "measured"). "No change occurred" or "The area is unchanged" is about
the ground.

## 3. Numbers (audit finding 2)

`unverifiable` is **only** for what no imagery of the box can show: cause, purpose, intent, legality,
ownership, licensing, who did it, and the future. A number is never `unverifiable` just because it is precise.

| Claim states | truth = `true` when | `false` when | otherwise |
|---|---|---|---|
| Area in ha or km² | the visibly changed area in the box is within **a factor of 2** of the stated figure | clearly outside a factor of 2 | `true` if the change is real but its edges can't be seen well enough to estimate; the support axis checks the exact number |
| Share of the box (%) | within ±15 percentage points of the visible share | clearly outside | as above |
| Index value (dNDVI −0.34) | the change it implies (sign beyond ±0.10) matches what is visible | the visible change goes the other way | judge the implied direction only. The value itself is checked on the support axis, never by eye |
| Shoreline distance or rate (m, m/yr) | the visible movement is in the stated direction and within a factor of 2 | opposite direction, or clearly outside a factor of 2 | `true` if the direction is right but the distance can't be estimated from the chips |
| Built area near the shore (ha) | as for area | as for area | as for area |
| Detection confidence | — | — | `about_detector` (rule 2) |

The tolerances are deliberately wider than the verifier's (25 %). The truth axis asks "is this a fair
description of the ground", while the support axis already checks the numbers exactly.

## 4. Change type and land cover

- A change-type claim ("vegetation loss in the north-east") is `true` when the label's `change_types` contains
  it **or** the chips show it plainly. The label is the reference, but two labellers agreed exactly on change
  types at only 3 of 10 sites (audit finding 6), so the chips may override a missing type. They may not
  override a contradicting one: if the label says `vegetation_gain`, "vegetation loss" is `false`.
- A land-cover claim ("trees were replaced by bare ground") follows the Phase 14 (a) class labels once they
  exist. Before that, judge it from the chips with the Dynamic World class definitions.
- "Mining" as a land cover or activity ("open-pit mine", "coal spoil") is a **cause/purpose** claim and so
  `unverifiable` (PLAN: legality is never labelled; `mining_related` is a visual label, not ground truth for
  claims). "Exposed soil" or "excavation" is a land-cover claim and is judged normally.

## 5. Location

A location word is judged in the box's 3 × 3 grid, the same frame the evidence uses (D16). "In the south"
covers south, south-east and south-west, as in the verifier. A claim with the right change in the wrong
place is `false`.

## 6. Hedged and compound claims

- Hedges ("likely", "appears to", "may") do not change the judgement of a verifiable statement. "Likely
  vegetation loss" is judged as "vegetation loss". A hedged cause is still `unverifiable`.
- A claim that joins two statements is judged as `false` if either part is false, and as `unverifiable` if
  either part is unverifiable and none is false. The extractor is asked to split statements, so these should
  be rare. Each one is flagged `compound: true` so its count can be reported.

## 7. Process

- Claims are shown one site at a time, all conditions shuffled together, with the site's chips and label.
- The support axis is judged on a second pass with the evidence JSON shown, so that the evidence does not
  colour the truth judgement.
- **Second adjudicator:** a random 20 % of sites (fixed by seed before adjudication), adjudicated
  independently. Report κ and percent agreement on both axes. Disagreements are discussed and resolved to
  one final record; the first-pass records are kept for κ.
- Every judgement can carry a free-text note. Rule numbers ("R3 area") are encouraged, so that edge cases
  can be audited later.

## Record written per claim

`{site_id, condition, claim_id, type, level, text, [change_type], verdict, truth, support, about_detector,
compound, adjudicator, note}`. This is the `eval/metrics.py` record plus `about_detector`, `compound`,
`adjudicator` and `note`. The metrics drop `about_detector` claims from the hallucination denominator
(rule 2).
