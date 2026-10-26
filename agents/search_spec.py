"""Prompted change search (D7, step 1): a typed request -> a validated SearchSpec.

The Geo-VLM only *reads the sentence*. It never sees imagery here, and it never writes a region,
an outline or a coordinate: every field below is a filter over regions the Earth Engine detector
already found, or a pair of date windows for a new run. The AOI of a new run always comes from the
area the user drew or searched, never from the model.

Anything the model gets wrong is dropped, not repaired: unknown change types, locations or land-cover
classes, negative sizes, invalid date windows. Each drop is reported in `notes`, so the app can say
what it ignored. When the model is unreachable or answers with something that is not JSON, the caller
(the app's keyword parser, explore.js `parseQuery`) takes over. `T_IDX` is not prompt-tunable, and the
detector's other options are not part of the spec yet.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .schema import CHANGE_TYPES, LANDCOVER_CLASSES, LOCATIONS, validate_windows

PROMPT_VERSION = "searchspec_v1"
SCOPES = ("all", "view", "drawn", "selection")
MAX_TOP = 100

PROMPT = """You turn a request about satellite-detected land changes into one JSON object. Reply with the JSON only.

Fields (use null when the request does not say):
  "change_types": list of {types}
  "min_ha", "max_ha": numbers, hectares (1 km2 = 100 ha)
  "locations": list of {locations}
  "top": integer, only for "largest N" / "top N"
  "class_from", "class_to": one of {classes} (land cover before / after)
  "scope": one of {scopes}  ("drawn" = inside the area the user drew, "view" = on screen)
  "before_window", "after_window": [start, end] as YYYY-MM-DD, only if the request names dates or years.
      A year Y means the dry season: ["Y-11-01", "(Y+1)-03-31"]. "before" is the earlier one.
Meaning of the types: vegetation_loss = trees or plants gone; vegetation_gain = greener;
built_up_increase = more bare ground or buildings (open-pit mining looks like this, so "mining" =
vegetation_loss + built_up_increase); built_up_decrease = less bare ground; water_increase = new or
more water; water_decrease = less water.
Do not invent coordinates, place names or outlines. Today is {today}.

Request: {request}
JSON:"""


def build_prompt(request: str, today: date | None = None) -> str:
    return PROMPT.format(types=", ".join(CHANGE_TYPES), locations=", ".join(LOCATIONS), classes=", ".join(LANDCOVER_CLASSES),
                         scopes=", ".join(SCOPES), today=(today or date.today()).isoformat(), request=request.strip()[:500])


def parse_answer(text: str) -> dict | None:
    """The first JSON object in the model's text (it may add prose or code fences), or None."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except ValueError:
                    break
        start = text.find("{", start + 1)
    return None


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def validate(raw: dict) -> tuple[dict, list[str]]:
    """(clean spec, notes about what was dropped). The clean spec always has every key."""
    notes: list[str] = []
    spec = {"change_types": None, "min_ha": None, "max_ha": None, "locations": None, "top": None,
            "class_from": None, "class_to": None, "scope": None, "before_window": None, "after_window": None}

    def pick(key, allowed, label):
        vals = raw.get(key)
        if vals is None:
            return None
        vals = [vals] if isinstance(vals, str) else vals
        good = [v for v in vals if isinstance(v, str) and v in allowed] if isinstance(vals, list) else []
        bad = [v for v in (vals if isinstance(vals, list) else [vals]) if v not in good]
        if bad:
            notes.append(f"ignored unknown {label}: {', '.join(map(str, bad))}")
        return good or None

    spec["change_types"] = pick("change_types", CHANGE_TYPES, "change type")
    spec["locations"] = pick("locations", LOCATIONS, "location")
    for key in ("min_ha", "max_ha"):
        if raw.get(key) is not None:
            spec[key] = _num(raw[key])
            if spec[key] is None:
                notes.append(f"ignored {key}: not a non-negative number")
    if spec["min_ha"] is not None and spec["max_ha"] is not None and spec["min_ha"] > spec["max_ha"]:
        spec["min_ha"], spec["max_ha"] = spec["max_ha"], spec["min_ha"]
    if raw.get("top") is not None:
        top = raw["top"]
        if isinstance(top, (int, float)) and not isinstance(top, bool) and 1 <= top <= MAX_TOP:
            spec["top"] = int(top)
        else:
            notes.append(f"ignored top: must be 1 to {MAX_TOP}")
    for key in ("class_from", "class_to"):
        if raw.get(key) is not None:
            if raw[key] in LANDCOVER_CLASSES:
                spec[key] = raw[key]
            else:
                notes.append(f"ignored unknown land-cover class: {raw[key]}")
    if raw.get("scope") is not None:
        if raw["scope"] in SCOPES:
            spec["scope"] = raw["scope"]
        else:
            notes.append(f"ignored unknown scope: {raw['scope']}")

    bw, aw = raw.get("before_window"), raw.get("after_window")
    if bw is not None or aw is not None:
        errors = validate_windows(bw, aw)
        if errors:
            notes.append("ignored the dates: " + "; ".join(errors))
        else:
            spec["before_window"], spec["after_window"] = list(bw), list(aw)
    return spec, notes


def spec_from_prompt(vlm, request: str, today: date | None = None) -> dict:
    """Ask the model. Returns {"status": "ok" | "invalid", ...}; raises VLMUnavailable when there is no model."""
    prompt = build_prompt(request, today)
    out = vlm.generate(prompt, [], max_new_tokens=300, replay_key=f"{PROMPT_VERSION}:{request.strip()}")
    raw = parse_answer(out["text"])
    base = {"model": out["model"], "prompt_version": PROMPT_VERSION, "raw": out["text"][:1000]}
    if raw is None:
        return {"status": "invalid", "detail": "the model's answer was not a JSON object", **base}
    spec, notes = validate(raw)
    if all(v is None for v in spec.values()):
        return {"status": "invalid", "detail": "the model found nothing to search for", "notes": notes, **base}
    return {"status": "ok", "spec": spec, "notes": notes, **base}
