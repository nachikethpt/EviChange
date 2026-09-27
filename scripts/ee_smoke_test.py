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
import os
import sys

AOI_BOUNDS = [107.22, 20.98, 107.40, 21.10]   # Cam Pha study box, same as the web app and notebook
S2 = "COPERNICUS/S2_SR_HARMONIZED"
WINDOWS = {"before (2018 dry season)": ("2018-11-01", "2019-03-31"),
           "after (2022 dry season)": ("2022-11-01", "2023-03-31")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("EE_PROJECT"), help="Earth Engine Cloud project id")
    ap.add_argument("--max-cloud", type=float, default=30)
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

    aoi = ee.Geometry.Rectangle(AOI_BOUNDS)
    ok = True
    for label, (start, end) in WINDOWS.items():
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
