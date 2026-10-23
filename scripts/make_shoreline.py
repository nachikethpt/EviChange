r"""Shoreline change for the study AOI over the monthly period (D11, Phase 11).

Reads Phase 10's data/quangninh/monthly/summary.json (months + Sentinel-1 thresholds) and writes
data/quangninh/shoreline/: transects.geojson (with rates), baseline.geojson, shorelines.geojson (one
line per month), positions.json and summary.json.

    python scripts\make_shoreline.py          # needs an Earth Engine login (EE_PROJECT); ~5-15 min
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import monthly, shoreline        # noqa: E402
from agents.study import load_study_config   # noqa: E402


def main() -> None:
    t0 = time.time()
    study = load_study_config()
    summary = json.loads(monthly.SUMMARY_FILE.read_text(encoding="utf-8"))
    print(f"monthly series {summary['period'][0]} - {summary['period'][1]}, {len(summary['months'])} months")
    result = shoreline.build(study["aoi"], summary)
    out = shoreline.write_outputs(result)
    print(f"{out['transects']} transects on {out['baseline_km']} km of baseline; change (optically confirmed) {out['changes']}; "
          f"radar trends {out['radar_trends']}; tidal {out['tidal_transects']}; month positions {out['month_status']}; "
          f"fastest confirmed advance {out['fastest_advance_m_yr']} m/yr, retreat {out['fastest_retreat_m_yr']} m/yr; "
          f"{time.time() - t0:.0f} s -> {shoreline.SHORELINE_DIR}")


if __name__ == "__main__":
    main()
