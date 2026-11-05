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


STEP_SHARE = 0.5                     # a change is a "step" when one season-to-season jump is >= this share of |NSM|


def magnitude_agreement(years: dict) -> dict:
    """Confirmed changes: the optical shift as a share of the radar's net movement. Confirmation checks only
    the direction and a 20 m minimum, so this shows how often the two disagree on size."""
    r = sorted(abs(st["opt_shift"]) / abs(st["nsm"]) for st in years["transects"].values()
               if st["change"] in ("advancing", "retreating") and st.get("nsm") and st.get("opt_shift") is not None)
    return {"n": len(r), "median_ratio": round(statistics.median(r), 2) if r else None,
            "optical_under_half_of_radar": sum(x < 0.5 for x in r), "optical_under_quarter_of_radar": sum(x < 0.25 for x in r)}


def step_changes(years: dict, share: float = STEP_SHARE) -> dict:
    """Confirmed changes where the largest jump between consecutive seasons with a position is at least `share`
    of |NSM|: an event (reclamation, port works) rather than a steady trend, which a linear rate misdescribes."""
    def max_jump(series):
        q = [v for v in series if v is not None]
        return max((abs(b - a) for a, b in zip(q, q[1:])), default=0.0)
    rows = [(tid, st) for tid, st in years["transects"].items() if st["change"] in ("advancing", "retreating") and st.get("nsm")]
    steps = sum(max_jump(years["positions"][tid]) >= share * abs(st["nsm"]) for tid, st in rows)
    return {"confirmed": len(rows), "step_like": steps, "share": share}


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


def planet_tail(planet: dict, monthly: dict, transects: dict, hidden: set[str], far_m: float = 100, min_pairs: int = 4) -> dict:
    """Off the tidal flats, where the large (> far_m) Planet-vs-radar differences come from: transects whose
    median difference is itself > far_m ("chronic", with >= min_pairs pairs), and how many of the large pairs
    they hold. Hidden reference transects are left out."""
    tidal = {f["id"]: bool(f["properties"].get("tidal")) for f in transects["features"]}
    months = monthly["months"]
    per: dict[str, list[float]] = {}
    for tid, series in planet["positions"].items():
        if tid in hidden or tidal.get(tid) or tid not in monthly["positions"]:
            continue
        for m, p in zip(planet["months"], series):
            r = monthly["positions"][tid][months.index(m)] if m in months else None
            if p is not None and r is not None:
                per.setdefault(tid, []).append(p - r)
    far = [d for v in per.values() for d in v if abs(d) > far_m]
    chronic = [t for t, v in per.items() if len(v) >= min_pairs and statistics.median(abs(d) for d in v) > far_m]
    return {"transects": len(per), "pairs": sum(map(len, per.values())), "far_pairs": len(far),
            "far_landward": sum(d < 0 for d in far), "chronic_transects": len(chronic),
            "far_pairs_on_chronic": sum(abs(d) > far_m for t in chronic for d in per[t])}


def built_near_change(years: dict, transects: dict, cells: dict, hidden: set[str], radius_m: float = 300) -> dict:
    """Built-up growth between the detector's windows (Dynamic World, coastal-strip cells of
    windows_*.json) within radius_m of the baseline point of transects with a given change call, and in all
    other cells: is new building concentrated behind the advancing shoreline? "stable" is the control.
    Hidden reference transects are left out."""
    g, cols = cells["grid"], {c: i for i, c in enumerate(cells["columns"])}
    base_t = shoreline.LAND_M / (shoreline.LAND_M + shoreline.SEA_M)   # baseline point along the transect
    out = {}
    for kind in ("advancing", "stable"):
        pts = []
        for f in transects["features"]:
            if f["id"] in hidden or years["transects"].get(f["id"], {}).get("change") != kind:
                continue
            (a, b), (c, d) = f["geometry"]["coordinates"]
            pts.append((a + (c - a) * base_t, b + (d - b) * base_t))
        sums = {"near": [0.0, 0.0, 0.0], "far": [0.0, 0.0, 0.0]}
        for cell in cells["cells"]:
            lon = g["lon0"] + (cell[cols["cx"]] + 0.5) * g["step"]
            lat = g["lat0"] + (cell[cols["cy"]] + 0.5) * g["step"]
            kx = math.cos(math.radians(lat)) * shoreline.M_PER_DEG
            close = any(math.hypot((lon - px) * kx, (lat - py) * shoreline.M_PER_DEG) <= radius_m for px, py in pts)
            s = sums["near" if close else "far"]
            s[0] += cell[cols["built_ha_before"]]
            s[1] += cell[cols["built_ha_after"]]
            s[2] += cell[cols["land_ha"]]
        out[kind] = {"transects": len(pts), **{k: {"built_before_ha": round(b0, 1), "built_after_ha": round(b1, 1),
                                                     "land_ha": round(land, 1),
                                                     "growth_per_100ha_land": round(100 * (b1 - b0) / land, 1) if land else None}
                                                 for k, (b0, b1, land) in sums.items()}}
    return {"radius_m": radius_m, "windows": cells.get("windows"), **out}


def compute() -> dict:
    load = lambda name: json.loads((shoreline.SHORELINE_DIR / name).read_text(encoding="utf-8"))
    years, planet, monthly, transects = load("years.json"), load("planet.json"), load("positions.json"), load("transects.geojson")
    hidden = shoreline.hidden_transects(transects)
    return {"seasons": [s[0] for s in years["seasons"]], "transects": len(years["transects"]),
            "coast_by_change": coast_by_change(years), "rates": rates(years),
            "too_few": too_few_breakdown(years), "unconfirmed": unconfirmed_breakdown(years),
            "optical_threshold": threshold_sensitivity(years),
            "magnitude_agreement": magnitude_agreement(years), "step_changes": step_changes(years),
            "planet_vs_monthly_by_tidal": planet_by_tidal(planet, monthly, transects, hidden),
            "planet_tail_off_flats": planet_tail(planet, monthly, transects, hidden),
            "built_near_change": built_near_change(years, transects, json.loads(
                (ROOT / "data" / "quangninh" / "coastal" / "windows_2018-11_2022-11.json").read_text(encoding="utf-8")), hidden)}


def markdown(n: dict) -> str:
    lines = [f"Shoreline paper numbers: {n['transects']} transects, seasons {n['seasons'][0]} to {n['seasons'][-1]}", ""]
    lines += ["| Change | Transects | Coast, km |", "|---|---:|---:|"]
    lines += [f"| {k} | {v['transects']} | {v['km']} |" for k, v in sorted(n["coast_by_change"].items())]
    lines += ["", "Rates: " + "; ".join(f"{k} n={v['n']}, LRR median {v['lrr_median']} (from {v['lrr_min']} to {v['lrr_max']}) m/yr, "
                                         f"|NSM| median {v['abs_nsm_median']} m" for k, v in n["rates"].items())]
    lines += ["", "Too few seasons: " + ", ".join(f"{k} {v}" for k, v in n["too_few"].items())]
    lines += ["Unconfirmed radar trends: " + ", ".join(f"{k} {v}" for k, v in n["unconfirmed"].items())]
    ma, sc = n["magnitude_agreement"], n["step_changes"]
    lines += [f"Confirmed changes: optical shift / radar NSM median {ma['median_ratio']} (n={ma['n']}), under half "
              f"{ma['optical_under_half_of_radar']}, under a quarter {ma['optical_under_quarter_of_radar']}; "
              f"step-like (one jump >= {sc['share']:.0%} of |NSM|) {sc['step_like']} of {sc['confirmed']}"]
    lines += ["", "| Optical threshold | Advancing | Retreating | Unconfirmed |", "|---|---:|---:|---:|"]
    lines += [f"| {k} | {v['advancing']} | {v['retreating']} | {v['unconfirmed']} |" for k, v in n["optical_threshold"].items()]
    lines += ["", "| Planet − monthly radar | n | Bias, m | Median abs, m | RMSE, m | Within 20 m | Over 100 m |", "|---|---:|---:|---:|---:|---:|---:|"]
    lines += [f"| {k} | {v['n']} | {v.get('bias_m')} | {v.get('median_abs_m')} | {v.get('rmse_m')} | {v.get('within_20m')} | {v.get('share_over_100m')} |"
              for k, v in n["planet_vs_monthly_by_tidal"].items()]
    t = n["planet_tail_off_flats"]
    lines += ["", f"Off the flats: {t['far_pairs']} of {t['pairs']} pairs > 100 m ({t['far_landward']} with Planet landward); "
                  f"{t['chronic_transects']} of {t['transects']} transects have a median > 100 m and hold {t['far_pairs_on_chronic']} of them"]
    b = n["built_near_change"]
    lines += ["", f"Built-up growth {b['windows'][0][0][:7]} to {b['windows'][1][0][:7]} within {b['radius_m']:.0f} m of the transects' baseline point, "
                  "ha per 100 ha of strip land:"]
    lines += [f"- near {k} ({b[k]['transects']} transects): {b[k]['near']['growth_per_100ha_land']} "
              f"({b[k]['near']['built_before_ha']} -> {b[k]['near']['built_after_ha']} ha); elsewhere {b[k]['far']['growth_per_100ha_land']}"
              for k in ("advancing", "stable")]
    return "\n".join(lines)


if __name__ == "__main__":
    numbers = compute()
    print(json.dumps(numbers, indent=1) if "--json" in sys.argv else markdown(numbers))
