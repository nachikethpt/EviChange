r"""Geo-VLM model / image-set comparison on development regions (Phase 4, D15).

Checks a fixed sample of QN change regions OUTSIDE the 30 labelled sites with whichever model the
Colab server (notebooks/EviChange_vlm_server.ipynb) has loaded, under each image set, and appends
every answer to the answer log (data/vlm_checks.jsonl). scripts/vlm_compare.py then compares.

    # once: draw the sample (data/quangninh/vlm_dev_sample.json, committed so every model sees it)
    python scripts\vlm_batch.py --draw
    # render every chip once with Earth Engine (~30 min, no GPU needed):
    python scripts\vlm_batch.py --render-only
    # with the server on Qwen2.5-VL-7B (VLM_URL / VLM_TOKEN set as the notebook prints):
    python scripts\vlm_batch.py
    # restart the notebook with MODEL = 'qwen3-8b', set the new VLM_URL / VLM_TOKEN, run again:
    python scripts\vlm_batch.py
    python scripts\vlm_compare.py --dev --out docs\vlm_compare_d15.md

Resumable: a check already in the log (same analysis, region, prompt version and model) is skipped,
so after a Colab disconnect just reconnect and rerun. Chips are rendered once per region and cached
in data/vlm_chips/ (not committed), so every model and image set sees the same PNGs.
Needs an Earth Engine login for the first render of each region.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import vlm_check                          # noqa: E402
from agents.schema import region_change_types         # noqa: E402

REGIONS = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"
SAMPLE = ROOT / "data" / "quangninh" / "vlm_dev_sample.json"
CHIP_DIR = ROOT / "data" / "vlm_chips"
SAMPLE_SIZE, SEED = 60, 15
SERVER_TRIES, RETRY_WAIT_S = 4, 15     # a dropped tunnel connection is retried before giving up


# ---------- regions ----------
def bbox(geometry: dict) -> tuple[float, float, float, float]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def analysis_params(fc: dict) -> dict:
    """Same fields as webapp/backend/data_store.analysis_params, so batch and app share check keys."""
    meta = fc.get("metadata") or {}
    return {"aoi": meta["aoi"], "before_window": meta["before_window"], "after_window": meta["after_window"],
            "max_cloud_pct": float((meta.get("thresholds") or {}).get("max_cloud_pct", 30.0))}


def dw_changed(region: dict) -> bool | None:
    """Dynamic World class changed between the windows (D10); None when either class is unknown."""
    before, after = region.get("class_before"), region.get("class_after")
    return None if not before or not after else before != after


def stratum(region: dict) -> tuple[bool, str]:
    """(Dynamic World changed?, the detector's first change type or 'none')."""
    return bool(dw_changed(region)), (region_change_types(region) or ["none"])[0]


def draw_sample(features: list[dict], n: int = SAMPLE_SIZE, seed: int = SEED) -> list[str]:
    """n region ids outside the labelled sites: half where Dynamic World's class changes, half where it
    doesn't (or all there are), each half spread round-robin over the detector's change types so rare
    types are in. Deterministic for a given seed and regions file."""
    rng = random.Random(seed)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for f in features:
        props = f["properties"]
        if vlm_check.touches_labelled_site(bbox(f["geometry"])) or dw_changed(props) is None:
            continue
        groups[stratum(props)].append(props["id"])
    for ids in groups.values():
        rng.shuffle(ids)
    picked: list[str] = []
    for changed in (True, False):
        quota = n // 2 if changed else n - len(picked)
        types = sorted(t for c, t in groups if c == changed)
        pools = {t: list(groups[(changed, t)]) for t in types}
        taken = 0
        while taken < quota and any(pools.values()):
            for t in types:
                if pools[t] and taken < quota:
                    picked.append(pools[t].pop())
                    taken += 1
    return picked


# ---------- negative controls ----------
CONTROLS = ROOT / "data" / "quangninh" / "vlm_dev_controls.json"
N_CONTROLS, NEAR_M, MAX_WATER = 20, 200, 0.5
M_PER_DEG = 111_320


def _expand(box: tuple, metres: float) -> tuple:
    import math
    dx = metres / (M_PER_DEG * math.cos(math.radians((box[1] + box[3]) / 2)))
    dy = metres / M_PER_DEG
    return box[0] - dx, box[1] - dy, box[2] + dx, box[3] + dy


def _overlaps(a: tuple, b: tuple) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def control_candidates(features: list[dict], aoi_box: tuple, sizes: list[tuple[float, float]], n: int, seed: int = SEED) -> list[tuple]:
    """Up to n boxes inside the AOI with no detected region within NEAR_M of them and no labelled site:
    the detector saw no change there. Each box copies the width / height of a sampled region, so controls
    look like the detections in size. Deterministic for a seed."""
    rng = random.Random(seed)
    region_boxes = [_expand(bbox(f["geometry"]), NEAR_M) for f in features]
    out, tries = [], 0
    while len(out) < n and tries < 200 * n:
        tries += 1
        w, h = sizes[rng.randrange(len(sizes))]
        x = rng.uniform(aoi_box[0], aoi_box[2] - w)
        y = rng.uniform(aoi_box[1], aoi_box[3] - h)
        box = (x, y, x + w, y + h)
        if any(_overlaps(box, r) for r in region_boxes) or vlm_check.touches_labelled_site(box):
            continue
        if any(_overlaps(box, o) for o in out):
            continue
        out.append(box)
    return out


def water_share(aoi: dict, window: list[str], boxes: list[tuple]) -> list[float]:
    """Dynamic World water probability over each box in one window (one Earth Engine request)."""
    from agents.ee_engine import _ee, _inclusive_end
    from agents.landcover import DW_COLLECTION
    ee = _ee()
    img = (ee.ImageCollection(DW_COLLECTION).filterBounds(ee.Geometry(aoi))
           .filterDate(window[0], _inclusive_end(window)).select("water").mean())
    col = ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle(list(b)), {"i": i}) for i, b in enumerate(boxes)])
    feats = img.reduceRegions(collection=col, reducer=ee.Reducer.mean(), scale=10).getInfo()["features"]
    by_i = {f["properties"]["i"]: f["properties"].get("mean") for f in feats}
    return [by_i.get(i) if by_i.get(i) is not None else 1.0 for i in range(len(boxes))]


def control_feature(cid: str, box: tuple) -> dict:
    """A box as a pseudo-region: index deltas 0 (the detector saw nothing), so vlm_check works unchanged."""
    w, s, e, n = box
    ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"id": cid, "control": True, "area_ha": 0.0, "mean_conf": 0.0, "dNDVI": 0.0, "dNDBI": 0.0,
                           "dMNDWI": 0.0, "location": "centre"}}


def draw_controls(fc: dict, sample_ids: list[str], n: int = N_CONTROLS, seed: int = SEED, water=water_share) -> list[dict]:
    """n land control boxes (mostly not water in both windows, Dynamic World), sized like the sample."""
    params = analysis_params(fc)
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    sizes = [(b[2] - b[0], b[3] - b[1]) for b in (bbox(by_id[i]["geometry"]) for i in sample_ids)]
    pts = params["aoi"]["coordinates"][0]
    aoi_box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    cands = control_candidates(fc["features"], aoi_box, sizes, 6 * n, seed)
    before, after = water(params["aoi"], params["before_window"], cands), water(params["aoi"], params["after_window"], cands)
    land = [b for b, wb, wa in zip(cands, before, after) if wb < MAX_WATER and wa < MAX_WATER]
    return [control_feature(f"c{i}", b) for i, b in enumerate(land[:n], 1)]


# ---------- chips ----------
def chip_dir(params: dict, box: tuple) -> Path:
    key = hashlib.sha256(json.dumps([params, [round(v, 6) for v in box]], sort_keys=True).encode()).hexdigest()[:16]
    return CHIP_DIR / key


def chips_for(params: dict, box: tuple, kinds: tuple[str, ...], render=None) -> dict[str, bytes]:
    """before_<kind> / after_<kind> PNGs, from the cache or rendered once (all kinds needed later too)."""
    folder = chip_dir(params, box)
    want = [f"{when}_{k}" for k in kinds for when in ("before", "after")]
    if not all((folder / f"{name}.png").exists() for name in want):
        if render is None:
            from agents.ee_engine import region_chips as render
        all_kinds = tuple(dict.fromkeys(k for s in vlm_check.CHIP_SETS.values() for k in s))
        chips = render(params["aoi"], params["before_window"], params["after_window"], params["max_cloud_pct"],
                       box, kinds=all_kinds)
        folder.mkdir(parents=True, exist_ok=True)
        for name, png in chips.items():
            (folder / f"{name}.png").write_bytes(png)
    return {name: (folder / f"{name}.png").read_bytes() for name in want}


# ---------- run ----------
def run(vlm, fc: dict, ids: list[str], chip_sets: list[str], log_path: Path | None = None, render=None, log=print,
        sleep=time.sleep) -> dict:
    """Check every sampled region under every chip set with the server's current model; skip checks
    already logged. Returns counts {'done', 'skipped', 'failed'}."""
    status = vlm.status()
    if not status["available"]:
        raise SystemExit(f"Geo-VLM not available: {status['detail']}")
    model = status["model"]
    params = analysis_params(fc)
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    logged = {r["key"] for r in vlm_check.read_log(log_path)}
    counts = {"done": 0, "skipped": 0, "failed": 0}
    total = len(ids) * len(chip_sets)
    log(f"model {model}: {len(ids)} regions x {len(chip_sets)} image sets = {total} checks")
    n = 0
    for chip_set in chip_sets:
        version = vlm_check.prompt_version(chip_set)
        for rid in ids:
            n += 1
            feature = by_id[rid]
            box = bbox(feature["geometry"])
            if vlm_check.touches_labelled_site(box):          # the sample never has these; belt and braces
                raise SystemExit(f"{rid} overlaps a labelled site: the sample file is wrong")
            if vlm_check.check_key(params, rid, version, model) in logged:
                counts["skipped"] += 1
                continue
            from agents.vlm_client import VLMUnavailable
            for attempt in range(1, SERVER_TRIES + 1):
                t0 = time.time()
                try:
                    chips = chips_for(params, box, vlm_check.chip_kinds(chip_set), render)
                    _, record = vlm_check.check(vlm, params, feature["properties"], box, chip_set, chips, t0=t0)
                    break
                except VLMUnavailable as exc:      # the tunnel drops single connections now and then
                    if attempt == SERVER_TRIES:
                        raise SystemExit(f"server stopped answering ({exc}); reconnect and rerun to resume")
                    log(f"[{n}/{total}] {rid} {chip_set}: server did not answer, retrying in {RETRY_WAIT_S * attempt} s")
                    sleep(RETRY_WAIT_S * attempt)
                except Exception as exc:
                    record = None
                    counts["failed"] += 1
                    log(f"[{n}/{total}] {rid} {chip_set}: FAILED {str(exc)[:150]}")
                    break
            if record is None:
                continue
            vlm_check.log_check(record, log_path)
            counts["done"] += 1
            log(f"[{n}/{total}] {rid} {chip_set}: {record['verdict']} ({record['agreement']}) {record['seconds']} s")
    return counts


def with_controls(fc: dict) -> tuple[dict, list[str]]:
    """The regions file with the control boxes added as features, and the control ids ([] before drawn)."""
    if not CONTROLS.exists():
        return fc, []
    controls = json.loads(CONTROLS.read_text(encoding="utf-8"))["features"]
    return {**fc, "features": fc["features"] + controls}, [f["properties"]["id"] for f in controls]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draw", action="store_true", help=f"draw the sample into {SAMPLE.name} (refuses to redraw)")
    ap.add_argument("--draw-controls", action="store_true",
                    help=f"draw the negative-control boxes into {CONTROLS.name} (Earth Engine; refuses to redraw)")
    ap.add_argument("--chips", default=",".join(vlm_check.CHIP_SETS), help="image sets, comma-separated")
    ap.add_argument("--limit", type=int, help="only the first N sampled regions (a quick test)")
    ap.add_argument("--controls-only", action="store_true", help="check only the control boxes")
    ap.add_argument("--render-only", action="store_true",
                    help="only render and cache the chips (Earth Engine, no model server): do this before paying for GPU time")
    args = ap.parse_args(argv)
    fc = json.loads(REGIONS.read_text(encoding="utf-8"))
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if args.draw:
        if SAMPLE.exists():
            raise SystemExit(f"{SAMPLE} exists: the sample is fixed once drawn, so every model sees the same regions")
        ids = draw_sample(fc["features"])
        SAMPLE.write_text(json.dumps({
            "regions_file": REGIONS.relative_to(ROOT).as_posix(), "drawn": date.today().isoformat(), "seed": SEED,
            "rule": "outside the labelled sites; half Dynamic World class change, half not; round-robin over the "
                    "detector's first change type (scripts/vlm_batch.py draw_sample)",
            "ids": ids}, indent=1), encoding="utf-8")
        print(f"{len(ids)} regions -> {SAMPLE}")
        return
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    if args.draw_controls:
        if CONTROLS.exists():
            raise SystemExit(f"{CONTROLS} exists: the controls are fixed once drawn")
        feats = draw_controls(fc, sample["ids"])
        CONTROLS.write_text(json.dumps({"type": "FeatureCollection", "metadata": {
            "regions_file": REGIONS.relative_to(ROOT).as_posix(), "drawn": date.today().isoformat(), "seed": SEED,
            "rule": f"boxes sized like the sample regions, inside the AOI, no detected region within {NEAR_M} m, "
                    f"no labelled site, Dynamic World water < {MAX_WATER} in both windows (scripts/vlm_batch.py draw_controls)"},
            "features": feats}, indent=1), encoding="utf-8")
        print(f"{len(feats)} control boxes -> {CONTROLS}")
        return
    fc, control_ids = with_controls(fc)
    ids = control_ids if args.controls_only else sample["ids"][:args.limit] + control_ids
    if args.render_only:
        params, by_id = analysis_params(fc), {f["properties"]["id"]: f for f in fc["features"]}
        all_kinds = tuple(dict.fromkeys(k for s in vlm_check.CHIP_SETS.values() for k in s))
        for n, rid in enumerate(ids, 1):
            t0 = time.time()
            try:
                chips_for(params, bbox(by_id[rid]["geometry"]), all_kinds)
                print(f"[{n}/{len(ids)}] {rid} {time.time() - t0:.0f} s")
            except Exception as exc:
                print(f"[{n}/{len(ids)}] {rid} FAILED {str(exc)[:150]}")
        return
    chip_sets = [c.strip() for c in args.chips.split(",") if c.strip()]
    for c in chip_sets:
        vlm_check.chip_kinds(c)
    from agents.vlm_client import VLMClient
    counts = run(VLMClient(), fc, ids, chip_sets)
    print(f"done {counts['done']}, already logged {counts['skipped']}, failed {counts['failed']}")


if __name__ == "__main__":
    main()
