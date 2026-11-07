r"""The 4b cover examples with Dynamic World as evidence in the prompt (2026-11-07): the "dw" variant.

    python scripts\baselines_cover.py                 # writes data/finetune/baselines/dw_boxes.json (Earth Engine)
    python scripts\finetune_dw_prompts.py             # writes data/finetune/cover_dw_{train,holdout}.jsonl

Same boxes, images and targets as cover_{train,holdout}.jsonl; only the prompt changes: Dynamic World's share of
the box at each date is added as evidence (agents/cover_check.with_dw), and the model checks it against the images.
Train and evaluate with `finetune_train.py --variant dw`. Dynamic World is computed from imagery only, never from
the labels, so the held-out boxes stay untouched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import cover_check          # noqa: E402

DATA = ROOT / "data" / "finetune"


def dw_rows(rows: list[dict], shares: dict[str, dict]) -> list[dict]:
    """The rows with the Dynamic World evidence added to each prompt (boxes without DW say so)."""
    return [{**r, "prompt": cover_check.with_dw(r["prompt"], shares.get(r["id"], {}))} for r in rows]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--shares", type=Path, default=DATA / "baselines" / "dw_boxes.json")
    args = ap.parse_args(argv)
    shares = json.loads(args.shares.read_text(encoding="utf-8"))
    for split in ("train", "holdout"):
        rows = [json.loads(l) for l in (args.data / f"cover_{split}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        out = dw_rows(rows, shares)
        missing = sum(r["id"] not in shares for r in rows)
        (args.data / f"cover_dw_{split}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
        print(f"cover_dw_{split}.jsonl: {len(out)} boxes ({missing} without Dynamic World shares)")


if __name__ == "__main__":
    main()
