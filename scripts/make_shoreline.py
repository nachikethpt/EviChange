r"""Shoreline change for the study AOI over the monthly period (D11, Phase 11).

Reads Phase 10's data/quangninh/monthly/summary.json (months + Sentinel-1 thresholds) and writes
data/quangninh/shoreline/: transects.geojson (with rates), baseline.geojson, shorelines.geojson (one
line per month), positions.json and summary.json.

    python scripts\make_shoreline.py                     # needs an Earth Engine login (EE_PROJECT); ~5-15 min
    python scripts\make_shoreline.py --keep-transects    # re-measure on the existing baseline and transects

--keep-transects keeps transect ids (and so the Phase 14 reference labels) matching: a full rebuild from newer
Sentinel-1 looks moves the baseline slightly and renumbers the transects (2026-11-07: 731 instead of 735).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import monthly, shoreline        # noqa: E402
from agents.study import load_study_config   # noqa: E402


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keep-transects", action="store_true", help="re-measure on the existing baseline and transects")
    args = ap.parse_args(argv)
    t0 = time.time()
    study = load_study_config()
    summary = json.loads(monthly.SUMMARY_FILE.read_text(encoding="utf-8"))
    print(f"monthly series {summary['period'][0]} - {summary['period'][1]}, {len(summary['months'])} months")
    result = shoreline.build(study["aoi"], summary,
                             existing_dir=shoreline.SHORELINE_DIR if args.keep_transects else None)
    out = shoreline.write_outputs(result)
    print(f"{out['transects']} transects on {out['baseline_km']} km of baseline; change (optically confirmed) {out['changes']}; "
          f"radar trends {out['radar_trends']}; tidal {out['tidal_transects']}; month positions {out['month_status']}; "
          f"fastest confirmed advance {out['fastest_advance_m_yr']} m/yr, retreat {out['fastest_retreat_m_yr']} m/yr; "
          f"{time.time() - t0:.0f} s -> {shoreline.SHORELINE_DIR}")


if __name__ == "__main__":
    main()
