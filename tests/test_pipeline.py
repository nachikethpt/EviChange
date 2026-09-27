from agents.graph import run_pipeline


AOI = {"type": "Point", "coordinates": [107.3, 21.04]}


def test_pipeline_publishes_gated_report():
    result = run_pipeline("test-aoi", AOI, "2018-01-01", "2022-06-01")
    assert result["status"] == "done"
    assert result["published_geojson"]["type"] == "FeatureCollection"
    assert result["published_report"]["condition"] == "gated"
    assert result["attempt"] <= 3


def test_invalid_condition_fails_without_ingestion():
    result = run_pipeline("test-aoi", AOI, "2018-01-01", "2022-06-01", condition="invalid")
    assert result["status"] == "failed"
    assert result["attempt"] == 1
    assert len(result["log"]) == 2


def test_case_normalized_condition_and_invalid_input_rejected():
    result = run_pipeline("caps-aoi", AOI, "2018-01-01", "2022-06-01", condition="GATED")
    assert result["status"] == "done"
    assert result["published_report"]["condition"] == "gated"

    bad_input = run_pipeline("bad-aoi", None, "2018-01-01", "2022-06-01")
    assert bad_input["status"] == "failed"

    bad_dates = run_pipeline("bad-dates", AOI, "2022-06-01", "2018-01-01")
    assert bad_dates["status"] == "failed"
