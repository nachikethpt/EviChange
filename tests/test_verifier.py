import pytest

from agents.verifier import claimed_change_types, claimed_locations, verify

EV = {
    "change_frac": 0.02,
    "regions": [
        {"id": "r1", "area_ha": 182.4, "mean_conf": 0.86, "dNDVI": -0.34, "dNDBI": 0.21, "dMNDWI": -0.03, "location": "north-east"},
        {"id": "r2", "area_ha": 41.7, "mean_conf": 0.55, "dNDVI": 0.04, "dNDBI": 0.03, "dMNDWI": 0.16, "location": "south-west"},
        {"id": "r3", "area_ha": 19.9, "mean_conf": 0.33, "dNDVI": -0.25, "dNDBI": 0.02, "dMNDWI": 0.00, "location": "west"},
    ],
}
EMPTY = {"change_frac": 0.0, "regions": []}


def claim(level, type_, text, **extra):
    return {"claim_id": "c1", "level": level, "type": type_, "text": text,
            "region_ref": None, "evidence_ref": [], "stated_conf": None, **extra}


@pytest.mark.parametrize("c, ev, expected", [
    # L4 is never checkable
    (claim("L4", "cause", "The expansion is likely illegal."), EV, ("unsupported", "beyond_evidence")),
    (claim("L3", "cause", "Caused by coal mining."), EV, ("unsupported", "beyond_evidence")),
    # malformed / bad citations
    ({"claim_id": "c1", "text": "hi"}, EV, ("uncertain", "malformed_claim")),
    (claim("L1", "presence", "Change occurred.", evidence_ref=["licence_map"]), EV, ("unsupported", "cites_missing_evidence")),
    # L1 presence, including the prototype's understatement rule
    (claim("L1", "presence", "Land-cover change occurred."), EV, ("supported", "consistent_with_mask")),
    (claim("L1", "presence", "No significant change is visible."), EV, ("unsupported", "denies_detected_change")),
    (claim("L1", "presence", "Land-cover change occurred."), EMPTY, ("unsupported", "change_not_in_evidence")),
    (claim("L1", "presence", "No change detected in the selected area."), EMPTY, ("supported", "consistent_with_mask")),
    # L2 extent: numbers are checked, vague extent is not
    (claim("L2", "extent", "About 244 ha changed in total."), EV, ("supported", "extent_matches")),
    (claim("L2", "extent", "About 900 ha changed in total."), EV, ("unsupported", "extent_mismatch")),
    (claim("L2", "extent", "Roughly 2% of the area changed."), EV, ("supported", "extent_matches")),
    (claim("L2", "extent", "Roughly 30% of the area changed."), EV, ("unsupported", "extent_mismatch")),
    (claim("L2", "extent", "A large area changed."), EV, ("uncertain", "extent_not_quantified")),
    # L2 location, region-bound and free-text
    (claim("L2", "location", "Region r1: 182 ha of change in the north-east.", region_ref="r1"), EV, ("supported", "region_located")),
    (claim("L2", "location", "Region r1: change in the south.", region_ref="r1"), EV, ("unsupported", "location_mismatch")),
    (claim("L2", "location", "Region r9 changed.", region_ref="r9"), EV, ("unsupported", "unknown_region")),
    (claim("L2", "location", "Change is concentrated in the south-east."), EV, ("unsupported", "no_change_at_location")),
    (claim("L2", "location", "There is change in the northern part."), EV, ("supported", "region_located")),
    (claim("L2", "location", "Region r1 is 500 ha in the north-east.", region_ref="r1"), EV, ("unsupported", "extent_mismatch")),
    # L3 change type: structured and free text
    (claim("L3", "change_type", "Vegetation loss in r1.", region_ref="r1", change_type="vegetation_loss"), EV, ("supported", "index_supports_type")),
    (claim("L3", "change_type", "Vegetation gain in r1.", region_ref="r1", change_type="vegetation_gain"), EV, ("unsupported", "contradicts_index")),
    (claim("L3", "change_type", "Water increase in r1.", region_ref="r1", change_type="water_increase"), EV, ("unsupported", "below_threshold")),
    (claim("L3", "change_type", "Forest was replaced with exposed soil in the north-east."), EV, ("supported", "index_supports_type")),
    (claim("L3", "change_type", "A new water reservoir appears in the south."), EV, ("supported", "index_supports_type")),
    (claim("L3", "change_type", "A new lake appeared in the north-east."), EV, ("unsupported", "below_threshold")),
    (claim("L3", "change_type", "Something odd happened in the north-east."), EV, ("uncertain", "type_not_checkable")),
    (claim("L3", "change_type", "Vegetation was lost."), EMPTY, ("unsupported", "change_not_in_evidence")),
    # quoted numbers must match
    (claim("L3", "change_type", "Region r1 shows vegetation loss (dNDVI -0.34).", region_ref="r1", change_type="vegetation_loss"), EV, ("supported", "index_supports_type")),
    (claim("L3", "change_type", "Region r1 shows vegetation loss (dNDVI -0.60).", region_ref="r1", change_type="vegetation_loss"), EV, ("unsupported", "misquoted_evidence")),
    # a true claim resting only on a weak detection
    (claim("L3", "change_type", "Vegetation loss in the west.", change_type="vegetation_loss"), EV, ("uncertain", "low_detection_confidence")),
    (claim("L2", "location", "No change in the north-east."), EV, ("unsupported", "denies_detected_change")),
])
def test_verdicts(c, ev, expected):
    assert tuple(verify(c, ev)) == expected


def test_confidence_threshold_is_a_parameter():
    c = claim("L3", "change_type", "Vegetation loss in the west.", change_type="vegetation_loss")
    assert verify(c, EV, min_conf=0.3).verdict == "supported"


def test_text_parsing_helpers():
    assert claimed_locations("in the North-Eastern corner and the centre") == {"north-east", "centre"}
    assert claimed_locations("southwest") == {"south-west"}
    assert claimed_change_types({"text": "Forest was cleared for an open pit"}) == {"vegetation_loss", "built_up_increase"}
    assert claimed_change_types({"text": "The pond dried up"}) == {"water_decrease"}
    assert claimed_change_types({"text": "anything", "change_type": "water_increase"}) == {"water_increase"}
