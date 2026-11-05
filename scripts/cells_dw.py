r"""Dynamic World built per Phase 14 (c) coastal cell and labelled month: the system side of the cells score.

    python scripts\cells_dw.py                     # writes data/quangninh/labels/phase14/cells_dw.json
    python scripts\phase14_report.py --cells-dw data\quangninh\labels\phase14\cells_dw.json

A cell (30 m, 3 x 3 Dynamic World pixels) is built in a month when more than half of its observed area is
`built` in that month's per-pixel label mode (monthly.class_image), the rule the labellers used (D13 (c)).
A month with no Dynamic World look over the cell is left out (the score skips it). Runs only once the (c)
labels exist (blindness: the labeller must not see the system's answer first).

Needs `pip install -r requirements-ee.txt`, `earthengine authenticate` and EE_PROJECT.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import labels14 as l14, monthly            # noqa: E402

OUT = l14.LABELS_DIR / "cells_dw.json"
BUILT = 6                                               # Dynamic World V1 label of `built`
SCALE_M = 10


def month_range(month: str) -> tuple[str, str]:
    y, m = map(int, month.split("-"))
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01", f"{y2:04d}-{m2:02d}-01"


def is_built(share: float | None) -> bool | None:
    """More than half the observed cell is built; None when nothing was observed."""
    return None if share is None else share > 0.5


def label_months(folder: Path = l14.LABELS_DIR) -> list[str]:
    path = folder / "labels14_cells.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} is missing: the (c) labels must exist before the system's answer is computed")
    return sorted({m for r in l14.load_labels(path, "cells") for m in r["months"]})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    import ee
    ee.Initialize(project=os.environ.get("EE_PROJECT", "space-510615"))
    cells = json.loads(l14.CELLS_FILE.read_text(encoding="utf-8"))
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry(c["outline"]), {"cell_id": c["cell_id"]}) for c in cells])
    aoi = fc.geometry().bounds().getInfo()
    out: dict[str, dict[str, bool]] = {c["cell_id"]: {} for c in cells}
    for month in label_months():
        start, end = month_range(month)
        built = monthly.class_image(ee, aoi, start, end).eq(BUILT).rename("built")
        got = built.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=SCALE_M).getInfo()
        for f in got["features"]:
            b = is_built(f["properties"].get("mean"))
            if b is not None:
                out[f["properties"]["cell_id"]][month] = b
        print(f"{month}: {sum(month in v for v in out.values())} cells observed, "
              f"{sum(v.get(month) is True for v in out.values())} built")
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
