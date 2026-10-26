r"""CCDC month of change (D14) for the labelled sites or development regions.

    python scripts\ccdc_change_month.py --dev r200 r227        # development regions: any time
    python scripts\ccdc_change_month.py --sites                # the 30 sites: only after Phase 14 (d) is labelled
    python scripts\phase14_report.py --ccdc data\quangninh\ccdc_sites.json

Needs `pip install -r requirements-ee.txt`, `earthengine authenticate` and EE_PROJECT.

Blindness (PLAN Phase 14): the month of change at the 30 sites is labelled on Planet months without
seeing CCDC, so --sites refuses to run until labels14_change_month.jsonl covers all 30 sites.

Writes data/quangninh/ccdc_<sites|dev>.json: {"results": {id: site_result}, "windows": {id: window},
"params": {...}}. "windows" is the --ccdc input of scripts/phase14_report.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agents import ccdc, labels14 as l14            # noqa: E402

SITES = ROOT / "data" / "quangninh" / "labels" / "sites.json"


def bbox(geom: dict) -> tuple[float, float, float, float]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


def labels_complete(folder: Path | None = None) -> tuple[bool, int]:
    """(all 30 sites have a change-month label, how many are missing)."""
    sites = {s["site_id"] for s in json.loads(SITES.read_text(encoding="utf-8"))}
    path = (folder or l14.LABELS_DIR) / "labels14_change_month.jsonl"
    done = {r["site_id"] for r in l14.load_labels(path, "change_month")} if path.exists() else set()
    missing = len(sites - done)
    return missing == 0, missing


def boxes(mode: str, ids: list[str]) -> dict[str, tuple]:
    if mode == "sites":
        return {s["site_id"]: bbox(s["outline"]) for s in json.loads(SITES.read_text(encoding="utf-8"))}
    import vlm_batch
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise SystemExit(f"unknown region ids: {unknown}")
    from agents import vlm_check
    out = {}
    for i in ids:
        b = vlm_batch.bbox(by_id[i]["geometry"])
        if vlm_check.touches_labelled_site(b):
            raise SystemExit(f"{i} overlaps a labelled site: use --sites after the Phase 14 labels")
        out[i] = b
    return out


def run(mode: str, ids: list[str], site_fn=None, log=print) -> dict:
    if mode == "sites":
        ok, missing = labels_complete()
        if not ok:
            raise SystemExit(f"Blind: {missing} of the 30 sites still have no change-month label "
                             "(labels14_change_month.jsonl). Label them first.")
    if site_fn is None:
        from agents.ee_engine import _ee
        ee = _ee()
        site_fn = lambda box: ccdc.ee_site(ee, box)
    results = {}
    for sid, box in boxes(mode, ids).items():
        try:
            results[sid] = ccdc.site_result(*site_fn(box))
        except Exception as exc:                      # one failed box never loses the others
            results[sid] = {"error": str(exc)}
        log(f"{sid}: {results[sid]}")
    return {"results": results, "windows": ccdc.windows_for_report(results),
            "params": {"history_start": ccdc.HISTORY_START, "period": list(ccdc.PERIOD), "lasting_share": ccdc.LASTING_SHARE,
                       "clear_share": ccdc.CLEAR_SHARE, "break_bands": ccdc.BREAK_BANDS, "run": date.today().isoformat()}}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="CCDC month of change (D14)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sites", action="store_true", help="the 30 labelled sites (after Phase 14 d)")
    g.add_argument("--dev", nargs="+", metavar="REGION_ID", help="development regions outside the labelled sites")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    mode = "sites" if args.sites else "dev"
    out = run(mode, args.dev or [])
    path = args.out or ROOT / "data" / "quangninh" / f"ccdc_{mode}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {path} ({len(out['windows'])} lasting of {len(out['results'])})")


if __name__ == "__main__":
    main()
