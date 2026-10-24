r"""LoRA fine-tuning of the Geo-VLM (Phase 4b, D17). Runs in Colab (notebooks/EviChange_finetune.ipynb) on an
A100; needs `transformers`, `peft`, `accelerate`, `pillow`. The base weights stay frozen: only small LoRA
adapters on the language model's attention and MLP layers are trained (the vision encoder is untouched).

    python scripts/finetune_train.py train --task check --data /content/ft --out /content/drive/MyDrive/evichange_ft
    python scripts/finetune_train.py eval  --task check --data /content/ft --adapter /content/drive/MyDrive/evichange_ft/check
    python scripts/finetune_train.py eval  --task check --data /content/ft --base-only     # the untrained baseline

Data: data/finetune/{task}_{train,holdout}.jsonl and chips.zip from scripts/finetune_build.py, unzipped into --data.
Training masks the prompt: the loss is only on the answer tokens. Greedy decoding at eval, as the server.
`eval` writes predictions_{task}_{name}.jsonl next to the adapter (or in --data for the baseline) and, for
the check, prints balanced accuracy against the held-out hand labels (the D15 measure).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
LORA_SUFFIXES = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
DEFAULTS = {"epochs": 3, "lr": 1e-4, "accum": 8, "rank": 16, "alpha": 32, "dropout": 0.05, "seed": 17}


# ---------- data (plain Python, tested locally) ----------
def load_examples(data: Path, task: str, split: str) -> list[dict]:
    path = Path(data) / f"{task}_{split}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def lora_targets(module_names: list[str]) -> list[str]:
    """The language model's attention / MLP projections; never the vision encoder ('visual')."""
    return [n for n in module_names if n.split(".")[-1] in LORA_SUFFIXES and "visual" not in n]


def balanced_accuracy(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (hand label verdict, predicted verdict) on firm labels; 'unsure' predictions count as misses."""
    change = [p for t, p in pairs if t == "change"]
    nochange = [p for t, p in pairs if t == "no_change"]
    hc = sum(p == "change" for p in change) / len(change) if change else None
    hn = sum(p == "no_change" for p in nochange) / len(nochange) if nochange else None
    bal = (hc + hn) / 2 if hc is not None and hn is not None else None
    return {"n": len(pairs), "on_change": hc, "on_no_change": hn, "balanced": bal}


def score(task: str, examples: list[dict], predictions: dict[str, str]) -> dict:
    """Parse each prediction with the parser the app and evaluation use; for the check, balanced accuracy."""
    from agents import gated, vlm_check
    out = {"n": len(examples), "parse_failures": 0}
    pairs = []
    for ex in examples:
        text = predictions.get(ex["id"], "")
        if task == "check":
            ans = vlm_check.parse_answer(text)
            out["parse_failures"] += not ans["parse_ok"]
            pairs.append((json.loads(ex["target"])["verdict"], ans["verdict"]))
        else:
            ok = gated.parse_report(text)[2]
            out["parse_failures"] += not ok
    if task == "check":
        out.update(balanced_accuracy(pairs))
    return out


# ---------- model (Colab only) ----------
def _load(base: str, adapter: str | None = None, train: bool = False, args=None):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    model = AutoModelForImageTextToText.from_pretrained(base, torch_dtype=torch.bfloat16, device_map="auto")
    processor = AutoProcessor.from_pretrained(base, min_pixels=256 * 28 * 28, max_pixels=1024 * 28 * 28)  # as the server
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
    elif train:
        from peft import LoraConfig, get_peft_model
        names = [n for n, m in model.named_modules() if isinstance(m, torch.nn.Linear)]
        cfg = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, target_modules=lora_targets(names),
                         task_type="CAUSAL_LM")
        model = get_peft_model(model, cfg)
        model.print_trainable_parameters()
    return model, processor


def _images(data: Path, ex: dict):
    from PIL import Image
    return [Image.open(Path(data) / name).convert("RGB") for name in ex["images"]]


def _messages(ex: dict, n_images: int, with_answer: bool) -> list[dict]:
    msgs = [{"role": "user", "content": [{"type": "image"} for _ in range(n_images)] + [{"type": "text", "text": ex["prompt"]}]}]
    if with_answer:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": ex["target"]}]})
    return msgs


def _batch(processor, data: Path, ex: dict, device):
    """Inputs with labels: -100 on every prompt token, so only the answer is learned."""
    imgs = _images(data, ex)
    full = processor.apply_chat_template(_messages(ex, len(imgs), True), tokenize=False)
    prompt = processor.apply_chat_template(_messages(ex, len(imgs), False), tokenize=False, add_generation_prompt=True)
    enc = processor(text=[full], images=imgs, return_tensors="pt")
    n_prompt = processor(text=[prompt], images=imgs, return_tensors="pt")["input_ids"].shape[1]
    labels = enc["input_ids"].clone()
    labels[:, :n_prompt] = -100
    enc["labels"] = labels
    return {k: v.to(device) for k, v in enc.items()}


def train(args) -> None:
    import torch
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    examples = load_examples(args.data, args.task, "train")
    model, processor = _load(args.base, train=True, args=args)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    steps = args.epochs * len(examples) // args.accum
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) * max(0.0, 1 - s / max(1, steps)))
    model.train()
    step = 0
    for epoch in range(args.epochs):
        order = examples[:]
        random.shuffle(order)
        total = 0.0
        for i, ex in enumerate(order, 1):
            loss = model(**_batch(processor, args.data, ex, model.device)).loss / args.accum
            loss.backward()
            total += loss.item() * args.accum
            if i % args.accum == 0 or i == len(order):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step(); sched.step(); opt.zero_grad()
                step += 1
            if i % 50 == 0:
                print(f"epoch {epoch + 1} example {i}/{len(order)} mean loss {total / i:.4f}", flush=True)
        print(f"epoch {epoch + 1} done: mean loss {total / len(order):.4f}", flush=True)
    out = Path(args.out) / args.task
    model.save_pretrained(out)
    (out / "train_config.json").write_text(json.dumps({**{k: getattr(args, k) for k in DEFAULTS}, "base": args.base,
                                                       "task": args.task, "n_train": len(examples)}, indent=1))
    print(f"adapter -> {out}")


def evaluate(args) -> None:
    import torch
    examples = load_examples(args.data, args.task, "holdout")
    model, processor = _load(args.base, adapter=None if args.base_only else args.adapter)
    model.eval()
    preds = {}
    for i, ex in enumerate(examples, 1):
        imgs = _images(args.data, ex)
        text = processor.apply_chat_template(_messages(ex, len(imgs), False), tokenize=False, add_generation_prompt=True)
        enc = processor(text=[text], images=imgs, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=900 if args.task == "gated" else 300, do_sample=False)
        preds[ex["id"]] = processor.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
        if i % 20 == 0:
            print(f"{i}/{len(examples)}", flush=True)
    name = "base" if args.base_only else "ft"
    dest = (Path(args.data) if args.base_only else Path(args.adapter)) / f"predictions_{args.task}_{name}.jsonl"
    dest.write_text("".join(json.dumps({"id": k, "text": v}) + "\n" for k, v in preds.items()), encoding="utf-8")
    print(json.dumps(score(args.task, examples, preds), indent=1))
    print(f"predictions -> {dest}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("train", "eval"))
    ap.add_argument("--task", choices=("check", "gated"), required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--out", default="/content/drive/MyDrive/evichange_ft")
    ap.add_argument("--adapter")
    ap.add_argument("--base-only", action="store_true")
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k}", type=type(v), default=v)
    args = ap.parse_args(argv)
    if args.cmd == "train":
        train(args)
    else:
        if not args.base_only and not args.adapter:
            raise SystemExit("eval needs --adapter or --base-only")
        evaluate(args)


if __name__ == "__main__":
    main()
