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
