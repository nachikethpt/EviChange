"""Order PlanetScope imagery for the Quang Ninh AOI, one clear acquisition day per month (D12, Phase 13a).

    python scripts/planet_order.py search 2024-10 2025-09         # writes a plan, prints months + km²
    python scripts/planet_order.py order data/planet/plan_2024-10_2025-09.json            # dry run
    python scripts/planet_order.py order data/planet/plan_2024-10_2025-09.json --confirm  # places orders
    python scripts/planet_order.py status                         # state of placed orders
    python scripts/planet_order.py download                       # finished orders -> data/planet/raw/<month>/
    python scripts/planet_order.py download --copy-to "G:/My Drive/EviChange/planet"   # ... and a copy in Drive

Needs PL_API_KEY (Planet account -> My settings -> API key), set in the shell, never committed.

Per month: PSScene items with 8-band surface reflectance, at most --max-cloud cloud cover, grouped by
acquisition day (UTC); the day whose scenes cover the AOI best with the most clear sky wins. Orders
are clipped to the AOI and harmonised to Sentinel-2. The km² shown is the AOI area those scenes
cover (the clipped area); check in Planet Explorer how the E&R quota counts clipped orders before
the first large order. `order` refuses to go over --max-km2 (default 3,000, one month's quota).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.schema import aoi_area_ha  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "data" / "quangninh" / "study.json"
OUT = ROOT / "data" / "planet"
ORDERS_LOG = OUT / "orders.json"
SEARCH_URL = "https://api.planet.com/data/v1/quick-search"
ORDERS_URL = "https://api.planet.com/compute/ops/orders/v2"
ITEM_TYPE, ASSET, BUNDLE = "PSScene", "ortho_analytic_8b_sr", "analytic_8b_sr_udm2"
PLANET_DELAY_DAYS = 30


# ---------- months ----------
def months(start: str, end: str) -> list[str]:
    """'2024-10', '2025-01' -> ['2024-10', '2024-11', '2024-12', '2025-01']."""
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    if (y, m) > (ey, em):
        raise ValueError(f"start {start} is after end {end}")
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(month: str) -> tuple[str, str]:
    y, m = map(int, month.split("-"))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01T00:00:00Z", f"{ny:04d}-{nm:02d}-01T00:00:00Z"


# ---------- geometry (no shapely: the AOI is sampled on a grid) ----------
def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _in_geometry(x: float, y: float, geom: dict) -> bool:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return any(_in_ring(x, y, p[0]) and not any(_in_ring(x, y, h) for h in p[1:]) for p in polys)


def aoi_grid(aoi: dict, n: int = 60) -> list[tuple[float, float]]:
    """Points on an n x n grid over the AOI's bounding box that fall inside the AOI."""
    polys = [aoi["coordinates"]] if aoi["type"] == "Polygon" else aoi["coordinates"]
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    w, s, e, nn = min(xs), min(ys), max(xs), max(ys)
    pts = [(w + (i + 0.5) * (e - w) / n, s + (j + 0.5) * (nn - s) / n) for i in range(n) for j in range(n)]
    return [p for p in pts if _in_geometry(*p, aoi)]


def coverage(grid: list[tuple[float, float]], footprints: list[dict]) -> float:
    """Share of the AOI (grid points) inside the union of the footprints."""
    if not grid:
        return 0.0
    return sum(any(_in_geometry(x, y, f) for f in footprints) for x, y in grid) / len(grid)


# ---------- search ----------
def search_filter(aoi: dict, month: str, max_cloud: float) -> dict:
    gte, lt = month_bounds(month)
    return {"type": "AndFilter", "config": [
        {"type": "GeometryFilter", "field_name": "geometry", "config": aoi},
        {"type": "DateRangeFilter", "field_name": "acquired", "config": {"gte": gte, "lt": lt}},
        {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": max_cloud}},
        {"type": "StringInFilter", "field_name": "quality_category", "config": ["standard"]},
        {"type": "AssetFilter", "config": [ASSET]},
        {"type": "PermissionFilter", "config": ["assets:download"]},
    ]}


def search_month(session, aoi: dict, month: str, max_cloud: float) -> list[dict]:
    resp = _call(session.post, SEARCH_URL, json={"item_types": [ITEM_TYPE], "filter": search_filter(aoi, month, max_cloud)})
    body = resp.json()
    items = list(body.get("features", []))
    while body.get("_links", {}).get("_next"):
        body = _call(session.get, body["_links"]["_next"]).json()
        items += body.get("features", [])
    return items


def _clear_pct(item: dict) -> float:
    p = item["properties"]
    return float(p["clear_percent"]) if p.get("clear_percent") is not None else 100 * (1 - float(p.get("cloud_cover", 1)))


def pick_day(items: list[dict], grid: list[tuple[float, float]]) -> dict | None:
    """Best acquisition day: score = AOI coverage x mean clear share of that day's scenes."""
    days: dict[str, list[dict]] = {}
    for it in items:
        days.setdefault(it["properties"]["acquired"][:10], []).append(it)
    best = None
    for day, its in sorted(days.items()):
        cov = coverage(grid, [it["geometry"] for it in its])
        clear = sum(_clear_pct(it) for it in its) / len(its)
        score = cov * clear / 100
        if best is None or score > best["score"]:
            best = {"date": day, "item_ids": sorted(it["id"] for it in its), "coverage": round(cov, 3),
                    "clear_pct": round(clear, 1), "score": round(score, 3)}
    if best:
        best["days_found"] = len(days)
    return best


def make_plan(session, aoi: dict, month_list: list[str], max_cloud: float, today: date | None = None) -> dict:
    aoi_km2 = aoi_area_ha(aoi) / 100
    grid = aoi_grid(aoi)
    newest = (today or date.today()) - timedelta(days=PLANET_DELAY_DAYS)
    rows = []
    for month in month_list:
        row = {"month": month}
        if month_bounds(month)[0][:10] > newest.isoformat():
            row["note"] = f"after {newest.isoformat()}: PlanetScope has a {PLANET_DELAY_DAYS}-day delay"
        best = pick_day(search_month(session, aoi, month, max_cloud), grid)
        if best is None:
            row.update({"date": None, "item_ids": [], "km2": 0.0, "note": row.get("note") or "no scene under the cloud limit"})
        else:
            row.update(best, km2=round(aoi_km2 * best["coverage"], 1))
        rows.append(row)
    return {"aoi": aoi, "aoi_km2": round(aoi_km2, 1), "max_cloud": max_cloud, "item_type": ITEM_TYPE,
            "product_bundle": BUNDLE, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "months": rows, "total_km2": round(sum(r["km2"] for r in rows), 1)}


def print_plan(plan: dict) -> None:
    print(f"AOI {plan['aoi_km2']} km², cloud cover <= {plan['max_cloud']:.0%}\n")
    print(f"{'month':8} {'day':10} {'scenes':>6} {'AOI cov':>8} {'clear':>6} {'km²':>7}  note")
    for r in plan["months"]:
        if r["date"]:
            print(f"{r['month']:8} {r['date']:10} {len(r['item_ids']):>6} {r['coverage']:>8.0%} {r['clear_pct']:>5.0f}% {r['km2']:>7.1f}  {r.get('note', '')}")
        else:
            print(f"{r['month']:8} {'-':10} {'-':>6} {'-':>8} {'-':>6} {0:>7.1f}  {r.get('note', '')}")
    print(f"\nTotal ≈ {plan['total_km2']} km² (clipped to the AOI)")


# ---------- orders ----------
def order_request(plan: dict, row: dict) -> dict:
    return {"name": f"evichange-qn-{row['month']}-{row['date']}",
            "products": [{"item_ids": row["item_ids"], "item_type": plan["item_type"], "product_bundle": plan["product_bundle"]}],
            "tools": [{"clip": {"aoi": plan["aoi"]}}, {"harmonize": {"target_sensor": "Sentinel-2"}}]}


def load_log() -> dict:
    return json.loads(ORDERS_LOG.read_text(encoding="utf-8")) if ORDERS_LOG.exists() else {}


def save_log(log: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ORDERS_LOG.write_text(json.dumps(log, indent=1), encoding="utf-8")


def pending_rows(plan: dict, log: dict, min_coverage: float = 0.0) -> list[dict]:
    """Months in the plan with scenes that cover enough of the AOI and have not been ordered yet."""
    return [r for r in plan["months"] if r["item_ids"] and r["month"] not in log and r["coverage"] >= min_coverage]


def place_orders(session, plan: dict, confirm: bool, max_km2: float, min_coverage: float = 0.5) -> list[str]:
    log = load_log()
    rows = pending_rows(plan, log, min_coverage)
    km2 = round(sum(r["km2"] for r in rows), 1)
    for r in rows:
        print(f"  {r['month']}  {r['date']}  {len(r['item_ids'])} scene(s)  {r['km2']} km²")
    skipped = [r["month"] for r in plan["months"] if r["month"] in log]
    if skipped:
        print(f"  already ordered, skipped: {', '.join(skipped)}")
    thin = [f"{r['month']} ({r['coverage']:.0%})" for r in plan["months"]
            if r["item_ids"] and r["month"] not in log and r["coverage"] < min_coverage]
    if thin:
        print(f"  under {min_coverage:.0%} of the AOI, skipped (search again with a higher --max-cloud): {', '.join(thin)}")
    print(f"To order: {len(rows)} month(s), ≈ {km2} km²")
    if km2 > max_km2:
        raise SystemExit(f"Refusing: {km2} km² is over --max-km2 {max_km2}. Order fewer months (a shorter plan).")
    if not confirm:
        print("Dry run: nothing ordered. Add --confirm to place these orders.")
        return []
    placed = []
    for r in rows:
        body = _call(session.post, ORDERS_URL, json=order_request(plan, r)).json()
        log[r["month"]] = {"order_id": body["id"], "date": r["date"], "item_ids": r["item_ids"], "km2": r["km2"],
                           "placed": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        save_log(log)   # after each order, so a failure halfway never re-orders the months already placed
        placed.append(body["id"])
        print(f"  ordered {r['month']}: {body['id']}")
    return placed


def show_status(session) -> None:
    for month, entry in sorted(load_log().items()):
        state = _call(session.get, f"{ORDERS_URL}/{entry['order_id']}").json().get("state")
        print(f"{month}  {entry['date']}  {state:10}  {entry['order_id']}")


def download(session, copy_to: Path | None = None) -> None:
    """Finished orders -> data/planet/raw/<month>/; with copy_to, also mirrored to copy_to/<month>/
    (e.g. a Google Drive for desktop folder). Files already there with the same size are skipped.
    A file that keeps failing is reported at the end and retried on the next run."""
    failed: list[str] = []
    for month, entry in sorted(load_log().items()):
        order = _call(session.get, f"{ORDERS_URL}/{entry['order_id']}").json()
        if order.get("state") != "success":
            print(f"{month}: {order.get('state')}, not ready")
            continue
        folder = OUT / "raw" / month
        folder.mkdir(parents=True, exist_ok=True)
        for res in order["_links"].get("results", []):
            target = folder / Path(res["name"]).name
            if target.exists():
                continue
            if fetch(session, res["location"], target):
                print(f"{month}: {target.relative_to(ROOT)}")
            else:
                failed.append(f"{month}/{target.name}")
        if copy_to:
            mirror(folder, Path(copy_to) / month)
    if failed:
        print(f"\n{len(failed)} file(s) failed after retries; run download again to resume them: {', '.join(failed)}")


def fetch(session, url: str, target: Path, attempts: int = 5) -> bool:
    """Stream url to target via target.part, resuming the .part with an HTTP Range request after a
    dropped connection. The .part is renamed to target only when complete. False if all attempts fail."""
    import requests
    part = target.with_name(target.name + ".part")
    for attempt in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with session.get(url, stream=True, headers=headers, timeout=(30, 120)) as resp:
                if resp.status_code == 416:            # .part already holds the whole file
                    part.replace(target)
                    return True
                _check(resp)
                resume = have and resp.status_code == 206
                with open(part, "ab" if resume else "wb") as f:
                    for chunk in resp.iter_content(1 << 20):
                        f.write(chunk)
            part.replace(target)
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as exc:
            print(f"  connection dropped on {target.name} ({type(exc).__name__}); retry {attempt + 1}/{attempts - 1}"
                  if attempt < attempts - 1 else f"  giving up on {target.name} for now")
            time.sleep(min(2 ** attempt, 30))
    return False


def mirror(src: Path, dst: Path) -> int:
    """Copy files from src to dst unless dst already has them at the same size. Returns files copied."""
    import shutil
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in sorted(src.iterdir()):
        if not f.is_file() or f.suffix == ".part":
            continue
        out = dst / f.name
        if out.exists() and out.stat().st_size == f.stat().st_size:
            continue
        shutil.copy2(f, out)
        copied += 1
    if copied:
        print(f"  copied {copied} file(s) to {dst}")
    return copied


# ---------- plumbing ----------
def _call(method, url, **kw):
    """session.get / session.post with retries on 429 (Planet's rate limit), then _check."""
    for attempt in range(5):
        resp = method(url, **kw)
        if resp.status_code != 429:
            break
        time.sleep(2 ** attempt)
    return _check(resp)


def _check(resp):
    if resp.status_code == 401:
        raise SystemExit("Planet rejected PL_API_KEY (401).")
    if resp.status_code >= 400:
        raise SystemExit(f"Planet API {resp.status_code}: {resp.text[:300]}")
    return resp


def _session():
    import requests
    key = os.environ.get("PL_API_KEY", "")
    if not key:
        raise SystemExit("Set PL_API_KEY first (Planet account -> My settings -> API key).")
    s = requests.Session()
    s.auth = (key, "")
    return s


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="find the best day per month and write a plan")
    s.add_argument("start", help="first month, YYYY-MM")
    s.add_argument("end", help="last month, YYYY-MM")
    s.add_argument("--max-cloud", type=float, default=0.3, help="max cloud cover per scene, 0-1 (default 0.3)")
    o = sub.add_parser("order", help="order a plan's months (dry run without --confirm)")
    o.add_argument("plan")
    o.add_argument("--confirm", action="store_true")
    o.add_argument("--max-km2", type=float, default=3000)
    o.add_argument("--min-coverage", type=float, default=0.5, help="skip months covering less of the AOI, 0-1 (default 0.5)")
    sub.add_parser("status")
    d = sub.add_parser("download", help="download finished orders")
    d.add_argument("--copy-to", help="also copy into this folder, e.g. a Google Drive for desktop folder")
    args = ap.parse_args(argv)

    session = _session()
    if args.cmd == "search":
        aoi = json.loads(STUDY.read_text(encoding="utf-8"))["aoi"]
        plan = make_plan(session, aoi, months(args.start, args.end), args.max_cloud)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"plan_{args.start}_{args.end}.json"
        path.write_text(json.dumps(plan, indent=1), encoding="utf-8")
        print_plan(plan)
        print(f"Plan saved: {path.relative_to(ROOT)}. Nothing ordered.")
    elif args.cmd == "order":
        place_orders(session, json.loads(Path(args.plan).read_text(encoding="utf-8")), args.confirm, args.max_km2, args.min_coverage)
    elif args.cmd == "status":
        show_status(session)
    else:
        download(session, Path(args.copy_to) if args.copy_to else None)


if __name__ == "__main__":
    main()
