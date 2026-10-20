r"""Add Dynamic World land-cover classes (D10, Phase 9) to an existing change-regions file.

Region ids, geometry and the detector fields are unchanged, so labels that refer to region ids stay
valid; only class_before / class_after / class_frac_before / class_frac_after are added. The date
windows come from the file's metadata (falling back to data/quangninh/study.json).

    python scripts\add_landcover.py                                   # the QN v3 regions, in place
    python scripts\add_landcover.py data\quangninh\change_regions_quangninh_v3.json --out other.json
    python import_geojson.py data\quangninh\change_regions_quangninh_v3.json    # then show it in the app

Needs an Earth Engine login (EE_PROJECT). About 5-15 minutes for the 504 QN regions.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import landcover                       # noqa: E402
from agents.schema import validate_change_regions  # noqa: E402

STUDY = ROOT / "data" / "quangninh" / "study.json"
DEFAULT = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("regions", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--out", type=Path, help="write here instead of in place")
    args = ap.parse_args(argv)

    fc = json.loads(args.regions.read_text(encoding="utf-8"))
    meta, study = fc.get("metadata") or {}, json.loads(STUDY.read_text(encoding="utf-8"))
    aoi = meta.get("aoi") or study["aoi"]
    before, after = meta.get("before_window") or study["before_window"], meta.get("after_window") or study["after_window"]

    t0 = time.time()
    out_fc = landcover.add_landcover(fc, aoi, before, after)
    errors = validate_change_regions(out_fc)
    if errors:
        sys.exit("result does not match agents/schema.py:\n  " + "\n  ".join(errors[:20]))
    out = args.out or args.regions
    out.write_text(json.dumps(out_fc), encoding="utf-8")

    regions = [f["properties"] for f in out_fc["features"]]
    known = [r for r in regions if landcover.transition(r)]
    changed = Counter(landcover.transition(r) for r in known if r["class_before"] != r["class_after"])
    print(f"{len(regions)} regions, {len(known)} with both classes, {sum(changed.values())} change class "
          f"({time.time() - t0:.0f} s) -> {out}")
    for name, n in changed.most_common(8):
        print(f"  {n:4d}  {name}")
    return out


if __name__ == "__main__":
    main()
