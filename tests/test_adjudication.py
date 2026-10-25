"""eval/adjudication.py and the /api/adjudicate endpoints: blinding, the shuffled queue, the second
adjudicator's overlap, and the join back to eval/metrics.py records."""
import json

import pytest
from fastapi.testclient import TestClient

from eval import adjudication as adj
from eval import metrics
from webapp.backend import main


@pytest.mark.parametrize("text, blind", [
    ("Region r200: 13 ha of change in the centre.", "13 ha of change in the centre."),
    ("In region r1 (north-east, ~182 ha) the imagery shows vegetation loss (dNDVI -0.34).",
     "In the north-east (~182 ha), the imagery shows vegetation loss."),
    ("Transect t0042: the shoreline moved about 30 m landward in the south (-4.2 m/yr).",
     "The shoreline moved about 30 m landward in the south (-4.2 m/yr)."),   # a rate is a claim, kept
    ("Region r9 changed.", "An area changed."),
    ("Vegetation loss in region r12, mostly in the north.", "Vegetation loss, mostly in the north."),
    ("Forest was replaced with exposed soil in the north-east.", "Forest was replaced with exposed soil in the north-east."),
])
def test_blind_text(text, blind):
    assert adj.blind_text(text) == blind


def claim(cid, text, verdict="supported", **extra):
    return {"claim_id": cid, "level": "L2", "type": "location", "text": text, "verdict": verdict,
            "verdict_reason": "region_located", "region_ref": "r1", "evidence_ref": ["area_ha"], **extra}


EV = {"change_frac": 0.1, "regions": [{"id": "r1", "area_ha": 10.0}]}
REPORTS = [
    {"arm": arm, "box_id": site, "stratum": "detected", "box": [107.3, 21.0, 107.31, 21.01], "evidence": EV,
     "parse_ok": arm != "ungated" or site != "s3", "dropped": 1 if arm == "ungated" else 0,
     "claims": [claim("c1", f"Region r1: {site} {arm} one."), claim("c2", f"Region r1: {site} {arm} two.", verdict="unsupported")]}
    for site in ("s1", "s2", "s3", "s4", "s5") for arm in ("template", "gated", "ungated")
]


def test_queue_is_blind_and_shuffled():
    q = adj.queue(REPORTS)
    assert sorted(s["site_id"] for s in q) == ["s1", "s2", "s3", "s4", "s5"]
    blob = json.dumps([s["items"] for s in q])            # the evidence is the API's to withhold on pass 1
    for leak in ('"template"', '"gated"', '"ungated"', "verdict", "region_ref", "evidence_ref", "r1"):
        assert leak not in blob
    texts = [it["text"] for it in q[0]["items"]]
    assert len(texts) == 6 and texts != sorted(texts)      # all conditions together, not grouped
    assert adj.queue(REPORTS) == q                          # seeded


def test_second_adjudicator_overlap_is_fixed():
    second = adj.queue(REPORTS, role="second")
    assert len(second) == 1                                  # 20 % of 5 sites
    assert adj.second_sites(["s1", "s2", "s3", "s4", "s5"]) == {second[0]["site_id"]}
    assert adj.second_sites([]) == set()


def test_rerun_replaces_the_earlier_report():
    rerun = {**REPORTS[0], "claims": [claim("c1", "Region r1: rerun.")]}
    items = adj.build_items(REPORTS + [rerun])
    assert len(items) == len(REPORTS) * 2 - 1


def test_join_back_to_metric_records():
    items = adj.build_items(REPORTS)
    judgements = []
    for iid, it in items.items():
        judgements.append({"item_id": iid, "adjudicator": "p3", "truth": "false" if it["condition"] == "ungated" else "true"})
        judgements.append({"item_id": iid, "adjudicator": "p3", "support": "supported"})
    one = next(iter(items))
    judgements.append({"item_id": one, "adjudicator": "p3", "about_detector": True})
    claims, runs = adj.to_metric_records(REPORTS, judgements, "p3")
    assert len(claims) == len(items) - 1                    # the about_detector claim is left out
    assert all(metrics.check_claim(c) == [] for c in claims)
    assert {c["condition"] for c in claims} == {"template", "gated", "ungated"}
    assert len(adj.to_metric_records(REPORTS, judgements, "p3", drop_about_detector=False)[0]) == len(items)
    run = next(r for r in runs if r["site_id"] == "s3" and r["condition"] == "ungated")
    assert run == {"site_id": "s3", "condition": "ungated", "n_claims": 2, "n_parse_failures": 2}
    rep = metrics.report(claims, runs, {}, {s: {"origin": "detected"} for s in ("s1", "s2", "s3", "s4", "s5")}, reps=100)
    assert rep["conditions"]["ungated"]["pooled"]["hallucination"][0] == 1.0
    assert rep["comparisons"]["primary"]["pooled_rate_diff"][0] == pytest.approx(-1.0)


def test_half_judged_claims_are_not_records():
    iid = next(iter(adj.build_items(REPORTS)))
    claims, _ = adj.to_metric_records(REPORTS, [{"item_id": iid, "adjudicator": "p3", "truth": "true"}], "p3")
    assert claims == []


def test_judgement_checks():
    assert adj.check_judgement({"item_id": "x", "adjudicator": "p3", "truth": "true"}) == []
    assert adj.check_judgement({"item_id": "x", "adjudicator": "../etc", "truth": "true"})
    assert adj.check_judgement({"item_id": "x", "adjudicator": "p3", "truth": "maybe"})


# ---------- API ----------
@pytest.fixture
def api(tmp_path, monkeypatch):
    reports = tmp_path / "reports.jsonl"
    reports.write_text("".join(json.dumps(r) + "\n" for r in REPORTS))
    monkeypatch.setitem(main.ADJ_SOURCES, "dev", reports)
    monkeypatch.setattr(main, "ADJ_DIR", tmp_path / "adj")
    monkeypatch.setattr(main, "_chip_folder", lambda box: tmp_path / "chips")
    (tmp_path / "chips").mkdir()
    (tmp_path / "chips" / "before_rgb.png").write_bytes(b"\x89PNG fake")
    return TestClient(main.app), tmp_path


def test_api_round_trip(api):
    client, tmp = api
    q = client.get("/api/adjudicate/dev", params={"adjudicator": "p3"}).json()
    assert q["progress"] == {"items": 30, "truth_done": 0, "support_done": 0}
    site = q["sites"][0]
    assert site["evidence"] is None and site["chips"] == ["before_rgb.png"]       # pass 1: no evidence
    iid = site["items"][0]["item_id"]
    r = client.post("/api/adjudicate/dev", json={"item_id": iid, "adjudicator": "p3", "truth": "true", "note": "R3"})
    assert r.status_code == 200 and r.json()["progress"]["truth_done"] == 1
    client.post("/api/adjudicate/dev", json={"item_id": iid, "adjudicator": "p3", "truth": "false"})   # a correction
    again = client.get("/api/adjudicate/dev", params={"adjudicator": "p3", "pass": 2}).json()
    assert again["sites"][0]["judgements"][iid] == {"truth": "false", "note": "R3"}
    assert again["sites"][0]["evidence"] == EV                                     # pass 2 shows it
    assert len((tmp / "adj" / "dev_p3.jsonl").read_text().splitlines()) == 2
    chip = client.get(f"/api/adjudicate/dev/chip/{site['site_id']}/before_rgb.png")
    assert chip.status_code == 200 and chip.headers["content-type"] == "image/png"


def test_api_rejects_bad_input(api):
    client, _ = api
    assert client.get("/api/adjudicate/dev", params={"adjudicator": "../x"}).status_code == 400
    assert client.get("/api/adjudicate/nope", params={"adjudicator": "p3"}).status_code == 404
    assert client.post("/api/adjudicate/dev", json={"item_id": "zzz", "adjudicator": "p3", "truth": "true"}).status_code == 404
    assert client.post("/api/adjudicate/dev", json={"item_id": "zzz", "adjudicator": "p3", "truth": "maybe"}).status_code == 422
    assert client.get("/api/adjudicate/dev/chip/s1/..%2Fsecret.png").status_code in (400, 404)
    assert client.get("/api/adjudicate/dev/chip/s1/after_rgb.png").status_code == 404
    assert client.get("/adjudicate").status_code == 200
