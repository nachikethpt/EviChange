"""A learned verifier for the ablation: the same claims and box evidence as agents/verifier.py, judged
by a natural-language-inference (NLI) model instead of rules.

The evidence is written out as plain sentences (the premise) and each claim is the hypothesis:
entailment -> supported, contradiction -> unsupported, otherwise uncertain. Nothing else is borrowed
from the rule verifier (no thresholds, no L4 rule), so the comparison isolates "rules vs a learned
judge" (docs/related_work.md: no head-to-head on structured evidence was found).

The model is any callable (premise, hypothesis) -> {"entailment": p, "neutral": p, "contradiction": p}.
hf_nli() wraps a Hugging Face cross-encoder; it needs `pip install transformers torch` and is never
imported by the app or the tests.
"""
from __future__ import annotations

from typing import Callable

from .schema import CHANGE_TYPES, T_IDX
from .verifier import Verdict

NLIModel = Callable[[str, str], dict]
DEFAULT_MODEL = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli"
THRESHOLD = 0.5
_INDEX_WORDS = {"dNDVI": "vegetation index (NDVI)", "dNDBI": "built-up / bare index (NDBI)", "dMNDWI": "water index (MNDWI)"}


def _change_words(region: dict) -> list[str]:
    out = []
    for name, (field, sign, label) in CHANGE_TYPES.items():
        v = region.get(field)
        if isinstance(v, (int, float)) and sign * v > T_IDX:
            out.append(label)
    return out


def evidence_text(ev: dict) -> str:
    """The box evidence as sentences an NLI model can read. Deterministic; every fact the rule verifier
    can use is stated, so neither verifier sees more than the other."""
    regions = ev.get("regions") or []
    if not regions:
        parts = ["No change was detected in the area."]
    else:
        total = sum(r["area_ha"] for r in regions)
        parts = [f"Change was detected in the area: {len(regions)} region{'s' if len(regions) > 1 else ''}, "
                 f"{total:.1f} ha in total, {100 * ev.get('change_frac', 0):.0f} % of the area."]
    for r in regions:
        s = f"Region {r['id']} is in the {r['location']} and covers {r['area_ha']:.1f} ha."
        idx = "; ".join(f"the {_INDEX_WORDS[f]} changed by {r[f]:+.2f}" for f in _INDEX_WORDS if isinstance(r.get(f), (int, float)))
        kinds = _change_words(r)
        s += f" There {idx}." if idx else ""
        s += f" This indicates {', '.join(kinds)}." if kinds else " No index changed clearly."
        if r.get("class_before") and r.get("class_after"):
            s += (f" Its land cover stayed {r['class_before'].replace('_', ' ')}." if r["class_before"] == r["class_after"]
                  else f" Its land cover changed from {r['class_before'].replace('_', ' ')} to {r['class_after'].replace('_', ' ')}.")
        s += f" Detection confidence is {r.get('mean_conf', 0):.2f}."
        parts.append(s)
    for t in ev.get("transects") or []:
        nsm = f"{abs(t['nsm']):.0f} m {'seaward' if t['nsm'] > 0 else 'landward'}" if t.get("nsm") is not None else "an unknown distance"
        parts.append(f"At transect {t['id']} in the {t['location']} the shoreline is {t['change']}, net movement {nsm}.")
    for st in ev.get("coastal_strips") or []:
        parts.append(f"Built area {st['strip']} m from the shore went from {st['built_ha_before']:.1f} ha to {st['built_ha_after']:.1f} ha.")
    return " ".join(parts)


def nli_verify(claim: dict, ev: dict, model: NLIModel, threshold: float = THRESHOLD) -> Verdict:
    scores = model(evidence_text(ev), claim["text"])
    if scores.get("entailment", 0) >= threshold:
        return Verdict("supported", "nli_entailment")
    if scores.get("contradiction", 0) >= threshold:
        return Verdict("unsupported", "nli_contradiction")
    return Verdict("uncertain", "nli_neutral")


def hf_nli(model_name: str = DEFAULT_MODEL) -> NLIModel:          # pragma: no cover - needs transformers + weights
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch
    tok = AutoTokenizer.from_pretrained(model_name)
    mdl = AutoModelForSequenceClassification.from_pretrained(model_name).eval()
    labels = {i: name.lower() for i, name in mdl.config.id2label.items()}

    def run(premise: str, hypothesis: str) -> dict:
        with torch.no_grad():
            logits = mdl(**tok(premise, hypothesis, truncation=True, return_tensors="pt")).logits[0]
        probs = torch.softmax(logits, -1).tolist()
        return {labels[i]: p for i, p in enumerate(probs)}
    return run
