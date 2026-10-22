"""land_cover claims (D13): the verifier checks "trees were replaced by bare ground" against the
Dynamic World classes of the region (class_before / class_after, D10)."""
import pytest

from agents.schema import CLAIM_TYPES, REASONS, validate_claim
from agents.verifier import claimed_class_transition, verify

QUIET = {"dNDVI": 0.0, "dNDBI": 0.0, "dMNDWI": 0.0}
EV_LC = {
    "change_frac": 0.02,
    "regions": [
        {"id": "r1", "area_ha": 182.4, "mean_conf": 0.86, "location": "north-east", **QUIET,
         "class_before": "trees", "class_after": "bare"},
        {"id": "r2", "area_ha": 41.7, "mean_conf": 0.55, "location": "south-west", **QUIET,
         "class_before": "bare", "class_after": "water"},
        {"id": "r3", "area_ha": 19.9, "mean_conf": 0.12, "location": "west", **QUIET,
         "class_before": "crops", "class_after": "built"},
        {"id": "r4", "area_ha": 30.0, "mean_conf": 0.70, "location": "south", **QUIET,
         "class_before": None, "class_after": None},          # no usable Dynamic World scene
    ],
}
EMPTY = {"change_frac": 0.0, "regions": []}


def lc(text, level="L3", **extra):
    return {"claim_id": "c1", "level": level, "type": "land_cover", "text": text,
            "region_ref": None, "evidence_ref": [], "stated_conf": None, **extra}


@pytest.mark.parametrize("c, ev, expected", [
    # structured classes
    (lc("Region r1: trees became bare ground.", region_ref="r1", class_before="trees", class_after="bare"),
     EV_LC, ("supported", "class_transition_matches")),
    (lc("Region r1: trees became built.", region_ref="r1", class_before="trees", class_after="built"),
     EV_LC, ("unsupported", "class_transition_mismatch")),
    (lc("Region r1 is bare now.", region_ref="r1", class_after="bare"), EV_LC, ("supported", "class_transition_matches")),
    (lc("Region r1 is water now.", region_ref="r1", class_after="water"), EV_LC, ("unsupported", "class_transition_mismatch")),
    # text only, with and without a location
    (lc("Trees were replaced by bare ground in the north-east."), EV_LC, ("supported", "class_transition_matches")),
    (lc("Bare ground replaced the trees in the north-east."), EV_LC, ("supported", "class_transition_matches")),
    (lc("Region r1: forest turned into built-up area.", region_ref="r1"), EV_LC, ("unsupported", "class_transition_mismatch")),
    (lc("Bare ground became water in the south-west."), EV_LC, ("supported", "class_transition_matches")),
    (lc("Trees were replaced by bare ground."), EV_LC, ("supported", "class_transition_matches")),   # some region matches
    # a region without classes cannot be checked, and is never counted as a mismatch
    (lc("Trees became bare.", region_ref="r4", class_before="trees", class_after="bare"),
     EV_LC, ("uncertain", "class_not_in_evidence")),
    # text that names no checkable classes
    (lc("Land cover changed in the north-east."), EV_LC, ("uncertain", "type_not_checkable")),
    # a true claim resting only on a weak detection
    (lc("Crops became built.", region_ref="r3", class_before="crops", class_after="built"),
     EV_LC, ("uncertain", "low_detection_confidence")),
    # existing rules still run first
    (lc("Trees became bare in r9.", region_ref="r9", class_before="trees", class_after="bare"), EV_LC, ("unsupported", "unknown_region")),
    (lc("Trees were replaced by bare ground in the south.", region_ref="r1"), EV_LC, ("unsupported", "location_mismatch")),
    (lc("No land-cover change in the north-east."), EV_LC, ("unsupported", "denies_detected_change")),
    (lc("Trees became bare.", class_before="trees", class_after="bare"), EMPTY, ("unsupported", "change_not_in_evidence")),
    (lc("Trees became bare.", region_ref="r1", class_before="trees", class_after="bare",
        evidence_ref=["class_before", "class_after"]), EV_LC, ("supported", "class_transition_matches")),
    (lc("Trees became bare.", region_ref="r1", class_before="trees", class_after="bare",
        evidence_ref=["soil_map"]), EV_LC, ("unsupported", "cites_missing_evidence")),
    # the type decides, not the level
    (lc("Trees became bare.", level="L2", region_ref="r1", class_before="trees", class_after="bare"),
     EV_LC, ("supported", "class_transition_matches")),
])
def test_land_cover_verdicts(c, ev, expected):
    verdict = verify(c, ev)
    assert tuple(verdict) == expected
    assert verdict.reason in REASONS


@pytest.mark.parametrize("text, expected", [
    ("Trees were replaced by bare ground.", ("trees", "bare")),
    ("From trees to built-up area.", ("trees", "built")),
    ("Forest was cleared for an open pit.", ("trees", "bare")),
    ("Bare ground replaced the trees.", ("trees", "bare")),
    ("Water became built area.", ("water", "built")),
    ("Built area next to the water grew.", (None, None)),       # two classes, no direction
    ("Trees, grass and bare ground changed.", (None, None)),    # three classes
    ("The area became bare.", (None, None)),                    # one class: the before is unknown
    ("Something happened here.", (None, None)),
])
def test_text_transition_parsing(text, expected):
    assert claimed_class_transition({"text": text}) == expected


def test_structured_classes_win_over_text():
    claim = {"text": "Trees were replaced by bare ground.", "class_before": "water", "class_after": "built"}
    assert claimed_class_transition(claim) == ("water", "built")


def test_land_cover_is_a_valid_claim_type_and_classes_are_checked():
    assert "land_cover" in CLAIM_TYPES
    assert validate_claim(lc("Trees became bare.", class_before="trees", class_after="bare")) == []
    assert validate_claim(lc("Trees became lava.", class_before="trees", class_after="lava"))