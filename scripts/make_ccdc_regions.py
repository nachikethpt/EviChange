r"""CCDC for every detector change region (D14, Phase 10b): when the detected change happened (between the
detector's two windows) and whether the region changed again in the monitoring period (Oct 2024 - Sep 2026).
Writes data/quangninh/ccdc_regions.json; resumes from it, so a stopped run picks up where it was.

    python scripts\make_ccdc_regions.py              # needs an Earth Engine login (EE_PROJECT); ~5-15 min
    python scripts\make_ccdc_regions.py --redo       # start over

Regions mostly inside a labelled site (the 22 whose classes are locked, D10) are not run: the Phase 14 (d)
change-month labels at the 30 sites are made blind to CCDC (scripts/ccdc_change_month.py --sites runs them
after those labels exist).
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import ccdc, landcover            # noqa: E402

REGIONS = ROOT / "data" / "quangninh" / "change_regions_quangninh_v3.json"
OUT = ROOT / "data" / "quangninh" / "ccdc_regions.json"


def locked_ids(fc: dict) -> set[str]:
    return {f["properties"]["id"] for f in landcover.hide_at_labelled_sites(fc)["features"] if f["properties"].get("class_hidden")}


def params(detection: tuple[str, str]) -> dict:
    return {"history_start": ccdc.HISTORY_START, "detection": list(detection), "monitoring": list(ccdc.PERIOD),
            "lasting_share": ccdc.LASTING_SHARE, "break_bands": ccdc.BREAK_BANDS, "magnitude_bands": ccdc.MAG_BANDS,
            "scale_m": ccdc.SCALE_M, "algorithm": "ee.Algorithms.TemporalSegmentation.Ccdc, Earth Engine defaults"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--batch", type=int, default=ccdc.REGION_BATCH)
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    fc = json.loads(REGIONS.read_text(encoding="utf-8"))
    p0 = fc["features"][0]["properties"]
    detection = ccdc.detection_period(p0["date_before"], p0["date_after"])
    locked = locked_ids(fc)
    out = {"params": params(detection), "locked": sorted(locked), "regions": {}}
    if OUT.exists() and not args.redo:
        out["regions"] = json.loads(OUT.read_text(encoding="utf-8")).get("regions", {})
    todo = [f for f in fc["features"] if f["properties"]["id"] not in locked and f["properties"]["id"] not in out["regions"]]
    print(f"{len(fc['features'])} regions, {len(locked)} locked at labelled sites, {len(out['regions'])} done, {len(todo)} to run; "
          f"detection {detection[0]} .. {detection[1]}, monitoring {ccdc.PERIOD[0]} .. {ccdc.PERIOD[1]}")
    from agents.ee_engine import _ee
    ee = _ee()
    t0 = time.time()
    for b in range(0, len(todo), args.batch):
        batch = todo[b: b + args.batch]
        for attempt in range(3):
            try:
                det = ccdc.ee_regions(ee, batch, detection)
                mon = ccdc.ee_regions(ee, batch, ccdc.PERIOD)
                break
            except Exception as exc:                       # Earth Engine hiccup: smaller pieces next time
                print(f"  batch {b // args.batch + 1}: {exc}; retry {attempt + 1}")
                time.sleep(5)
        else:
            print(f"  batch {b // args.batch + 1} skipped after 3 tries (rerun to fill it)")
            continue
        for f in batch:
            rid = f["properties"]["id"]
            out["regions"][rid] = {"detection": det.get(rid), "monitoring": mon.get(rid)}
        out["params"]["run"] = date.today().isoformat()
        OUT.write_text(json.dumps(out), encoding="utf-8")
        print(f"  {min(b + args.batch, len(todo))} / {len(todo)}  ({time.time() - t0:.0f} s)")
    lasting = lambda per: sum(1 for r in out["regions"].values() if (r.get(per) or {}).get("lasting"))
    print(f"wrote {OUT}: {len(out['regions'])} regions; lasting change dated in the detection period: {lasting('detection')}; "
          f"changed again in the monitoring period: {lasting('monitoring')}")


if __name__ == "__main__":
    main()
