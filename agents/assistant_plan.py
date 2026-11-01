"""Map assistant, VLM side (D9, Phase 7c): a typed request -> the same step objects the app's keyword
parser makes (webapp/frontend/assistant.js parseStep), from the Geo-VLM (text only, no images).

The app asks the keyword parser first. Only when it doesn't understand a request that looks like an
action does it call POST /api/assistant/plan. The model answers with {"steps": [...]} or {"search": true}
(not an action: the chat then searches change regions as before). Every step is checked here for its
shape (known action, the fields it needs, sane values) and again in the browser against the layers that
exist (validateStep), so a model can never run anything the parser couldn't. Layers stay phrases here;
the browser resolves them. Like the parser: nothing here starts an Earth Engine run (D7).
"""
from __future__ import annotations

import re

from .search_spec import parse_answer

PROMPT_VERSION = "assistplan_v1"
COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "violet", "pink", "cyan", "teal", "brown",
          "black", "white", "grey")
INDICES = ("NDVI", "NDBI", "MNDWI")
INDEX_KINDS = ("change", "before", "after")
FORMATS = ("geojson", "csv", "kml")
MAX_STEPS = 6

PROMPT = """You turn a request to a GIS map app into a list of tool steps. Reply with JSON only.

Layers on the map: {layers}. "it" / "the result" means the layer the previous step made.
Steps (use only these, with exactly these fields):
  {{"action": "style_layer", "layer": <layer>, "color": one of {colors} or "#rrggbb" (optional), "opacity": 0..1 (optional; 95 % transparent = 0.05)}}
  {{"action": "buffer", "layer": <layer>, "distance": number, "units": "meters" | "kilometers"}}
  {{"action": "clip", "layer": <layer>, "other": <layer>}}
  {{"action": "intersect", "layer": <layer>, "other": <layer>}}
  {{"action": "dissolve", "layer": <layer>, "field": attribute name or ""}}
  {{"action": "add_index_layer", "index": one of {indices}, "kind": one of {kinds}}}
  {{"action": "export", "layer": <layer>, "format": one of {formats}, "selectedOnly": true | false}}
  {{"action": "zoom", "layer": <layer>}}
  {{"action": "chart"}}
  {{"action": "undo"}}
<layer> is a layer's name as listed, or "it".
If the request is a search for changes (e.g. "forest loss in the north", "largest new buildings") and not
a tool action, reply {{"search": true}}. If it asks for something none of the steps can do, reply {{"steps": []}}.
Never start an analysis run.

Request: {request}
JSON:"""


def build_prompt(request: str, layer_names: list[str]) -> str:
    names = ", ".join(f'"{n}"' for n in layer_names[:30]) or "none"
    return PROMPT.format(layers=names, colors=", ".join(COLORS), indices=", ".join(INDICES), kinds=", ".join(INDEX_KINDS),
                         formats=", ".join(FORMATS), request=request.strip()[:500])


def _layer(v) -> str | None:
    return v.strip()[:120] if isinstance(v, str) and v.strip() else None


def _number(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check_step(raw: dict) -> tuple[dict | None, str | None]:
    """(clean step, None) or (None, why it was dropped)."""
    if not isinstance(raw, dict):
        return None, "a step that isn't an object"
    act = raw.get("action")
    if act in ("undo", "chart"):
        return {"action": act}, None
    if act == "add_index_layer":
        idx, kind = str(raw.get("index", "")).upper(), raw.get("kind", "change")
        if idx not in INDICES or kind not in INDEX_KINDS:
            return None, f"index layer {idx or '?'} {kind}"
        return {"action": act, "index": idx, "kind": kind}, None
    layer = _layer(raw.get("layer"))
    if layer is None:
        return None, f"{act or 'a step'} without a layer"
    if act == "style_layer":
        step = {"action": act, "layer": layer}
        color = str(raw.get("color") or "").lower()
        if color == "gray":
            color = "grey"
        if color and (color in COLORS or re.fullmatch(r"#[0-9a-f]{6}", color)):
            step["color"] = color
        op = _number(raw.get("opacity"))
        if op is not None:
            if not 0 <= op <= 1:
                return None, "opacity outside 0..1"
            step["opacity"] = op
        if len(step) == 2:
            return None, "style without a colour or opacity"
        return step, None
    if act == "buffer":
        d, units = _number(raw.get("distance")), raw.get("units", "meters")
        if not d or units not in ("meters", "kilometers"):
            return None, "buffer without a non-zero distance in meters or kilometers"
        return {"action": act, "layer": layer, "distance": d, "units": units}, None
    if act in ("clip", "intersect"):
        other = _layer(raw.get("other"))
        return ({"action": act, "layer": layer, "other": other}, None) if other else (None, f"{act} without a second layer")
    if act == "dissolve":
        field = raw.get("field") or ""
        if not isinstance(field, str) or (field and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field)):
            return None, "dissolve by an invalid field"
        return {"action": act, "layer": layer, "field": field}, None
    if act == "export":
        fmt = str(raw.get("format", "")).lower()
        if fmt not in FORMATS:
            return None, f"export as {fmt or '?'}"
        return {"action": act, "layer": layer, "format": fmt, "selectedOnly": bool(raw.get("selectedOnly"))}, None
    if act == "zoom":
        return {"action": act, "layer": layer}, None
    return None, f"unknown action {act!r}"


def validate(raw: dict) -> dict:
    """{"status": "ok", "steps", "notes"} | {"status": "search"} | {"status": "invalid", "detail", "notes"}.
    One bad step makes the whole plan invalid: a half-run request is worse than none."""
    if raw.get("search") is True and not raw.get("steps"):
        return {"status": "search"}
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        return {"status": "invalid", "detail": "the model found no tool step for this request", "notes": []}
    if len(steps) > MAX_STEPS:
        return {"status": "invalid", "detail": f"more than {MAX_STEPS} steps", "notes": []}
    clean, notes = [], []
    for s in steps:
        step, why = check_step(s)
        if why:
            notes.append(why)
        else:
            clean.append(step)
    if notes:
        return {"status": "invalid", "detail": "the model proposed a step the app can't run: " + "; ".join(notes), "notes": notes}
    if any(s.get("layer") in ("it", "the result") for s in clean[:1]):
        return {"status": "invalid", "detail": "the first step refers to “it”", "notes": []}
    return {"status": "ok", "steps": clean, "notes": []}


def plan_from_prompt(vlm, request: str, layer_names: list[str]) -> dict:
    """Ask the model. Raises VLMUnavailable when there is no model."""
    out = vlm.generate(build_prompt(request, layer_names), [], max_new_tokens=400,
                       replay_key=f"{PROMPT_VERSION}:{request.strip()}")
    base = {"model": out["model"], "prompt_version": PROMPT_VERSION, "raw": out["text"][:1000]}
    raw = parse_answer(out["text"])
    if raw is None:
        return {"status": "invalid", "detail": "the model's answer was not a JSON object", "notes": [], **base}
    return {**validate(raw), **base}
