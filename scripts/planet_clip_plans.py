r"""Planet plans clipped to what uses them (D12 / D17, 2026-11-01), so they fit the monthly quota now instead
of waiting for the next one. Planet charges the clipped area, not the scene.

    python scripts\planet_clip_plans.py          # writes data/planet/plan_<name>_clip.json, prints km2

- 4b windows (before 2018-19, after 2022-23): the chips of the 4b training and held-out boxes and of the
  30 labelled sites (ee_engine.chip_box framing), instead of the whole AOI.
- Apr - Jun 2026: the Phase 11 transect corridor (300 m landward to 500 m seaward), instead of the AOI.

The clip shape is the union of those areas on a GRID_DEG grid, as a MultiPolygon of non-overlapping
rectangles (rows of cells merged, then equal rows stacked), kept under Planet's 500-vertex clip limit.
Then: python scripts\planet_order.py order data\planet\plan_<name>_clip.json [--confirm]
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PLANET = ROOT / "data" / "planet"
GRID_DEG = 0.002                 # ~200 m cells (the transect corridor)
GRID_4B_DEG = 0.004              # ~400 m cells: the 4b chips are spread out, so a coarser grid stays under the vertex limit
MAX_VERTICES = 500               # Planet's clip tool limit
SHRINK_DEG = 2e-5                # ~2 m each side: Planet checks validity in UTM, where smaller gaps still "touch"


def grid_union(rects: list[list[float]], aoi: tuple[float, float, float, float], step: float = GRID_DEG) -> tuple[list, float]:
    """(MultiPolygon coordinates, km2) of the cells of the AOI grid that any rect touches."""
    W, S, E, N = aoi
    nx, ny = math.ceil((E - W) / step), math.ceil((N - S) / step)
    on = [[False] * nx for _ in range(ny)]
    for w, s, e, n in rects:
        for j in range(max(0, int((s - S) / step)), min(ny, int((n - S) / step) + 1)):
            for i in range(max(0, int((w - W) / step)), min(nx, int((e - W) / step) + 1)):
                on[j][i] = True
    runs_by_row = []
    for j in range(ny):
        runs, i = [], 0
        while i < nx:
            if on[j][i]:
                k = i
                while k < nx and on[j][k]:
                    k += 1
                runs.append((i, k))
                i = k
            else:
                i += 1
        runs_by_row.append(runs)
    rects_out, open_ = [], {}
    for j, runs in enumerate(runs_by_row + [[]]):
        nxt = {}
        for r in runs:
            nxt[r] = open_.pop(r, j)                       # continue a rectangle with the same run, or start one
        for (i0, i1), j0 in open_.items():
            rects_out.append((i0, j0, i1, j))
        open_ = nxt
    coords, km2 = [], 0.0
    for i0, j0, i1, j1 in rects_out:
        w, s, e, n = W + i0 * step, S + j0 * step, min(E, W + i1 * step), min(N, S + j1 * step)
        if e - w < 1e-9 or n - s < 1e-9:                   # a cell row on the AOI's edge, cut to nothing
            continue
        # polygons of a MultiPolygon may not share edges: shrink each by ~2 m so neighbours don't touch
        w, s, e, n = w + SHRINK_DEG, s + SHRINK_DEG, e - SHRINK_DEG, n - SHRINK_DEG
        coords.append([[[w, s], [e, s], [e, n], [w, n], [w, s]]])
        km2 += (e - w) * 111.32 * math.cos(math.radians((s + n) / 2)) * (n - s) * 111.32
    return coords, km2


def chips_4b() -> list[list[float]]:
    import finetune_data as fd
    from agents.ee_engine import chip_box
    boxes = [x["box"] for x in json.loads((ROOT / "data" / "quangninh" / "ft_boxes.json").read_text(encoding="utf-8"))["boxes"]]
    boxes += [list(b) for b in fd.holdout_boxes()]
    for site in json.loads((ROOT / "data" / "quangninh" / "labels" / "sites.json").read_text(encoding="utf-8")):
        ring = site["outline"]["coordinates"][0]
        boxes.append([min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)])
    return [chip_box(tuple(b)) for b in boxes]


def transect_corridor() -> list[list[float]]:
    tr = json.loads((ROOT / "data" / "quangninh" / "shoreline" / "transects.geojson").read_text(encoding="utf-8"))
    out = []
    for f in tr["features"]:
        (x1, y1), (x2, y2) = f["geometry"]["coordinates"]
        for t in range(11):                                # small boxes along each transect
            x, y = x1 + (x2 - x1) * t / 10, y1 + (y2 - y1) * t / 10
            out.append([x - 0.0005, y - 0.0005, x + 0.0005, y + 0.0005])
    return out


def clipped(plan_file: str, rects: list[list[float]], name: str, step: float = GRID_DEG) -> None:
    plan = json.loads((PLANET / plan_file).read_text(encoding="utf-8"))
    ring = plan["aoi"]["coordinates"][0]
    aoi = (min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring))
    coords, km2 = grid_union(rects, aoi, step)
    if 5 * len(coords) > MAX_VERTICES:
        raise SystemExit(f"{name}: {len(coords)} rectangles is over the vertex limit; use a coarser grid")
    share = km2 / plan["aoi_km2"]
    plan["aoi"] = {"type": "MultiPolygon", "coordinates": coords}
    plan["aoi_km2"] = round(km2, 1)
    plan["clipped_to"] = name
    for m in plan["months"]:
        m["km2"] = round(min(m["km2"], km2), 1)
        m["quota_km2"] = round(m["quota_km2"] * share, 1)   # the scenes' charge scales with the clipped share
    plan["total_km2"] = round(sum(m["km2"] for m in plan["months"]), 1)
    plan["total_quota_km2"] = round(sum(m["quota_km2"] for m in plan["months"]), 1)
    out = PLANET / plan_file.replace(".json", "_clip.json")
    out.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"{out.name}: {name}, {len(coords)} rectangles, {km2:.1f} km2 per month, quota estimate {plan['total_quota_km2']} km2")


def main() -> None:
    four_b = chips_4b()
    clipped("plan_before_2018-19.json", four_b, "4b box and site chips", GRID_4B_DEG)
    clipped("plan_after_2022-23.json", four_b, "4b box and site chips", GRID_4B_DEG)
    clipped("plan_dec_2026.json", transect_corridor(), "Phase 11 transect corridor")


if __name__ == "__main__":
    main()
