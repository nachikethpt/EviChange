r"""Turn the hand labels into fine-tuning examples (Phase 4b, D17) for both tasks, and bundle the chips.

    python scripts\finetune_build.py            # data/finetune/{check,gated}_{train,holdout}.jsonl + chips.zip
    python scripts\finetune_build.py --stats    # counts only

Each example is {"id", "split", "images": [chip paths inside chips.zip], "prompt", "target"}: the exact
prompt the model gets at test time (agents/vlm_check.py, agents/gated.py, image set rgb_swir) and the
answer it should give. Upload chips.zip and the .jsonl files to Drive for notebooks/EviChange_finetune.ipynb.

Targets:
- check: {"verdict", "change_types"} = the hand label ("other" kept as a type).
- gated: built per box from the box evidence (agents/site_evidence.py) and the hand label. A claim is
  kept only when it is in the evidence AND agrees with the label; everything else becomes an
  abstention with the reason. Causes, legality and the future are always abstentions.
"Unsure" labels are left out. Train = the D17 training boxes; holdout = the 80 D15 boxes.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import finetune_data as fd                                  # noqa: E402
import vlm_batch                                            # noqa: E402
from agents import gated, site_evidence, vlm_check          # noqa: E402
from agents.schema import CHANGE_TYPES, region_change_types  # noqa: E402

OUT = ROOT / "data" / "finetune"
CHIP_SET = "rgb_swir"
MAX_LOCATED = 3            # location / type claims for at most the 3 largest regions in the box
ALWAYS_ABSTAIN = [
    {"topic": "cause of the change", "reason": "The evidence contains no information about causes."},
    {"topic": "legality or permits", "reason": "Licence and permit data are not part of the evidence."},
    {"topic": "what will happen next", "reason": "The evidence describes two dates only; no forecast is supported."},
]


def _ha(a: float) -> str:
    return f"{a:.1f}" if a < 10 else f"{a:.0f}"


def gated_target(ev: dict, label: dict) -> dict:
    """The gated answer for one box: claims in the evidence that the label agrees with, abstentions for the rest."""
    claims, abstain = [], []
    regions = ev["regions"][:MAX_LOCATED]
    if label["verdict"] == "no_change":
        if not ev["regions"]:
            claims.append({"level": "L1", "type": "presence", "text": "No change was detected in the box.",
                           "region_ref": None, "evidence_ref": ["change_frac"]})
        else:
            abstain.append({"topic": "change in the box", "reason": "The detector marked change here, but the images "
                            "show no clear land-cover change, so no change claim is made."})
        return {"claims": claims, "abstain": abstain + ALWAYS_ABSTAIN}
    # label: change
    if not ev["regions"]:
        abstain.append({"topic": "change in the box", "reason": "The images suggest change, but the detector found "
                        "none here, so there is no evidence to cite."})
        return {"claims": claims, "abstain": abstain + ALWAYS_ABSTAIN}
    claims.append({"level": "L1", "type": "presence", "text": "Change was detected in the box.",
                   "region_ref": None, "evidence_ref": ["change_frac"]})
    total = sum(r["area_ha"] for r in ev["regions"])
    claims.append({"level": "L2", "type": "extent", "text": f"About {_ha(total)} ha of the box changed "
                   f"({100 * ev['change_frac']:.0f}% of it).", "region_ref": None, "evidence_ref": ["area_ha", "change_frac"]})
    seen = set(label["types"])
    for r in regions:
        claims.append({"level": "L2", "type": "location", "text": f"Region {r['id']}: {_ha(r['area_ha'])} ha of change "
                       f"in the {r['location']} of the box.", "region_ref": r["id"], "evidence_ref": ["location", "area_ha"]})
        for name in region_change_types(r):
            field, _, words = CHANGE_TYPES[name]
            if name in seen:
                claims.append({"level": "L3", "type": "change_type", "change_type": name, "region_ref": r["id"],
                               "evidence_ref": [field], "text": f"Region {r['id']} shows {words} ({field} {r[field]:+.2f})."})
            else:
                abstain.append({"topic": f"{words} in region {r['id']}", "reason": f"{field} moved ({r[field]:+.2f}), "
                                "but the images don't show this change."})
    in_evidence = {t for r in regions for t in region_change_types(r)}
    for name in sorted(seen - in_evidence - {"other"}):
        abstain.append({"topic": CHANGE_TYPES[name][2], "reason": "The images suggest it, but no index in the evidence "
                        "supports it."})
    return {"claims": claims[:8], "abstain": abstain + ALWAYS_ABSTAIN}


def check_target(label: dict) -> dict:
    return {"verdict": label["verdict"], "change_types": label["types"] if label["verdict"] == "change" else []}


def build(labels: dict[str, dict]) -> tuple[list[dict], list[dict], dict[str, Path]]:
    """(check examples, gated examples, {zip name: chip file})."""
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    params = vlm_batch.analysis_params(fc)
    meta = fc.get("metadata") or {}
    train = json.loads(fd.BOXES.read_text(encoding="utf-8"))["boxes"]
    boxes = [{**b, "split": "train"} for b in train] + [{**b, "split": "holdout"} for b in fd.holdout_items(fc)]
    check, gate, files = [], [], {}
    for b in boxes:
        lab = labels.get(b["id"])
        if not lab or lab["verdict"] == "unsure":
            continue
        box = tuple(b["box"])
        folder = vlm_batch.chip_dir(params, box)
        names = []
        for key in vlm_check.chip_keys(CHIP_SET):
            name = f"{folder.name}/{key}.png"
            files[name] = folder / f"{key}.png"
            names.append(name)
        ev = site_evidence.site_evidence(box, fc["features"], params["before_window"], params["after_window"],
                                         source=meta.get("code_version", "regions"), pair_id=f"ft:{b['id']}")
        base = {"id": b["id"], "split": b["split"], "images": names}
        check.append({**base, "prompt": vlm_check.build_prompt(params["before_window"], params["after_window"], CHIP_SET),
                      "target": json.dumps(check_target(lab))})
        gate.append({**base, "prompt": gated.build_prompt(ev, params["before_window"], params["after_window"], CHIP_SET),
                     "target": json.dumps(gated_target(ev, lab))})
    return check, gate, files


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    labels = fd.read_labels()
    check, gate, files = build(labels)
    for split in ("train", "holdout"):
        rows = [c for c in check if c["split"] == split]
        v = Counter(json.loads(c["target"])["verdict"] for c in rows)
        print(f"{split}: {len(rows)} examples per task ({v['change']} change, {v['no_change']} no change)")
    if args.stats:
        return
    missing = [n for n, p in files.items() if not p.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} chips missing (run finetune_data.py --render): {missing[:3]}")
    OUT.mkdir(parents=True, exist_ok=True)
    for task, rows in (("check", check), ("gated", gate)):
        for split in ("train", "holdout"):
            path = OUT / f"{task}_{split}.jsonl"
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows if r["split"] == split), encoding="utf-8")
    with zipfile.ZipFile(OUT / "chips.zip", "w", zipfile.ZIP_STORED) as z:
        for name, path in sorted(files.items()):
            z.write(path, name)
    print(f"-> {OUT} (check/gated train + holdout .jsonl, chips.zip with {len(files)} images)")


if __name__ == "__main__":
    main()
