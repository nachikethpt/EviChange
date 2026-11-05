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
