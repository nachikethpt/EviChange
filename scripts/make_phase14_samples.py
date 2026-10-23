r"""Draw the Phase 14 samples (D13): 30 reference transects and 30 coastal cells.

Reads the Phase 11 transects (data/quangninh/shoreline/transects.geojson) and writes
data/quangninh/labels/phase14/reference_transects.json and coastal_cells.json. No Earth Engine.
The draw is seeded (labels14.SEED), so rerunning gives the same samples; it refuses to overwrite
existing files unless --force, because labels refer to these ids.

    .venv312\Scripts\python scripts\make_phase14_samples.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import labels14, shoreline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="overwrite existing sample files")
    args = ap.parse_args()

    transects = shoreline.load("transects.geojson")
    if transects is None:
        sys.exit("no transects: run scripts/make_shoreline.py first")
    files = (labels14.TRANSECTS_FILE, labels14.CELLS_FILE)
    if not args.force and any(f.exists() for f in files):
        sys.exit("sample files exist (labels refer to their ids); pass --force to redraw")

    refs = labels14.sample_transects(transects)
    cells = labels14.sample_cells(transects)
    labels14.LABELS_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in zip(files, (refs, cells)):
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    hidden = labels14.hidden_transect_ids(transects, refs)
    strips = {s: sum(c["strip"] == s for c in cells) for s in sorted({c["strip"] for c in cells})}
    print(f"{len(refs)} reference transects ({len(hidden)} transects hidden in the app with their neighbours)")
    print(f"{len(cells)} coastal cells: {strips}")
    print(f"written to {labels14.LABELS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
