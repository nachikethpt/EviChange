"""Figures for the shoreline paper (docs/paper_shoreline_draft.md), as static SVG from the committed outputs.

    figure_shoreline_map.svg      the 735 transects coloured by their ten-year change call (Fig. 1)
    figure_planet_error.svg       cumulative share of Planet-vs-radar differences, tidal flats apart (Fig. 4)
    figure_case_<id>.svg          a transect's yearly radar and optical positions (Fig. 3), for --case ids

Plain SVG like scripts/results_tables.py (no plotting library on the project PC); every mark carries a
<title> for on-screen reading. Phase 14 reference transects and their neighbours are drawn without their
statistics and labelled hidden, as in the app, and can't be chosen as a case.

    python scripts/shoreline_figures.py [--out docs/figures] [--case t0123 ...]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import shoreline  # noqa: E402

INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"     # as scripts/results_tables.py
ADVANCING, RETREATING = "#2a78d6", "#eb6834"                               # diverging poles (validated pair)
FONT = 'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" font-size="12"'
# change call -> (colour, width, dash, legend text); order is the legend's
STYLE = {
    "advancing": (ADVANCING, 3.0, "", "advancing (land gained)"),
    "retreating": (RETREATING, 3.0, "", "retreating (sea moved in)"),
    "unconfirmed": ("#8a8883", 2.0, "4 3", "radar trend, optical did not confirm"),
    "stable": ("#c4c2bc", 1.0, "", "stable"),
    "too_few": (GRID, 1.0, "", "too few seasons"),
    "hidden": ("#a8a6a0", 1.0, "1 3", "hidden until the Phase 14 reference shorelines are in"),
}


def _load(name: str):
    return json.loads((shoreline.SHORELINE_DIR / name).read_text(encoding="utf-8"))


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" {FONT}>',
                      f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
                      f'<text x="16" y="22" font-size="14" font-weight="600" fill="{INK}">{escape(title)}</text>',
                      *body, "</svg>"])


def map_figure(transects: dict, years: dict, hidden: set[str], baseline: dict | None = None, width: int = 760) -> str:
    """Fig. 1: transects on an equirectangular projection (fine at this scale), coloured by change."""
    feats = transects["features"]
    pts = [p for f in feats for p in f["geometry"]["coordinates"]]
    lon0, lon1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lat0, lat1 = min(p[1] for p in pts), max(p[1] for p in pts)
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    pad, top, legend_w = 16, 40, 0
    plot_w = width - 2 * pad
    scale = plot_w / ((lon1 - lon0) * kx)
    plot_h = (lat1 - lat0) * scale
    height = int(top + plot_h + 150)
    xy = lambda lon, lat: (pad + (lon - lon0) * kx * scale, top + (lat1 - lat) * scale)
    stats = years["transects"]
    call = {f["id"]: ("hidden" if f["id"] in hidden else stats.get(f["id"], {}).get("change", "too_few")) for f in feats}
    body = []
    if baseline:
        for f in baseline["features"]:
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(*p) for p in f["geometry"]["coordinates"]))
            body.append(f'<polyline points="{d}" fill="none" stroke="{MUTED}" stroke-width="0.6" opacity="0.5"/>')
    # quiet classes first, so the changes draw on top
    for kind in ("too_few", "hidden", "stable", "unconfirmed", "retreating", "advancing"):
        color, w, dash, _ = STYLE[kind]
        for f in feats:
            if call[f["id"]] != kind:
                continue
            (x1, y1), (x2, y2) = (xy(*p) for p in f["geometry"]["coordinates"])
            if kind == "hidden":
                tip = f"{f['id']}: hidden (Phase 14 reference)"
            else:
                st = stats.get(f["id"], {})
                tip = f"{f['id']}: {kind}" + (f", {st['lrr']:+.1f} m/yr" if st.get("lrr") is not None and kind != "too_few" else "")
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            body.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
                        f'stroke-width="{w}" stroke-linecap="round"{dash_attr}><title>{escape(tip)}</title></line>')
    # scale bar: 5 km
    km = 1000 * scale / shoreline.M_PER_DEG                 # pixels per km (x is lon * cos(lat) * scale)
    sx, sy = pad, top + plot_h + 24
    body.append(f'<line x1="{sx}" y1="{sy}" x2="{sx + 5 * km:.1f}" y2="{sy}" stroke="{INK}" stroke-width="2"/>')
    body.append(f'<text x="{sx}" y="{sy + 16}" fill="{MUTED}">5 km</text>')
    # legend with counts (identity is never colour alone: width and dash differ too)
    counts = {k: sum(v == k for v in call.values()) for k in STYLE}
    ly = sy + 34
    for i, kind in enumerate(k for k in STYLE if counts[k]):
        color, w, dash, text = STYLE[kind]
        x = pad + (i % 2) * 370
        y = ly + (i // 2) * 20
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        body.append(f'<line x1="{x}" y1="{y}" x2="{x + 26}" y2="{y}" stroke="{color}" stroke-width="{max(w, 1.5)}"{dash_attr}/>')
        body.append(f'<text x="{x + 34}" y="{y + 4}" fill="{INK}">{escape(text)}: {counts[kind]}</text>')
    seasons = years["seasons"]
    return _svg(width, height, body, f"Shoreline change {seasons[0][0]} to {seasons[-1][0]}, {len(feats)} transects every "
                                     f"{shoreline.TRANSECT_SPACING_M} m")


def planet_error_figure(groups: dict[str, list[float]], width: int = 720, max_m: int = 300) -> str:
    """Fig. 4: share of transect-months with |Planet - radar| <= x, for tidal-flat transects and the rest."""
    left, right, top, plot_h = 60, 24, 64, 240
    plot_w = width - left - right
    x = lambda m: left + plot_w * min(m, max_m) / max_m
    y = lambda share: top + plot_h * (1 - share)
    body = []
    for t in range(0, max_m + 1, 50):
        body.append(f'<line x1="{x(t)}" x2="{x(t)}" y1="{top}" y2="{top + plot_h}" stroke="{GRID}"/>')
        body.append(f'<text x="{x(t)}" y="{top + plot_h + 16}" text-anchor="middle" fill="{MUTED}">{t}</text>')
    for s in (0, 0.25, 0.5, 0.75, 1):
        body.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y(s)}" y2="{y(s)}" stroke="{GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y(s) + 4}" text-anchor="end" fill="{MUTED}">{int(s * 100)} %</text>')
    body.append(f'<text x="{left + plot_w / 2}" y="{top + plot_h + 36}" text-anchor="middle" fill="{MUTED}">'
                f'|Planet − radar| on the same transect and month, m (cut at {max_m})</text>')
    series = (("not_tidal", "other transects", ADVANCING), ("tidal", "tidal flats (monthly spread > 100 m)", RETREATING))
    lx = left
    for key, label, color in series:
        a = sorted(abs(v) for v in groups.get(key, []))
        if not a:
            continue
        n = len(a)
        pts = [(0, 0.0)] + [(v, (i + 1) / n) for i, v in enumerate(a) if v <= max_m]
        d = " ".join(f"{x(v):.1f},{y(s):.1f}" for v, s in pts)
        within20 = sum(v <= 20 for v in a) / n
        med = a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2
        body.append(f'<g><title>{escape(label)}: n = {n}, median {med:.1f} m, {within20:.0%} within 20 m</title>'
                    f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/></g>')
        # direct label at the median
        body.append(f'<circle cx="{x(med):.1f}" cy="{y(0.5):.1f}" r="4" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>')
        body.append(f'<text x="{x(med) + 8:.1f}" y="{y(0.5) - 6 if key == "not_tidal" else y(0.5) + 16:.1f}" fill="{INK}">median {med:.1f} m</text>')
        body.append(f'<line x1="{lx}" y1="44" x2="{lx + 22}" y2="44" stroke="{color}" stroke-width="2"/>')
        text = f"{label} (n = {n:,})"
        body.append(f'<text x="{lx + 28}" y="48" fill="{MUTED}">{escape(text)}</text>')
        lx += 48 + 7 * len(text)
    return _svg(width, top + plot_h + 52, body, "Where the 3 m Planet shoreline sits relative to the radar shoreline")


def case_figure(tid: str, years: dict, width: int = 720) -> str:
    """Fig. 3: one transect's yearly radar (tide-averaged) and optical (Sentinel-2) positions, with its rate."""
    seasons = [s[0] for s in years["seasons"]]
    radar, optical = years["positions"][tid], years["optical"].get(tid, [None] * len(seasons))
    st = years["transects"][tid]
    vals = [v for v in (*radar, *optical) if v is not None]
    lo, hi = min(vals + [0]), max(vals + [0])
    span = hi - lo or 1
    lo, hi = lo - 0.1 * span, hi + 0.1 * span
    left, right, top, plot_h = 64, 40, 64, 240
    plot_w = width - left - right
    x = lambda i: left + plot_w * i / (len(seasons) - 1)
    y = lambda v: top + plot_h * (hi - v) / (hi - lo)
    body = []
    step = 10 ** math.floor(math.log10(span)) if span > 0 else 10
    t = math.ceil(lo / step) * step
    while t <= hi:
        body.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{INK if t == 0 else GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end" fill="{MUTED}">{"0" if t == 0 else f"{t:+.0f}"}</text>')
        t += step
    for i, s in enumerate(seasons):
        if i % 2 == 0:
            body.append(f'<text x="{x(i):.1f}" y="{top + plot_h + 16}" text-anchor="middle" fill="{MUTED}">{s}</text>')
    body.append(f'<text x="14" y="{top + plot_h / 2}" fill="{MUTED}" transform="rotate(-90 14 {top + plot_h / 2})" '
                f'text-anchor="middle">m from the baseline, seaward +</text>')
    lx = left
    for name, series, color, label in (("radar", radar, ADVANCING, "radar, tide-averaged per dry season"),
                                       ("optical", optical, RETREATING, "optical (Sentinel-2 MNDWI)")):
        pts = [(i, v) for i, v in enumerate(series) if v is not None]
        runs, cur = [], []                      # a season without a position is a gap, never bridged
        for i, v in pts:
            if cur and i != cur[-1][0] + 1:
                runs.append(cur)
                cur = []
            cur.append((i, v))
        runs.append(cur)
        for run in (r for r in runs if len(r) > 1):
            d = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in run)
            body.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in pts:
            body.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="{color}" stroke="{SURFACE}" stroke-width="2">'
                        f'<title>{seasons[i]}, {name}: {v:+.0f} m</title></circle>')
        body.append(f'<line x1="{lx}" y1="44" x2="{lx + 22}" y2="44" stroke="{color}" stroke-width="2"/>')
        body.append(f'<text x="{lx + 28}" y="48" fill="{MUTED}">{escape(label)}</text>')
        lx += 60 + 7 * len(label)
    rate = "" if st.get("lrr") is None else f", {st['lrr']:+.1f} m/yr (95 % CI ±{st['ci95']:.1f})"
    return _svg(width, top + plot_h + 30, body, f"Transect {tid}: {st['change']}{rate}")


def reference_figure(matched: list[tuple[str, float, float]], width: int = 760) -> str:
    """Fig. 5: yearly (tide-averaged radar) position against the traced reference, one small panel per season,
    with the 1:1 line and a ±20 m band. matched = shoreline_reference_ge.pairs()."""
    seasons = sorted({s for s, _, _ in matched})
    vals = [v for _, t, m in matched for v in (t, m)] or [0.0]
    lo, hi = min(vals), max(vals)
    pad_v = 0.05 * (hi - lo or 1)
    lo, hi = lo - pad_v, hi + pad_v
    gap, top, size = 18, 64, (width - 32 - 18 * (max(len(seasons), 1) - 1)) / max(len(seasons), 1)
    body = []
    for k, season in enumerate(seasons):
        x0 = 16 + k * (size + gap)
        sx = lambda v: x0 + size * (v - lo) / (hi - lo)
        sy = lambda v: top + size * (hi - v) / (hi - lo)
        pts = [(t, m) for s, t, m in matched if s == season]
        errs = [m - t for t, m in pts]
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        bias = sum(errs) / len(errs)
        body.append(f'<rect x="{x0}" y="{top}" width="{size:.1f}" height="{size:.1f}" fill="none" stroke="{GRID}"/>')
        step = 10 ** math.floor(math.log10(hi - lo)) if hi > lo else 10
        step /= 2 if (hi - lo) / step < 4 else 1          # at least about four ticks per panel
        t = math.ceil(lo / step) * step
        while t <= hi:                                   # ticks on both axes, labelled on x only (the axes match)
            body.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top + size:.1f}" y2="{top + size + 4:.1f}" stroke="{MUTED}"/>')
            body.append(f'<line x1="{x0 - 4}" x2="{x0}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" stroke="{MUTED}"/>')
            body.append(f'<text x="{sx(t):.1f}" y="{top + size + 14:.1f}" text-anchor="middle" font-size="10" fill="{MUTED}">{t:.0f}</text>')
            t += step
        band = f"{sx(lo):.1f},{sy(lo + 20):.1f} {sx(hi - 20):.1f},{sy(hi):.1f} {sx(hi):.1f},{sy(hi):.1f} {sx(hi):.1f},{sy(hi - 20):.1f} {sx(lo + 20):.1f},{sy(lo):.1f} {sx(lo):.1f},{sy(lo):.1f}"
        body.append(f'<polygon points="{band}" fill="{GRID}" opacity="0.6"><title>within ±20 m</title></polygon>')
        body.append(f'<line x1="{sx(lo):.1f}" y1="{sy(lo):.1f}" x2="{sx(hi):.1f}" y2="{sy(hi):.1f}" stroke="{MUTED}" stroke-width="1"/>')
        for t, m in pts:
            body.append(f'<circle cx="{sx(t):.1f}" cy="{sy(m):.1f}" r="4" fill="{ADVANCING}" stroke="{SURFACE}" stroke-width="2">'
                        f'<title>{season}: traced {t:+.0f} m, extracted {m:+.0f} m</title></circle>')
        body.append(f'<text x="{x0}" y="{top - 8}" font-weight="600" fill="{INK}">{season}</text>')
        body.append(f'<text x="{x0}" y="{top + size + 30:.1f}" fill="{MUTED}">n {len(pts)} · bias {bias:+.0f} m · RMSE {rmse:.0f} m</text>')
    body.append(f'<text x="16" y="{top + size + 50:.1f}" fill="{MUTED}">x: traced on Google Earth; y: tide-averaged radar; m from '
                f'the baseline, seaward +; grey band: within ±20 m of 1:1</text>')
    return _svg(width, int(top + size + 62), body, "Extracted against traced reference shorelines, per dry season")


def planet_groups(hidden: set[str]) -> dict[str, list[float]]:
    planet, monthly, transects = _load("planet.json"), _load("positions.json"), _load("transects.geojson")
    tidal = {f["id"]: bool(f["properties"].get("tidal")) for f in transects["features"]}
    months = monthly["months"]
    out = {"tidal": [], "not_tidal": []}
    for tid, series in planet["positions"].items():
        if tid in hidden or tid not in monthly["positions"]:
            continue
        for m, p in zip(planet["months"], series):
            r = monthly["positions"][tid][months.index(m)] if m in months else None
            if p is not None and r is not None:
                out["tidal" if tidal.get(tid) else "not_tidal"].append(p - r)
    return out


def write_all(out: Path, cases: list[str]) -> list[Path]:
    transects, years = _load("transects.geojson"), _load("years.json")
    hidden = shoreline.hidden_transects(transects)
    bad = [c for c in cases if c in hidden]
    if bad:
        raise SystemExit(f"{bad}: hidden Phase 14 reference transects (or neighbours) can't be case studies until unlocked")
    out.mkdir(parents=True, exist_ok=True)
    files = {"figure_shoreline_map.svg": map_figure(transects, years, hidden, _load("baseline.geojson")),
             "figure_planet_error.svg": planet_error_figure(planet_groups(hidden)),
             **{f"figure_case_{c}.svg": case_figure(c, years) for c in cases}}
    # Fig. 5 plots extracted positions AT the reference transects, so it exists only once they are unlocked:
    # made earlier, it would show a labeller still tracing what they must not see (D13 blindness).
    if shoreline.REFERENCE_TRANSECTS_UNLOCKED:
        from agents import labels14
        import shoreline_reference_ge as ge
        recs = [r for f in sorted(labels14.LABELS_DIR.glob("shoreline_ge_*.jsonl")) for r in labels14.load_labels(f, "shoreline")]
        if recs:
            files["figure_reference_accuracy.svg"] = reference_figure(ge.pairs(recs, years)[0])
    for name, svg in files.items():
        (out / name).write_text(svg, encoding="utf-8")
    return [out / n for n in files]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "figures")
    ap.add_argument("--case", nargs="*", default=[])
    args = ap.parse_args()
    for p in write_all(args.out, args.case):
        print("wrote", p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)
