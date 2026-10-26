"""D7 step 1: typed request -> validated SearchSpec (agents/search_spec.py, POST /api/search_spec)."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from agents import search_spec
from agents.vlm_client import VLMClient
from webapp.backend import main

GOOD = {"change_types": ["vegetation_loss", "built_up_increase"], "min_ha": 5, "locations": ["north-east"],
        "scope": "drawn", "before_window": ["2018-11-01", "2019-03-31"], "after_window": ["2022-11-01", "2023-03-31"]}


def test_parse_answer_handles_fences_prose_and_garbage():
    assert search_spec.parse_answer('```json\n{"min_ha": 5}\n```') == {"min_ha": 5}
    assert search_spec.parse_answer('Sure! {"a": {"b": 1}} hope that helps') == {"a": {"b": 1}}
    assert search_spec.parse_answer("no json here") is None
    assert search_spec.parse_answer("[1, 2]") is None
    assert search_spec.parse_answer('{"broken": ') is None


def test_validate_keeps_good_fields():
    spec, notes = search_spec.validate(GOOD)
    assert spec["change_types"] == GOOD["change_types"] and spec["min_ha"] == 5.0 and spec["scope"] == "drawn"
    assert spec["before_window"] == GOOD["before_window"] and notes == []


def test_validate_drops_and_reports_bad_fields():
    spec, notes = search_spec.validate({
        "change_types": ["vegetation_loss", "lava"], "locations": "atlantis", "min_ha": -3, "top": 5000,
        "class_from": "forest", "scope": "everywhere"})
    assert spec["change_types"] == ["vegetation_loss"]
    assert spec["locations"] is None and spec["min_ha"] is None and spec["top"] is None
    assert spec["class_from"] is None and spec["scope"] is None
    assert len(notes) == 6


def test_validate_swaps_reversed_sizes():
    spec, _ = search_spec.validate({"min_ha": 50, "max_ha": 5})
    assert (spec["min_ha"], spec["max_ha"]) == (5.0, 50.0)


@pytest.mark.parametrize("bw, aw", [
    (["2022-11-01", "2023-03-31"], ["2018-11-01", "2019-03-31"]),    # before after after
    (["2018-11-01", "2020-03-31"], ["2022-11-01", "2023-03-31"]),    # longer than 12 months
    (["Nov 2018", "Mar 2019"], ["2022-11-01", "2023-03-31"]),        # not ISO
])
def test_validate_drops_invalid_windows_together(bw, aw):
    spec, notes = search_spec.validate({"min_ha": 1, "before_window": bw, "after_window": aw})
    assert spec["before_window"] is None and spec["after_window"] is None
    assert any("dates" in n for n in notes)


def test_prompt_lists_the_schema_vocabulary_and_forbids_coordinates():
    p = search_spec.build_prompt("trees to built in the north", date(2026, 10, 25))
    assert "vegetation_loss" in p and "north-east" in p and "shrub_and_scrub" in p
    assert "Today is 2026-10-25" in p and "Do not invent coordinates" in p and "trees to built" in p


def _replay(tmp_path, answers):
    f = tmp_path / "replay.json"
    f.write_text(json.dumps({f"{search_spec.PROMPT_VERSION}:{k}": v for k, v in answers.items()}))
    return VLMClient(mode="replay", replay_file=str(f))


def test_spec_from_prompt_ok_and_invalid(tmp_path):
    vlm = _replay(tmp_path, {"mining 2018 vs 2022": json.dumps(GOOD), "hmm": "I cannot help", "empty": "{}"})
    ok = search_spec.spec_from_prompt(vlm, "mining 2018 vs 2022")
    assert ok["status"] == "ok" and ok["spec"]["change_types"] == GOOD["change_types"]
    assert search_spec.spec_from_prompt(vlm, "hmm")["status"] == "invalid"
    assert search_spec.spec_from_prompt(vlm, "empty")["status"] == "invalid"


def test_endpoint_503_without_a_model_and_ok_with_one(tmp_path, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "vlm", VLMClient(mode="off"))
    assert client.post("/api/search_spec", json={"prompt": "big changes"}).status_code == 503
    monkeypatch.setattr(main, "vlm", _replay(tmp_path, {"big changes": json.dumps({"min_ha": 20})}))
    body = client.post("/api/search_spec", json={"prompt": "big changes"}).json()
    assert body["status"] == "ok" and body["spec"]["min_ha"] == 20.0
    assert client.post("/api/search_spec", json={"prompt": "  "}).status_code == 400
