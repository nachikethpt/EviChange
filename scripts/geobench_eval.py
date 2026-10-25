r"""GEOBench-VLM temporal tasks as an outside yardstick for the Geo-VLM choice (D15 addendum).

Runs a model on the multiple-choice questions of GEOBench-VLM's Temporal set (crop type, disaster type,
farm-pond change, land use, damaged-building count; Danish et al., ICCV 2025) and reports accuracy per
task, with the random-guess level (1 in 5). Evaluation only: the benchmark is never used for training.
Runs in Colab (notebooks/EviChange_geobench.ipynb) with the model loaded directly; same greedy decoding
and image limits as the server notebook.

    python scripts/geobench_eval.py --data /content/geobench/Temporal --model Qwen/Qwen2.5-VL-7B-Instruct
    python scripts/geobench_eval.py --data ... --model Qwen/Qwen3-VL-8B-Instruct --limit 200

Writes geobench_<model>.jsonl (one answer per question) and prints the per-task table. Resumable: questions
already in the output file are skipped.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

LETTERS = "ABCDE"
TASK_KEYS = ("task", "task_name", "category", "type")


# ---------- plain Python (tested locally) ----------
def load_questions(data: Path) -> list[dict]:
    qa = json.loads((Path(data) / "qa.json").read_text(encoding="utf-8"))
    return qa if isinstance(qa, list) else list(qa.values())


def task_of(q: dict, default: str = "temporal") -> str:
    for k in TASK_KEYS:
        if isinstance(q.get(k), str) and q[k]:
            return q[k]
    path = q.get("image_path")
    first = path[0] if isinstance(path, list) and path else path
    return Path(first).parts[0] if isinstance(first, str) and len(Path(first).parts) > 1 else default


def image_paths(q: dict, data: Path) -> list[Path]:
    p = q.get("image_path") or q.get("image_paths") or []
    paths = p if isinstance(p, list) else [p]
    root = Path(data)
    return [root / x if (root / x).exists() else root / "images" / x for x in paths]


def build_prompt(q: dict) -> str:
    prompts = q.get("prompts") or [q.get("question", "")]
    question = prompts[0] if isinstance(prompts, list) else str(prompts)
    return f"{question}\n{q['options']}\nAnswer with the letter of the correct option only (A, B, C, D or E)."


def parse_letter(text: str) -> str | None:
    """The first standalone option letter in the answer ('B', 'B.', '(B)', 'Answer: B'), else None."""
    m = re.search(r"(?<![A-Za-z])([A-E])(?![A-Za-z])", (text or "").strip())
    return m.group(1) if m else None


def table(rows: list[dict]) -> str:
    per = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        t = per[r["task"]]
        t[0] += 1
        t[1] += r["pred"] == r["gt"]
        t[2] += r["pred"] is None
    lines = ["| task | questions | accuracy | unparsed |", "|---|---|---|---|"]
    for task in sorted(per):
        n, ok, bad = per[task]
        lines.append(f"| {task} | {n} | {ok / n:.1%} | {bad} |")
    n = sum(v[0] for v in per.values())
    ok = sum(v[1] for v in per.values())
    lines.append(f"| **all** | {n} | **{ok / n:.1%}** | {sum(v[2] for v in per.values())} |" if n else "| all | 0 | – | – |")
    lines.append("| random guess | | 20.0% | |")
    return "\n".join(lines)


# ---------- model (Colab only) ----------
def run(args) -> None:
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor
    out = Path(args.out or f"geobench_{args.model.split('/')[-1]}.jsonl")
    done = {json.loads(line)["question_id"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    questions = [q for q in load_questions(args.data) if q["question_id"] not in done][: args.limit]
    model = AutoModelForImageTextToText.from_pretrained(args.model, torch_dtype=torch.bfloat16, device_map="auto")
    kw = {"min_pixels": 256 * 28 * 28, "max_pixels": 1024 * 28 * 28} if "Qwen2.5" in args.model else {}
    processor = AutoProcessor.from_pretrained(args.model, **kw)
    with open(out, "a", encoding="utf-8") as f:
        for i, q in enumerate(questions, 1):
            imgs = [Image.open(p).convert("RGB") for p in image_paths(q, args.data)]
            msgs = [{"role": "user", "content": [{"type": "image"} for _ in imgs] + [{"type": "text", "text": build_prompt(q)}]}]
            text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            enc = processor(text=[text], images=imgs or None, return_tensors="pt").to(model.device)
            with torch.no_grad():
                gen = model.generate(**enc, max_new_tokens=16, do_sample=False)
            answer = processor.batch_decode(gen[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
            f.write(json.dumps({"question_id": q["question_id"], "task": task_of(q), "gt": q["ground_truth_option"],
                                "pred": parse_letter(answer), "raw": answer}) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"{i}/{len(questions)}", flush=True)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    print(f"{args.model} on GEOBench-VLM Temporal\n\n{table(rows)}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="the unzipped Temporal folder (has qa.json)")
    ap.add_argument("--model", default="Qwen/Qwen2.5-VL-7B-Instruct")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    ap.add_argument("--table", type=Path, help="only print the table of an existing answers file")
    args = ap.parse_args(argv)
    if args.table:
        print(table([json.loads(line) for line in args.table.read_text(encoding="utf-8").splitlines()]))
        return
    run(args)


if __name__ == "__main__":
    main()
