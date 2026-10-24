r"""Training data for fine-tuning the Geo-VLM (Phase 4b, D17): draw the training boxes, render their
chips, and make blind labelling pages.

    python scripts\finetune_data.py --draw          # once: data/quangninh/ft_boxes.json (240 detected + 60 no-detection)
    python scripts\finetune_data.py --render        # chips via Earth Engine, in labelling order (~25 s a box; resumable)
    python scripts\finetune_data.py --sheet         # next 50 unlabelled, rendered training boxes -> ft_label_<n>.html
    python scripts\finetune_data.py --sheet --holdout   # the 80 held-out D15 boxes, same page
    python scripts\finetune_data.py --status        # how many are rendered / labelled

Labels: open the page, decide each box (change / no change / unsure + the change types you see), Save,
and put the downloaded file in data/quangninh/ft_labels/. Any number of files; the latest label for a
box wins. The pages show only the chips: no ids that reveal detection, no evidence, no model output.

Guards (D17): no box within 500 m of a labelled site, none of the 80 D15 boxes (the held-out set).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import vlm_batch                                   # noqa: E402
from agents import vlm_check                       # noqa: E402
from agents.schema import CHANGE_TYPES             # noqa: E402

BOXES = ROOT / "data" / "quangninh" / "ft_boxes.json"
LABEL_DIR = ROOT / "data" / "quangninh" / "ft_labels"
ASSIGNED = ROOT / "data" / "quangninh" / "ft_assigned.json"   # page -> {labeller, ids}: no box on two open pages
N_DETECTED, N_NODETECT, SEED, SITE_BUFFER_M, SHEET_SIZE = 240, 60, 17, 500, 50
ALL_KINDS = ("rgb", "swir", "cir")
LABEL_TYPES = (*CHANGE_TYPES, "other")


# ---------- guards ----------
def near_labelled_site(box: tuple, metres: float = SITE_BUFFER_M) -> bool:
    return any(vlm_batch._overlaps(box, vlm_batch._expand(s, metres)) for s in vlm_check.labelled_site_boxes())


def holdout_ids() -> set[str]:
    """The 80 D15 boxes: the held-out development test (D17)."""
    sample = json.loads(vlm_batch.SAMPLE.read_text(encoding="utf-8"))["ids"]
    controls = json.loads(vlm_batch.CONTROLS.read_text(encoding="utf-8"))["features"] if vlm_batch.CONTROLS.exists() else []
    return set(sample) | {c["properties"]["id"] for c in controls}


def holdout_boxes() -> list[tuple]:
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    fc, _ = vlm_batch.with_controls(fc)
    return [vlm_batch.bbox(f["geometry"]) for f in fc["features"] if f["properties"]["id"] in holdout_ids()]


# ---------- draw ----------
def draw(fc: dict, water=vlm_batch.water_share, seed: int = SEED) -> list[dict]:
    """[{'id', 'kind', 'box'}]: N_DETECTED detected regions stratified like the D15 sample, then
    N_NODETECT land boxes with no detection within 200 m; all outside the guards above."""
    held = holdout_ids()
    held_boxes = holdout_boxes()
    keep = [f for f in fc["features"] if f["properties"]["id"] not in held and not near_labelled_site(vlm_batch.bbox(f["geometry"]))]
    det_ids = vlm_batch.draw_sample(keep, n=N_DETECTED, seed=seed)
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    out = [{"id": rid, "kind": "detected", "box": list(vlm_batch.bbox(by_id[rid]["geometry"]))} for rid in det_ids]

    params = vlm_batch.analysis_params(fc)
    pts = params["aoi"]["coordinates"][0]
    aoi_box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    sizes = [(b[2] - b[0], b[3] - b[1]) for b in (tuple(x["box"]) for x in out)]
    cands = vlm_batch.control_candidates(fc["features"], aoi_box, sizes, 40 * N_NODETECT, seed)
    cands = [c for c in cands if not near_labelled_site(c) and not any(vlm_batch._overlaps(c, h) for h in held_boxes)]
    before, after = water(params["aoi"], params["before_window"], cands), water(params["aoi"], params["after_window"], cands)
    land = [c for c, wb, wa in zip(cands, before, after) if wb < vlm_batch.MAX_WATER and wa < vlm_batch.MAX_WATER]
    out += [{"id": f"t{i}", "kind": "no_detection", "box": list(c)} for i, c in enumerate(land[:N_NODETECT], 1)]
    random.Random(seed).shuffle(out)            # labelling order: detected and no-detection mixed
    return out


# ---------- labels ----------
def read_labels(folder: Path | None = None, overlap: bool = False) -> dict[str, dict]:
    """{box id: {'verdict', 'types', 'labeller'}} from every file in the label folder (later files win).
    Boxes repeated on another labeller's page for agreement are skipped there, so training keeps the first
    label; with overlap=True only those repeats are returned (for kappa)."""
    folder = Path(folder or LABEL_DIR)
    assigned = read_assigned()
    out: dict[str, dict] = {}
    for p in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime):
        repeats = set(assigned.get(p.stem, {}).get("overlap", []))
        for bid, lab in json.loads(p.read_text(encoding="utf-8")).items():
            if (bid in repeats) != overlap:
                continue
            if isinstance(lab, dict) and lab.get("verdict") in vlm_check.VERDICTS:
                types = [t for t in lab.get("types") or [] if t in LABEL_TYPES]
                out[bid] = {"verdict": lab["verdict"], "types": types if lab["verdict"] == "change" else [],
                            "labeller": labeller_of(p.name)}
    return out


def rendered(params: dict, box: tuple) -> bool:
    folder = vlm_batch.chip_dir(params, box)
    return all((folder / f"{w}_{k}.png").exists() for k in ALL_KINDS for w in ("before", "after"))


# ---------- page assignments ----------
def read_assigned() -> dict:
    return json.loads(ASSIGNED.read_text(encoding="utf-8")) if ASSIGNED.exists() else {}


def assign(page: str, labeller: str, ids: list[str], overlap: list[str] = ()) -> None:
    """Record a page's boxes; `overlap` = boxes another labeller already labelled, repeated for agreement (kappa)."""
    data = read_assigned()
    data[page] = {"labeller": labeller, "ids": list(ids), "overlap": list(overlap)}
    ASSIGNED.write_text(json.dumps(data, indent=1), encoding="utf-8")


def labeller_of(label_file: str) -> str:
    """'ft_label_p3_1.json' -> 'P3'; every other label file is P2's (the default labeller, D17)."""
    stem = Path(label_file).stem
    return stem.split("_")[2].upper() if stem.startswith("ft_label_p") and stem.split("_")[2][1:].isdigit() else "P2"


# ---------- labelling page ----------
def sheet(items: list[dict], params: dict, title: str, seed: int = SEED) -> str:
    """Blind page: chips only, a number per box (the box id is only inside the saved file's keys)."""
    items = list(items)
    random.Random(seed).shuffle(items)
    cards = []
    for n, it in enumerate(items, 1):
        folder = vlm_batch.chip_dir(params, tuple(it["box"]))
        figs = "".join(
            f'<figure><img src="data:image/png;base64,{base64.b64encode((folder / f"{w}_{k}.png").read_bytes()).decode()}">'
            f'<figcaption>{w} · {k}</figcaption></figure>' for k in ALL_KINDS for w in ("before", "after"))
        bid = html.escape(it["id"])
        verdicts = "".join(f'<label><input type="radio" name="v_{bid}" value="{v}"> {v.replace("_", " ")}</label>'
                           for v in vlm_check.VERDICTS)
        types = "".join(f'<label><input type="checkbox" name="t_{bid}" value="{t}"> {t.replace("_", " ")}</label>'
                        for t in LABEL_TYPES)
        cards.append(f'<section data-id="{bid}"><h2>{n}.</h2><div class="imgs">{figs}</div>'
                     f'<p class="v">{verdicts}</p><p class="t">If change: {types}</p></section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;max-width:1300px}}section{{border-top:1px solid #ccc;padding:8px 0}}
.imgs{{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}}figure{{margin:0}}img{{width:100%}}
figcaption{{font-size:11px;color:#555}}label{{margin-right:12px;white-space:nowrap}}.t{{font-size:13px}}
button{{font-size:15px;padding:6px 14px;position:sticky;bottom:8px}}</style></head><body>
<h1>{html.escape(title)} ({len(items)} boxes)</h1>
<p>Did real land-cover change happen <b>inside the yellow box</b> between before and after? If yes, tick the
kinds of change you see. Use <b>unsure</b> when the images don't let you tell. Boxes are shuffled; nothing on
this page says whether a box was detected.</p>
{''.join(cards)}
<p><button onclick="save()">Save labels</button> <span id="n"></span></p>
<script>
function save() {{
  const out = {{}};
  document.querySelectorAll('section[data-id]').forEach(s => {{
    const id = s.dataset.id, v = s.querySelector('input[type=radio]:checked');
    if (!v) return;
    out[id] = {{verdict: v.value, types: [...s.querySelectorAll('input[type=checkbox]:checked')].map(c => c.value)}};
  }});
  document.getElementById('n').textContent = Object.keys(out).length + ' of {len(items)} labelled';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}}));
  a.download = '{html.escape(title).replace(" ", "_").lower()}.json'; a.click();
}}
</script></body></html>
"""


def holdout_items(fc: dict) -> list[dict]:
    fc2, _ = vlm_batch.with_controls(fc)
    held = holdout_ids()
    return [{"id": f["properties"]["id"], "box": list(vlm_batch.bbox(f["geometry"]))} for f in fc2["features"]
            if f["properties"]["id"] in held]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--holdout", action="store_true", help="with --sheet / --render: the 80 held-out D15 boxes")
    ap.add_argument("--labeller", default="P2", help="with --sheet: who labels the page (P2 default; e.g. P3)")
    ap.add_argument("--overlap", type=int, default=0, help="with --sheet: also repeat this many boxes already labelled, for kappa")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    params = vlm_batch.analysis_params(fc)
    if args.draw:
        if BOXES.exists():
            raise SystemExit(f"{BOXES} exists: the training boxes are fixed once drawn")
        boxes = draw(fc)
        BOXES.write_text(json.dumps({"drawn": date.today().isoformat(), "seed": SEED, "rule":
            f"{N_DETECTED} detected regions (vlm_batch.draw_sample strata) + {N_NODETECT} land boxes with no detection "
            f"within 200 m; none within {SITE_BUFFER_M} m of a labelled site; none of the 80 D15 boxes (held out)",
            "boxes": boxes}, indent=1), encoding="utf-8")
        print(f"{sum(b['kind'] == 'detected' for b in boxes)} detected + {sum(b['kind'] != 'detected' for b in boxes)} "
              f"no-detection boxes -> {BOXES}")
        return
    items = holdout_items(fc) if args.holdout else json.loads(BOXES.read_text(encoding="utf-8"))["boxes"]
    if args.render:
        import time
        todo = [it for it in items if not rendered(params, tuple(it["box"]))]
        print(f"{len(items) - len(todo)} already rendered, {len(todo)} to go")
        for n, it in enumerate(todo, 1):
            t0 = time.time()
            for attempt in range(3):
                try:
                    vlm_batch.chips_for(params, tuple(it["box"]), ALL_KINDS)
                    print(f"[{n}/{len(todo)}] {time.time() - t0:.0f} s")
                    break
                except Exception as exc:
                    if attempt == 2:
                        print(f"[{n}/{len(todo)}] FAILED {str(exc)[:150]}")
        return
    labels = read_labels()
    if args.status:
        done = [it for it in items if it["id"] in labels]
        print(f"{len(items)} boxes, {sum(rendered(params, tuple(it['box'])) for it in items)} rendered, {len(done)} labelled "
              f"({sum(labels[it['id']]['verdict'] == 'unsure' for it in done)} unsure)")
        return
    if args.sheet:
        assigned = read_assigned()
        saved = {f.stem for f in LABEL_DIR.glob("*.json")} if LABEL_DIR.exists() else set()
        taken = {i for name, page in assigned.items() if name not in saved for i in page["ids"]}   # open pages only
        ready = [it for it in items if it["id"] not in labels and it["id"] not in taken and rendered(params, tuple(it["box"]))]
        if not args.holdout:
            ready = ready[:SHEET_SIZE]
        if not ready:
            raise SystemExit("nothing to label: every rendered box is labelled or on an open page (run --status)")
        who = args.labeller.lower()
        prefix = "ft_label" if who == "p2" else f"ft_label_{who}"
        n = 1 + sum(1 for k in assigned if k.startswith(prefix + "_") and k[len(prefix) + 1:].isdigit())
        name = "ft_label_holdout" if args.holdout else f"{prefix}_{n}"
        overlap = []
        if args.overlap and not args.holdout:
            done = sorted(i for i, lab in labels.items() if lab["verdict"] != "unsure" and i in {it["id"] for it in items})
            overlap = random.Random(f"{SEED}-{name}").sample(done, min(args.overlap, len(done)))
        page_items = ready + [it for it in items if it["id"] in overlap]
        out = ROOT / f"{name}.html"
        out.write_text(sheet(page_items, params, name.replace("_", " ")), encoding="utf-8")
        assign(name, args.labeller.upper(), [it["id"] for it in ready], overlap)
        print(f"{len(page_items)} boxes ({len(overlap)} repeated for agreement) -> {out}  (Save, then put the .json in {LABEL_DIR})")


if __name__ == "__main__":
    main()
