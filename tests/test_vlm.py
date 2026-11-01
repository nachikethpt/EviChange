import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from agents import ee_engine, planet, planet_vlm, vlm_check
from agents.vlm_client import VLMClient, VLMUnavailable
from webapp.backend import data_store, main

QN_AOI = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
BEFORE, AFTER = ["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"]
V1_PROMPT_SHA256 = "74689617d1a12dcd2bb2296b3f2aaea9058010ced8595e4ad87f1fdf97b114c5"   # vlmcheck_v1 for BEFORE/AFTER


# ---------- parsing + comparison ----------
@pytest.mark.parametrize("text, verdict, types, ok", [
    ('{"verdict": "change", "change_types": ["vegetation_loss"], "reason": "cleared"}', "change", ["vegetation_loss"], True),
    ('```json\n{"verdict": "change", "change_types": ["water_increase", "lava"], "reason": "x"}\n```', "change", ["water_increase"], True),
    ('{"verdict": "no_change", "change_types": ["vegetation_loss"], "reason": "same"}', "no_change", [], True),
    ('Looks like a new pond.', "unsure", [], False),
    ('{"verdict": "maybe"}', "unsure", [], False),
])
def test_parse_answer(text, verdict, types, ok):
    a = vlm_check.parse_answer(text)
    assert (a["verdict"], a["change_types"], a["parse_ok"]) == (verdict, types, ok)


REGION = {"id": "r1", "dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.0}   # detector: vegetation_loss + built_up_increase


@pytest.mark.parametrize("verdict, types, agreement", [
    ("change", ["vegetation_loss", "built_up_increase"], "agrees"),
    ("change", ["vegetation_loss"], "partly"),
    ("change", ["water_increase"], "different_type"),
    ("change", ["other"], "change_only"),
    ("no_change", [], "disagrees"),
    ("unsure", [], "unsure"),
])
def test_compare_with_detector(verdict, types, agreement):
    out = vlm_check.compare({"verdict": verdict, "change_types": types}, REGION)
    assert out == {"detector_types": ["vegetation_loss", "built_up_increase"], "agreement": agreement}


@pytest.fixture
def locked(monkeypatch):
    """The lock as it was before the D19 freeze: these tests check the lock still works if switched on."""
    monkeypatch.setattr(vlm_check, "LABELLED_SITES_UNLOCKED", False)


def test_labelled_sites_unlocked_since_the_freeze():
    assert vlm_check.LABELLED_SITES_UNLOCKED                 # D19, 2026-10-27: the 30-site run may use them
    assert not vlm_check.touches_labelled_site(vlm_check.labelled_site_boxes()[0])


def test_labelled_sites_are_locked(locked):
    box = vlm_check.labelled_site_boxes()[0]
    assert len(vlm_check.labelled_site_boxes()) == 30
    assert vlm_check.touches_labelled_site(box)
    assert not vlm_check.touches_labelled_site((0.0, 0.0, 0.1, 0.1))


# ---------- client ----------
def test_client_off_without_url(monkeypatch):
    monkeypatch.delenv("VLM_URL", raising=False); monkeypatch.delenv("EVICHANGE_VLM", raising=False)
    c = VLMClient()
    assert c.status()["available"] is False
    with pytest.raises(VLMUnavailable):
        c.generate("hi")


def test_client_refuses_plain_http_remote():
    with pytest.raises(VLMUnavailable, match="https"):
        VLMClient(url="http://example.com", token="t").generate("hi")


@pytest.fixture
def fake_server():
    """A local stand-in for the Colab model server, recording what it receives."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            self._reply(200, {"model": "fake-qwen"})

        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Authorization") != "Bearer secret":
                return self._reply(401, {"detail": "bad token"})
            seen.append(json.loads(payload))
            self._reply(200, {"text": '{"verdict": "change", "change_types": ["vegetation_loss"], "reason": "cleared"}', "model": "fake-qwen"})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()


def test_client_http_roundtrip(fake_server):
    url, seen = fake_server
    c = VLMClient(url=url, token="secret")
    assert c.status() == {"available": True, "mode": "http", "model": "fake-qwen", "detail": url}
    out = c.generate("look", [b"\x89PNG-a", b"\x89PNG-b"])
    assert out["model"] == "fake-qwen" and "vegetation_loss" in out["text"]
    assert seen[0]["prompt"] == "look" and len(seen[0]["images"]) == 2


def test_client_bad_token(fake_server):
    url, _ = fake_server
    with pytest.raises(VLMUnavailable, match="rejected VLM_TOKEN"):
        VLMClient(url=url, token="wrong").generate("look")


# ---------- endpoint ----------
def square(cx, cy, d=0.002):
    return {"type": "Polygon", "coordinates": [[[cx - d, cy - d], [cx + d, cy - d], [cx + d, cy + d], [cx - d, cy + d], [cx - d, cy - d]]]}


@pytest.fixture
def client(tmp_path, monkeypatch, fake_server):
    site = vlm_check.labelled_site_boxes()[0]
    regions = {"type": "FeatureCollection", "metadata": {"aoi": QN_AOI, "before_window": BEFORE, "after_window": AFTER},
               "features": [
                   {"type": "Feature", "geometry": square(107.215, 20.975),     # outside every labelled site
                    "properties": {"id": "free", "area_ha": 5.0, "mean_conf": 0.3, "dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.0, "location": "west"}},
                   {"type": "Feature", "geometry": square((site[0] + site[2]) / 2, (site[1] + site[3]) / 2),
                    "properties": {"id": "onsite", "area_ha": 5.0, "mean_conf": 0.3, "dNDVI": -0.3, "dNDBI": 0.0, "dMNDWI": 0.0, "location": "centre"}}]}
    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_store, "REGIONS_PATH", tmp_path / "change_regions.json")
    monkeypatch.setattr(data_store, "AOI_PATH", tmp_path / "aoi.json")
    (tmp_path / "change_regions.json").write_text(json.dumps(regions))
    calls = []
    monkeypatch.setattr(ee_engine, "region_chips", lambda *a, kinds: calls.append((*a, kinds)) or
                        {f"{w}_{k}": f"{w}_{k}".encode() for k in kinds for w in ("before", "after")})
    url, seen = fake_server
    monkeypatch.setattr(main, "vlm", VLMClient(url=url, token="secret"))
    monkeypatch.setattr(vlm_check, "LOG_FILE", tmp_path / "vlm_checks.jsonl")
    main._vlm_checks.clear(); monkeypatch.setattr(main, "_vlm_log_loaded", False)
    c = TestClient(main.app); c.chip_calls = calls; c.seen = seen
    return c


def test_check_region_end_to_end(client):
    body = client.post("/api/vlm/check", json={"region_id": "free"}).json()
    assert body["status"] == "checked" and body["verdict"] == "change"
    assert body["detector_types"] == ["vegetation_loss", "built_up_increase"] and body["agreement"] == "partly"
    assert body["model"] == "fake-qwen" and body["prompt_version"] == vlm_check.PROMPT_VERSION
    client.post("/api/vlm/check", json={"region_id": "free"})
    assert len(client.chip_calls) == 1                                  # second call served from the cache


def test_check_chip_sets(client):
    import base64
    body = client.post("/api/vlm/check", json={"region_id": "free", "chips": "rgb"}).json()
    assert body["chips"] == "rgb" and body["prompt_version"] == "vlmcheck_v1_rgb"
    sent = client.seen[-1]
    assert [base64.b64decode(i) for i in sent["images"]] == [b"before_rgb", b"after_rgb"]
    assert "two Sentinel-2 images" in sent["prompt"] and "SWIR" not in sent["prompt"]
    body = client.post("/api/vlm/check", json={"region_id": "free", "chips": "rgb_swir_cir"}).json()
    assert body["prompt_version"] == "vlmcheck_v1_rgb_swir_cir" and len(client.seen[-1]["images"]) == 6
    assert client.post("/api/vlm/check", json={"region_id": "free", "chips": "x"}).status_code == 400
    status = client.get("/api/vlm/status").json()
    assert status["default_chips"] == "rgb_swir" and "rgb" in status["chip_sets"]


def test_default_prompt_is_v1():
    """rgb_swir must keep the exact vlmcheck_v1 prompt: results and replays recorded under v1 stay valid."""
    import hashlib
    assert vlm_check.prompt_version("rgb_swir") == "vlmcheck_v1" == vlm_check.PROMPT_VERSION
    prompt = vlm_check.build_prompt(BEFORE, AFTER)
    assert "four Sentinel-2 images" in prompt and "SWIR false colour (B11-B8-B4)" in prompt
    assert hashlib.sha256(prompt.encode()).hexdigest() == V1_PROMPT_SHA256


def test_check_blocks_labelled_sites(client, locked):
    body = client.post("/api/vlm/check", json={"region_id": "onsite"}).json()
    assert body["status"] == "blocked" and not client.chip_calls       # nothing rendered or sent


def test_check_unknown_region(client):
    assert client.post("/api/vlm/check", json={"region_id": "nope"}).status_code == 404


def test_check_without_model_server(client, monkeypatch, locked):
    monkeypatch.setattr(main, "vlm", VLMClient(mode="off"))
    resp = client.post("/api/vlm/check", json={"region_id": "free"})
    assert resp.status_code == 503 and "VLM_URL" in resp.json()["detail"]
    status = client.get("/api/vlm/status").json()
    assert status["available"] is False and status["labelled_sites_locked"] is True


def test_answers_are_logged_and_survive_a_restart(client, monkeypatch):
    first = client.post("/api/vlm/check", json={"region_id": "free"}).json()
    client.post("/api/vlm/check", json={"region_id": "free"})              # cached: not logged twice
    log = vlm_check.read_log()
    assert len(log) == 1
    rec = log[0]
    assert rec["region_id"] == "free" and rec["model"] == "fake-qwen" and rec["chips"] == "rgb_swir"
    assert rec["verdict"] == "change" and rec["agreement"] == "partly" and rec["seconds"] >= 0
    assert '"verdict"' in rec["raw"] and len(rec["bbox"]) == 4
    client.post("/api/vlm/check", json={"region_id": "free", "chips": "rgb"})   # another image set: a new line
    assert len(vlm_check.read_log()) == 2

    main._vlm_checks.clear(); monkeypatch.setattr(main, "_vlm_log_loaded", False)   # app restarted
    again = client.post("/api/vlm/check", json={"region_id": "free"}).json()
    assert again["from_log"] is True and again["verdict"] == first["verdict"]
    assert len(client.chip_calls) == 2 and len(vlm_check.read_log()) == 2        # no new render, no new line


def test_blocked_sites_are_not_logged(client, locked):
    client.post("/api/vlm/check", json={"region_id": "onsite"})
    assert vlm_check.read_log() == []


def test_read_log_skips_broken_lines(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text('{"key": "a", "region_id": "r1"}\n{"key": "b", "regi', encoding="utf-8")
    assert [r["key"] for r in vlm_check.read_log(p)] == ["a"]


@pytest.fixture
def planet_client(client, monkeypatch):
    rows = [{"month": "2025-01", "date": "2025-01-12", "asset_id": "jan", "clear_share": .9},
            {"month": "2025-09", "date": "2025-09-20", "asset_id": "sep", "clear_share": .8}]
    monkeypatch.setattr(main, "_planet_catalog", lambda: {"months": rows})
    monkeypatch.setattr(main.ee_engine, "_ee", lambda: object())
    monkeypatch.setattr(main.shoreline, "hidden_transects", lambda *_: set())
    monkeypatch.setattr(planet, "box_clear_share", lambda *_: .9)
    calls = []
    monkeypatch.setattr(planet, "region_chips", lambda month, box, kinds: calls.append((month, kinds)) or
                        {k: f"{month}_{k}".encode() for k in kinds})
    client.planet_calls = calls
    return client


PLANET_REQUEST = {"region_id": "free", "source": "planet", "before_month": "2025-01", "after_month": "2025-09"}


def test_planet_check_dates_chips_and_cache_are_separate(planet_client):
    import base64
    body = planet_client.post("/api/vlm/check", json=PLANET_REQUEST).json()
    assert body["status"] == "checked" and body["source"] == "planet"
    assert body["agreement"] == "different_period" and body["comparable"] is False
    assert body["prompt_version"].startswith("planetcheck_v1_")
    sent = planet_client.seen[-1]
    assert "2025-01-12" in sent["prompt"] and "2025-09-20" in sent["prompt"]
    assert "Sentinel-2 images" not in sent["prompt"] and "SWIR false colour" not in sent["prompt"]
    assert [base64.b64decode(im) for im in sent["images"]] == [
        b"2025-01_rgb", b"2025-09_rgb", b"2025-01_nir", b"2025-09_nir"]
    planet_client.post("/api/vlm/check", json=PLANET_REQUEST)
    assert len(planet_client.planet_calls) == 2
    sentinel = planet_client.post("/api/vlm/check", json={"region_id": "free"}).json()
    assert sentinel["prompt_version"] == vlm_check.PROMPT_VERSION and len(planet_client.chip_calls) == 1
    assert len(vlm_check.read_log()) == 2


@pytest.mark.parametrize("patch,status", [
    ({"before_month": "2025-09", "after_month": "2025-01"}, 400),
    ({"before_month": None}, 400), ({"after_month": "2025-13"}, 400),
    ({"after_month": "2025-02"}, 404), ({"chips": "rgb_swir"}, 400),
])
def test_invalid_or_missing_planet_pair_never_renders_or_calls_model(planet_client, patch, status):
    response = planet_client.post("/api/vlm/check", json={**PLANET_REQUEST, **patch})
    assert response.status_code == status
    assert planet_client.planet_calls == [] and planet_client.seen == []


def test_planet_cloudy_box_does_not_get_a_model_verdict(planet_client, monkeypatch):
    monkeypatch.setattr(planet, "box_clear_share", lambda *_: .2)
    body = planet_client.post("/api/vlm/check", json=PLANET_REQUEST).json()
    assert body["status"] == "insufficient_imagery" and "verdict" not in body
    assert planet_client.planet_calls == [] and planet_client.seen == [] and vlm_check.read_log() == []


def test_planet_respects_both_evaluation_locks(planet_client, monkeypatch, locked):
    assert planet_client.post("/api/vlm/check", json={**PLANET_REQUEST, "region_id": "onsite"}).json()["status"] == "blocked"
    f = {"id": "reference", "geometry": {"coordinates": [[107.214, 20.974], [107.216, 20.976]]}}
    monkeypatch.setattr(main.shoreline, "load", lambda *_: {"features": [f]})
    monkeypatch.setattr(main.shoreline, "hidden_transects", lambda *_: {"reference"})
    assert planet_client.post("/api/vlm/check", json=PLANET_REQUEST).json()["status"] == "blocked"
    assert planet_client.planet_calls == [] and planet_client.seen == []


def test_planet_pair_replay_identity_includes_acquisitions_and_framing():
    rows = [{"month": "2025-01", "date": "2025-01-12", "asset_id": "jan"},
            {"month": "2025-09", "date": "2025-09-20", "asset_id": "sep"}]
    params = {"before_window": ["2025-01-01", "2025-01-31"], "after_window": ["2025-09-01", "2025-09-30"]}
    seen = []
    class Model:
        def generate(self, _prompt, _images, replay_key):
            seen.append(replay_key)
            return {"text": '{"verdict":"no_change","reason":"same"}', "model": "fake"}
    chips = {f"{when}_rgb": b"png" for when in ("before", "after")}
    result, record = planet_vlm.check(Model(), params, REGION, (0, 0, 1, 1), "planet_rgb", rows, chips, [.9, .9])
    assert result["comparable"] is True and result["agreement"] == "disagrees"
    changed = [{**rows[0], "date": "2025-01-13"}, rows[1]]
    planet_vlm.check(Model(), params, REGION, (0, 0, 1, 1), "planet_rgb", changed, chips, [.9, .9])
    planet_vlm.check(Model(), params, REGION, (0, 0, 2, 2), "planet_rgb", rows, chips, [.9, .9])
    assert len(set(seen)) == 3 and record["source"] == "planet"
