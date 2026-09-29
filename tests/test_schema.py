import pytest
import random

from agents import tools
from agents.schema import REASONS, SchemaError, check, validate_aoi, validate_change_regions, validate_claim, validate_evidence, validate_region, validate_windows
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


def test_aoi_validation_accepts_study_polygon_and_rejects_point():
    aoi = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
    assert validate_aoi(aoi) == []
    assert validate_aoi({"type": "Point", "coordinates": [107.3, 21.04]})


def test_window_validation():
    assert validate_windows(["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]) == []
    assert validate_windows(["2019-03-31", "2019-01-01"], ["2022-11-01", "2023-03-31"])
    assert validate_windows(["2019-01-01", "2020-06-01"], ["2022-11-01", "2023-03-31"])
    assert validate_windows(["2019-01-01", "2019-06-01"], ["2019-05-01", "2019-07-01"])


def test_mock_detector_region_and_metadata_contract(monkeypatch):
    monkeypatch.setenv("EVICHANGE_ENGINE", "mock")
    aoi = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
    before = ["2018-11-01", "2019-03-31"]
    after = ["2022-11-01", "2023-03-31"]
    thresholds = {"max_cloud_pct": 30, "index_delta": 0.1, "min_area_ha": 1.0, "mean_conf_min": 0.5}
    change_frac, regions, metadata = tools.run_change_detection(random.Random(4), aoi, before, after, thresholds, n_regions=20)
    assert 0 <= change_frac <= 1
    assert all(validate_region(region) == [] for region in regions)
    assert metadata["before_window"] == before
    assert metadata["after_window"] == after
    assert metadata["thresholds"] == thresholds
    assert metadata["aoi"] == aoi
