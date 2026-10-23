import base64
import json

import pytest
from fastapi.testclient import TestClient

from agents import ungated
from agents.gpt_client import GPTClient
from agents.schema import CONDITIONS, REPORT_CONDITIONS, validate_claim
from agents.vlm_client import VLMClient, VLMUnavailable
from webapp.backend import data_store, main
from webapp.backend.report import build_report

BEFORE, AFTER = ["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]
EV = {"change_frac": 0.02, "regions": [
    {"id": "r1", "area_ha": 182.4, "mean_conf": 0.86, "dNDVI": -0.34, "dNDBI": 0.21, "dMNDWI": -0.03, "location": "north-east"}]}
GPT_TEXT = ("Forest in the north-east of the box was cleared for open-pit coal mining, about 180 ha. "
            "A new reservoir appeared in the south. The mine is likely unlicensed.")
EXTRACTED = json.dumps([
    {"text": "Forest in the north-east was cleared.", "level": "L3", "type": "change_type", "change_type": "vegetation_loss"},
    {"text": "About 180 ha changed.", "level": "L2", "type": "extent", "change_type": None},
    {"text": "The clearing is for open-pit coal mining.", "level": "L4", "type": "cause"},
    {"text": "A new reservoir appeared in the south.", "level": "L3", "type": "change_type", "change_type": "water_increase"},
    {"text": "The mine is likely unlicensed.", "level": "L4", "type": "cause"},
])


def replay(tmp_path, name, answers):
    path = tmp_path / name
    path.write_text(json.dumps(answers), encoding="utf-8")
    return str(path)


# ---------- GPTClient never calls OpenAI unless asked ----------
def test_gpt_is_off_by_default_even_with_a_key(monkeypatch):
    monkeypatch.delenv("EVICHANGE_GPT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "some-model")
    client = GPTClient()
    assert client.status()["available"] is False
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("must not call the network"))
    with pytest.raises(VLMUnavailable):
        client.generate("p", [b"img"])


def test_gpt_http_needs_key_and_model():
    assert GPTClient(mode="http", api_key="", model="m").status()["available"] is False
    assert GPTClient(mode="http", api_key="k", model="").status()["available"] is False


def test_gpt_http_request_shape(monkeypatch):
    """The Chat Completions payload, checked against a fake urlopen: nothing is sent anywhere."""
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"model": "m-2026", "choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, auth=req.headers["Authorization"], body=json.loads(req.data))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = GPTClient(mode="http", api_key="k", model="m").generate("prompt", [b"PNG1", b"PNG2"], max_new_tokens=50)
    assert out == {"text": "hello", "model": "m-2026"}
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == "Bearer k"
    content = seen["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "prompt"}
    assert [c["image_url"]["url"] for c in content[1:]] == [
        "data:image/png;base64," + base64.b64encode(b).decode() for b in (b"PNG1", b"PNG2")]
    assert seen["body"]["model"] == "m" and seen["body"]["max_completion_tokens"] == 50


# ---------- prompts + extraction ----------
def test_both_ungated_arms_get_no_evidence():
    prompt = ungated.build_report_prompt(BEFORE, AFTER)
    assert "2018-11-01 to 2019-03-31" in prompt and "yellow box" in prompt
    for leak in ("dNDVI", "area_ha", "mean_conf", "evidence"):
        assert leak not in prompt


@pytest.mark.parametrize("text, n, ok, dropped", [
    (EXTRACTED, 5, True, 0),
    ("```json\n" + EXTRACTED + "\n```", 5, True, 0),
    ('[{"text": "x", "level": "L9", "type": "cause"}, {"level": "L1", "type": "presence"}, "junk"]', 0, True, 3),
    ("The report says forest was cleared.", 0, False, 0),
])
def test_parse_claims(text, n, ok, dropped):
    claims, parse_ok, n_dropped = ungated.parse_claims(text)
    assert (len(claims), parse_ok, n_dropped) == (n, ok, dropped)
    assert all(validate_claim(c) == [] and c["evidence_ref"] == [] and c["stated_conf"] is None for c in claims)


def test_ungated_gpt_report_end_to_end(tmp_path):
    """GPT text -> Geo-VLM extractor -> verifier, all from replay files."""
    gpt = GPTClient(mode="replay", replay_file=replay(tmp_path, "gpt.json", {"ungated_report_v0:ungated_gpt:s1": GPT_TEXT}))
    ext = VLMClient(mode="replay", replay_file=replay(tmp_path, "ext.json", {"claim_extract_v0:ungated_gpt:s1": EXTRACTED}))
    out = ungated.run_ungated(gpt, ext, "ungated_gpt", "s1", BEFORE, AFTER, [b"a", b"b", b"c", b"d"])
    assert out["raw"] == GPT_TEXT and out["parse_ok"] and len(out["claims"]) == 5
    rep = build_report(EV, "ungated_gpt", ungated=out)
    verdicts = {c["text"]: (c["verdict"], c["verdict_reason"]) for c in rep["claims"]}
    assert verdicts["The clearing is for open-pit coal mining."] == ("unsupported", "beyond_evidence")
    assert verdicts["The mine is likely unlicensed."] == ("unsupported", "beyond_evidence")
    assert verdicts["About 180 ha changed."] == ("supported", "extent_matches")
    assert rep["status"] == "ok" and rep["extract_version"] == "claim_extract_v0"
    assert rep["counts"]["unsupported"] >= 2


def test_ungated_gpt_without_output_is_not_run():
    rep = build_report(EV, "ungated_gpt")
    assert rep["status"] == "not_run" and rep["claims"] == []


# ---------- conditions + API ----------
def test_gpt_is_a_report_arm_not_a_pipeline_condition():
    assert "ungated_gpt" in REPORT_CONDITIONS and "ungated_gpt" not in CONDITIONS


def test_api_ungated_gpt_on_demo_data_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    monkeypatch.setattr(data_store, "AOI_PATH", tmp_path / "aoi.json")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("must not call the network"))
    ids = sorted(data_store.known_region_ids())
    body = TestClient(main.app).post("/api/report", json={"region_ids": ids, "condition": "ungated_gpt"}).json()
    assert body["status"] == "not_run" and body["claims"] == [] and body["detail"]


def test_api_ungated_gpt_runs_once_and_caches(tmp_path, monkeypatch):
    """Selection -> one union-box chip set -> GPT + extractor (replayed) -> verified report; second call is cached."""
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    monkeypatch.setattr(data_store, "AOI_PATH", tmp_path / "aoi.json")
    ids = sorted(data_store.known_region_ids())[:2]
    sel = ",".join(ids)
    params = {"aoi": {}, "before_window": BEFORE, "after_window": AFTER, "max_cloud_pct": 20}
    calls = []

    def fake_chips(aoi, before, after, cloud, bbox, kinds):
        calls.append(bbox)
        return {f"{w}_{k}": b"png" for k in kinds for w in ("before", "after")}

    monkeypatch.setattr(data_store, "analysis_params", lambda run_id=None: params)
    monkeypatch.setattr(main.vlm_check, "touches_labelled_site", lambda bbox: False)
    monkeypatch.setattr(main.ee_engine, "region_chips", fake_chips)
    monkeypatch.setattr(main, "gpt", GPTClient(mode="replay", replay_file=replay(
        tmp_path, "gpt.json", {f"ungated_report_v0:ungated_gpt:{sel}": GPT_TEXT})))
    monkeypatch.setattr(main, "vlm", VLMClient(mode="replay", replay_file=replay(
        tmp_path, "ext.json", {f"claim_extract_v0:ungated_gpt:{sel}": EXTRACTED})))
    monkeypatch.setattr(main, "_ungated_gpt_runs", {})
    client = TestClient(main.app)
    for _ in range(2):
        body = client.post("/api/report", json={"region_ids": ids, "condition": "ungated_gpt"}).json()
        assert body["status"] == "ok" and body["raw_output"] == GPT_TEXT and len(body["claims"]) == 5
    assert len(calls) == 1


def test_api_ungated_gpt_respects_labelled_site_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    monkeypatch.setattr(data_store, "AOI_PATH", tmp_path / "aoi.json")
    monkeypatch.setattr(main.vlm_check, "touches_labelled_site", lambda bbox: True)
    monkeypatch.setattr(main.ee_engine, "region_chips", lambda *a, **k: pytest.fail("must not render chips"))
    ids = sorted(data_store.known_region_ids())[:1]
    body = TestClient(main.app).post("/api/report", json={"region_ids": ids, "condition": "ungated_gpt"}).json()
    assert body["status"] == "not_run" and "labelled evaluation site" in body["detail"]
