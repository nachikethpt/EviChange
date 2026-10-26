"""shoreline and coastal_built claims (D13): the verifier checks "the shoreline moved ~40 m seaward in
the north-east" against the transect statistics (D11) and "built area within 200 m of the shore grew
by ~3 ha" against the coastal-strip built areas (Phase 12)."""
import pytest

from agents.schema import CLAIM_TYPES, REASONS, validate_claim, validate_evidence
from agents.verifier import claimed_shoreline, claimed_strip, verify

REGION = {"id": "r1", "area_ha": 20.0, "mean_conf": 0.8, "location": "north-east",
          "dNDVI": -0.3, "dNDBI": 0.2, "dMNDWI": 0.0}
EV = {
    "change_frac": 0.02,
    "regions": [REGION],
    "transects": [
        {"id": "t0001", "location": "north-east", "change": "advancing", "nsm": 42.0, "lrr": 21.5, "ci95": 6.0},
        {"id": "t0002", "location": "north-east", "change": "stable", "nsm": 3.0, "lrr": 1.2, "ci95": 4.0},
        {"id": "t0003", "location": "south", "change": "stable", "nsm": -2.0, "lrr": -0.8, "ci95": 3.0},
        {"id": "t0004", "location": "west", "change": "unconfirmed", "nsm": -35.0, "lrr": -17.0, "ci95": 9.0},
        {"id": "t0005", "location": "north-west", "change": "too_few", "nsm": None, "lrr": None, "ci95": None},
    ],
    "coastal_strips": [
        {"strip": "0-200", "built_ha_before": 12.0, "built_ha_after": 15.1},
        {"strip": "200-500", "built_ha_before": 30.0, "built_ha_after": 30.2},
    ],
}
NO_COAST = {"change_frac": 0.02, "regions": [REGION]}


def claim(ctype, text, level="L2", **extra):
    return {"claim_id": "c1", "level": level, "type": ctype, "text": text,
            "region_ref": None, "evidence_ref": [], "stated_conf": None, **extra}


def sh(text, **extra):
    return claim("shoreline", text, **extra)


def cb(text, **extra):
    return claim("coastal_built", text, **extra)


@pytest.mark.parametrize("c, ev, expected", [
    # direction and distance against the confirmed trend and nsm
    (sh("The shoreline moved ~40 m seaward in the north-east."), EV, ("supported", "shoreline_matches")),
    (sh("The shoreline advanced about 21 m/yr in the north-east."), EV, ("supported", "shoreline_matches")),
    (sh("The shoreline moved 150 m seaward in the north-east."), EV, ("unsupported", "extent_mismatch")),
    (sh("The shoreline retreated in the north-east."), EV, ("unsupported", "shoreline_mismatch")),
    (sh("The coast eroded in the south."), EV, ("unsupported", "shoreline_mismatch")),
    (sh("The shoreline was stable in the south."), EV, ("supported", "shoreline_matches")),
    (sh("The shoreline was stable in the north-east."), EV, ("unsupported", "shoreline_mismatch")),
    # a radar trend the imagery does not confirm is never a verdict either way
    (sh("The shoreline retreated in the west."), EV, ("uncertain", "shoreline_unconfirmed")),
    (sh("The shoreline did not move in the west."), EV, ("uncertain", "shoreline_unconfirmed")),
    (sh("The shoreline advanced in the west."), EV, ("unsupported", "shoreline_mismatch")),
    (sh("The shoreline advanced in the north-west."), EV, ("uncertain", "shoreline_not_in_evidence")),
    # structured fields
    (sh("Transect t0001 advanced.", transect_ref="t0001", shoreline_change="advancing"), EV, ("supported", "shoreline_matches")),
    (sh("Transect t0003 moved.", transect_ref="t0003", shoreline_change="retreating"), EV, ("unsupported", "shoreline_mismatch")),
    (sh("Transect t0009 advanced.", transect_ref="t0009"), EV, ("unsupported", "unknown_transect")),
    (sh("Transect t0001 advanced in the south.", transect_ref="t0001"), EV, ("unsupported", "location_mismatch")),
    # unlocated: some transect has to match
    (sh("Part of the shoreline moved seaward by about 40 m."), EV, ("supported", "shoreline_matches")),
    (sh("The shoreline was stable."), EV, ("unsupported", "shoreline_mismatch")),
    (sh("The shoreline moved in the south-east."), EV, ("unsupported", "no_transect_at_location")),
    (sh("The shoreline changed in the north-east."), EV, ("uncertain", "type_not_checkable")),
    (sh("The shoreline moved seaward in the north-east."), NO_COAST, ("uncertain", "shoreline_not_in_evidence")),
    # the type decides, not the level, and existing early rules still run
    (sh("The shoreline moved ~40 m seaward in the north-east.", level="L3"), EV, ("supported", "shoreline_matches")),
    (sh("The shoreline advanced because of illegal reclamation.", level="L4"), EV, ("unsupported", "beyond_evidence")),
    (sh("The shoreline advanced.", evidence_ref=["tide_gauge"]), EV, ("unsupported", "cites_missing_evidence")),
    (sh("The shoreline advanced.", evidence_ref=["nsm", "change"]), EV, ("supported", "shoreline_matches")),
])
def test_shoreline_verdicts(c, ev, expected):
    verdict = verify(c, ev)
    assert tuple(verdict) == expected
    assert verdict.reason in REASONS


@pytest.mark.parametrize("c, ev, expected", [
    (cb("Built area within 200 m of the shore grew by ~3 ha."), EV, ("supported", "coastal_built_matches")),
    (cb("Built area within 200 m of the shore grew from 12 ha to 15 ha."), EV, ("supported", "coastal_built_matches")),
    (cb("Built area within 200 m of the shore grew by 10 ha."), EV, ("unsupported", "extent_mismatch")),
    (cb("Built area within 200 m of the shore decreased."), EV, ("unsupported", "coastal_built_mismatch")),
    (cb("Built area 200-500 m from the shore increased."), EV, ("unsupported", "coastal_built_mismatch")),   # +0.2 ha: no clear change
    (cb("Built area 200-500 m from the shore was unchanged."), EV, ("supported", "coastal_built_matches")),
    (cb("New buildings appeared within 500 m of the shore, about 3.3 ha."), EV, ("supported", "coastal_built_matches")),
    (cb("Coastal built area grew.", strip="0-200"), EV, ("supported", "coastal_built_matches")),
    (cb("Something was built near the shore."), EV, ("uncertain", "type_not_checkable")),
    (cb("Built area within 200 m of the shore grew."), NO_COAST, ("uncertain", "coastal_not_in_evidence")),
    # strips carry no location here, so a located claim cannot be checked
    (cb("Built area within 200 m of the shore grew in the north-east."), EV, ("uncertain", "coastal_not_in_evidence")),
])
def test_coastal_built_verdicts(c, ev, expected):
    verdict = verify(c, ev)
    assert tuple(verdict) == expected
    assert verdict.reason in REASONS


def test_located_coastal_strips():
    ev = {"change_frac": 0.0, "regions": [], "coastal_strips": [
        {"strip": "0-200", "built_ha_before": 5.0, "built_ha_after": 8.0, "location": "north-east"},
        {"strip": "0-200", "built_ha_before": 5.0, "built_ha_after": 5.0, "location": "south"},
    ]}
    assert verify(cb("Built area within 200 m of the shore grew in the north-east."), ev).reason == "coastal_built_matches"
    assert verify(cb("Built area within 200 m of the shore grew in the south."), ev).reason == "coastal_built_mismatch"


@pytest.mark.parametrize("text, expected", [
    ("The shoreline moved ~40 m seaward.", ("advancing", [40.0], [])),
    ("The coast retreated 1.2 km at 12 m/yr.", ("retreating", [1200.0], [12.0])),
    ("No shoreline change.", ("stable", [], [])),
    ("Land was gained here and lost there.", (None, [], [])),
])
def test_shoreline_parsing(text, expected):
    assert claimed_shoreline({"text": text}) == expected


@pytest.mark.parametrize("text, expected", [
    ("within 200 m of the shore", "0-200"),
    ("200-500 m from the shoreline", "200-500"),
    ("between 200 and 500 m inland", "200-500"),
    ("within 500 m of the coast", "0-500"),
    ("near the coast", "0-500"),
    ("grew by 200 ha near the coast", "0-500"),
    ("grew by 200.5 ha near the coast", "0-500"),        # a decimal area is not the 200 m strip
    ("grew by 500,000 m² near the coast", "0-500"),
])
def test_strip_parsing(text, expected):
    assert claimed_strip({"text": text}) == expected


def test_claim_types_and_fields_are_validated():
    assert {"shoreline", "coastal_built"} <= set(CLAIM_TYPES)
    assert validate_claim(sh("x", shoreline_change="advancing", transect_ref="t0001")) == []
    assert validate_claim(sh("x", shoreline_change="sideways"))
    assert validate_claim(cb("x", strip="0-500")) == []
    assert validate_claim(cb("x", strip="0-1000"))


def test_evidence_validation():
    assert validate_evidence(EV) == []
    bad = {**EV, "transects": [{**EV["transects"][0], "change": "wobbling"}, EV["transects"][0]]}
    errors = validate_evidence(bad)
    assert any("change" in e for e in errors) and any("unique" in e for e in errors)
    assert validate_evidence({**EV, "coastal_strips": [{"strip": "0-200", "built_ha_before": -1, "built_ha_after": 2}]})
    assert validate_evidence({**EV, "transects": "t0001"})
