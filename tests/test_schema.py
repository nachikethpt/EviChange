import pytest
import random

from agents import tools
from agents.schema import (REASONS, SchemaError, aoi_area_ha, check, validate_aoi, validate_change_regions, validate_claim,
                           validate_evidence, validate_region, validate_strip, validate_transect, validate_windows)
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


def ring(w, s, e, n):
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


@pytest.mark.parametrize("aoi, fragment", [
    ({"type": "Polygon", "coordinates": [5]}, "lists of rings"),
    ({"type": "MultiPolygon", "coordinates": [[5]]}, "lists of rings"),
    ({"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [1, 2]]]}, "invalid or zero-area ring"),       # too few points
    ({"type": "Polygon", "coordinates": [ring(107.2, 21.0, 107.3, 21.1)[:-1]]}, "invalid or zero-area ring"),   # not closed
    ({"type": "Polygon", "coordinates": [ring(200.0, 21.0, 200.1, 21.1)]}, "out of range"),
    ({"type": "Polygon", "coordinates": [ring(107.2, 21.0, 107.201, 21.001)]}, "between 1 and 500"),   # ~0.01 km²
    ({"type": "Polygon", "coordinates": []}, "non-empty"),
    ("not an object", "GeoJSON object"),
])
def test_bad_aoi(aoi, fragment):
    errors = validate_aoi(aoi)
    assert any(fragment in e for e in errors), errors


def test_aoi_hole_is_subtracted():
    outer, hole = ring(107.2, 21.0, 107.3, 21.1), ring(107.22, 21.02, 107.28, 21.08)
    full = aoi_area_ha({"type": "Polygon", "coordinates": [outer]})
    holed = {"type": "Polygon", "coordinates": [outer, hole]}
    assert validate_aoi(holed) == []
    assert aoi_area_ha(holed) == pytest.approx(full * (1 - 0.36), rel=1e-3)
    two = {"type": "MultiPolygon", "coordinates": [[outer], [ring(107.4, 21.0, 107.5, 21.1)]]}
    assert aoi_area_ha(two) == pytest.approx(2 * full, rel=1e-2)


def test_windows_sharing_a_day_overlap():
    """Window ends are inclusive (ee_engine._inclusive_end), so a shared day is in both composites."""
    assert validate_windows(["2019-01-01", "2019-03-31"], ["2019-03-31", "2019-06-01"])
    assert validate_windows(["2019-01-01", "2019-03-31"], ["2019-04-01", "2019-06-01"]) == []
    assert validate_windows("2019", None) == ["before_window must be [start, end]", "after_window must be [start, end]"]


def test_transect_and_strip_validation():
    tr = {"id": "t1", "location": "north", "change": "advancing", "nsm": 12.0, "lrr": 3.1, "ci95": 1.0}
    assert validate_transect(tr) == []
    assert validate_transect({**tr, "nsm": None, "lrr": None, "ci95": None}) == []      # too few quarters
    assert validate_transect({**tr, "change": "eroding"}) and validate_transect({**tr, "nsm": "far"})
    assert validate_transect({"id": "t1"}) and validate_transect("t1") == ["transect is not an object"]
    st = {"strip": "0-200", "built_ha_before": 1.0, "built_ha_after": 2.5}
    assert validate_strip(st) == [] and validate_strip({**st, "location": "east"}) == []
    assert validate_strip({**st, "strip": "0-1000"}) and validate_strip({**st, "built_ha_after": -1})
    assert validate_strip({**st, "location": "inland"})
    ev = {"change_frac": 0.1, "regions": [], "transects": [tr, tr], "coastal_strips": [st]}
    assert any("transect ids are not unique" in e for e in validate_evidence(ev))
    assert any("'coastal_strips' must be a list" in e for e in validate_evidence({**ev, "transects": [], "coastal_strips": {}}))


def test_coast_and_landcover_claim_fields():
    ok = {"claim_id": "c1", "level": "L2", "type": "shoreline", "text": "x", "evidence_ref": [], "shoreline_change": "retreating"}
    assert validate_claim(ok) == []
    assert validate_claim({**ok, "shoreline_change": "eroding"})
    assert validate_claim({**ok, "type": "coastal_built", "shoreline_change": None, "strip": "0-500"}) == []
    assert validate_claim({**ok, "strip": "0-1000"})
    assert validate_claim({**ok, "class_before": "forest"})
    assert validate_claim({**ok, "verdict": "maybe"})
    assert validate_claim({**ok, "evidence_ref": "nsm"})
    assert validate_claim("c1") == ["claim is not an object"]


def test_change_regions_validation():
    point = {"type": "Point", "coordinates": [107.3, 21.0]}
    good = {"type": "Feature", "geometry": point, "properties": GOOD}
    assert validate_change_regions({"type": "FeatureCollection", "features": [good]}) == []
    assert validate_change_regions({"type": "Feature"}) == ["not a GeoJSON FeatureCollection"]
    bad = validate_change_regions({"type": "FeatureCollection", "features": [
        {**good, "geometry": {"type": "LineString", "coordinates": []}}, good, {"geometry": point, "properties": None}]})
    assert any("unsupported geometry" in e for e in bad) and any("unique" in e for e in bad)
    assert any("region is not an object" in e for e in bad)


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
