"""Phase 14 ground truth (D13, D14): samples, label records and the blind-labelling lock.

Four label sets, each labelled blind in notebooks/EviChange_labeling_phase14.ipynb:
  (a) classes      from / to Dynamic World class at the 30 Phase 3 sites (dominant class in the box)
  (b) shoreline    reference land / water edge on PlanetScope at 2 dates on 30 random transects
  (c) cells        30 coastal cells (CELL_M square, 0-200 m and 200-500 m landward of the baseline)
                   labelled built / not built at the same 2 dates
  (d) change_month first month a lasting change is visible at the 30 sites, on the Planet months

This module draws the samples for (b) and (c) (scripts/make_phase14_samples.py writes them) and
checks label records. Everything here is plain Python: no Earth Engine.

Blindness (PLAN Phase 14): the labeller built the classes and the shoreline, so (a) classes stay
hidden at the labelled sites (landcover.CLASSES_UNLOCKED_AT_LABELLED_SITES), (b) the extracted
shorelines are hidden at the reference transects and their neighbours
(shoreline.hide_at_reference_transects), and the notebook draws each reference transect with a
random extension at both ends, so the baseline (the long-term sea edge, 300 m from the landward end)
can't be read off the drawing.
"""
from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path
from typing import Any

from .schema import LANDCOVER_CLASSES
from .shoreline import LAND_M, SEA_M, TRANSECT_SPACING_M, LocalFrame

LABELS_DIR = Path(__file__).resolve().parent.parent / "data" / "quangninh" / "labels" / "phase14"
TRANSECTS_FILE = LABELS_DIR / "reference_transects.json"
CELLS_FILE = LABELS_DIR / "coastal_cells.json"

SEED = 20261023
N_TRANSECTS = 30
N_CELLS = 30
STRIPS = ((0, 200), (200, 500))     # m landward of the baseline (D11 coastal strips); half the cells in each
CELL_M = 30                         # cell side: 3 x 3 Dynamic World pixels, 10 x 10 Planet pixels
CELL_MIN_GAP_M = 150                # cells at least this far apart (centre to centre)
EXTEND_MAX_M = 200                  # drawn transect = the real one extended by U(0, this) at each end
NEIGHBOUR_M = TRANSECT_SPACING_M    # transects this close along the same line are hidden with a reference one
# Reference dates for (b) and (c): the plan's Oct 2024 / Sep 2026; Sep 2026 Planet is ordered in
# November (D12), so the notebook uses the last delivered month until then and records which.
REF_DATES = ("2024-10", "2026-09")

YES_NO = ("yes", "no", "unsure")
CONFIDENCE = ("low", "medium", "high")
CLASS_ANSWERS = (*LANDCOVER_CLASSES, "unsure")
SHORE_STATUS = ("edge", "no_edge", "not_visible")      # edge found / transect all land or all water / cloud, no data
CELL_ANSWERS = ("built", "not_built", "unsure")
PROTOCOL = "labels14_v1"
KINDS = ("classes", "shoreline", "cells", "change_month")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SEASON = re.compile(r"^\d{4}-\d{2}$")
# (b) on Google Earth (D13, changed 2026-10-28): the same 30 reference transects traced on Google Earth
# Pro's historical imagery for 4 dry seasons across the yearly shorelines' ten years, so the yearly
# lines are checked over their whole span. Planet (b) stays for the recent dates when its months arrive.
GE_SEASONS = ("2016-17", "2019-20", "2022-23", "2025-26")
SOURCES = ("planet", "google_earth")
TICK_M = 25                         # tick marks on the drawn transect in the KML


# ---------- (b) reference transects ----------
def usable(feature: dict) -> bool:
    """A transect with an extracted rate (>= 5 quarters with a position): the RMSE needs positions."""
    return feature["properties"].get("trend") != "too_few"


def sample_transects(transects: dict, n: int = N_TRANSECTS, seed: int = SEED) -> list[dict]:
    """n usable transects spread along the coast: usable transects in coast order (line, chainage)
    are cut into n equal runs and one is drawn at random from each. Only ids and geometry are kept,
    never the extracted statistics. Each gets extend_land_m / extend_sea_m for the drawing."""
    feats = sorted((f for f in transects["features"] if usable(f)),
                   key=lambda f: (f["properties"]["line"], f["properties"]["chainage_m"]))
    if len(feats) < n:
        raise ValueError(f"only {len(feats)} usable transects, need {n}")
    rng = random.Random(seed)
    out = []
    for k in range(n):
        lo, hi = len(feats) * k // n, len(feats) * (k + 1) // n
        f = feats[rng.randrange(lo, hi)]
        p = f["properties"]
        out.append({"transect_id": f["id"], "line": p["line"], "chainage_m": p["chainage_m"],
                    "geometry": f["geometry"],
                    "extend_land_m": round(rng.uniform(0, EXTEND_MAX_M)), "extend_sea_m": round(rng.uniform(0, EXTEND_MAX_M))})
    return out


def drawn_segment(ref: dict) -> tuple[tuple[float, float], tuple[float, float], float]:
    """The line the labeller sees: (start lon/lat, end lon/lat, length m), start at the landward end
    of the extended transect. Distances the labeller gives are metres from that start."""
    (lon_a, lat_a), (lon_b, lat_b) = ref["geometry"]["coordinates"]
    frame = LocalFrame(lon_a, lat_a)
    bx, by = frame.to_m(lon_b, lat_b)
    length = math.hypot(bx, by)
    ux, uy = bx / length, by / length
    el, es = ref["extend_land_m"], ref["extend_sea_m"]
    start = frame.to_lonlat(-ux * el, -uy * el)
    end = frame.to_lonlat(bx + ux * es, by + uy * es)
    return start, end, length + el + es


def drawn_to_baseline(ref: dict, s_m: float) -> float:
    """Distance along the drawn line -> position in the shoreline module's frame (metres from the
    baseline, seaward positive), comparable with positions.json."""
    return round(s_m - ref["extend_land_m"] - LAND_M, 1)


def hidden_transect_ids(transects: dict, refs: list[dict], neighbour_m: float = NEIGHBOUR_M) -> set[str]:
    """Reference transects and the transects within neighbour_m of one along the same baseline line."""
    keys = {(r["line"], r["chainage_m"]) for r in refs}
    out = set()
    for f in transects["features"]:
        p = f["properties"]
        if any(p["line"] == line and abs(p["chainage_m"] - c) <= neighbour_m + 1e-6 for line, c in keys):
            out.add(f["id"])
    return out


def ticks(ref: dict, step: float = TICK_M) -> list[tuple[float, float, float]]:
    """[(metres from the drawn start, lon, lat)] every `step` along the drawn (extended) transect."""
    (lon0, lat0), (lon1, lat1), length = drawn_segment(ref)
    return [(s, lon0 + (lon1 - lon0) * s / length, lat0 + (lat1 - lat0) * s / length)
            for s in [k * step for k in range(int(length // step) + 1)]]


def ge_kml(refs: list[dict], title: str) -> str:
    """Google Earth Pro KML: each reference transect as its drawn line (numbered as on the page), a short
    tick every TICK_M m and a label every 50 m (metres from the drawn line's landward start, which is not
    the baseline). Ids, the baseline and the extracted shorelines are left out (blind)."""
    marks = []
    for n, ref in enumerate(refs, 1):
        (lon0, lat0), (lon1, lat1), length = drawn_segment(ref)
        frame = LocalFrame(lon0, lat0)
        ex, ey = frame.to_m(lon1, lat1)
        px, py = -ey / length, ex / length                       # unit normal, for the ticks
        marks.append(f"<Placemark><name>{n}</name><Style><LineStyle><color>ff00ffff</color><width>2</width></LineStyle></Style>"
                     f"<LineString><coordinates>{lon0:.7f},{lat0:.7f},0 {lon1:.7f},{lat1:.7f},0</coordinates></LineString></Placemark>")
        segs, labels = [], []
        for s, lon, lat in ticks(ref):
            x, y = frame.to_m(lon, lat)
            half = 8 if s % 50 == 0 else 4
            a, b = frame.to_lonlat(x - px * half, y - py * half), frame.to_lonlat(x + px * half, y + py * half)
            segs.append(f"<LineString><coordinates>{a[0]:.7f},{a[1]:.7f},0 {b[0]:.7f},{b[1]:.7f},0</coordinates></LineString>")
            if s % 50 == 0:
                labels.append(f"<Placemark><name>{s:g}</name><styleUrl>#tick</styleUrl><Point><coordinates>{lon:.7f},{lat:.7f},0</coordinates></Point></Placemark>")
        marks.append(f"<Placemark><name>{n} ticks</name><Style><LineStyle><color>ff00ffff</color><width>1.5</width></LineStyle></Style>"
                     f"<MultiGeometry>{''.join(segs)}</MultiGeometry></Placemark>")
        marks.append(f"<Folder><name>{n} metres</name>{''.join(labels)}</Folder>")
    style = ('<Style id="tick"><IconStyle><scale>0</scale></IconStyle><LabelStyle><scale>0.7</scale>'
             '<color>ff00ffff</color></LabelStyle></Style>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{title}</name>{style}{''.join(marks)}</Document></kml>\n")


# ---------- (c) coastal cells ----------
def _origin_and_landward(feature: dict) -> tuple[LocalFrame, tuple[float, float], tuple[float, float]]:
    """Baseline point (metres, frame at the landward end) and the unit vector pointing inland."""
    (lon_a, lat_a), (lon_b, lat_b) = feature["geometry"]["coordinates"]
    frame = LocalFrame(lon_a, lat_a)
    bx, by = frame.to_m(lon_b, lat_b)
    length = math.hypot(bx, by)
    ux, uy = bx / length, by / length                # landward end -> seaward end
    o = (ux * LAND_M * length / (LAND_M + SEA_M), uy * LAND_M * length / (LAND_M + SEA_M))
    return frame, o, (-ux, -uy)


def cell_polygon(lon: float, lat: float, side: float = CELL_M) -> dict:
    frame = LocalFrame(lon, lat)
    h = side / 2
    ring = [frame.to_lonlat(x, y) for x, y in ((-h, -h), (h, -h), (h, h), (-h, h), (-h, -h))]
    return {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)] for x, y in ring]]}


def sample_cells(transects: dict, n: int = N_CELLS, seed: int = SEED, strips=STRIPS,
                 min_gap: float = CELL_MIN_GAP_M) -> list[dict]:
    """n cells, n / len(strips) per strip: a random transect, a random distance inside the strip
    landward of its baseline point, redrawn if within min_gap of an earlier cell. Any transect
    qualifies (usable or not): the cells test the built-up claims, not the shoreline. Cell ids are
    anonymous and shuffled; the strip is kept (it's a distance, not an output)."""
    rng = random.Random(seed + 1)
    feats = transects["features"]
    per = [n // len(strips) + (1 if i < n % len(strips) else 0) for i in range(len(strips))]
    picked: list[dict] = []
    for (lo, hi), k in zip(strips, per):
        tries = 0
        while sum(c["strip"] == f"{lo}-{hi}" for c in picked) < k:
            tries += 1
            if tries > 10_000:
                raise ValueError("can't place the cells: lower min_gap")
            f = feats[rng.randrange(len(feats))]
            frame, (ox, oy), (lx, ly) = _origin_and_landward(f)
            d = rng.uniform(lo + CELL_M / 2, hi - CELL_M / 2)
            lon, lat = frame.to_lonlat(ox + lx * d, oy + ly * d)
            if any(_dist_m(lon, lat, c["lon"], c["lat"]) < min_gap for c in picked):
                continue
            picked.append({"lon": round(lon, 7), "lat": round(lat, 7), "strip": f"{lo}-{hi}",
                           "landward_m": round(d, 1), "transect_id": f["id"]})
    rng.shuffle(picked)
    return [{"cell_id": f"c{i + 1:02d}", **c, "outline": cell_polygon(c["lon"], c["lat"])} for i, c in enumerate(picked)]


def _dist_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    x, y = LocalFrame(lon1, lat1).to_m(lon2, lat2)
    return math.hypot(x, y)


# ---------- label records ----------
def _check_month(v: Any) -> bool:
    return isinstance(v, str) and bool(_MONTH.match(v))


def validate_record(kind: str, rec: dict) -> list[str]:
    """Problems with one label record (empty = valid). Shared fields: protocol, labeler, labeled_at,
    confidence, notes, seconds_spent; the item id is site_id, transect_id or cell_id."""
    if kind not in KINDS:
        return [f"unknown kind {kind!r}"]
    errs = []
    if rec.get("protocol") != PROTOCOL:
        errs.append(f"protocol must be {PROTOCOL}")
    if not rec.get("labeler"):
        errs.append("labeler is required")
    if rec.get("confidence") not in CONFIDENCE:
        errs.append(f"confidence must be one of {CONFIDENCE}")
    if kind in ("classes", "change_month") and not rec.get("site_id"):
        errs.append("site_id is required")
    if kind == "classes":
        for f in ("class_before", "class_after"):
            if rec.get(f) not in CLASS_ANSWERS:
                errs.append(f"{f} must be one of {CLASS_ANSWERS}")
    elif kind == "shoreline":
        if not rec.get("transect_id"):
            errs.append("transect_id is required")
        if not _check_month(rec.get("month")):
            errs.append("month must be YYYY-MM")
        if rec.get("status") not in SHORE_STATUS:
            errs.append(f"status must be one of {SHORE_STATUS}")
        elif rec["status"] == "edge":
            if not isinstance(rec.get("drawn_m"), (int, float)) or not isinstance(rec.get("pos_m"), (int, float)):
                errs.append("an edge needs drawn_m and pos_m")
        elif rec.get("pos_m") is not None:
            errs.append("pos_m must be null unless status is edge")
        if rec.get("source", "planet") not in SOURCES:
            errs.append(f"source must be one of {SOURCES}")
        if rec.get("season") is not None and not (isinstance(rec["season"], str) and _SEASON.match(rec["season"])):
            errs.append("season must be like 2016-17")
    elif kind == "cells":
        if not rec.get("cell_id"):
            errs.append("cell_id is required")
        months = rec.get("months") or {}
        if sorted(months) != sorted(rec.get("dates", [])) or len(months) != 2:
            errs.append("months must give an answer for each of the 2 dates")
        for m, v in months.items():
            if not _check_month(m) or v not in CELL_ANSWERS:
                errs.append(f"months[{m!r}] must be one of {CELL_ANSWERS}")
    elif kind == "change_month":
        if rec.get("lasting_change") not in YES_NO:
            errs.append(f"lasting_change must be one of {YES_NO}")
        win = rec.get("change_window")
        if rec.get("lasting_change") == "yes":
            if not (isinstance(win, list) and len(win) == 2 and all(map(_check_month, win)) and win[0] < win[1]):
                errs.append("a lasting change needs change_window [last month before, first month after]")
        elif win is not None:
            errs.append("change_window must be null unless lasting_change is yes")
    return errs


def load_labels(path: Path, kind: str) -> list[dict]:
    """Read a .jsonl label file and raise on the first invalid record."""
    out = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        rec = json.loads(line)
        errs = validate_record(kind, rec)
        if errs:
            raise ValueError(f"{path}:{i}: {'; '.join(errs)}")
        out.append(rec)
    return out


def load_samples(path: Path) -> list[dict] | None:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
