r"""LoRA fine-tuning of the Geo-VLM (Phase 4b, D17). Runs in Colab (notebooks/EviChange_finetune.ipynb) on an
A100; needs `transformers`, `peft`, `accelerate`, `pillow`. The base weights stay frozen: only small LoRA
adapters on the language model's attention and MLP layers are trained (the vision encoder is untouched).

    python scripts/finetune_train.py train --task check --data /content/ft --out /content/drive/MyDrive/evichange_ft
    python scripts/finetune_train.py eval  --task check --data /content/ft --adapter /content/drive/MyDrive/evichange_ft/check
    python scripts/finetune_train.py eval  --task check --data /content/ft --base-only     # the untrained baseline
    python scripts/finetune_train.py eval  --task cover --data /content/ft --base-only --base Qwen/Qwen3-VL-8B-Instruct
                                                                    # another model, zero-shot (COMPARE_MODELS)

Data: data/finetune/{task}_{train,holdout}.jsonl and chips.zip from scripts/finetune_build.py, unzipped into --data.
Training masks the prompt: the loss is only on the answer tokens. Greedy decoding at eval, as the server.
`eval` writes predictions_{task}_{name}.jsonl next to the adapter (or in --data for the baseline) and, for
the check, prints balanced accuracy against the held-out hand labels (the D15 measure); for the cover task (the
4b target since 2026-11-02, D17), main-cover accuracy per date and the balanced accuracy of the derived change.
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
DEFAULTS = {"epochs": 3, "lr": 1e-4, "accum": 8, "rank": 16, "alpha": 32, "dropout": 0.05, "seed": 17,
            "change_weight": 1}
# change_weight (cover task): each training box whose main cover differs between the dates is shown this many
# times per epoch. 1 = as labelled. The first 4b run (2026-11-07, weight 1: 64 of 327 boxes change) learned to
# repeat the before cover and never predicted a change; the second run uses 3.

# Zero-shot comparison on the cover hold-out (2026-11-07): open models that load with AutoModelForImageTextToText,
# none gated on Hugging Face. 4-bit = loaded with bitsandbytes (a 40 GB A100 can't hold 32B in bf16).
COMPARE_MODELS = [
    {"base": "Qwen/Qwen3-VL-8B-Instruct", "four_bit": False},
    {"base": "OpenGVLab/InternVL3-8B-hf", "four_bit": False},
    {"base": "Qwen/Qwen2.5-VL-32B-Instruct", "four_bit": True},
]


def model_tag(base: str) -> str:
    """File-name tag for a model's predictions: 'base' for the system model (the name used since 4b run 1)."""
    if base == BASE_MODEL:
        return "base"
    return base.split("/")[-1].lower().replace(".", "_")


def processor_kwargs(base: str) -> dict:
    """Qwen's image-size limits, as the server; other processors don't take them."""
    return {"min_pixels": 256 * 28 * 28, "max_pixels": 1024 * 28 * 28} if "qwen" in base.lower() else {}


# ---------- data (plain Python, tested locally) ----------
def load_examples(data: Path, task: str, split: str, variant: str = "") -> list[dict]:
    """{task}[_{variant}]_{split}.jsonl; variant "dw" = the cover prompt with Dynamic World evidence."""
    path = Path(data) / f"{task}{'_' + variant if variant else ''}_{split}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_folds(examples: list[dict], folds: int, seed: int = 17) -> list[list[str]]:
    """Box ids in `folds` groups, stratified on change / no change and seeded, so every fold has change boxes.
    Cross-validation uses only the training boxes; the held-out boxes are never in a fold."""
    rng = random.Random(seed)
    out: list[list[str]] = [[] for _ in range(folds)]
    k = 0
    for group in (sorted(e["id"] for e in examples if is_change(e)), sorted(e["id"] for e in examples if not is_change(e))):
        rng.shuffle(group)
        for i in group:
            out[k % folds].append(i)
            k += 1
    return out


def run_name(args) -> str:
    """Prediction / score file tag: the model, the prompt variant."""
    return (model_tag(args.base) if args.base_only else "ft") + (f"_{args.variant}" if args.variant else "")


def is_change(ex: dict) -> bool:
    """A cover example whose target main cover differs between the two dates."""
    try:
        target = json.loads(ex["target"])
    except (TypeError, ValueError, KeyError):
        return False
    return isinstance(target, dict) and target.get("before") is not None and target.get("before") != target.get("after")


def weighted(examples: list[dict], task: str, change_weight: int = 1) -> list[dict]:
    """One epoch's examples: change boxes repeated change_weight times (cover task only; others unchanged)."""
    if task != "cover" or change_weight <= 1:
        return list(examples)
    return [ex for ex in examples for _ in range(change_weight if is_change(ex) else 1)]


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


def cover_scores(rows: list[tuple[dict, dict]]) -> dict:
    """rows = (target {"before", "after"}, parsed answer): main-cover accuracy per date ("cant_tell" counts as a
    miss) and the balanced accuracy of the change derived from the two covers."""
    from agents import cover_check
    dates = [(t[w], a[w]) for t, a in rows for w in cover_check.DATES]
    acc = sum(x == y for x, y in dates) / len(dates) if dates else None
    pairs = [(cover_check.derived_change(t), cover_check.derived_change(a)) for t, a in rows]
    return {"main_cover_accuracy": acc, "derived_change": balanced_accuracy(pairs)}


def score(task: str, examples: list[dict], predictions: dict[str, str]) -> dict:
    """Parse each prediction with the parser the app and evaluation use; for the check, balanced accuracy;
    for the cover task, main-cover accuracy and the derived change."""
    from agents import cover_check, gated, vlm_check
    out = {"n": len(examples), "parse_failures": 0}
    pairs, covers = [], []
    for ex in examples:
        text = predictions.get(ex["id"], "")
        if task == "cover":
            ans = cover_check.parse_answer(text)
            out["parse_failures"] += not ans["parse_ok"]
            covers.append((json.loads(ex["target"]), ans))
        elif task == "check":
            ans = vlm_check.parse_answer(text)
            out["parse_failures"] += not ans["parse_ok"]
            pairs.append((json.loads(ex["target"])["verdict"], ans["verdict"]))
        else:
            ok = gated.parse_report(text)[2]
            out["parse_failures"] += not ok
    if task == "check":
        out.update(balanced_accuracy(pairs))
    if task == "cover":
        out.update(cover_scores(covers))
    return out


# ---------- model (Colab only) ----------
def _load(base: str, adapter: str | None = None, train: bool = False, args=None):
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    extra = {}
    if getattr(args, "four_bit", False):
        from transformers import BitsAndBytesConfig
        extra["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                          bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForImageTextToText.from_pretrained(base, torch_dtype=torch.bfloat16, device_map="auto", **extra)
    processor = AutoProcessor.from_pretrained(base, **processor_kwargs(base))
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
    elif train:
        from peft import LoraConfig, get_peft_model
        if extra:                                       # QLoRA: LoRA on a 4-bit base (e.g. the 32B model)
            from peft import prepare_model_for_kbit_training
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        names = [n for n, m in model.named_modules() if isinstance(m, (torch.nn.Linear,)) or type(m).__name__ == "Linear4bit"]
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


def predict(model, processor, data: Path, examples: list[dict], task: str) -> dict[str, str]:
    """Greedy answers (as the server) for each example: {id: text}."""
    import torch
    model.eval()
    preds = {}
    for i, ex in enumerate(examples, 1):
        imgs = _images(data, ex)
        text = processor.apply_chat_template(_messages(ex, len(imgs), False), tokenize=False, add_generation_prompt=True)
        enc = processor(text=[text], images=imgs, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=900 if task == "gated" else 300, do_sample=False)
        preds[ex["id"]] = processor.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
        if i % 20 == 0:
            print(f"{i}/{len(examples)}", flush=True)
    return preds


def _write_preds(dest: Path, preds: dict[str, str]) -> None:
    dest.write_text("".join(json.dumps({"id": k, "text": v}) + "\n" for k, v in preds.items()), encoding="utf-8")


def train(args) -> None:
    import torch
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    all_train = load_examples(args.data, args.task, "train", args.variant)
    held = []
    if args.folds:
        fold_ids = set(split_folds(all_train, args.folds)[args.fold])
        held = [e for e in all_train if e["id"] in fold_ids]
        all_train = [e for e in all_train if e["id"] not in fold_ids]
        print(f"fold {args.fold} of {args.folds}: train on {len(all_train)} boxes, score on {len(held)}", flush=True)
    examples = weighted(all_train, args.task, args.change_weight)
    print(f"{len(examples)} training examples per epoch ({sum(map(is_change, examples))} with a change, "
          f"change_weight {args.change_weight})", flush=True)
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
    config = {**{k: getattr(args, k) for k in DEFAULTS}, "base": args.base, "task": args.task, "variant": args.variant,
              "folds": args.folds, "fold": args.fold, "four_bit": args.four_bit, "n_train": len(examples)}
    (out / "train_config.json").write_text(json.dumps(config, indent=1))
    print(f"adapter -> {out}")
    if held:                                            # cross-validation: score the left-out training boxes
        preds = predict(model, processor, args.data, held, args.task)
        _write_preds(out / "predictions_fold.jsonl", preds)
        res = {"config": config, "score": score(args.task, held, preds)}
        (out / "fold_score.json").write_text(json.dumps(res, indent=1))
        print("FOLD SCORE " + json.dumps(res["score"]), flush=True)
    if args.eval_holdout:                               # the held-out boxes, without reloading the model
        hold = load_examples(args.data, args.task, "holdout", args.variant)
        preds = predict(model, processor, args.data, hold, args.task)
        _write_preds(out / f"predictions_{args.task}_{run_name(args)}.jsonl", preds)
        res = {"config": config, "score": score(args.task, hold, preds)}
        (out / "holdout_score.json").write_text(json.dumps(res, indent=1))
        print("HOLDOUT SCORE " + json.dumps(res["score"]), flush=True)


def evaluate(args) -> None:
    examples = load_examples(args.data, args.task, "holdout", args.variant)
    model, processor = _load(args.base, adapter=None if args.base_only else args.adapter, args=args)
    preds = predict(model, processor, args.data, examples, args.task)
    dest = (Path(args.data) if args.base_only else Path(args.adapter)) / f"predictions_{args.task}_{run_name(args)}.jsonl"
    _write_preds(dest, preds)
    res = score(args.task, examples, preds)
    print(json.dumps(res, indent=1))
    print("HOLDOUT SCORE " + json.dumps(res), flush=True)
    print(f"predictions -> {dest}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("train", "eval"))
    ap.add_argument("--task", choices=("cover", "check", "gated"), required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--out", default="/content/drive/MyDrive/evichange_ft")
    ap.add_argument("--adapter")
    ap.add_argument("--base-only", action="store_true")
    ap.add_argument("--four_bit", action="store_true", help="load the model in 4-bit (bitsandbytes), e.g. a 32B model")
    ap.add_argument("--variant", default="", choices=("", "dw"), help="dw: the cover prompt with Dynamic World evidence")
    ap.add_argument("--folds", type=int, default=0, help="cross-validation on the training boxes: number of folds")
    ap.add_argument("--fold", type=int, default=0, help="which fold to leave out and score (0-based)")
    ap.add_argument("--eval_holdout", action="store_true", help="after training, score the held-out boxes")
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
