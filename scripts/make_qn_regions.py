r"""Regenerate the Quang Ninh change regions with the current Earth Engine detector.

Reads the study settings (AOI, windows, thresholds) from data/quangninh/study.json, runs
agents/ee_engine.run_engine() and writes data/quangninh/change_regions_quangninh_<tag>.json.
The tag defaults to the detector's code version suffix (ee-threshold-v2 -> v2), so an older
file (which existing labels may refer to by region id) is never overwritten.

    python scripts\make_qn_regions.py            # needs an Earth Engine login (EE_PROJECT)
    python import_geojson.py data\quangninh\change_regions_quangninh_v2.json   # show it in the app
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import ee_engine                      # noqa: E402
from agents.schema import validate_change_regions  # noqa: E402

STUDY = ROOT / "data" / "quangninh" / "study.json"


def main(tag: str | None = None) -> Path:
    study = json.loads(STUDY.read_text())
    tag = tag or ee_engine.CODE_VERSION.rsplit("-", 1)[-1]
    out = STUDY.parent / f"change_regions_{study['name']}_{tag}.json"
    if out.exists():
        sys.exit(f"{out} already exists; delete it or pass another tag")

    t0 = time.time()
    fc = ee_engine.run_engine(study["aoi"], study["before_window"], study["after_window"], study["thresholds"])
    errors = validate_change_regions(fc)
    if errors:
        sys.exit("detector output does not match agents/schema.py:\n  " + "\n  ".join(errors[:20]))
    out.write_text(json.dumps(fc))

    confs = [f["properties"]["mean_conf"] for f in fc["features"]]
    print(f"{len(fc['features'])} regions, change_frac {fc['metadata']['change_frac']:.3f}, "
          f"mean_conf {min(confs):.2f}-{max(confs):.2f} ({len(set(confs))} distinct), "
          f"{time.time() - t0:.0f} s -> {out}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
