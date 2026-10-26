# Phase 14 brief: third labeller (P1)

**Owner:** P1, from 2026-10-26. **Estimate:** ≈ 2–3 h.
**What for:** P2 labels every item; P3 (second labeller) and you (third) label the same 10 items of each
task. Your labels give inter-labeller agreement from someone who built neither the land-cover classes
nor the shoreline method, which is the strongest answer to the blindness question in the write-up.
**Spec:** `docs/PLAN.md` row 14, `docs/decisions.md` D13 / D14, and the notebook's own instructions.

## Your tasks

Use `notebooks/EviChange_labeling_phase14.ipynb` in Colab, the same way as the Phase 3 notebook.

| Task | Items | You? |
|---|---|---|
| (a) land-cover class before / after at the sites | 10 sites | yes: needs only Sentinel-2, so you can start now |
| (b) reference shoreline on PlanetScope, 2 dates | 10 transects | yes, once the Planet months are in Earth Engine |
| (c) coastal cells built / not built | — | **no**: you build Phase 12 (built area near the shore), so you aren't blind for it |
| (d) month of change on the Planet months | 10 sites | yes, once the Planet months are in Earth Engine |

The notebook prints whether the Planet months are in Earth Engine yet. If they aren't, do (a) now and
ask P2 when (b) and (d) are ready.

## Settings (Step 2 of the notebook)

```python
LABELER = 'p1'
N_ITEMS = 10      # picks the same 10 items as the other labellers (fixed seed)
```

Leave `SEED` as it is. Your answers go to `MyDrive/evichange/labeling/labels14_<task>_p1.jsonl`, so they
can't overwrite anyone else's. Skip the (c) cells.

## Blind rules

- Label each item from the imagery **before** you open anything the system made for it: no app, no
  Dynamic World classes, no extracted shorelines or transect rates, no CCDC dates.
- **Don't open the other labellers' files** (`labels14_*.jsonl` from P2 or P3) before yours are in.
- `unsure`, `not visible` and `no edge` are valid answers. Don't guess.
- The Phase 3 sites are the ones you labelled for change in Phase 3. That's fine: (a) asks for the
  class, not whether something changed.

## Hand-in

1. Download `labels14_classes_p1.jsonl`, `labels14_shoreline_p1.jsonl` and `labels14_change_month_p1.jsonl`
   from Drive.
2. Put them in `data/quangninh/labels/phase14/` on a branch from `team/main`, and open a PR on the
   public repo. Don't edit a label after it's committed; corrections go in a new `labels14_v2*` file.
3. P2 runs `python scripts/phase14_report.py --second p1` for your agreement with labeller 1.

Ask P2 about anything in the notebook.
