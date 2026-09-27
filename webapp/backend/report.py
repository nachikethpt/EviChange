"""AI change report: the ONE implementation of claim generation, used by both the
web app's report panel and the agent pipeline's Geo-VLM Agent (agents/webapp_bridge.py).

RIGHT NOW: no AI model is called.
  - template_claims(): real rule-based logic (same as the notebook).
  - ungated_claims():  a canned example of what an unconstrained VLM tends to say.
  - gated_claims():    evidence-cited claims + abstentions, produced by rules for now.
Phase 3 replaces ungated_claims() / gated_claims() with real Qwen2.5-VL output
(through agents' VLMClient). Keep the returned shape identical.

Claims are checked by agents/verifier.py and must match agents/schema.py.
"""
from agents.schema import CHANGE_TYPES, REASONS, T_IDX, region_change_types
from agents.verifier import verify


def _number(claims):
    for i, c in enumerate(claims, 1):
        c["claim_id"] = f"c{i}"
    return claims


def template_claims(ev):
    claims = []
    if not ev["regions"]:
        return _number([dict(level="L1", type="presence", text="No change detected in the selected area.",
                             region_ref=None, evidence_ref=["change_frac"], stated_conf=1.0)])
    claims.append(dict(level="L1", type="presence", text="Change detected between the two dates.",
                       region_ref=None, evidence_ref=["change_frac"], stated_conf=1.0))
    total = sum(r["area_ha"] for r in ev["regions"])
    claims.append(dict(level="L2", type="extent", text=f"About {total:.0f} ha changed in total.",
                       region_ref=None, evidence_ref=["area_ha"], stated_conf=1.0))
    for r in ev["regions"]:
        claims.append(dict(level="L2", type="location",
                           text=f"Region {r['id']}: {r['area_ha']:.0f} ha of change in the {r['location']}.",
                           region_ref=r["id"], evidence_ref=["location", "area_ha"], stated_conf=r["mean_conf"]))
        for name in region_change_types(r):
            field, _, label = CHANGE_TYPES[name]
            claims.append(dict(level="L3", type="change_type", change_type=name,
                               text=f"Region {r['id']}: spectral signal indicates {label}.",
                               region_ref=r["id"], evidence_ref=[field], stated_conf=r["mean_conf"]))
    return _number(claims)


def ungated_claims(ev):
    """DEMO: typical free-text VLM output, already split into claims. Contains unsupported bits on purpose."""
    raw = ("Large-scale open-pit coal mining has expanded significantly in the north-east, replacing forest "
           "with exposed soil. A new water reservoir appears in the south. The expansion is likely illegal "
           "and will continue to grow over the next few years.")
    claims = [
        dict(level="L1", type="presence", text="Land-cover change occurred.", region_ref=None),
        dict(level="L3", type="change_type", text="Forest was replaced with exposed soil in the north-east.", region_ref=None),
        dict(level="L3", type="change_type", text="A new water reservoir appears in the south.", region_ref=None),
        dict(level="L4", type="cause", text="The change is caused by open-pit coal mining.", region_ref=None),
        dict(level="L4", type="cause", text="The expansion is likely illegal.", region_ref=None),
        dict(level="L4", type="other", text="The expansion will continue over the next few years.", region_ref=None),
    ]
    for c in claims:
        c.update(evidence_ref=[], stated_conf=None)
    return raw, _number(claims)


def gated_claims(ev):
    """DEMO: what the evidence-gated model should produce — only cited claims, plus abstentions."""
    claims = [c for c in template_claims(ev) if c["level"] in ("L1", "L2", "L3")]
    by_id = {r["id"]: r for r in ev["regions"]}
    for c in claims:  # phrase like a model would, quoting the evidence values
        r = by_id.get(c.get("region_ref"))
        if r and c["type"] == "change_type":
            field, _, label = CHANGE_TYPES[c["change_type"]]
            c["text"] = (f"In region {r['id']} ({r['location']}, ~{r['area_ha']:.0f} ha) the imagery shows "
                         f"{label} ({field} {r[field]:+.2f}).")
    abstain = [
        {"topic": "cause of change (e.g. mining)", "reason": "The evidence contains no information about causes."},
        {"topic": "legality / licensing", "reason": "Licence data is not part of the evidence."},
        {"topic": "future expansion", "reason": "The evidence describes two dates only; no forecast is supported."},
    ]
    for r in ev["regions"]:
        if not region_change_types(r):
            abstain.append({"topic": f"type of change in region {r['id']}",
                            "reason": f"All spectral index changes are within ±{T_IDX} (no clear change)."})
    return _number(claims), abstain


def build_report(ev, condition):
    raw, abstain = None, []
    if condition == "template":
        claims = template_claims(ev)
    elif condition == "ungated":
        raw, claims = ungated_claims(ev)
    elif condition == "gated":
        claims, abstain = gated_claims(ev)
    else:
        raise ValueError(f"unknown condition: {condition}")
    for c in claims:
        c["verdict"], c["verdict_reason"] = verify(c, ev)
        c["verdict_note"] = REASONS[c["verdict_reason"]]
    counts = {v: sum(c["verdict"] == v for c in claims) for v in ("supported", "unsupported", "uncertain")}
    return {
        "condition": condition, "model": "demo (no AI yet)", "evidence": ev,
        "raw_output": raw, "claims": claims, "abstain": abstain, "counts": counts,
    }
