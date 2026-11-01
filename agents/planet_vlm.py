"""Planet-only Geo-VLM checks (Phase 13c), separate from frozen Sentinel-2 prompts and replays."""
from __future__ import annotations

import time
from datetime import date

from . import planet, vlm_check

PROMPT_VERSION = "planetcheck_v1"
CHIP_SETS = {"planet_rgb": ("rgb",), "planet_rgb_nir": ("rgb", "nir")}
MIN_BOX_CLEAR = 0.5


def pair(catalog: dict, before: str, after: str) -> list[dict]:
    """Require two delivered, chronologically ordered acquisitions; never substitute a nearby month."""
    planet.check_month(before)
    planet.check_month(after)
    if before >= after:
        raise ValueError("Planet before_month must precede after_month")
    by_month = {r["month"]: r for r in catalog["months"]}
    if before not in by_month or after not in by_month:
        raise LookupError("both selected Planet months must be delivered; missing months are gaps")
    rows = [by_month[before], by_month[after]]
    for row in rows:
        acquired = date.fromisoformat(row.get("date") or "")
        if acquired.strftime("%Y-%m") != row["month"]:
            raise ValueError("Planet acquisition date does not match its month")
    return rows


def build_prompt(rows: list[dict], chip_set: str) -> str:
    kinds = CHIP_SETS[chip_set]
    images = "; ".join(f"{when.upper()}, {'true colour' if k == 'rgb' else 'NIR false colour (NIR-red-green)'}"
                       for k in kinds for when in ("before", "after"))
    return (f"You get {2 * len(kinds)} PlanetScope images, 3 m source resolution, of the same place: {images}.\n"
            f"BEFORE acquisition: {rows[0]['date']}. AFTER acquisition: {rows[1]['date']}.\n"
            "The same stretch and yellow outline are used for both dates. Black areas outside the clear mask "
            "are missing data, not land-cover change. Ignore cloud, haze, shadows and changes outside the box. "
            "These are single-day images at different tides; waterline movement alone is not proof of lasting change.\n"
            + ("In NIR false colour vegetation is red and water is dark.\n" if "nir" in kinds else "")
            + "Look ONLY inside the yellow box. Did real land-cover change happen between these acquisitions? "
            "If you cannot tell, say unsure. Planet has no SWIR; do not infer a SWIR measurement.\n"
            + "change_types must contain zero or more of: " + ", ".join(vlm_check.VLM_TYPES) + ".\n"
            + 'Answer with JSON only: {"verdict":"change"|"no_change"|"unsure","change_types":[], '
            + '"reason":"one short sentence about what is visible inside the box"}.')


def context(params: dict, rows: list[dict], bbox: tuple) -> dict:
    return {"analysis": params, "source": planet.SOURCE, "collection": planet.PLANET_COLLECTION,
            "acquisitions": rows, "bbox": list(bbox), "min_box_clear": MIN_BOX_CLEAR}


def check(vlm, params: dict, region: dict, bbox: tuple, chip_set: str, rows: list[dict], chips: dict,
          clear_shares: list[float], run_id: str | None = None) -> tuple[dict, dict]:
    t0 = time.time()
    version = f"{PROMPT_VERSION}_{chip_set}"
    identity = context(params, rows, bbox)
    # Include dates/assets/framing in replay identity as well as in the persisted cache key.
    replay_key = vlm_check.check_key(identity, region["id"], version, "replay")
    keys = [f"{when}_{kind}" for kind in CHIP_SETS[chip_set] for when in ("before", "after")]
    out = vlm.generate(build_prompt(rows, chip_set), [chips[k] for k in keys], replay_key=f"{version}:{replay_key}")
    answer = vlm_check.parse_answer(out["text"])
    comparable = (params["before_window"][0] <= rows[0]["date"] <= params["before_window"][1]
                  and params["after_window"][0] <= rows[1]["date"] <= params["after_window"][1])
    comparison = vlm_check.compare(answer, region)
    if not comparable:
        comparison["agreement"] = "different_period"
    result = {"region_id": region["id"], "status": "checked", **answer, **comparison,
              "source": "planet", "comparable": comparable, "acquisitions": rows, "box_clear_share": clear_shares,
              "attribution": planet.ATTRIBUTION, "scale_m": planet.NATIVE_SCALE,
              "model": out["model"], "prompt_version": version, "chips": chip_set, "raw": out["text"][:1000],
              "detector_windows": [params["before_window"], params["after_window"]]}
    record = {**result, "key": vlm_check.check_key(identity, region["id"], version, out["model"]),
              "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run_id": run_id, "bbox": list(bbox),
              "seconds": round(time.time() - t0, 1), "raw": out["text"]}
    return result, record
