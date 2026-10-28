# Phase 4b labels, scheme v2 (land cover per date, D17)

Saved from the pages made by `scripts/finetune_mcq.py --sheet` (`lc_<set>_<labeller>_<n>.json`):
box id → `before` / `after` → `covers` (multi-select), `main`, `cant_tell`, `image_date` (Google Earth
image month). Change is derived (`finetune_mcq.derive()`), never labelled. Labels follow the
aquaculture rule (D17: fish ponds and cage farms are water).

| File | Labeller | Boxes | Saved |
|---|---|---|---|
| `lc_calib_p2_1.json` | P2 | 40 calibration boxes | 2026-10-25 |
| `lc_calib_p3_1.json` | P3 | 40 calibration boxes | 2026-10-27 |

Calibration round 1: main cover per date κ 0.72, derived change κ 0.40 (below 0.5). Round 2 uses the cell
rule (5 × 5 grid) on 40 fresh `calib2` boxes (D17).

## Corrections
- `lc_calib_p2_1.json`, after the 22:47 save, from P2's answers on 2026-10-25:
  - r172 (page box 1) after: `image_date` 2022-10 (was empty; also in P2's 23:05 re-save).
  - r450 (page box 26) before: `main` water (was empty; P2's answer).
  - r172 after and r395 (page box 7) before: the chosen `main` (bare; sparse vegetation) was not among
    the ticked covers, so it was ticked. `derive()` already counts the main cover as present, so the
    derived change of both boxes is unchanged.
