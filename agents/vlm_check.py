"""Geo-VLM region check (D7 candidate check, made usable from "Find changes").

For one detected region, the VLM sees before/after chips (true colour + SWIR by default; see
CHIP_SETS) with the region's box outlined, and says whether it sees real land-cover change inside the box and of what kind.
It does NOT see the detector's index values or change types: the answer is an independent
second look, compared with the detector afterwards. A "no_change" answer flags the region;
it never removes it (D7).

Labelled sites: until the Phase-4 report prompts are frozen, regions overlapping any of the
30 labelled QN sites are not sent to the model, so no prompt is ever tried on the test set.
Set LABELLED_SITES_UNLOCKED = True in the commit that freezes the Phase-4 prompts.

Answer log: every answer the model gives is appended to LOG_FILE (data/vlm_checks.jsonl, or
VLM_LOG), one JSON line each, so answers survive restarts and model / image-set comparisons can be
made afterwards (scripts/vlm_compare.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .schema import CHANGE_TYPES, region_change_types

PROMPT_VERSION = "vlmcheck_v1"
LABELLED_SITES_UNLOCKED = True     # Phase-4 prompts frozen 2026-10-27 (D19); unlocked for the 30-site run
SITES_FILE = Path(__file__).resolve().parent.parent / "data" / "quangninh" / "labels" / "sites.json"
LOG_FILE = Path(os.environ.get("VLM_LOG") or Path(__file__).resolve().parent.parent / "data" / "vlm_checks.jsonl")
VERDICTS = ("change", "no_change", "unsure")
VLM_TYPES = (*CHANGE_TYPES, "other")

# Chip sets: which before/after image pairs the model sees (ee_engine.CHIP_VIS kinds, in order).
# "rgb_swir" is the original v1 set and keeps the plain PROMPT_VERSION; the others exist to
# compare inputs before the Phase-4 freeze. Default from VLM_CHIPS, per request via `chips`.
CHIP_SETS = {"rgb": ("rgb",), "rgb_swir": ("rgb", "swir"), "rgb_swir_cir": ("rgb", "swir", "cir")}
DEFAULT_CHIP_SET = os.environ.get("VLM_CHIPS", "rgb_swir")
_CHIP_TEXT = {   # (label on its first image, label on the second, colour key or None)
    "rgb": ("true colour", "true colour", None),
    "swir": ("SWIR false colour (B11-B8-B4)", "SWIR false colour",
             "In SWIR false colour, vegetation is green, bare soil and rock are pink/brown, water is dark blue/black."),
    "cir": ("colour infrared (B8-B4-B3)", "colour infrared",
            "In colour infrared, vegetation is bright red, bare soil and built-up areas are grey/cyan/white, water is dark blue/black."),
}
_COUNT = {2: "two", 4: "four", 6: "six"}

PROMPT = """You are checking a satellite change detection. You get {count} Sentinel-2 images of the same place:
{images}
Before: {{before}}. After: {{after}}. Both dates use the same colour stretch, so colour differences are real.
{keys}
Look ONLY inside the yellow box. Did real land-cover change happen inside it between the two dates?
Ignore haze, shadows, small colour shifts and changes outside the box. If you cannot tell, say "unsure".

Answer with JSON only, no other text:
{{{{"verdict": "change" | "no_change" | "unsure",
  "change_types": [zero or more of: {types}],
  "reason": "one short sentence about what you see inside the box"}}}}"""


def chip_kinds(chip_set: str) -> tuple[str, ...]:
    if chip_set not in CHIP_SETS:
        raise ValueError(f"chips must be one of {sorted(CHIP_SETS)}")
    return CHIP_SETS[chip_set]


def chip_keys(chip_set: str) -> list[str]:
    """region_chips() keys in the order the images are sent: before/after per kind."""
    return [f"{when}_{kind}" for kind in chip_kinds(chip_set) for when in ("before", "after")]


def prompt_version(chip_set: str) -> str:
    chip_kinds(chip_set)
    return PROMPT_VERSION if chip_set == "rgb_swir" else f"{PROMPT_VERSION}_{chip_set}"


def build_prompt(before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    labels = [f"{n}. {when}, {_CHIP_TEXT[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(_CHIP_TEXT[kind][2] + "\n" for kind in kinds if _CHIP_TEXT[kind][2])
    template = PROMPT.format(count=_COUNT[2 * len(kinds)], images="   ".join(labels), keys=keys,
                             types=", ".join(VLM_TYPES))
    return template.format(before=" to ".join(before_window), after=" to ".join(after_window))


def parse_answer(text: str) -> dict:
    """{"verdict", "change_types", "reason", "parse_ok"} from the model's text. Unparseable or
    invalid answers become verdict "unsure" with parse_ok False, never an exception."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        raw = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        raw = None
    if not isinstance(raw, dict) or raw.get("verdict") not in VERDICTS:
        return {"verdict": "unsure", "change_types": [], "reason": "The model's answer could not be read.", "parse_ok": False}
    types = raw.get("change_types") or []
    types = [t for t in types if t in VLM_TYPES] if isinstance(types, list) else []
    if raw["verdict"] != "change":
        types = []
    return {"verdict": raw["verdict"], "change_types": types, "reason": str(raw.get("reason", ""))[:300], "parse_ok": True}


def compare(answer: dict, region: dict) -> dict:
    """How the VLM's answer relates to the detector's change types for this region."""
    detector = region_change_types(region)
    vlm = [t for t in answer["change_types"] if t != "other"]
    if answer["verdict"] == "no_change":
        agreement = "disagrees"            # the detector says change; the VLM sees none
    elif answer["verdict"] == "unsure":
        agreement = "unsure"
    elif not detector or not vlm:
        agreement = "change_only"          # both see change, but one side gives no type to compare
    elif set(vlm) == set(detector):
        agreement = "agrees"
    elif set(vlm) & set(detector):
        agreement = "partly"
    else:
        agreement = "different_type"
    return {"detector_types": detector, "agreement": agreement}


def check(vlm, params: dict, region: dict, bbox: tuple[float, float, float, float], chip_set: str,
          chips: dict[str, bytes], run_id: str | None = None, t0: float | None = None) -> tuple[dict, dict]:
    """Ask the model about one region whose chips are already rendered: (result, log record).
    The app endpoint and scripts/vlm_batch.py both use this, so their answers are logged alike.
    `t0` (when the chips started rendering) makes `seconds` include the rendering."""
    import time
    t0 = t0 if t0 is not None else time.time()
    version = prompt_version(chip_set)
    prompt = build_prompt(params["before_window"], params["after_window"], chip_set)
    out = vlm.generate(prompt, [chips[k] for k in chip_keys(chip_set)], replay_key=f"{version}:{region['id']}")
    answer = parse_answer(out["text"])
    result = {"region_id": region["id"], "status": "checked", **answer, **compare(answer, region),
              "model": out["model"], "prompt_version": version, "chips": chip_set, "raw": out["text"][:1000],
              "before_window": params["before_window"], "after_window": params["after_window"]}
    record = {"key": check_key(params, region["id"], version, out["model"]), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "run_id": run_id, "bbox": [round(v, 6) for v in bbox], "seconds": round(time.time() - t0, 1),
              **result, "raw": out["text"]}   # full text in the log, for replays
    return result, record


# ---------- answer log ----------
def check_key(params: dict, region_id: str, version: str, model: str) -> str:
    """Identity of one check: same analysis, region, prompt version (incl. image set) and model."""
    blob = json.dumps([params, region_id, version, model], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def log_check(record: dict, path: Path | None = None) -> None:
    path = Path(path or LOG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log(path: Path | None = None) -> list[dict]:
    """All logged checks, oldest first. Lines that aren't valid JSON (e.g. a cut-off last line) are skipped."""
    path = Path(path or LOG_FILE)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("key"):
            out.append(rec)
    return out


# ---------- labelled-site guard ----------
_site_boxes: list[tuple[float, float, float, float]] | None = None


def labelled_site_boxes() -> list[tuple[float, float, float, float]]:
    global _site_boxes
    if _site_boxes is None:
        _site_boxes = []
        if SITES_FILE.exists():
            for site in json.loads(SITES_FILE.read_text(encoding="utf-8")):
                ring = site["outline"]["coordinates"][0]
                _site_boxes.append((min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)))
    return _site_boxes


def touches_labelled_site(bbox: tuple[float, float, float, float]) -> bool:
    """True when the region's bounding box overlaps any labelled site's box (and sites are still locked)."""
    if LABELLED_SITES_UNLOCKED:
        return False
    w, s, e, n = bbox
    return any(w <= b[2] and e >= b[0] and s <= b[3] and n >= b[1] for b in labelled_site_boxes())
