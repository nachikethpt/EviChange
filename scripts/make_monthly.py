r"""Build the monthly time series for the QN AOI (D11, Phase 10).

Writes data/quangninh/monthly/summary.json (AOI numbers per month: scene counts, clear share, class
cover and areas, water area, change vs the previous month and vs the first month) and
regions_monthly.json (per change region and month: Dynamic World class, water share, share seen clear).
The period is `monthly` in data/quangninh/study.json (Oct 2024 – Sep 2026).

    python scripts\make_monthly.py                     # both files (summary ~5 min, regions longer)
    python scripts\make_monthly.py --summary-only
    python scripts\make_monthly.py --regions-only      # reuses the radar thresholds in summary.json

The region series is saved after every month (regions_monthly.partial.json), so a rerun after an
interruption carries on from the last finished month.

The web app serves both (GET /api/monthly, /api/monthly/layer, /api/monthly/regions/{id}).
Needs an Earth Engine login (EE_PROJECT).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import monthly                  # noqa: E402
from agents.study import load_study_config  # noqa: E402

DEFAULT_REGIONS = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"
PARTIAL = monthly.MONTHLY_DIR / "regions_monthly.partial.json"   # per-month checkpoint; a rerun resumes from it


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", type=Path, default=DEFAULT_REGIONS, help="change regions for the per-region series")
    ap.add_argument("--start", help="first month, YYYY-MM (default: study.json)")
    ap.add_argument("--end", help="last month, YYYY-MM (default: study.json)")
    only = ap.add_mutually_exclusive_group()
    only.add_argument("--summary-only", action="store_true")
    only.add_argument("--regions-only", action="store_true")
    args = ap.parse_args(argv)

    study = load_study_config()
    start, end = args.start or study["monthly"]["start"], args.end or study["monthly"]["end"]
    monthly.MONTHLY_DIR.mkdir(parents=True, exist_ok=True)

    if not args.regions_only:
        t0 = time.time()
        summary = monthly.build_summary(study["aoi"], start, end)
        monthly.SUMMARY_FILE.write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(f"summary: {len(summary['months'])} months ({time.time() - t0:.0f} s) -> {monthly.SUMMARY_FILE}")

    if not args.summary_only:
        t0 = time.time()
        summary = monthly.load(monthly.SUMMARY_FILE) or {}
        thresholds = {m["month"]: m["s1_thresholds_db"] for m in summary.get("months", [])}
        fc = json.loads(args.regions.read_text(encoding="utf-8"))
        regions_file = args.regions.resolve().relative_to(ROOT).as_posix()
        partial = monthly.load(PARTIAL) or {}
        done = partial.get("done", {}) if partial.get("regions_file") == regions_file else {}
        if done:
            print(f"resuming: {len(done)} months already done ({PARTIAL.name})")

        def save(d: dict) -> None:
            PARTIAL.write_text(json.dumps({"regions_file": regions_file, "done": d}, separators=(",", ":")), encoding="utf-8")

        series = monthly.region_series(fc, study["aoi"], start, end, thresholds, done=done, save=save)
        series["regions_file"] = regions_file
        monthly.REGIONS_FILE.write_text(json.dumps(series, separators=(",", ":")), encoding="utf-8")
        PARTIAL.unlink(missing_ok=True)
        print(f"regions: {len(series['regions'])} x {len(series['months'])} months ({time.time() - t0:.0f} s) "
              f"-> {monthly.REGIONS_FILE}")


if __name__ == "__main__":
    main()
