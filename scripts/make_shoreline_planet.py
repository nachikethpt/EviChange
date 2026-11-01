r"""Planet 3 m shorelines on the Phase 11 transects (agents/shoreline.build_planet(), D12 Phase 13c): one
position per transect and Planet month, compared with the monthly radar shorelines and the 2024-25 yearly
shoreline. Writes data/quangninh/shoreline/planet.json and planet_lines.geojson.

    python scripts\make_shoreline_planet.py          # needs an Earth Engine login with read access to the Planet collection
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import shoreline                 # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    transects = shoreline.load("transects.geojson")
    if transects is None:
        sys.exit("no transects: run scripts/make_shoreline.py first")
    t0 = time.time()
    result = shoreline.build_planet(transects)
    out = shoreline.planet_outputs(result, transects)
    print(f"{json.dumps(out)}; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
