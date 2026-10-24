# D15 model / image-set comparison: 360 checks on 60 of 60 development regions

Regions outside the 30 labelled sites only (data/quangninh/vlm_dev_sample.json). Criteria in docs/decisions.md D15.

## Per condition (detected regions)

| Condition | n | change | no change | unsure | ✓ agrees | ≈ partly | ✓? change_only | ≠ different_type | ✗ disagrees | ? unsure | unparsed | median s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen2.5-VL-7B-Instruct · rgb | 60 | 59 (98%) | 0 (0%) | 1 (2%) | 2 (3%) | 8 (13%) | 10 (17%) | 39 (65%) | 0 (0%) | 1 (2%) | 0 | 3.7 |
| Qwen2.5-VL-7B-Instruct · rgb_swir | 60 | 60 (100%) | 0 (0%) | 0 (0%) | 2 (3%) | 11 (18%) | 10 (17%) | 37 (62%) | 0 (0%) | 0 (0%) | 0 | 4.2 |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 60 | 60 (100%) | 0 (0%) | 0 (0%) | 2 (3%) | 11 (18%) | 10 (17%) | 37 (62%) | 0 (0%) | 0 (0%) | 0 | 4.6 |
| Qwen3-VL-8B-Instruct · rgb | 60 | 36 (60%) | 22 (37%) | 2 (3%) | 1 (2%) | 5 (8%) | 7 (12%) | 23 (38%) | 22 (37%) | 2 (3%) | 0 | 3.8 |
| Qwen3-VL-8B-Instruct · rgb_swir | 60 | 52 (87%) | 8 (13%) | 0 (0%) | 2 (3%) | 6 (10%) | 10 (17%) | 34 (57%) | 8 (13%) | 0 (0%) | 0 | 5.0 |
| Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 48 (80%) | 12 (20%) | 0 (0%) | 1 (2%) | 9 (15%) | 8 (13%) | 30 (50%) | 12 (20%) | 0 (0%) | 0 | 5.5 |

## Negative controls (20 boxes with no detection within 200 m)

| Condition | n | no change (wanted) | unsure | change |
|---|---|---|---|---|
| Qwen2.5-VL-7B-Instruct · rgb | 20 | 0 (0%) | 0 (0%) | 20 (100%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | 20 | 0 (0%) | 0 (0%) | 20 (100%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 20 | 0 (0%) | 0 (0%) | 20 (100%) |
| Qwen3-VL-8B-Instruct · rgb | 20 | 11 (55%) | 5 (25%) | 4 (20%) |
| Qwen3-VL-8B-Instruct · rgb_swir | 20 | 0 (0%) | 0 (0%) | 20 (100%) |
| Qwen3-VL-8B-Instruct · rgb_swir_cir | 20 | 4 (20%) | 0 (0%) | 16 (80%) |

## Against Dynamic World class change (weak reference)

| Condition | n | DW changed → change | DW same → no change | agreement (unsure counts as miss) |
|---|---|---|---|---|
| Qwen2.5-VL-7B-Instruct · rgb | 60 | 30 (100%) | 0 (0%) | 30 (50%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | 60 | 30 (100%) | 0 (0%) | 30 (50%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 60 | 30 (100%) | 0 (0%) | 30 (50%) |
| Qwen3-VL-8B-Instruct · rgb | 60 | 24 (80%) | 17 (57%) | 41 (68%) |
| Qwen3-VL-8B-Instruct · rgb_swir | 60 | 27 (90%) | 5 (17%) | 32 (53%) |
| Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 27 (90%) | 9 (30%) | 36 (60%) |

## Same verdict across image sets

| Model | image sets | regions in all | same verdict in all |
|---|---|---|---|
| Qwen2.5-VL-7B-Instruct | rgb, rgb_swir, rgb_swir_cir | 60 | 59 (98%) |
| Qwen3-VL-8B-Instruct | rgb, rgb_swir, rgb_swir_cir | 60 | 40 (67%) |

## Between conditions

| Condition A | Condition B | regions in both | same verdict | same verdict + types |
|---|---|---|---|---|
| Qwen2.5-VL-7B-Instruct · rgb | Qwen2.5-VL-7B-Instruct · rgb_swir | 60 | 59 (98%) | 46 (77%) |
| Qwen2.5-VL-7B-Instruct · rgb | Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 60 | 59 (98%) | 46 (77%) |
| Qwen2.5-VL-7B-Instruct · rgb | Qwen3-VL-8B-Instruct · rgb | 60 | 36 (60%) | 3 (5%) |
| Qwen2.5-VL-7B-Instruct · rgb | Qwen3-VL-8B-Instruct · rgb_swir | 60 | 52 (87%) | 12 (20%) |
| Qwen2.5-VL-7B-Instruct · rgb | Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 48 (80%) | 7 (12%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 60 | 60 (100%) | 57 (95%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | Qwen3-VL-8B-Instruct · rgb | 60 | 36 (60%) | 0 (0%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | Qwen3-VL-8B-Instruct · rgb_swir | 60 | 52 (87%) | 6 (10%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 48 (80%) | 0 (0%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | Qwen3-VL-8B-Instruct · rgb | 60 | 36 (60%) | 0 (0%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | Qwen3-VL-8B-Instruct · rgb_swir | 60 | 52 (87%) | 8 (13%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 48 (80%) | 1 (2%) |
| Qwen3-VL-8B-Instruct · rgb | Qwen3-VL-8B-Instruct · rgb_swir | 60 | 41 (68%) | 32 (53%) |
| Qwen3-VL-8B-Instruct · rgb | Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 44 (73%) | 36 (60%) |
| Qwen3-VL-8B-Instruct · rgb_swir | Qwen3-VL-8B-Instruct · rgb_swir_cir | 60 | 54 (90%) | 45 (75%) |

## Model disagreements to look at (64)

- c1 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c10 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c11 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- c12 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c13 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- c14 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c15 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c16 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- c17 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c19 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c20 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c4 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c5 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- c6 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c7 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- c9 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r1 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r148 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r158 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r170 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r176 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r204 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r23 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- r238 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r287 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct unsure
- r294 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r31 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r340 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r349 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r359 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r373 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r408 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r419 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r43 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r433 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r442 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r443 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r476 (rgb): Qwen2.5-VL-7B-Instruct unsure; Qwen3-VL-8B-Instruct no_change
- r5 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r84 (rgb): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r158 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r287 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r294 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r340 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r419 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r420 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r476 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r5 (rgb_swir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c11 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c20 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c6 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- c7 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r158 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r204 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r294 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r340 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r373 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r409 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r419 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r420 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r43 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r442 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r476 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change
- r5 (rgb_swir_cir): Qwen2.5-VL-7B-Instruct change; Qwen3-VL-8B-Instruct no_change

## Against the hand decisions on disagreements

| Condition | adjudicated regions | matches |
|---|---|---|
| Qwen2.5-VL-7B-Instruct · rgb | 26 | 17 (65%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir | 26 | 17 (65%) |
| Qwen2.5-VL-7B-Instruct · rgb_swir_cir | 26 | 17 (65%) |
| Qwen3-VL-8B-Instruct · rgb | 26 | 9 (35%) |
| Qwen3-VL-8B-Instruct · rgb_swir | 26 | 14 (54%) |
| Qwen3-VL-8B-Instruct · rgb_swir_cir | 26 | 13 (50%) |
