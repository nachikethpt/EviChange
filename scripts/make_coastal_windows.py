r"""Built area in the coastal strips between the detector's two windows, for the box evidence (D13, D16; Phase 15).

The box reports compare the detector windows (QN: Nov 2018 - Mar 2019 vs Nov 2022 - Mar 2023), so their
coastal-strip evidence is measured in those windows. Writes data/quangninh/coastal/windows_<before>_<after>.json
(agents/coastal.build_windows(): ~100 m strip cells with the built area before and after);
coastal.evidence_strips(box, ...) clips it to a box and returns the `coastal_strips[]` evidence.

    python scripts\make_coastal_windows.py                 # windows from the QN v3 regions' metadata
    python scripts\make_coastal_windows.py --before 2018-11-01 2019-03-31 --after 2022-11-01 2023-03-31

Needs scripts/make_coastal.py to have run first (it caches the sea polygons).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import coastal, shoreline        # noqa: E402
from agents.ee_engine import _ee             # noqa: E402
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
    baseline, sea = shoreline.load("baseline.geojson"), coastal.load("sea.geojson")
    if baseline is None or sea is None:
        sys.exit("no baseline / sea polygons: run scripts/make_shoreline.py and scripts/make_coastal.py first")
    t0 = time.time()
    aoi = load_study_config()["aoi"]
    ee = _ee()
    ee.data.setDeadline(600 * 1000)
    strip = coastal.strip_image(ee, baseline, sea["features"])
    result = coastal.build_windows(ee, aoi, strip, before, after)
    path = coastal.windows_file(before, after)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")
    print(f"{result['totals']}; {time.time() - t0:.0f} s -> {path}")


if __name__ == "__main__":
    main()
