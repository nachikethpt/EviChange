r"""Buildings near the shoreline for the study AOI over the monthly period (D11, Phase 12).

Reads Phase 10's data/quangninh/monthly/summary.json (months + Sentinel-1 thresholds) and Phase 11's
data/quangninh/shoreline/baseline.geojson, and writes data/quangninh/coastal/: summary.json (strip totals,
monthly + dry-season built area, season change, patch counts, Open Buildings reference), strips.geojson,
patches.geojson (new built patches) and sea.geojson (the Phase 11 sea polygons, cached).

    python scripts\make_coastal.py                   # needs an Earth Engine login (EE_PROJECT)
    python scripts\make_coastal.py --refresh-sea     # recompute the sea polygons instead of using the cache
    python scripts\make_coastal.py --skip-open-buildings
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import coastal, monthly, shoreline   # noqa: E402
from agents.study import load_study_config       # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh-sea", action="store_true", help="recompute the sea polygons (slow) instead of reading coastal/sea.geojson")
    ap.add_argument("--skip-open-buildings", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    study = load_study_config()
    summary = json.loads(monthly.SUMMARY_FILE.read_text(encoding="utf-8"))
    baseline = shoreline.load("baseline.geojson")
    if baseline is None:
        sys.exit("no baseline: run scripts/make_shoreline.py first")
    cached = None if args.refresh_sea else coastal.load("sea.geojson")
    sea = cached["features"] if cached else None
    print(f"monthly series {summary['period'][0]} - {summary['period'][1]}; baseline {len(baseline['features'])} lines; "
          f"sea polygons {'from cache' if sea else 'recomputed'}")
    result = coastal.build(study["aoi"], summary, baseline, sea, with_open_buildings=not args.skip_open_buildings)
    out = coastal.write_outputs(result)
    print(f"strips {out['strips']}; patches {out['patches']}; season change {out['season_change']}; "
          f"{time.time() - t0:.0f} s -> {coastal.COASTAL_DIR}")


if __name__ == "__main__":
    main()
