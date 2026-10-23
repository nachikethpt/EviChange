"""Gated report arm (agents/gated.py): prompt, parser and a replayed run, plus the template's
shoreline / coastal claims (D13). No model is ever called."""
import json

from agents import gated
from agents.schema import validate_claim
from agents.vlm_client import VLMClient
from webapp.backend.report import build_report, template_claims

BEFORE, AFTER = ["2024-10-01", "2025-03-31"], ["2025-10-01", "2026-03-31"]
EV = {
    "change_frac": 0.02,
    "regions": [{"id": "r1", "area_ha": 182.4, "mean_conf": 0.86, "dNDVI": -0.34, "dNDBI": 0.21, "dMNDWI": -0.03,
                 "location": "north-east", "class_before": "trees", "class_after": "bare",
                 "_geometry": {"type": "Polygon", "coordinates": []}}],
    "transects": [
        {"id": "t0001", "location": "north-east", "change": "advancing", "nsm": 42.0, "lrr": 21.5, "ci95": 6.0},
        {"id": "t0004", "location": "west", "change": "unconfirmed", "nsm": -35.0, "lrr": -17.0, "ci95": 9.0},
    ],
    "coastal_strips": [
        {"strip": "0-200", "built_ha_before": 12.0, "built_ha_after": 15.1},
        {"strip": "200-500", "built_ha_before": 30.0, "built_ha_after": 30.2},
    ],
}
ANSWER = json.dumps({
    "claims": [
        {"text": "Change was detected.", "level": "L1", "type": "presence", "evidence_ref": ["change_frac"]},
        {"text": "In region r1 (north-east) trees became bare ground.", "level": "L3", "type": "land_cover",
         "region_ref": "r1", "class_before": "trees", "class_after": "bare", "evidence_ref": ["class_before", "class_after"]},
        {"text": "At transect t0001 the shoreline moved about 42 m seaward.", "level": "L2", "type": "shoreline",
         "transect_ref": "t0001", "shoreline_change": "advancing", "evidence_ref": ["change", "nsm"]},
        {"text": "Built area within 200 m of the shore grew by about 3 ha.", "level": "L2", "type": "coastal_built",
         "strip": "0-200", "evidence_ref": ["built_ha_before", "built_ha_after"]},
        {"text": "The shoreline moved sideways.", "level": "L2", "type": "shoreline", "shoreline_change": "sideways"},
        {"level": "L2", "type": "extent"},
    ],
    "abstain": [{"topic": "cause", "reason": "The evidence has no causes."}, {"reason": "no topic"}],
})


def test_prompt_shows_the_evidence_without_geometry():
    p = gated.build_prompt(EV, BEFORE, AFTER)
    assert "_geometry" not in p and '"t0001"' in p and '"built_ha_after": 15.1' in p and "2024-10-01 to 2025-03-31" in p
    assert "{" not in p.split("EVIDENCE")[0]          # no unformatted placeholders before the evidence
    shown = gated.prompt_evidence({"change_frac": 0.0, "regions": []})
    assert shown == {"change_frac": 0.0, "regions": []}   # no empty coast lists when there is no coast


def test_parse_keeps_valid_claims_and_counts_the_rest():
    claims, abstain, ok, dropped = gated.parse_report("Here you go:\n" + ANSWER)
    assert ok and dropped == 2 and len(claims) == 4
    assert [c["claim_id"] for c in claims] == ["c1", "c2", "c3", "c4"]
    assert claims[2]["transect_ref"] == "t0001" and claims[3]["strip"] == "0-200"
    assert all(validate_claim(c) == [] for c in claims)
    assert abstain == [{"topic": "cause", "reason": "The evidence has no causes."}]
    assert gated.parse_report("not json") == ([], [], False, 0)
    assert gated.parse_report('{"claims": "none"}')[2] is False


def test_replayed_gated_run_is_verified(tmp_path):
    replay = tmp_path / "vlm.json"
    replay.write_text(json.dumps({f"{gated.PROMPT_VERSION}:gated:s1": ANSWER}), encoding="utf-8")
    out = gated.run_gated(VLMClient(mode="replay", replay_file=str(replay)), "s1", EV, BEFORE, AFTER, [b"a", b"b"])
    assert out["prompt_version"] == gated.PROMPT_VERSION and out["dropped"] == 2
    rep = build_report(EV, "gated", gated=out)
    assert rep["counts"] == {"supported": 4, "unsupported": 0, "uncertain": 0}
    assert rep["abstain"] == out["abstain"] and rep["prompt_version"] == gated.PROMPT_VERSION


def test_template_states_the_coast_and_the_verifier_agrees():
    coast = [c for c in template_claims(EV) if c["type"] in ("shoreline", "coastal_built")]
    assert [c["type"] for c in coast] == ["shoreline", "coastal_built", "coastal_built"]   # unconfirmed transect: no claim
    rep = build_report(EV, "template")
    assert all(c["verdict"] == "supported" for c in rep["claims"] if c["type"] in ("shoreline", "coastal_built"))
    no_regions = template_claims({**EV, "regions": []})
    assert no_regions[0]["type"] == "presence" and len(no_regions) == 4


def test_demo_gated_abstains_on_unconfirmed_shoreline():
    rep = build_report(EV, "gated")
    assert any("t0004" in a["topic"] for a in rep["abstain"])
