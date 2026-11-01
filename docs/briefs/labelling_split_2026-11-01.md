# Remaining labelling, split between P1 and P3 (2026-11-01)

From 2026-11-01 P2 does no more labelling except the 4b calibration round 2 (`calib2`, P2's half against
P1's, D17). Everything else that is left goes to P1 and P3. This is also better for blindness: P2 built the
land-cover classes and the shoreline method, P1 and P3 built neither (P1 built Phase 12, so P1 still doesn't
label (c)). The write-up states who labelled what.

**Spec:** `docs/PLAN.md` rows 4b and 14, `docs/decisions.md` D13 (Phase 14), D17 (4b).

## Who does what

| Task | First labeller (all items) | Second labeller (same 10 items) | Estimate |
|---|---|---|---|
| 14 (a) land-cover class before / after, 30 sites | **P3** | P1 | P3 ≈ 1.5 h, P1 ≈ 0.5 h |
| 14 (b) reference shoreline on Google Earth, 30 transects × 4 dry seasons | **P1** | P3 (transects 1–10 of the page) | P1 ≈ 4 h, P3 ≈ 1.5 h |
| 14 (c) coastal cells built / not built, 30 cells | **P3** | none (P1 built Phase 12; stated as a limit) | ≈ 1 h |
| 14 (d) month of change on the Planet months, 30 sites | **P1** | P3 | P1 ≈ 1.5 h, P3 ≈ 0.5 h |
| 4b held-out set, 80 D15 boxes (scheme v2) | **P1** | — | ≈ 3 h |
| 4b training boxes (scheme v2), after calib2 passes κ ≥ 0.5 | **P3** | — | ≈ 5 h |

About 9 h each. P1's earlier third-labeller brief (`phase14_p1_third_labeller.md`) is replaced by this one.

## How

**14 (a), (c), (d)** — `notebooks/EviChange_labeling_phase14.ipynb` in Colab (needs read access to the
Earth Engine project `space-510615`: ask P2 to add your Google account). Step 2 settings:

```python
LABELER = 'labeler1'      # first labeller of a task: all items
N_ITEMS = None
# second labeller of a task:
LABELER = 'p3'            # or 'p1'
N_ITEMS = 10              # the same 10 items for everyone (fixed seed)
```

Run only the cells of your tasks. Files land in `MyDrive/evichange/labeling/` as `labels14_<task>.jsonl`
(first labeller) or `labels14_<task>_<you>.jsonl`.

**14 (b)** — Google Earth Pro on your own computer. Make your page from a checkout of `team/main`:

```bash
python scripts/shoreline_reference_ge.py --page --labeller P1     # P3: --labeller P3, and fill transects 1-10 only
```

Open `shoreline_ge_<you>.kml` in Google Earth Pro and `shoreline_ge_<you>.html` in a browser. The page
explains each step and keeps your answers as you type; press **Save** at the end for `shoreline_ge_<you>.json`.

**4b** — after P2's `calib2` is in and κ ≥ 0.5 (`python scripts/finetune_mcq.py --kappa`):

```bash
python scripts/finetune_mcq.py --sheet --set holdout --labeller P1    # P1: the 80 held-out boxes
python scripts/finetune_mcq.py --sheet --set train --labeller P3      # P3: training boxes, one page at a time
```

Use the cell rule (5 × 5 grid, D17) from the page. Save, and put the file in `data/quangninh/ft_labels_v2/`.

## Blind rules

- Label each item from the imagery **before** you see anything the system made for it: no app, no Dynamic
  World classes, no extracted shorelines or transect rates, no CCDC dates, nothing in `data/quangninh/shoreline/`.
- Don't open another labeller's file before yours is in.
- `unsure`, `not visible` and `no edge` are valid answers. Don't guess.

## Hand-in

Put your files in `data/quangninh/labels/phase14/` (Phase 14) or `data/quangninh/ft_labels_v2/` (4b) on a
branch from `team/main` and open a PR on the public repo. Don't edit a label after it's committed;
corrections go in a new file. P2 then imports and scores (`shoreline_reference_ge.py --import / --score`,
`phase14_report.py --second <you>`, `finetune_mcq.py --kappa`).
