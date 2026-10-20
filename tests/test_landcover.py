"""Land-cover classes (D10, Phase 9): field handling, schema rules and the labelled-site guard.
Earth Engine itself is not called here."""
import json

import pytest
from fastapi.testclient import TestClient

from agents import landcover, vlm_check
from agents.schema import LANDCOVER_CLASSES, validate_region
from webapp.backend import data_store, main


def square(cx, cy, d=0.002):
    return {"type": "Polygon", "coordinates": [[[cx - d, cy - d], [cx + d, cy - d], [cx + d, cy + d], [cx - d, cy + d], [cx - d, cy - d]]]}


BASE = {"id": "r1", "area_ha": 5.0, "mean_conf": 0.3, "dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.0, "location": "west"}
FRAC = {c: 0.0 for c in LANDCOVER_CLASSES} | {"trees": 0.7, "bare": 0.3}


def test_transition():
    assert landcover.transition({"class_before": "trees", "class_after": "bare"}) == "trees → bare"
    assert landcover.transition({"class_before": "water", "class_after": "water"}) == "water"
    assert landcover.transition({"class_before": None, "class_after": "built"}) is None
    assert landcover.transition({}) is None


def test_props_from_reduce_regions_output():
    stats = {"b_label_mode": 1.0, **{f"b_{c}_mean": v for c, v in FRAC.items()}}
    assert landcover._props(stats, "b") == {"class": "trees", "frac": FRAC}
    assert landcover._props({}, "a") == {"class": None, "frac": None}            # no image in the window: never guessed


def test_batches_respect_size():
    feats = [{"geometry": square(107.3, 21.0 + i / 100), "properties": {"id": f"r{i}"}} for i in range(10)]
    size = lambda b: sum(len(json.dumps(f["geometry"])) for f in b)  # noqa: E731
    limit = 3 * len(json.dumps(feats[0]["geometry"]))
    batches = landcover._batches(feats, max_bytes=limit)
    assert len(batches) > 1 and all(size(b) <= limit for b in batches) and sum(batches, []) == feats


@pytest.mark.parametrize("fields, ok", [
    ({}, True),                                                                   # regions before Phase 9
    ({"class_before": "trees", "class_after": "bare", "class_frac_before": FRAC, "class_frac_after": FRAC}, True),
    ({"class_before": None, "class_after": None, "class_frac_before": None, "class_frac_after": None}, True),
    ({"class_before": "forest"}, False),
    ({"class_frac_after": {"lava": 0.5}}, False),
    ({"class_frac_after": {"trees": 1.5}}, False),
])
def test_schema_class_fields(fields, ok):
    assert (validate_region({**BASE, **fields}) == []) is ok


def _fc():
    site = vlm_check.labelled_site_boxes()[0]
    classes = {"class_before": "trees", "class_after": "bare", "class_frac_before": FRAC, "class_frac_after": FRAC}
    return {"type": "FeatureCollection", "metadata": {}, "features": [
        {"type": "Feature", "geometry": square(107.215, 20.975), "properties": {**BASE, "id": "free", **classes}},
        {"type": "Feature", "geometry": square((site[0] + site[2]) / 2, (site[1] + site[3]) / 2),
         "properties": {**BASE, "id": "onsite", **classes}}]}


def test_classes_hidden_at_labelled_sites(monkeypatch):
    out = landcover.hide_at_labelled_sites(_fc())
    free, onsite = (f["properties"] for f in out["features"])
    assert free["class_after"] == "bare" and "class_hidden" not in free
    assert onsite["class_hidden"] is True and not any(k in onsite for k in landcover.CLASS_FIELDS)
    assert _fc()["features"][1]["properties"]["class_after"] == "bare"           # input not modified
    monkeypatch.setattr(landcover, "CLASSES_UNLOCKED_AT_LABELLED_SITES", True)
    assert landcover.hide_at_labelled_sites(_fc())["features"][1]["properties"]["class_after"] == "bare"


def test_api_hides_classes_at_labelled_sites(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    (tmp_path / "change_regions.json").write_text(json.dumps(_fc()))
    body = TestClient(main.app).get("/api/data/change_regions").json()
    by_id = {f["properties"]["id"]: f["properties"] for f in body["features"]}
    assert by_id["free"]["class_before"] == "trees"
    assert by_id["onsite"].get("class_hidden") is True and "class_before" not in by_id["onsite"]
