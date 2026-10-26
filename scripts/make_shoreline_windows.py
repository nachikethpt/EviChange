r"""Shoreline change between the detector's two windows, for the box evidence (D13, D16; Phase 15).

The box reports compare the detector windows (QN: Nov 2018 - Mar 2019 vs Nov 2022 - Mar 2023), so
their shoreline evidence is measured in those windows, on the Phase 11 transects. Writes
data/quangninh/shoreline/windows_<before>_<after>.json (agents/shoreline.build_windows()).

    python scripts\make_shoreline_windows.py                 # windows from the QN v3 regions' metadata
    python scripts\make_shoreline_windows.py --before 2018-11-01 2019-03-31 --after 2022-11-01 2023-03-31
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import shoreline                 # noqa: E402
from agents.study import load_study_config   # noqa: E402

REGIONS = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", nargs=2, metavar=("START", "END"))
    ap.add_argument("--after", nargs=2, metavar=("START", "END"))
    args = ap.parse_args()
    if args.before and args.after:
        before, after = args.before, args.after
    else:
        meta = json.loads(REGIONS.read_text(encoding="utf-8"))["metadata"]
        before, after = meta["before_window"], meta["after_window"]
    transects = shoreline.load("transects.geojson")
    if transects is None:
        sys.exit("no transects: run scripts/make_shoreline.py first")
    t0 = time.time()
    result = shoreline.build_windows(load_study_config()["aoi"], transects, before, after)
    path = shoreline.windows_file(before, after)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{result['status_counts']} over {result['years']} years; {time.time() - t0:.0f} s -> {path}")


if __name__ == "__main__":
    main()
