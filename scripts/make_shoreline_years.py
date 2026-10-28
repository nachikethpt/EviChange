r"""Yearly shorelines for the map's time slider: one per dry season (Oct - Mar), 2015-16 to 2025-26,
on the Phase 11 transects (agents/shoreline.build_years()). Writes data/quangninh/shoreline/years.json
and years_lines.geojson.

    python scripts\make_shoreline_years.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import shoreline                 # noqa: E402
from agents.study import load_study_config   # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    transects = shoreline.load("transects.geojson")
    if transects is None:
        sys.exit("no transects: run scripts/make_shoreline.py first")
    t0 = time.time()
    result = shoreline.build_years(load_study_config()["aoi"], transects)
    out = shoreline.years_outputs(result, transects)
    print(f"{json.dumps(out)}; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
