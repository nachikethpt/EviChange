r"""Re-check the labelled sites' strata against a newer detector run.

The labelled sites (data/quangninh/labels/sites.json) were drawn from one regions file; the
labels describe what is inside each site's box, which doesn't depend on the detector. This script
measures every box against another regions file and assigns a stratum for that detector run:

  detected    at least --min-cover (default 10%) of the box is covered by detected regions
  background  no detected region within 200 m of the box (the notebook's rule for random sites)
  edge        anything else (a little change in the box, or change just outside it)

Writes data/quangninh/labels/sites_strata_<tag>.json. Like sites_key.json, that file reveals
which sites are detections: labellers must not open it. Only totals are printed.

    python scripts\restratify_sites.py data\quangninh\change_regions_quangninh_v2.json
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agents.site_evidence import M_PER_DEG, area_m2, bbox, inside_part, overlaps  # noqa: E402  (shared clipping)

LABELS = ROOT / "data" / "quangninh" / "labels"
NEAR_M = 200


def covered_m2(geom, box, lat0):
    """Area of the region inside the box: clipped outer rings minus clipped holes."""
    return inside_part(geom, box)[0]


def expand(box, metres, lat0):
    dx, dy = metres / (M_PER_DEG * math.cos(math.radians(lat0))), metres / M_PER_DEG
    w, s, e, n = box
    return w - dx, s - dy, e + dx, n + dy


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("regions", type=Path)
    ap.add_argument("--min-cover", type=float, default=0.10)
    ap.add_argument("--tag", default=None, help="output tag (default: the regions file's suffix, e.g. v2)")
    args = ap.parse_args()

    fc = json.loads(args.regions.read_text())
    regions = [(f["properties"]["id"], f["geometry"], bbox(f["geometry"])) for f in fc["features"]]
    sites = json.loads((LABELS / "sites.json").read_text())
    key = json.loads((LABELS / "sites_key.json").read_text())
    tag = args.tag or args.regions.stem.rsplit("_", 1)[-1]

    out = {}
    for site in sites:
        ring = site["outline"]["coordinates"][0]
        box = (min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring))
        lat0 = (box[1] + box[3]) / 2
        box_m2 = area_m2([tuple(p) for p in ring[:-1]], lat0)
        near = expand(box, NEAR_M, lat0)
        hits, cover = [], 0.0
        for rid, geom, rb in regions:
            if overlaps(rb, box):
                a = covered_m2(geom, box, lat0)
                if a > 0:
                    hits.append(rid); cover += a
        near_any = bool(hits) or any(overlaps(rb, near) and covered_m2(g, near, lat0) > 0 for _, g, rb in regions)
        frac = min(1.0, cover / box_m2)
        stratum = "detected" if frac >= args.min_cover else ("background" if not near_any else "edge")
        out[site["site_id"]] = {"stratum": stratum, "cover_frac": round(frac, 4), "region_ids": hits,
                                "within_200m": near_any, "origin_labelled_as": key[site["site_id"]]["origin"]}

    dest = LABELS / f"sites_strata_{tag}.json"
    dest.write_text(json.dumps({"regions_file": args.regions.name, "code_version": fc.get("metadata", {}).get("code_version"),
                                "min_cover": args.min_cover, "near_m": NEAR_M, "sites": out}, indent=1))
    table = collections.Counter((v["origin_labelled_as"], v["stratum"]) for v in out.values())
    print(f"wrote {dest} (do not show to labellers)")
    print(f"{'sampled as':10s} -> {'detected':>9s} {'edge':>5s} {'background':>11s}")
    for origin in ("detected", "random"):
        print(f"{origin:10s} -> {table[(origin, 'detected')]:9d} {table[(origin, 'edge')]:5d} {table[(origin, 'background')]:11d}")


if __name__ == "__main__":
    main()
