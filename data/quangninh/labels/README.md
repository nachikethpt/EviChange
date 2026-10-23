# Quang Ninh ground-truth labels (protocol `labels_v1`)

Produced with `notebooks/EviChange_labeling.ipynb` (blind protocol: before/after chips only,
no index values, no detector output, detected and random sites shuffled under anonymous ids).
These labels are the study's only ground truth. **Never edit a label after Phase 4 has produced
claims for its site.** Put corrections in a new `labels_v2*.jsonl` with the reason in `notes`.

| File | What it is |
|---|---|
| `sites.json` | The 30 sites: anonymous id, centre, yellow box (`outline`) and chip extent. No origin. |
| `sites_key.json` | Site id → `detected` / `random` (+ region id). **Labellers must not open it** until all labelling is done. |
| `labels_v1.jsonl` | `labeler1`: all 30 sites, 2026-10-05. |
| `labels_v1_labeler2.jsonl` | `labeler2`: 10 of the 30 sites, 2026-10-05, a different person from `labeler1`. |

## Agreement
`labeler2` labelled 10 sites in the same Colab session, after `labeler1`, without seeing
`labeler1`'s answers (the form never shows earlier labels). That makes these 10 sites an
**inter-rater** check, not a self-consistency relabel, so the ≥7-day gap of Step 7 doesn't apply.

On those 10 sites: `change_occurred` agrees on 9/10 (Cohen's κ = 0.63), `mining_related` on 9/10,
but the set of change types matches exactly on only 3/10 sites.

## Corrections
- 2026-10-06: `labels_v1_relabel.jsonl` was renamed to `labels_v1_labeler2.jsonl` and its `labeler`
  field changed from `labeler1` to `labeler2`. The notebook's `LABELER` setting had not been changed
  for the second person, so the file wrongly recorded one labeller. No label values were changed.

## Known limitations (open)
- `sites_key.json` region ids refer to `change_regions_quangninh_v1.json`. The current regions,
  `change_regions_quangninh_v3.json` (decisions.md D6), have the same 504 regions with the same ids;
  only `mean_conf` differs. `scripts/restratify_sites.py` confirms all 30 sites keep their strata.
- `sites_key.json` is in the repository, so any further labeller must be told not to open it.
- `labeler1` worked on the detector (Person 1), so was not fully blind to its output.

# Phase 14 labels (protocol `labels14_v1`, `phase14/`)

Produced with `notebooks/EviChange_labeling_phase14.ipynb` (decisions.md D13, D14), blind to every
system output. Samples come from `scripts/make_phase14_samples.py` (seeded; `agents/labels14.py`).

| File | What it is |
|---|---|
| `phase14/reference_transects.json` | 30 Phase 11 transects drawn at random, one per equal run of usable transects along the coast; id, geometry and the random extension of the drawn line at each end. No extracted statistics. |
| `phase14/coastal_cells.json` | 30 cells of 30 m, 15 at 0–200 m and 15 at 200–500 m inland of the baseline, ≥ 150 m apart, anonymous shuffled ids. |
| `phase14/labels14_classes*.jsonl` | (a) dominant class before / after at the 30 Phase 3 sites (Dynamic World's 9 classes or `unsure`). |
| `phase14/labels14_shoreline*.jsonl` | (b) land / water edge per transect and date: `status` edge / no_edge / not_visible, `drawn_m` along the drawn line, `pos_m` in the shoreline frame (m from the baseline, seaward +, as `positions.json`). |
| `phase14/labels14_cells*.jsonl` | (c) built / not_built / unsure per cell at both dates. |
| `phase14/labels14_change_month*.jsonl` | (d) lasting change yes / no / unsure on the Planet months, with `change_window` [last month before, first month after]. |

`labels14_<task>.jsonl` is `labeler1` (P2, all items); `labels14_<task>_labeler2.jsonl` is the second
labeller (P3, the same 10 seeded items of each task). `agents/labels14.load_labels()` validates every record.

**Locks until these labels are in:** classes at the labelled sites (`landcover.CLASSES_UNLOCKED_AT_LABELLED_SITES`)
and extracted shorelines / rates at the reference transects and their same-line neighbours, 81 transects
(`shoreline.REFERENCE_TRANSECTS_UNLOCKED`). Set both True in the commit that adds the labels.

**Known limitations:** the labeller (P2) built the classes and the shoreline method; the write-up says so.
Sep 2026 Planet isn't delivered yet (ordered in November, D12), so (b) and (c) use the last delivered
month until then and each record names its month. Reference shorelines are instantaneous waterlines,
the extracted positions are monthly radar water, so tide is part of the RMSE (D11). Cells are placed
from the baseline (the long-term sea edge), not from the Oct 2024 shoreline.
