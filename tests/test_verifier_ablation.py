"""agents/nli_verifier.py and scripts/verifier_ablation.py with a fake NLI model (no transformers)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import verifier_ablation as va  # noqa: E402
from agents import nli_verifier as nv  # noqa: E402

EV = {"change_frac": 0.12, "regions": [
    {"id": "r1", "area_ha": 12.0, "location": "north-east", "mean_conf": 0.4, "dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.0,
     "class_before": "trees", "class_after": "bare"}],
      "transects": [{"id": "t1", "location": "south", "change": "retreating", "nsm": -30.0, "lrr": -4.0, "ci95": 1.0}],
      "coastal_strips": [{"strip": "0-200", "built_ha_before": 1.0, "built_ha_after": 2.5}]}


def test_evidence_text_states_every_fact():
    t = nv.evidence_text(EV)
    for fact in ("1 region, 12.0 ha", "12 % of the area", "Region r1 is in the north-east", "vegetation index (NDVI) changed by -0.30",
                 "vegetation loss", "increase in built-up or bare surface", "from trees to bare", "confidence is 0.40",
                 "shoreline is retreating, net movement 30 m landward", "went from 1.0 ha to 2.5 ha"):
        assert fact in t, fact
    assert nv.evidence_text({"change_frac": 0, "regions": []}) == "No change was detected in the area."


def fake_nli(premise, hypothesis):
    """Entails a claim whose key word is in the premise; contradicts 'gain' claims when the premise says loss."""
    h = hypothesis.lower()
    if "gain" in h and "vegetation loss" in premise:
        return {"entailment": 0.05, "neutral": 0.15, "contradiction": 0.8}
    if "loss" in h and "vegetation loss" in premise:
        return {"entailment": 0.9, "neutral": 0.05, "contradiction": 0.05}
    return {"entailment": 0.2, "neutral": 0.7, "contradiction": 0.1}


def test_nli_verdicts():
    c = lambda t: {"text": t}
    assert nv.nli_verify(c("Vegetation loss in the north-east."), EV, fake_nli) == ("supported", "nli_entailment")
    assert nv.nli_verify(c("Vegetation gain."), EV, fake_nli) == ("unsupported", "nli_contradiction")
    assert nv.nli_verify(c("Mining caused this."), EV, fake_nli) == ("uncertain", "nli_neutral")


def test_compare_against_human_support():
    reports = [{"arm": "gated", "box_id": "s1", "evidence": EV, "claims": [{"claim_id": f"c{i}"} for i in range(4)]}]
    base = {"site_id": "s1", "condition": "gated", "type": "change_type", "level": "L3"}
    claims = [
        {**base, "claim_id": "c0", "text": "Vegetation loss here.", "verdict": "supported", "support": "supported", "truth": "true"},
        {**base, "claim_id": "c1", "text": "Vegetation gain here.", "verdict": "supported", "support": "unsupported", "truth": "false"},
        {**base, "claim_id": "c2", "text": "Mining caused it.", "verdict": "unsupported", "support": "unsupported", "truth": "unverifiable"},
        {**base, "claim_id": "c3", "text": "Vegetation loss is visible.", "verdict": "unsupported", "support": "supported", "truth": "true"},
        {**base, "claim_id": "c9", "text": "No evidence for me.", "verdict": "supported", "support": "supported", "truth": "true"},
    ]
    res = va.compare(reports, claims, fake_nli)
    assert res["n_without_evidence"] == 1
    assert res["rule"]["accuracy_vs_support"][0] == pytest.approx(0.5)      # c0, c2 right
    assert res["nli"]["accuracy_vs_support"][0] == pytest.approx(1.0)       # all four right
    assert res["mcnemar"]["rule_right_nli_wrong"] == 0 and res["mcnemar"]["nli_right_rule_wrong"] == 2
    assert res["mcnemar"]["p_exact"] == pytest.approx(0.5)
