# Brief: shoreline literature review (P1)

**Owner:** P1, from 2026-10-28. **Estimate:** ≈ 6–8 h. **Due:** 2026-11-04.
**Why:** on 2026-10-28 the professor asked for the paper to focus on the **shoreline**. The shoreline part
of `docs/related_work.md` ("Shoreline work uses MNDWI plus DSAS, with one Cam Pha study") is short, and
most of its citations are tagged [PK] (from memory, never checked). The paper needs it solid.
Nothing here blocks anyone, and no labels are involved, so there are no blindness rules.

## What to do

1. **Check every citation in that section and in "Index differencing is classical…"** (NDWI, MNDWI, AWEI,
   CoastSat, DSAS, Boak & Turner, Bishop-Taylor, Luijendijk, Mentaschi, Pekel, Pelich, Lappe, Duong Thi Loi).
   For each: authors, year, title, journal, volume / pages and a DOI that resolves (try `https://doi.org/<doi>`
   or Crossref). Change its tag to **[V]** when it checks out, correct it when it doesn't, and add a row to
   the "Verification log" table at the top of the file.
2. **Find a source for the Hon Gai / Ha Long tidal range.** The text says "spring range roughly 3–4 m" with
   no source. Tide tables (Vietnam's tide table book, or the Hon Gai station in a global tide model such as
   FES2014) or a VJES / VJMST paper. EviChange's tide caveat (D11) relies on this number.
3. **Add what's missing for our method.** Short paragraphs, each with 2–4 checked citations:
   - **Sentinel-1 (SAR) shoreline extraction**: water / land thresholding of VV backscatter, Otsu thresholds,
     speckle filtering. Our Phase 11 is built on this (`agents/shoreline.py`).
   - **Tide correction**: how others correct or average out the tide (tide models, tide-filtered composites).
     We average quarterly; is that standard?
   - **Accuracy of satellite shorelines**: typical RMSE in metres for Sentinel-2 / Sentinel-1 / Landsat
     against reference lines. We'll compare our RMSE (Phase 14 b) with these numbers.
   - **Shoreline change in Quang Ninh / Ha Long Bay / northern Vietnam**, including Vietnamese-language
     journals (VJES, VJMST, HUMG's *Journal of Mining and Earth Sciences*). Note anything about sea
     reclamation or coal spoil at the coast near Cam Pha.
4. **Update the "Gaps EviChange fills" bullet on shoreline** at the end of the file if what you find changes it.
   If someone *has* published a Sentinel-1 shoreline series for Quang Ninh, say so clearly: it changes our claim.

## Rules

- Only cite what you have opened (the paper, or at least its official abstract page). Tag anything else **[U]**.
- Keep the file's style: short paragraphs, the key number in bold, the source linked right after the claim.
- Don't change the other sections; just flag problems in your PR description.

## Hand-in

A branch from `team/main` changing `docs/related_work.md` only, with a PR on the public repo. In the PR
description, list what you corrected and anything you couldn't verify. Ask P2 about anything unclear.
