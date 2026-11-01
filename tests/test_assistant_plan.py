"""D9 / Phase 7c, VLM side: typed request -> map-assistant steps (agents/assistant_plan.py, POST /api/assistant/plan)."""
import json

from fastapi.testclient import TestClient

from agents import assistant_plan as ap
from agents.vlm_client import VLMClient
from webapp.backend import main


def test_check_step_keeps_good_and_drops_bad():
    assert ap.check_step({"action": "buffer", "layer": "rivers", "distance": 2, "units": "kilometers"}) == (
        {"action": "buffer", "layer": "rivers", "distance": 2.0, "units": "kilometers"}, None)
    assert ap.check_step({"action": "style_layer", "layer": "aoi", "color": "Gray", "opacity": 0.2})[0] == {
        "action": "style_layer", "layer": "aoi", "color": "grey", "opacity": 0.2}
    assert ap.check_step({"action": "add_index_layer", "index": "ndvi"})[0] == {"action": "add_index_layer", "index": "NDVI", "kind": "change"}
    for bad in ({"action": "buffer", "layer": "x", "distance": 0}, {"action": "style_layer", "layer": "x", "opacity": 3},
                {"action": "style_layer", "layer": "x"}, {"action": "export", "layer": "x", "format": "shp"},
                {"action": "run", "layer": "x"}, {"action": "dissolve", "layer": "x", "field": "a; drop"}, {"action": "clip", "layer": "x"}):
        assert ap.check_step(bad)[0] is None


def test_validate_plans():
    assert ap.validate({"search": True}) == {"status": "search"}
    assert ap.validate({"steps": []})["status"] == "invalid"
    assert ap.validate({"steps": [{"action": "zoom", "layer": "it"}]})["status"] == "invalid"
    half = ap.validate({"steps": [{"action": "zoom", "layer": "aoi"}, {"action": "teleport"}]})
    assert half["status"] == "invalid" and "teleport" in half["detail"]          # one bad step: nothing runs
    assert ap.validate({"steps": [{"action": "chart"}] * (ap.MAX_STEPS + 1)})["status"] == "invalid"
    assert ap.validate({"steps": [{"action": "undo"}]}) == {"status": "ok", "steps": [{"action": "undo"}], "notes": []}


def test_prompt_lists_layers_and_never_runs():
    text = ap.build_prompt("outline the rivers in blue", ["River lines", "Study area (AOI)"])
    assert '"River lines", "Study area (AOI)"' in text and "Never start an analysis run" in text


def _replay(tmp_path, answers):
    f = tmp_path / "replay.json"
    f.write_text(json.dumps({f"{ap.PROMPT_VERSION}:{k}": v for k, v in answers.items()}))
    return VLMClient(mode="replay", replay_file=str(f))


def test_endpoint(tmp_path, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "vlm", VLMClient(mode="off"))
    assert client.post("/api/assistant/plan", json={"text": "outline rivers"}).status_code == 503
    monkeypatch.setattr(main, "vlm", _replay(tmp_path, {
        "outline the rivers in blue": json.dumps({"steps": [{"action": "style_layer", "layer": "River lines", "color": "blue"}]}),
        "forest loss": json.dumps({"search": True}), "nonsense": "I can't"}))
    ok = client.post("/api/assistant/plan", json={"text": "outline the rivers in blue", "layers": ["River lines"]}).json()
    assert ok["status"] == "ok" and ok["steps"] == [{"action": "style_layer", "layer": "River lines", "color": "blue"}]
    assert client.post("/api/assistant/plan", json={"text": "forest loss"}).json()["status"] == "search"
    assert client.post("/api/assistant/plan", json={"text": "nonsense"}).json()["status"] == "invalid"
    assert client.post("/api/assistant/plan", json={"text": " "}).status_code == 400
