"""Numbers for the shoreline paper (docs/paper_shoreline_draft.md) from the committed shoreline outputs.

Everything is an aggregate over transects; nothing is printed per transect, so running this does not
show any Phase 14 reference transect's statistics. The Planet error breakdown leaves the hidden reference
transects out, as the published comparison in planet.json does.

    python scripts/shoreline_paper_numbers.py            prints the tables as Markdown
    python scripts/shoreline_paper_numbers.py --json     the same numbers as JSON
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import shoreline  # noqa: E402

SPACING_KM = shoreline.TRANSECT_SPACING_M / 1000
MIN_SEASONS = 5                      # shoreline.build_years: a rate needs >= 5 seasons with a position
THRESHOLDS_M = (10, 20, 30)          # optical confirmation shift; 20 m is the method's (two Sentinel-2 pixels)


def coast_by_change(years: dict) -> dict:
    """Transects and km of coast per change call (each transect stands for TRANSECT_SPACING_M of baseline)."""
    out: dict[str, dict] = {}
    for st in years["transects"].values():
        row = out.setdefault(st["change"], {"transects": 0})
        row["transects"] += 1
    for row in out.values():
        row["km"] = round(row["transects"] * SPACING_KM, 1)
    return out


def too_few_breakdown(years: dict) -> dict:
    """Why a transect has fewer than MIN_SEASONS seasons with a position, from which seasons have one:
    none at all; positions only from some season on (the shore came within reach, as with reclamation);
    positions only up to some season (the shore left it); or gaps in between."""
    out = {"no_position": 0, "only_later_seasons": 0, "only_earlier_seasons": 0, "scattered": 0}
    for tid, st in years["transects"].items():
        if st["change"] != "too_few":
            continue
        have = [p is not None for p in years["positions"][tid]]
        idx = [i for i, h in enumerate(have) if h]
        if not idx:
            out["no_position"] += 1
        elif all(have[idx[0]:]) and idx[0] > 0:
            out["only_later_seasons"] += 1
        elif all(have[: idx[-1] + 1]) and idx[-1] < len(have) - 1:
            out["only_earlier_seasons"] += 1
        else:
            out["scattered"] += 1
    return out


def unconfirmed_breakdown(years: dict) -> dict:
    """Why a significant radar trend was not confirmed by the optical shoreline."""
    out = {"no_optical_first_or_last": 0, "optical_moved_other_way": 0, "optical_moved_less_than_20m": 0}
    for st in years["transects"].values():
        if st["change"] != "unconfirmed":
            continue
        shift = st.get("opt_shift")
        if shift is None:
            out["no_optical_first_or_last"] += 1
            continue
        sign = 1 if st["trend"] == "advancing" else -1
        out["optical_moved_other_way" if sign * shift < 0 else "optical_moved_less_than_20m"] += 1
    return out


def threshold_sensitivity(years: dict) -> dict:
    """Confirmed advancing / retreating and unconfirmed counts if the optical shift threshold were 10, 20
    or 30 m (shoreline.confirm's rule, applied to the stored radar trends and optical shifts)."""
    out = {}
    for thr in THRESHOLDS_M:
        counts = {"advancing": 0, "retreating": 0, "unconfirmed": 0}
        for st in years["transects"].values():
            if st["trend"] not in ("advancing", "retreating"):
                continue
            counts[shoreline.confirm(st["trend"], st.get("opt_first"), st.get("opt_last"), thr)["change"]] += 1
        out[f"{thr} m"] = counts
    return out


def rates(years: dict) -> dict:
    out = {}
    for kind in ("advancing", "retreating"):
        r = sorted(st["lrr"] for st in years["transects"].values() if st["change"] == kind)
        nsm = sorted(abs(st["nsm"]) for st in years["transects"].values() if st["change"] == kind and st["nsm"] is not None)
        out[kind] = {"n": len(r), "lrr_median": statistics.median(r) if r else None, "lrr_min": min(r, default=None),
                     "lrr_max": max(r, default=None), "abs_nsm_median": statistics.median(nsm) if nsm else None}
    return out


def _err_stats(d: list[float]) -> dict:
    if not d:
        return {"n": 0}
    a = sorted(abs(x) for x in d)
    return {"n": len(d), "bias_m": round(sum(d) / len(d), 1), "median_abs_m": round(statistics.median(a), 1),
            "rmse_m": round(math.sqrt(sum(x * x for x in d) / len(d)), 1),
            "within_20m": round(sum(x <= 20 for x in a) / len(a), 3),
            "share_over_100m": round(sum(x > 100 for x in a) / len(a), 3)}


def planet_by_tidal(planet: dict, monthly: dict, transects: dict, hidden: set[str]) -> dict:
    """Planet day minus monthly radar position, same transect and month, split by the monthly mode's tidal
    flag (monthly positions spreading more than TIDAL_IQR_M). Hidden reference transects are left out."""
    tidal = {f["id"]: bool(f["properties"].get("tidal")) for f in transects["features"]}
    months = monthly["months"]
    groups = {"tidal": [], "not_tidal": []}
    for tid, series in planet["positions"].items():
        if tid in hidden or tid not in monthly["positions"]:
            continue
        for m, p in zip(planet["months"], series):
            if p is None or m not in months:
                continue
            r = monthly["positions"][tid][months.index(m)]
            if r is not None:
                groups["tidal" if tidal.get(tid) else "not_tidal"].append(p - r)
    return {k: _err_stats(v) for k, v in groups.items()}


def compute() -> dict:
    load = lambda name: json.loads((shoreline.SHORELINE_DIR / name).read_text(encoding="utf-8"))
    years, planet, monthly, transects = load("years.json"), load("planet.json"), load("positions.json"), load("transects.geojson")
    return {"seasons": [s[0] for s in years["seasons"]], "transects": len(years["transects"]),
            "coast_by_change": coast_by_change(years), "rates": rates(years),
            "too_few": too_few_breakdown(years), "unconfirmed": unconfirmed_breakdown(years),
            "optical_threshold": threshold_sensitivity(years),
            "planet_vs_monthly_by_tidal": planet_by_tidal(planet, monthly, transects, shoreline.hidden_transects(transects))}


def markdown(n: dict) -> str:
    lines = [f"Shoreline paper numbers: {n['transects']} transects, seasons {n['seasons'][0]} to {n['seasons'][-1]}", ""]
    lines += ["| Change | Transects | Coast, km |", "|---|---:|---:|"]
    lines += [f"| {k} | {v['transects']} | {v['km']} |" for k, v in sorted(n["coast_by_change"].items())]
    lines += ["", "Rates: " + "; ".join(f"{k} n={v['n']}, LRR median {v['lrr_median']} (from {v['lrr_min']} to {v['lrr_max']}) m/yr, "
                                         f"|NSM| median {v['abs_nsm_median']} m" for k, v in n["rates"].items())]
    lines += ["", "Too few seasons: " + ", ".join(f"{k} {v}" for k, v in n["too_few"].items())]
    lines += ["Unconfirmed radar trends: " + ", ".join(f"{k} {v}" for k, v in n["unconfirmed"].items())]
    lines += ["", "| Optical threshold | Advancing | Retreating | Unconfirmed |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {v['advancing']} | {v['retreating']} | {v['unconfirmed']} |" for k, v in n["optical_threshold"].items()]
    lines += ["", "| Planet − monthly radar | n | Bias, m | Median abs, m | RMSE, m | Within 20 m | Over 100 m |", "|---|---:|---:|---:|---:|---:|---:|"]
    lines += [f"| {k} | {v['n']} | {v.get('bias_m')} | {v.get('median_abs_m')} | {v.get('rmse_m')} | {v.get('within_20m')} | {v.get('share_over_100m')} |"
              for k, v in n["planet_vs_monthly_by_tidal"].items()]
    return "\n".join(lines)


if __name__ == "__main__":
    numbers = compute()
    print(json.dumps(numbers, indent=1) if "--json" in sys.argv else markdown(numbers))
