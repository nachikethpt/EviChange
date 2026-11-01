# Brief: second adjudicator for the 30-site claims (P1)

**Owner:** P1, from 2026-10-31. **Estimate:** ≈ 2–3 h. **Due:** 2026-11-06.
**Why:** the evaluation's agreement numbers (κ and percent agreement on the truth and support axes,
`docs/adjudication_rules.md` section 7, D18) need a second, independent adjudicator on a seeded 20 % of
the sites. That is **6 of the 30 sites, 96 of the 427 claims**. The site list is fixed by seed in
`eval/adjudication.py` (`second_sites`); the page picks them for you. Without this, the results have no
reliability figure for the adjudication.

## Order: do this after your Phase 14 labels

The claims mention land-cover classes and shoreline movement. Finish your Phase 14 labelling first
(`docs/briefs/phase14_p1_third_labeller.md`), so reading claims can't influence those labels. The
shoreline literature review can run in parallel.

## Setup (once)

1. Pull `team/main` and use the repo's Python environment, as for Phase 12.
2. **Chips:** the page shows each site's before/after image chips from `data/vlm_chips/` (gitignored).
   Ask P2 for the zip of that folder and unpack it into `data/vlm_chips/` in your checkout.
3. Start the app from the repo root: `python -m uvicorn webapp.backend.main:app --port 8000`.

## What to do

1. Read `docs/adjudication_rules.md` in full before starting. It is the rulebook: what counts as
   *true*, *false* and *unverifiable*, what *supported* means, and how `about_detector` / `compound` claims are marked.
2. Open `http://localhost:8000/adjudicate`. Reports: **30 labelled sites**, adjudicator **`p1`**, role
   **second (20 % overlap)**. The page shows only your 6 sites.
3. **Pass 1: truth** (label + chips): judge every claim against the site's chips and label. Then switch
   Pass to **2: evidence support**: the page shows the evidence JSON; judge whether each claim is supported.
4. Put the rule number in the note when a claim is an edge case (e.g. "R3 area").

## Rules

- **Independent:** don't look at P2's judgements file, and don't discuss individual claims with P2
  until you've both finished. Disagreements are resolved together afterwards (adjudicator `final`).
- The page hides which condition wrote a claim and what the verifier said; don't try to work it out.
- Your judgements are saved to `data/adjudication/sites_p1.jsonl` as you go (you can stop and resume).

## Done when

All 96 claims have both passes judged, and `data/adjudication/sites_p1.jsonl` is in a PR on the public
repo (branch from `team/main`). P2 then runs `python -m eval.adjudication agreement …` for κ.
