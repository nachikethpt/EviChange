r"""Phase 14 results (D13, D14): extraction accuracy against the blind labels, and agreement between
the two labellers, from the labels14_*.jsonl files in data/quangninh/labels/phase14/.

    python scripts\phase14_report.py                       # every label set that is complete
    python scripts\phase14_report.py --second p3           # second labeller's files: labels14_<task>_p3.jsonl
    python scripts\phase14_report.py --cells-dw cells_dw.json --ccdc ccdc_months.json
    python scripts\phase14_report.py --out docs\phase14_results.md

Blindness: a label set is scored against the system's output only once it is COMPLETE (all 30 sites,
all 30 transects at both dates, all 30 cells), because a partial score would show the labeller the
classes or shorelines they have still to label. Incomplete sets are listed with what is missing.

System side:
  (a) classes      Dynamic World class_before / class_after of each detected site's region (regions file)
  (b) shoreline    extracted positions (data/quangninh/shoreline/positions.json), same metre frame
  (c) cells        --cells-dw: {cell_id: {"YYYY-MM": true/false}}, Dynamic World built per cell and date
                   (Earth Engine; skipped without the file)
  (d) change_month --ccdc: {site_id: ["last month before", "first month after"]} (D14; skipped without it)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import labels14 as l14                          # noqa: E402
from eval import metrics                                    # noqa: E402

REGIONS = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"
POSITIONS = ROOT / "data" / "quangninh" / "shoreline" / "positions.json"


def label_file(task: str, labeler: str | None = None, folder: Path = l14.LABELS_DIR) -> Path:
    """Same names as the Phase 14 notebook: labels14_<task>.jsonl for labeler1, else _<labeler>."""
    return folder / (f"labels14_{task}.jsonl" if not labeler or labeler == "labeler1" else f"labels14_{task}_{labeler}.jsonl")


def read(task: str, labeler: str | None = None, folder: Path = l14.LABELS_DIR) -> list[dict] | None:
    path = label_file(task, labeler, folder)
    return l14.load_labels(path, task) if path.exists() else None


# ---------- completeness ----------
def missing(task: str, labels: list[dict], sites: list[str], transects: list[str], cells: list[str]) -> list[str]:
    """Items still to label: site ids, "transect@month", or cell ids."""
    if task in ("classes", "change_month"):
        done = {r["site_id"] for r in labels}
        return [s for s in sites if s not in done]
    if task == "shoreline":
        done = {(r["transect_id"], r["month"]) for r in labels}
        months = sorted({r["month"] for r in labels}) or list(l14.REF_DATES)
        months = months if len(months) == 2 else list(l14.REF_DATES)
        return [f"{t}@{m}" for t in transects for m in months if (t, m) not in done]
    done = {r["cell_id"] for r in labels}
    return [c for c in cells if c not in done]


# ---------- labeller vs labeller ----------
def _last(labels: list[dict], key) -> dict:
    return {key(r): r for r in labels}           # a relabelled item: the later record wins


def agreement(task: str, a: list[dict], b: list[dict]) -> dict:
    """Inter-labeller agreement on the items both labelled, unsure answers left out (and counted)."""
    if task == "classes":
        ka, kb = _last(a, lambda r: r["site_id"]), _last(b, lambda r: r["site_id"])
        common = sorted(set(ka) & set(kb))
        out = {"n_common": len(common)}
        for name, pick in (("before", lambda r: r["class_before"]), ("after", lambda r: r["class_after"]),
                           ("transition", lambda r: (r["class_before"], r["class_after"]))):
            pairs = [(pick(ka[s]), pick(kb[s])) for s in common
                     if "unsure" not in (ka[s]["class_before"], ka[s]["class_after"], kb[s]["class_before"], kb[s]["class_after"])]
            out[name] = {"n": len(pairs), "kappa": metrics.cohen_kappa([x for x, _ in pairs], [y for _, y in pairs]),
                         "agreement": metrics.wilson(sum(x == y for x, y in pairs), len(pairs))}
        return out
    if task == "shoreline":
        key = lambda r: (r["transect_id"], r["month"])
        ka, kb = _last(a, key), _last(b, key)
        common = sorted(set(ka) & set(kb))
        status = [(ka[k]["status"], kb[k]["status"]) for k in common]
        diffs = [kb[k]["pos_m"] - ka[k]["pos_m"] for k in common if ka[k]["status"] == kb[k]["status"] == "edge"]
        return {"n_common": len(common),
                "status_kappa": metrics.cohen_kappa([x for x, _ in status], [y for _, y in status]),
                "n_both_edge": len(diffs),
                "rmse_m": math.sqrt(sum(d * d for d in diffs) / len(diffs)) if diffs else None,
                "mean_diff_m": sum(diffs) / len(diffs) if diffs else None}
    if task == "cells":
        ka, kb = _last(a, lambda r: r["cell_id"]), _last(b, lambda r: r["cell_id"])
        pairs = [(ka[c]["months"][m], kb[c]["months"].get(m)) for c in sorted(set(ka) & set(kb)) for m in ka[c]["months"]]
        sure = [(x, y) for x, y in pairs if "unsure" not in (x, y) and y is not None]
        return {"n_common": len(set(ka) & set(kb)), "n": len(sure), "kappa": metrics.cohen_kappa([x for x, _ in sure], [y for _, y in sure]),
                "agreement": metrics.wilson(sum(x == y for x, y in sure), len(sure))}
    ka, kb = _last(a, lambda r: r["site_id"]), _last(b, lambda r: r["site_id"])
    common = sorted(set(ka) & set(kb))
    sure = [(ka[s]["lasting_change"], kb[s]["lasting_change"]) for s in common
            if "unsure" not in (ka[s]["lasting_change"], kb[s]["lasting_change"])]
    windows = [(ka[s]["change_window"], kb[s]["change_window"]) for s in common
               if ka[s]["lasting_change"] == kb[s]["lasting_change"] == "yes"]
    return {"n_common": len(common), "lasting_change_kappa": metrics.cohen_kappa([x for x, _ in sure], [y for _, y in sure]),
            "windows": metrics.change_month_agreement(windows)}


# ---------- labels vs the system ----------
def accuracy(task: str, labels: list[dict], *, regions: dict, key: dict, positions: dict | None,
             cells_dw: dict | None, ccdc: dict | None) -> dict | str:
    """The extraction-accuracy metric for one complete label set, or why it can't be computed."""
    if task == "classes":
        return metrics.class_agreement(labels, regions, key)
    if task == "shoreline":
        if positions is None:
            return "no extracted shorelines (run scripts/make_shoreline.py)"
        return metrics.shoreline_rmse(metrics.shoreline_pairs(labels, positions))
    if task == "cells":
        if cells_dw is None:
            return "no Dynamic World built per cell: pass --cells-dw"
        pairs = [(ans, cells_dw[r["cell_id"]][m]) for r in labels for m, ans in r["months"].items()
                 if m in cells_dw.get(r["cell_id"], {})]
        return metrics.built_accuracy(pairs)
    if ccdc is None:
        return "no CCDC change months (D14): pass --ccdc"
    pairs = [(r["change_window"], ccdc[r["site_id"]]) for r in labels
             if r["lasting_change"] == "yes" and ccdc.get(r["site_id"])]
    return metrics.change_month_agreement(pairs)


def report(second: str | None = None, folder: Path = l14.LABELS_DIR, cells_dw: dict | None = None,
           ccdc: dict | None = None, regions_path: Path = REGIONS, positions_path: Path = POSITIONS) -> dict:
    labels_dir = ROOT / "data" / "quangninh" / "labels"
    key = json.loads((labels_dir / "sites_key.json").read_text(encoding="utf-8"))
    sites = sorted(key)
    transects = [t["transect_id"] for t in l14.load_samples(folder / l14.TRANSECTS_FILE.name) or []]
    cells = [c["cell_id"] for c in l14.load_samples(folder / l14.CELLS_FILE.name) or []]
    regions = ({f["properties"]["id"]: f["properties"] for f in json.loads(regions_path.read_text(encoding="utf-8"))["features"]}
               if regions_path.exists() else {})
    positions = json.loads(positions_path.read_text(encoding="utf-8")) if positions_path.exists() else None
    out: dict = {}
    for task in l14.KINDS:
        first = read(task, None, folder)
        entry: dict = {}
        if first is None:
            entry["status"] = f"no labels yet ({label_file(task, None, folder).name})"
        else:
            todo = missing(task, first, sites, transects, cells)
            entry["n_labels"] = len(first)
            if todo:
                entry["status"] = f"incomplete: {len(todo)} to go, not scored (blindness)"
                entry["missing"] = todo[:10] + (["..."] if len(todo) > 10 else [])
            else:
                entry["status"] = "complete"
                entry["accuracy"] = accuracy(task, first, regions=regions, key=key, positions=positions,
                                             cells_dw=cells_dw, ccdc=ccdc)
        if second and first is not None:
            other = read(task, second, folder)
            entry["agreement"] = agreement(task, first, other) if other else f"no labels from {second}"
        out[task] = entry
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--second", help="second labeller's name (labels14_<task>_<name>.jsonl)")
    ap.add_argument("--cells-dw", type=Path, help="JSON {cell_id: {YYYY-MM: built true/false}}")
    ap.add_argument("--ccdc", type=Path, help="JSON {site_id: [last month before, first month after]}")
    ap.add_argument("--out", type=Path, help="also write the report here")
    args = ap.parse_args(argv)
    load = lambda p: json.loads(p.read_text(encoding="utf-8")) if p else None
    rep = report(args.second, cells_dw=load(args.cells_dw), ccdc=load(args.ccdc))
    lines = ["# Phase 14 results", ""]
    for task, entry in rep.items():
        lines.append(f"## {task}")
        lines += [f"{k}: {metrics._fmt(v) if not isinstance(v, dict) else ''}" for k, v in entry.items() if not isinstance(v, dict)]
        for k, v in entry.items():
            if isinstance(v, dict):
                lines.append(f"{k}:")
                lines += [f"  {kk}: {metrics._fmt(vv) if not isinstance(vv, dict) else json.dumps(vv, default=str)}" for kk, vv in v.items()]
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
