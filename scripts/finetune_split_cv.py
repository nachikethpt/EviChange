r"""Cross-validation of the split design (4b, exploratory, 2026-11-10; docs/analysis_plan.md section 10).

The split design takes the main cover from a fine-tune and the change verdict from the untrained model with
Dynamic World evidence. It was noticed on the held-out boxes, so it is checked here on the training-box folds:
the fine-tune's fold predictions (part B2 / C2 of notebooks/EviChange_finetune_experiments.ipynb) against the
untrained model's answers on the same boxes (part C2, `eval --base-only --split train`).

    python scripts/finetune_split_cv.py --data data/finetune --change exp_C2/predictions_cover_base_dw_train.jsonl \
        --cover exp_B2/cv_dw_w3_fold0__predictions_fold.jsonl exp_B2/cv_dw_w3_fold1__predictions_fold.jsonl \
                exp_B2/cv_dw_w3_fold2__predictions_fold.jsonl [--folds 3] [--out split_cv.json]

Prints, per fold and as the mean of the folds, the fine-tune alone, the untrained model alone and the split design.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finetune_train as ft  # noqa: E402


def read_preds(paths: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r["text"]
    return out


def _brief(s: dict) -> dict:
    d = s["derived_change"]
    return {"main_cover": s["main_cover_accuracy"], "change_balanced": d["balanced"],
            "on_change": d["on_change"], "on_no_change": d["on_no_change"], "parse_failures": s["parse_failures"]}


def split_cv(examples: list[dict], cover: dict[str, str], change: dict[str, str], folds: int = 3) -> dict:
    """Per fold (the folds of `ft.split_folds`, as the cross-validation runs): the fine-tune alone, the untrained
    model alone, the split design; then the mean of each over the folds."""
    rows = []
    for k, ids in enumerate(ft.split_folds(examples, folds)):
        ids = set(ids)
        fold = [e for e in examples if e["id"] in ids]
        missing = [e["id"] for e in fold if e["id"] not in cover or e["id"] not in change]
        if missing:
            raise SystemExit(f"fold {k}: no prediction for {len(missing)} boxes (e.g. {missing[:3]})")
        rows.append({"fold": k, "n": len(fold), "n_change": sum(map(ft.is_change, fold)),
                     "finetune": _brief(ft.score("cover", fold, cover)),
                     "untrained": _brief(ft.score("cover", fold, change)),
                     "split": _brief(ft.split_scores(fold, cover, change))})
    mean = {m: {key: sum(r[m][key] for r in rows) / len(rows) for key in ("main_cover", "change_balanced")}
            for m in ("finetune", "untrained", "split")}
    return {"folds": rows, "mean": mean}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="folder with cover_dw_train.jsonl")
    ap.add_argument("--cover", type=Path, nargs="+", required=True, help="the fine-tune's fold predictions")
    ap.add_argument("--change", type=Path, nargs="+", required=True, help="the untrained model's train-box answers")
    ap.add_argument("--variant", default="dw")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    res = split_cv(ft.load_examples(a.data, "cover", "train", a.variant), read_preds(a.cover), read_preds(a.change), a.folds)
    for r in res["folds"]:
        print(f"fold {r['fold']} ({r['n']} boxes, {r['n_change']} change): " + "; ".join(
            f"{m} cover {r[m]['main_cover']:.3f} change {r[m]['change_balanced']:.3f}" for m in ("finetune", "untrained", "split")))
    print("mean: " + "; ".join(f"{m} cover {v['main_cover']:.3f} change {v['change_balanced']:.3f}" for m, v in res["mean"].items()))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
