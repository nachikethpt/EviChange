"""scripts/shoreline_paper_numbers.py on a small synthetic yearly result, and on the committed outputs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import shoreline_paper_numbers as spn  # noqa: E402

N = None
YEARS = {
    "seasons": [["2015-16"], ["2016-17"], ["2017-18"], ["2018-19"], ["2019-20"], ["2020-21"]],
    "positions": {"a": [0, 5, 10, 15, 20, 25], "b": [N, N, N, N, N, N], "c": [N, N, N, 4, 5, 6],
                  "d": [1, 2, N, N, N, N], "e": [1, N, 2, N, N, 3], "f": [0] * 6, "g": [0] * 6, "h": [0] * 6},
    "transects": {
        "a": {"change": "advancing", "trend": "advancing", "lrr": 5.0, "nsm": 20.0, "opt_first": 0, "opt_last": 25, "opt_shift": 25},
        "b": {"change": "too_few", "trend": "too_few", "lrr": None, "nsm": None},
        "c": {"change": "too_few", "trend": "too_few", "lrr": None, "nsm": None},
        "d": {"change": "too_few", "trend": "too_few", "lrr": None, "nsm": None},
        "e": {"change": "too_few", "trend": "too_few", "lrr": None, "nsm": None},
        "f": {"change": "unconfirmed", "trend": "advancing", "lrr": 3.0, "nsm": 10.0, "opt_first": 0, "opt_last": 15, "opt_shift": 15},
        "g": {"change": "unconfirmed", "trend": "retreating", "lrr": -3.0, "nsm": -10.0, "opt_first": 0, "opt_last": 30, "opt_shift": 30},
        "h": {"change": "unconfirmed", "trend": "advancing", "lrr": 2.0, "nsm": 5.0, "opt_first": None, "opt_last": 3, "opt_shift": None},
    },
}


def test_breakdowns():
    assert spn.too_few_breakdown(YEARS) == {"no_position": 1, "only_later_seasons": 1, "only_earlier_seasons": 1, "scattered": 1}
    assert spn.unconfirmed_breakdown(YEARS) == {"no_optical_first_or_last": 1, "optical_moved_other_way": 1,
                                                "optical_moved_less_than_20m": 1}
    sens = spn.threshold_sensitivity(YEARS)
    assert sens["10 m"]["advancing"] == 2 and sens["20 m"]["advancing"] == 1 and sens["30 m"]["advancing"] == 0
    assert spn.coast_by_change(YEARS)["too_few"] == {"transects": 4, "km": 0.4}


def test_magnitude_and_steps():
    years = {"positions": {"s": [0, 0, 0, 100, 100, 100], "g": [0, 20, 40, 60, 80, 100]},
             "transects": {"s": {"change": "advancing", "nsm": 100.0, "opt_shift": 30.0},
                           "g": {"change": "advancing", "nsm": 100.0, "opt_shift": 110.0},
                           "u": {"change": "unconfirmed", "nsm": 50.0, "opt_shift": -40.0}}}
    assert spn.magnitude_agreement(years) == {"n": 2, "median_ratio": 0.7, "optical_under_half_of_radar": 1,
                                              "optical_under_quarter_of_radar": 0}
    assert spn.step_changes(years) == {"confirmed": 2, "step_like": 1, "share": 0.5}     # the step, not the steady trend


def test_planet_tail_counts_chronic_transects():
    planet = {"months": ["m1", "m2", "m3", "m4"], "positions": {"a": [200, 210, 190, 5], "b": [0, 150, 0, 0], "f": [400] * 4,
                                                                   "h": [500] * 4}}
    monthly = {"months": ["m1", "m2", "m3", "m4"], "positions": {k: [0, 0, 0, 0] for k in "abfh"}}
    transects = {"features": [{"id": k, "properties": {"tidal": k == "f"}} for k in "abfh"]}
    t = spn.planet_tail(planet, monthly, transects, hidden={"h"})
    assert t == {"transects": 2, "pairs": 8, "far_pairs": 4, "far_landward": 0, "chronic_transects": 1, "far_pairs_on_chronic": 3}


def test_built_near_change_splits_cells_by_distance():
    # one advancing transect along lon 107.3; baseline point 300 m from its landward end
    feats = [{"id": "a", "geometry": {"coordinates": [[107.3, 21.0], [107.3, 21.0 + 800 / 111_320]]}},
             {"id": "h", "geometry": {"coordinates": [[107.31, 21.0], [107.31, 21.0 + 800 / 111_320]]}}]
    years = {"transects": {"a": {"change": "advancing"}, "h": {"change": "advancing"}}}
    cells = {"grid": {"lon0": 107.2995, "lat0": 21.0022, "step": 0.001},
             "columns": ["strip", "cx", "cy", "land_ha", "observed_ha", "built_ha_before", "built_ha_after"],
             "cells": [[1, 0, 0, 1.0, 1.0, 0.1, 0.6],          # ~0 m from the baseline point: near
                       [1, 0, 20, 1.0, 1.0, 0.1, 0.2],         # ~2 km north: far
                       [1, 10, 0, 1.0, 1.0, 0.0, 0.9]],        # next to the hidden transect only: far
             "windows": [["2018-11-01"], ["2022-11-01"]]}
    r = spn.built_near_change(years, {"features": feats}, cells, hidden={"h"}, radius_m=300)
    assert r["advancing"]["transects"] == 1
    assert r["advancing"]["near"]["growth_per_100ha_land"] == 50.0
    assert r["advancing"]["far"]["growth_per_100ha_land"] == 50.0 and r["advancing"]["far"]["land_ha"] == 2.0


def test_median_of_an_even_count_is_the_middle_mean():
    years = {"transects": {str(i): {"change": "retreating", "lrr": v, "nsm": v} for i, v in enumerate([-46.4, -20.0, -7.0, -2.7])}}
    assert spn.rates(years)["retreating"]["lrr_median"] == -13.5


def test_committed_outputs_match_the_published_counts():
    n = spn.compute()
    counts = {k: v["transects"] for k, v in n["coast_by_change"].items()}
    assert sum(counts.values()) == n["transects"]
    assert n["optical_threshold"]["20 m"]["advancing"] == counts.get("advancing", 0)
    assert sum(n["too_few"].values()) == counts.get("too_few", 0)
    assert sum(n["unconfirmed"].values()) == counts.get("unconfirmed", 0)
