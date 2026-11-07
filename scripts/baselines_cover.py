r"""Non-VLM baselines for the 4b main-cover task (2026-11-07): the same 80 held-out boxes, the same targets.

    python scripts\baselines_cover.py            # Earth Engine + scikit-learn; writes data/finetune/baselines/

1. Dynamic World: the box's main cover at each date = the most common Dynamic World label inside the box, from the
   per-pixel label mode over the date's window (as D10), mapped to the six covers (DW_TO_COVER). No training.
2. Random forest: per box and date, the mean and standard deviation inside the box of the Sentinel-2 composite's
   bands (B2 B3 B4 B8 B11, the detector's composite) and of NDVI, NDBI, MNDWI: 16 numbers. Trained on the 327
   training boxes (both dates: 654 samples), class-balanced, seed 17; predicts the 80 held-out boxes.

Each writes predictions_cover_<name>.jsonl in the format finetune_train.py writes (one JSON answer per box), so
both are scored by the same finetune_train.score() as the VLMs. Needs requirements-ee.txt, scikit-learn, and an
Earth Engine login. Built after run 1's results were known; neither baseline was tuned on the held-out boxes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agents import cover_check                          # noqa: E402

DATA = ROOT / "data" / "finetune"
OUT = DATA / "baselines"
SEED = 17
DW_NAMES = ("water", "trees", "grass", "flooded_vegetation", "crops", "shrub_and_scrub", "built", "bare", "snow_and_ice")
DW_TO_COVER = {"water": "water", "trees": "dense_vegetation", "flooded_vegetation": "dense_vegetation",
               "grass": "sparse_vegetation", "shrub_and_scrub": "sparse_vegetation", "crops": "crops",
               "built": "built", "bare": "bare", "snow_and_ice": None}
BANDS = ("B2", "B3", "B4", "B8", "B11", "NDVI", "NDBI", "MNDWI")
FEATURES = tuple(f"{b}_{s}" for b in BANDS for s in ("mean", "stdDev"))


def dw_main(histogram: dict | None) -> str:
    """Main cover from a {DW label index: pixel count} histogram inside a box; cant_tell without pixels."""
    counts = Counter()
    for k, n in (histogram or {}).items():
        cover = DW_TO_COVER.get(DW_NAMES[int(float(k))])
        if cover:
            counts[cover] += n
    return counts.most_common(1)[0][0] if counts else cover_check.CANT_TELL


def dw_shares(histogram: dict | None) -> dict[str, float]:
    """{cover: share of the box's Dynamic World pixels} from a {label index: pixel count} histogram."""
    counts = Counter()
    for k, n in (histogram or {}).items():
        cover = DW_TO_COVER.get(DW_NAMES[int(float(k))])
        if cover:
            counts[cover] += n
    total = sum(counts.values())
    return {c: round(n / total, 3) for c, n in counts.items()} if total else {}


def feature_vector(props: dict, prefix: str) -> list[float] | None:
    """The 16 box statistics of one date (properties named <prefix><band>_<stat>), or None if any is missing."""
    vals = [props.get(prefix + f) for f in FEATURES]
    return None if any(v is None for v in vals) else [float(v) for v in vals]


def answer_text(before: str, after: str) -> str:
    return json.dumps({"before": before, "after": after})


def load_split(split: str, data: Path = DATA) -> dict[str, dict]:
    return {r["id"]: json.loads(r["target"]) for r in map(json.loads, open(data / f"cover_{split}.jsonl", encoding="utf-8"))}


def _box_stats(ee, boxes: list[dict], params: dict) -> dict[str, dict]:
    """{box id: properties} with DW histograms (dw_before / dw_after) and the 16 statistics per date (b_ / a_)."""
    from agents.ee_engine import _composite, _indices
    from agents.landcover import dw_window
    aoi = params["aoi"]
    images = []
    for prefix, key in (("b_", "before_window"), ("a_", "after_window")):
        comp, _ = _composite(ee, aoi, params[key], params["max_cloud_pct"])
        stack = comp.addBands(_indices(ee, comp)).select(list(BANDS))
        images.append(stack.rename([prefix + b for b in BANDS]))
        dw = dw_window(ee, aoi, params[key])
        if dw is not None:
            images.append(dw.select("label").rename("dw_" + key.split("_")[0]))
    img = ee.Image.cat(images)
    stats_bands = [p + b for p in ("b_", "a_") for b in BANDS]
    reducer = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)
    out: dict[str, dict] = {}
    for i in range(0, len(boxes), 100):
        chunk = boxes[i: i + 100]
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Rectangle(list(b["box"])), {"id": b["id"]}) for b in chunk])
        num = img.select(stats_bands).reduceRegions(collection=fc, reducer=reducer, scale=10, tileScale=4).getInfo()
        dw_bands = [n for n in ("dw_before", "dw_after") if n in img.bandNames().getInfo()]
        hist = img.select(dw_bands).reduceRegions(collection=fc, reducer=ee.Reducer.frequencyHistogram(), scale=10,
                                                  tileScale=4).getInfo() if dw_bands else {"features": []}
        for f in num["features"]:
            out[f["properties"]["id"]] = dict(f["properties"])
        for f in hist["features"]:
            p = f["properties"]
            for n in dw_bands:
                out[p["id"]][n] = p.get(n) if len(dw_bands) > 1 else p.get("histogram")
        print(f"  {min(i + 100, len(boxes))} / {len(boxes)} boxes", flush=True)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA, help="folder with cover_train.jsonl / cover_holdout.jsonl")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    import finetune_build
    import finetune_train as ft
    import vlm_batch
    from agents.ee_engine import _ee
    from sklearn.ensemble import RandomForestClassifier

    train_t, hold_t = load_split("train", args.data), load_split("holdout", args.data)
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    params = vlm_batch.analysis_params(fc)
    boxes = [b for b in finetune_build._boxes(fc) if b["id"] in train_t or b["id"] in hold_t]
    print(f"{len(boxes)} boxes ({len(train_t)} train, {len(hold_t)} held out)")
    stats = _box_stats(_ee(), boxes, params)
    args.out.mkdir(parents=True, exist_ok=True)
    shares = {b["id"]: {"before": dw_shares(stats.get(b["id"], {}).get("dw_before")),
                        "after": dw_shares(stats.get(b["id"], {}).get("dw_after"))} for b in boxes}
    (args.out / "dw_boxes.json").write_text(json.dumps(shares, indent=1), encoding="utf-8")

    preds = {"dynamic_world": {i: answer_text(dw_main(stats[i].get("dw_before")), dw_main(stats[i].get("dw_after")))
                               for i in hold_t}}
    X, y = [], []
    for i, t in train_t.items():
        for prefix, when in (("b_", "before"), ("a_", "after")):
            v = feature_vector(stats.get(i, {}), prefix)
            if v is not None and t.get(when) in cover_check.COVERS:
                X.append(v); y.append(t[when])
    rf = RandomForestClassifier(n_estimators=500, class_weight="balanced", random_state=SEED, n_jobs=-1).fit(X, y)
    print(f"random forest: {len(X)} training samples, classes {dict(Counter(y))}")
    rf_pred = {}
    for i in hold_t:
        got = []
        for prefix in ("b_", "a_"):
            v = feature_vector(stats.get(i, {}), prefix)
            got.append(rf.predict([v])[0] if v is not None else cover_check.CANT_TELL)
        rf_pred[i] = answer_text(*got)
    preds["random_forest"] = rf_pred

    examples = [json.loads(l) for l in open(args.data / "cover_holdout.jsonl", encoding="utf-8")]
    summary = {}
    for name, p in preds.items():
        (args.out / f"predictions_cover_{name}.jsonl").write_text(
            "".join(json.dumps({"id": k, "text": v}) + "\n" for k, v in p.items()), encoding="utf-8")
        summary[name] = ft.score("cover", examples, p)
        print(name, json.dumps(summary[name]))
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
