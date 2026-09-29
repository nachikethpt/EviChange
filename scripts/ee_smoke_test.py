"""Earth Engine smoke test: proves auth, Cloud project, and Sentinel-2 access work from
this machine, weeks before Phases 5-6 (real ingestion) depend on them.

One-time setup:
  1. Register a Cloud project for noncommercial Earth Engine use:
     https://code.earthengine.google.com/register  (note the project id)
  2. pip install -r requirements-ee.txt
  3. earthengine authenticate          (opens a browser, saves credentials locally)

Then, from the repo root:
  python scripts/ee_smoke_test.py --project YOUR_PROJECT_ID
  (or set EE_PROJECT=YOUR_PROJECT_ID once and omit --project)

Exit code 0 = ready for Phase 5.
"""
import argparse
import json
import os
import sys
from pathlib import Path

S2 = "COPERNICUS/S2_SR_HARMONIZED"
STUDY_PATH = Path(__file__).parents[1] / "data" / "quangninh" / "study.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("EE_PROJECT"), help="Earth Engine Cloud project id")
    ap.add_argument("--max-cloud", type=float, default=30)
    ap.add_argument("--study", type=Path, default=STUDY_PATH, help="study.json path")
    args = ap.parse_args()
    if not args.project:
        print("No project id. Pass --project YOUR_PROJECT_ID or set EE_PROJECT (see this file's docstring).")
        return 2

    try:
        import ee
    except ImportError:
        print("earthengine-api is not installed: pip install -r requirements-ee.txt")
        return 2
    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # auth and project errors both surface here
        print(f"Earth Engine init FAILED for project '{args.project}': {exc}")
        print("Run `earthengine authenticate`, and check the project is registered for Earth Engine.")
        return 1
    print(f"Earth Engine initialized (project={args.project}).")

    study = json.loads(args.study.read_text(encoding="utf-8"))
    aoi = ee.Geometry(study["aoi"])
    windows = {"before": study["before_window"], "after": study["after_window"]}
    ok = True
    for label, (start, end) in windows.items():
        col = (ee.ImageCollection(S2).filterBounds(aoi).filterDate(start, end)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", args.max_cloud)))
        n = col.size().getInfo()
        clouds = col.aggregate_array("CLOUDY_PIXEL_PERCENTAGE").getInfo()
        best = min(clouds) if clouds else None
        print(f"  {label:26s} {start}..{end}: {n} scenes <{args.max_cloud:.0f}% cloud"
              + (f", clearest {best:.1f}%" if best is not None else ""))
        ok &= n > 0
    if not ok:
        print("A window returned 0 scenes: widen the dates or raise --max-cloud before Phase 5.")
        return 1
    print("Ready for Phase 5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
