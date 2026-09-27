import pytest

from agents.schema import REASONS, SchemaError, check, validate_change_regions, validate_claim, validate_evidence, validate_region
from webapp.backend import demo_data

GOOD = {"id": "r1", "area_ha": 10.0, "mean_conf": 0.5, "dNDVI": -0.2, "dNDBI": 0.1, "dMNDWI": 0.0, "location": "north"}


def test_good_region_and_evidence():
    assert validate_region(GOOD) == []
    assert validate_evidence({"change_frac": 0.1, "regions": [GOOD]}) == []


@pytest.mark.parametrize("patch, fragment", [
    ({"location": "upstairs"}, "location"),
    ({"mean_conf": 1.5}, "mean_conf"),
    ({"area_ha": -1}, "area_ha"),
    ({"dNDVI": "big"}, "dNDVI"),
])
def test_bad_region(patch, fragment):
    errors = validate_region({**GOOD, **patch})
    assert errors and fragment in errors[0]


def test_duplicate_region_ids_rejected():
    assert any("unique" in e for e in validate_evidence({"change_frac": 0.1, "regions": [GOOD, GOOD]}))


def test_claim_validation():
    ok = {"claim_id": "c1", "level": "L3", "type": "change_type", "text": "x", "evidence_ref": [], "change_type": "vegetation_loss"}
    assert validate_claim(ok) == []
    assert validate_claim({**ok, "level": "L5"})
    assert validate_claim({**ok, "change_type": "mining"})
    assert validate_claim({**ok, "verdict_reason": "vibes"})


def test_demo_data_matches_schema():
    """The web app's fallback data must satisfy the same contract as real data."""
    assert validate_change_regions(demo_data.CHANGE_REGIONS) == []


def test_check_raises():
    with pytest.raises(SchemaError):
        check(["boom"], "thing")
    check([], "thing")


def test_every_reason_has_text():
    assert all(isinstance(v, str) and v for v in REASONS.values())
