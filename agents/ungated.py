"""Ungated report arms (D16): a model looks at the before/after chips with no evidence and no
rules, writes free text, and an extractor splits that text into claims for the verifier.

Both ungated arms use this module unchanged, so they differ only in the model that writes:
  ungated      Qwen2.5-VL (VLMClient), the pre-specified primary comparison with gated
  ungated_gpt  GPT (GPTClient), the secondary comparison (D16)
The extractor is always the Geo-VLM (VLMClient, text only) with its own prompt, so extraction
errors fall on both arms the same way. It copies statements, it never judges them.

Prompts are drafts (v0): develop them on QN regions outside the 30 labelled sites and freeze
them with the other Phase-4 prompts. The chips are the ones vlm_check renders (yellow box).
"""
from __future__ import annotations

import json
import re

from . import vlm_check
from .schema import CHANGE_TYPES, CLAIM_TYPES, LANDCOVER_CLASSES, validate_claim

REPORT_PROMPT_VERSION = "ungated_report_v0"
EXTRACT_PROMPT_VERSION = "claim_extract_v0"

REPORT_PROMPT = """You are a remote-sensing analyst. You get {count} Sentinel-2 images of the same place:
{images}
Before: {before}. After: {after}. Both dates use the same colour stretch, so colour differences are real.
{keys}
Write a short report (3 to 6 sentences) for a decision maker about the area inside the yellow box:
what changed between the two dates, where in the box, and roughly how large the change is."""

EXTRACT_PROMPT = """Split the satellite change report below into separate claims. Each claim is ONE statement
the report makes. Copy the report's wording as closely as possible. Do not add, merge, correct, judge
or leave out statements.

For each claim give:
  "text":  the statement
  "level": "L1" = whether change happened at all
           "L2" = how much changed (hectares, percent, size words) or where it is
           "L3" = what kind of change or land cover
           "L4" = cause, purpose, legality, who did it, or what will happen next
  "type":  one of {types}
  "change_type": one of {change_types}, or null
  "class_before", "class_after": one of {classes}, or null (only for land-cover statements)

Answer with a JSON list only, no other text.

REPORT:
{report}"""


def build_report_prompt(before_window: list[str], after_window: list[str], chip_set: str = "rgb_swir") -> str:
    kinds = vlm_check.chip_kinds(chip_set)
    pairs = [(kind, i, when) for kind in kinds for i, when in enumerate(("BEFORE", "AFTER"))]
    text = vlm_check._CHIP_TEXT
    labels = [f"{n}. {when}, {text[kind][i]}" for n, (kind, i, when) in enumerate(pairs, 1)]
    keys = "".join(text[kind][2] + "\n" for kind in kinds if text[kind][2])
    return REPORT_PROMPT.format(count=vlm_check._COUNT[2 * len(kinds)], images="   ".join(labels), keys=keys,
                                before=" to ".join(before_window), after=" to ".join(after_window))


def build_extract_prompt(report: str) -> str:
    return EXTRACT_PROMPT.format(types=", ".join(CLAIM_TYPES), change_types=", ".join(CHANGE_TYPES),
                                 classes=", ".join(LANDCOVER_CLASSES), report=report.strip())


def parse_claims(text: str) -> tuple[list[dict], bool, int]:
    """(claims, parse_ok, dropped) from the extractor's text. Items that break the claim schema
    are dropped and counted (a parse failure, evaluation metric 8), never repaired."""
    match = re.search(r"\[.*\]", text or "", re.S)
    try:
        items = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        items = None
    if not isinstance(items, list):
        return [], False, 0
    claims, dropped = [], 0
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            dropped += 1
            continue
        claim = {"level": item.get("level"), "type": item.get("type"), "text": str(item["text"]).strip(),
                 "region_ref": None, "evidence_ref": [], "stated_conf": None}
        for field in ("change_type", "class_before", "class_after"):
            if item.get(field) is not None:
                claim[field] = item[field]
        if validate_claim(claim):
            dropped += 1
            continue
        claims.append(claim)
    for i, c in enumerate(claims, 1):
        c["claim_id"] = f"c{i}"
    return claims, True, dropped


def run_ungated(writer, extractor, arm: str, key: str, before_window: list[str], after_window: list[str],
                images: list[bytes], chip_set: str = "rgb_swir") -> dict:
    """One ungated report: `writer` (VLMClient or GPTClient) writes free text from the chips, then
    `extractor` (VLMClient) splits it into claims. `key` names the site or selection for replay
    files. Raises VLMUnavailable if either model is unavailable."""
    prompt = build_report_prompt(before_window, after_window, chip_set)
    out = writer.generate(prompt, images, max_new_tokens=600, replay_key=f"{REPORT_PROMPT_VERSION}:{arm}:{key}")
    ext = extractor.generate(build_extract_prompt(out["text"]), [], max_new_tokens=1200,
                             replay_key=f"{EXTRACT_PROMPT_VERSION}:{arm}:{key}")
    claims, parse_ok, dropped = parse_claims(ext["text"])
    return {"raw": out["text"], "model": out["model"], "claims": claims, "parse_ok": parse_ok, "dropped": dropped,
            "extractor_model": ext["model"], "prompt_version": REPORT_PROMPT_VERSION,
            "extract_version": EXTRACT_PROMPT_VERSION, "chips": chip_set}
