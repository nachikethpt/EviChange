# Report prompts on development boxes

Detected = 60 development regions, control = 20 boxes with no detection within 200 m (the evaluation's random-site stratum). Verdicts from agents/verifier.py against each box's evidence.

## Per arm

| Arm | model | prompt | stratum | boxes | claims/box | supported | unsupported | uncertain | L4 claims | claims change | abstain/box | parse fails | dropped items | cleared classes | median s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v1 | control | 2 | 0.0 | – | – | – | – | 0 (0%) | 0.0 | 0 | 2 | 0 | 25.7 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v1 | detected | 2 | 2.5 | 5 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) | 0.0 | 0 | 0 | 0 | 41.7 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v2 | control | 7 | 1.0 | 7 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 22.3 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v2 | detected | 60 | 2.8 | 117 (71%) | 20 (12%) | 28 (17%) | 0 (0%) | 50 (83%) | 0.1 | 1 | 2 | 0 | 31.9 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v3 | control | 20 | 1.0 | 20 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 23.8 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v3 | detected | 60 | 2.9 | 140 (80%) | 15 (9%) | 19 (11%) | 0 (0%) | 52 (87%) | 0.1 | 4 | 4 | 0 | 18.4 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v4 | control | 20 | 1.0 | 20 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 5.9 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v4 | detected | 60 | 3.2 | 151 (77%) | 14 (7%) | 30 (15%) | 0 (0%) | 56 (93%) | 0.0 | 2 | 0 | 0 | 19.2 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v5 | control | 20 | 1.0 | 20 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 5.9 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v5 | detected | 60 | 5.8 | 233 (67%) | 26 (7%) | 91 (26%) | 0 (0%) | 59 (98%) | 0.0 | 1 | 2 | 0 | 29.6 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v6 | control | 20 | 1.0 | 20 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 5.9 |
| gated | Qwen2.5-VL-7B-Instruct | gated_report_v6 | detected | 60 | 3.5 | 153 (72%) | 14 (7%) | 45 (21%) | 0 (0%) | 60 (100%) | 0.0 | 0 | 0 | 0 | 18.7 |
| template | rules | template | control | 20 | 1.0 | 20 (100%) | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 0.0 | 0 | 0 | 0 | 0.0 |
| template | rules | template | detected | 60 | 6.8 | 296 (73%) | 0 (0%) | 109 (27%) | 0 (0%) | 60 (100%) | 0.0 | 0 | 0 | 0 | 0.0 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v1 | control | 2 | 2.0 | 0 (0%) | 4 (100%) | 0 (0%) | 0 (0%) | 2 (100%) | 0.0 | 0 | 7 | 0 | 39.4 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v1 | detected | 2 | 2.0 | 3 (75%) | 1 (25%) | 0 (0%) | 0 (0%) | 1 (50%) | 0.0 | 0 | 5 | 0 | 31.9 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v2 | control | 20 | 4.2 | 1 (1%) | 71 (84%) | 13 (15%) | 0 (0%) | 19 (95%) | 0.0 | 0 | 25 | 0 | 33.9 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v2 | detected | 60 | 4.1 | 201 (82%) | 8 (3%) | 37 (15%) | 0 (0%) | 51 (85%) | 0.0 | 0 | 90 | 0 | 39.1 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v3 | control | 2 | 5.5 | 0 (0%) | 8 (73%) | 3 (27%) | 0 (0%) | 2 (100%) | 0.0 | 0 | 0 | 0 | 37.5 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v3 | detected | 55 | 4.8 | 83 (31%) | 107 (40%) | 75 (28%) | 12 (5%) | 52 (95%) | 0.0 | 0 | 52 | 0 | 36.9 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v4 | control | 15 | 3.3 | 1 (2%) | 33 (66%) | 16 (32%) | 1 (2%) | 14 (93%) | 0.0 | 0 | 35 | 0 | 34.8 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v4 | detected | 60 | 3.5 | 71 (33%) | 71 (33%) | 71 (33%) | 9 (4%) | 55 (92%) | 0.0 | 0 | 126 | 0 | 36.0 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v5 | control | 20 | 3.0 | 0 (0%) | 22 (37%) | 37 (63%) | 1 (2%) | 13 (65%) | 0.0 | 0 | 63 | 0 | 35.3 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v5 | detected | 60 | 2.8 | 35 (21%) | 41 (24%) | 92 (55%) | 6 (4%) | 38 (63%) | 0.0 | 0 | 188 | 0 | 34.8 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v5+claim_parse_v2 | control | 20 | 6.0 | 0 (0%) | 55 (45%) | 66 (55%) | 4 (3%) | 20 (100%) | 0.0 | 0 | 1 | 62 | 35.3 |
| ungated | Qwen2.5-VL-7B-Instruct | ungated_report_v1+claim_extract_v5+claim_parse_v2 | detected | 60 | 5.9 | 102 (29%) | 88 (25%) | 162 (46%) | 15 (4%) | 59 (98%) | 0.0 | 0 | 4 | 184 | 34.8 |

## Why claims were not supported (all strata)

- gated: low_detection_confidence × 122
- gated: type_not_checkable × 75
- gated: denies_detected_change × 37
- gated: below_threshold × 20
- gated: extent_not_quantified × 12
- gated: cites_missing_evidence × 11
- gated: coastal_built_mismatch × 9
- gated: contradicts_index × 7
- gated: unlocated_claim × 3
- gated: extent_mismatch × 3
- gated: unknown_region × 2
- gated: shoreline_unconfirmed × 1
- template: low_detection_confidence × 109
- ungated: change_not_in_evidence × 174
- ungated: coastal_not_in_evidence × 167
- ungated: class_transition_mismatch × 167
- ungated: shoreline_not_in_evidence × 165
- ungated: type_not_checkable × 84
- ungated: extent_not_quantified × 62
- ungated: beyond_evidence × 50
- ungated: unlocated_claim × 42
- ungated: low_detection_confidence × 38
- ungated: below_threshold × 37
- ungated: extent_mismatch × 33
- ungated: contradicts_index × 22
- ungated: shoreline_unconfirmed × 14
- ungated: no_change_at_location × 12
- ungated: denies_detected_change × 8
- ungated: coastal_built_mismatch × 6
