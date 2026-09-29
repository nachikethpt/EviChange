from agents.graph import run_pipeline


AOI = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
BEFORE = ["2018-11-01", "2019-03-31"]
AFTER = ["2022-11-01", "2023-03-31"]


def test_pipeline_publishes_gated_report():
    result = run_pipeline("test-aoi", AOI, BEFORE, AFTER)
    assert result["status"] == "done"
    assert result["published_geojson"]["type"] == "FeatureCollection"
    assert result["published_report"]["condition"] == "gated"
    assert result["published_geojson"]["metadata"]["before_window"] == BEFORE
    assert result["published_geojson"]["metadata"]["after_window"] == AFTER
    assert result["published_geojson"]["metadata"]["aoi"] == AOI
    assert result["attempt"] <= 3


def test_invalid_condition_fails_without_ingestion():
    result = run_pipeline("test-aoi", AOI, BEFORE, AFTER, condition="invalid")
    assert result["status"] == "failed"
    assert result["attempt"] == 1
    assert len(result["log"]) == 2


def test_case_normalized_condition_and_invalid_input_rejected():
    result = run_pipeline("caps-aoi", AOI, BEFORE, AFTER, condition="GATED")
    assert result["status"] == "done"
    assert result["published_report"]["condition"] == "gated"

    bad_input = run_pipeline("bad-aoi", None, BEFORE, AFTER)
    assert bad_input["status"] == "failed"

    bad_dates = run_pipeline("bad-dates", AOI, AFTER, BEFORE)
    assert bad_dates["status"] == "failed"
