"""Main land cover per date (Phase 4b, D17 "main-cover target", 2026-11-02).

Two calibration rounds showed that labellers agree on what a box mostly IS at each date (main cover,
kappa 0.72 / 0.82) but not on whether it changed (kappa 0.40 / 0.37). So the 4b adapter learns the main
cover of the yellow box at each date; change is derived (the main covers differ), never asked.

The prompt mirrors agents/vlm_check.py (same chips, same image list and colour keys) so the base model
and the adapter are asked the same way.
"""
import json
import re

from . import vlm_check

PROMPT_VERSION = "covercheck_v1"
COVERS = ("water", "dense_vegetation", "sparse_vegetation", "crops", "bare", "built")
COVER_TEXT = {"water": "water (sea, rivers, ponds; aquaculture: fish / shrimp ponds, floating cages)",
              "dense_vegetation": "dense vegetation (forest, mangrove)",
              "sparse_vegetation": "sparse vegetation (scrub, grass)", "crops": "crops / fields (not fish ponds)",
              "bare": "bare ground (soil, rock, sand, mine, fill)", "built": "built-up (buildings, roads, concrete)"}
CANT_TELL = "cant_tell"
DATES = ("before", "after")

PROMPT = """You are describing land cover in satellite images. You get {count} {sensor} images of the same place:
{images}
Before: {{before}}. After: {{after}}. Both dates use the same colour stretch, so colour differences are real.
{keys}
Look ONLY inside the yellow box. For each date, which ONE land cover fills most of the box?
{covers}
Judge each date on its own. If cloud, haze or blur hides the box at a date, answer "cant_tell" for it.

Answer with JSON only, no other text:
{{{{"before": one of {choices},
  "after": one of {choices}}}}}"""


def build_prompt(before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = vlm_check.chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    labels = [f"{n}. {when}, {vlm_check._CHIP_TEXT[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(vlm_check._CHIP_TEXT[kind][2] + "\n" for kind in kinds if vlm_check._CHIP_TEXT[kind][2])
    sensor = "PlanetScope (3 m)" if chip_set in vlm_check.PLANET_SETS else "Sentinel-2"
    template = PROMPT.format(count=vlm_check._COUNT[2 * len(kinds)], sensor=sensor, images="   ".join(labels), keys=keys,
                             covers="".join(f"- {c}: {COVER_TEXT[c]}\n" for c in COVERS).rstrip("\n"),
                             choices=" | ".join(f'"{c}"' for c in (*COVERS, CANT_TELL)))
    return template.format(before=" to ".join(before_window), after=" to ".join(after_window))


def target(label: dict) -> dict | None:
    """{"before", "after"} main covers from a v2 per-date label (finetune_mcq); None unless both dates have one."""
    out = {}
    for when in DATES:
        d = label.get(when) or {}
        if d.get("cant_tell") or d.get("main") not in COVERS:
            return None
        out[when] = d["main"]
    return out


def parse_answer(text: str) -> dict:
    """{"before", "after", "parse_ok"} from the model's text; anything unreadable is "cant_tell", never an exception."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        raw = None
    ok = isinstance(raw, dict) and all(raw.get(w) in (*COVERS, CANT_TELL) for w in DATES)
    if not ok:
        return {"before": CANT_TELL, "after": CANT_TELL, "parse_ok": False}
    return {"before": raw["before"], "after": raw["after"], "parse_ok": True}


def derived_change(answer: dict) -> str:
    """change / no_change from the two main covers; unsure when either date is cant_tell."""
    if CANT_TELL in (answer["before"], answer["after"]):
        return "unsure"
    return "change" if answer["before"] != answer["after"] else "no_change"
