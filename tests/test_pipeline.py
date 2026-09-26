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
