r"""Land-cover-per-date labelling (Phase 4b, D17 v2): the second labelling scheme, after the first
(change / no change at 10 m) gave inter-rater kappa 0.05.

For each box and each date the labeller answers what is THERE, not whether it changed:
  - covers: every land cover taking up at least about a fifth of the box (multi-select)
  - main:   the one covering most of the box
  - or "can't tell" (cloud, too blurry, no imagery)
from water / dense vegetation / sparse vegetation / crops / bare ground / built-up, ideally looking at
Google Earth's high-resolution historical imagery (a link per box, and a KML of the page's boxes for
Google Earth Pro's history slider), with the Sentinel-2 chips on the page for reference. The date of the
image used is recorded per window. Change and change types are then DERIVED (derive()), never judged.

    python scripts\finetune_mcq.py --sheet --set calib  --labeller P2   # the 40 shared calibration boxes
    python scripts\finetune_mcq.py --sheet --set calib  --labeller P3   # same boxes, P3
    python scripts\finetune_mcq.py --sheet --set holdout --labeller P2  # the 80 held-out boxes (both labellers)
    python scripts\finetune_mcq.py --sheet --set train  --labeller P2   # next 50 training boxes
    python scripts\finetune_mcq.py --kappa                              # agreement on boxes both labelled
    python scripts\finetune_mcq.py --status

Each page is <name>.html + <name>.kml. Save on the page downloads <name>.json; put it in
data/quangninh/ft_labels_v2/. Page numbers only on the page and in the KML; box ids only in the saved file.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import finetune_data as fd                     # noqa: E402
import vlm_batch                               # noqa: E402

LABEL_DIR = ROOT / "data" / "quangninh" / "ft_labels_v2"
ASSIGNED = ROOT / "data" / "quangninh" / "ft_assigned_v2.json"
COVERS = ("water", "dense_vegetation", "sparse_vegetation", "crops", "bare", "built")
COVER_TEXT = {"water": "water (sea, rivers, ponds; aquaculture: fish / shrimp ponds, floating cages)", "dense_vegetation": "dense vegetation (forest, mangrove)",
              "sparse_vegetation": "sparse vegetation (scrub, grass)", "crops": "crops / fields (not fish ponds)",
              "bare": "bare ground (soil, rock, sand, mine, fill)", "built": "built-up (buildings, roads, concrete)"}
VEG = {"dense_vegetation", "sparse_vegetation", "crops"}
CALIB_N, SEED, SHEET_SIZE = 40, 23, 50


# ---------- deriving change ----------
def derive(label: dict) -> dict:
    """{'verdict', 'types'} from a per-date label {'before': {...}, 'after': {...}}.
    unsure if either date is "can't tell"; change if the set of covers or the main cover differs."""
    b, a = label.get("before") or {}, label.get("after") or {}
    if b.get("cant_tell") or a.get("cant_tell") or not b.get("main") or not a.get("main"):
        return {"verdict": "unsure", "types": []}
    cb, ca = set(b.get("covers") or []) | {b["main"]}, set(a.get("covers") or []) | {a["main"]}
    gone, new = cb - ca, ca - cb
    if b["main"] != a["main"]:
        gone, new = gone | {b["main"]}, new | {a["main"]}
    types = []
    if (gone & VEG) and not (new & VEG) or "dense_vegetation" in gone and "sparse_vegetation" in new:
        types.append("vegetation_loss")
    if (new & VEG) and not (gone & VEG) or "sparse_vegetation" in gone and "dense_vegetation" in new:
        types.append("vegetation_gain")
    if new & {"bare", "built"}:
        types.append("built_up_increase")
    if gone & {"bare", "built"}:
        types.append("built_up_decrease")
    if "water" in new:
        types.append("water_increase")
    if "water" in gone:
        types.append("water_decrease")
    if (gone or new) and not types:
        types.append("other")                     # e.g. crops <-> sparse vegetation only
    return {"verdict": "change" if gone or new else "no_change", "types": types}


def kappa(pairs: list[tuple[str, str]]) -> dict:
    """Cohen's kappa on firm change / no_change pairs."""
    firm = [(x, y) for x, y in pairs if "unsure" not in (x, y)]
    if not firm:
        return {"n": 0}
    po = sum(x == y for x, y in firm) / len(firm)
    p1, p2 = sum(x == "change" for x, _ in firm) / len(firm), sum(y == "change" for _, y in firm) / len(firm)
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    return {"n": len(firm), "agreement": round(po, 2), "kappa": round((po - pe) / (1 - pe), 2) if pe < 1 else None}


def cover_kappa(labels_a: dict, labels_b: dict) -> dict:
    """Agreement on the main cover per date (6 classes), on boxes both labelled with a main cover."""
    pairs = [(labels_a[i][w]["main"], labels_b[i][w]["main"]) for i in set(labels_a) & set(labels_b) for w in ("before", "after")
             if (labels_a[i].get(w) or {}).get("main") and (labels_b[i].get(w) or {}).get("main")]
    if not pairs:
        return {"n": 0}
    po = sum(x == y for x, y in pairs) / len(pairs)
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[c] * cb[c] for c in COVERS) / len(pairs) ** 2
    return {"n": len(pairs), "agreement": round(po, 2), "kappa": round((po - pe) / (1 - pe), 2) if pe < 1 else None}


# ---------- sets and labels ----------
def box_sets(fc: dict) -> dict[str, list[dict]]:
    """train: the D17 training boxes minus the calibration ones; calib: 40 of them, drawn once (seeded);
    holdout: the 80 D15 boxes."""
    train = json.loads(fd.BOXES.read_text(encoding="utf-8"))["boxes"]
    calib_ids = set(random.Random(SEED).sample(sorted(b["id"] for b in train), CALIB_N))
    return {"calib": [b for b in train if b["id"] in calib_ids],
            "train": [b for b in train if b["id"] not in calib_ids],
            "holdout": fd.holdout_items(fc)}


def read_labels(labeller: str | None = None, folder: Path | None = None) -> dict[str, dict]:
    """{box id: per-date label} from the v2 label files (later files win); one labeller's, or all
    (P2's then, for training: P2 wins over P3 on boxes both labelled)."""
    folder = Path(folder or LABEL_DIR)
    out: dict[str, dict] = {}
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    if labeller is None:
        files = [f for f in files if labeller_of(f.name) != "P2"] + [f for f in files if labeller_of(f.name) == "P2"]
    for p in files:
        who = labeller_of(p.name)
        if labeller and who != labeller.upper():
            continue
        for bid, lab in json.loads(p.read_text(encoding="utf-8")).items():
            if isinstance(lab, dict) and ("before" in lab or "after" in lab):
                out[bid] = {**lab, "labeller": who}
    return out


def labeller_of(label_file: str) -> str:
    """'lc_calib_p3_1.json' -> 'P3' (the v2 page naming: lc_<set>_<labeller>_<n>)."""
    parts = Path(label_file).stem.split("_")
    return parts[2].upper() if len(parts) >= 4 and parts[0] == "lc" else "P2"


def read_assigned() -> dict:
    return json.loads(ASSIGNED.read_text(encoding="utf-8")) if ASSIGNED.exists() else {}


# ---------- page ----------
def earth_link(box: tuple) -> str:
    lon, lat = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return f"https://earth.google.com/web/@{lat:.6f},{lon:.6f},10a,900d,35y,0h,0t,0r"


def kml(items: list[dict], title: str) -> str:
    marks = []
    for n, it in enumerate(items, 1):
        w, s, e, nn = it["box"]
        ring = " ".join(f"{x},{y},0" for x, y in ((w, s), (e, s), (e, nn), (w, nn), (w, s)))
        marks.append(f"<Placemark><name>{n}</name><Style><LineStyle><color>ff00ffff</color><width>2</width></LineStyle>"
                     f"<PolyStyle><fill>0</fill></PolyStyle></Style><Polygon><outerBoundaryIs><LinearRing><coordinates>{ring}"
                     f"</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")
    return (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{html.escape(title)}</name>{''.join(marks)}</Document></kml>\n")


def sheet(items: list[dict], params: dict, title: str, windows: list[list[str]]) -> str:
    """The page: per box, the Google Earth link, the Sentinel-2 chips, and the per-date questions."""
    cards = []
    for n, it in enumerate(items, 1):
        folder = vlm_batch.chip_dir(params, tuple(it["box"]))
        figs = "".join(
            f'<figure><img src="data:image/png;base64,{base64.b64encode((folder / f"{w}_{k}.png").read_bytes()).decode()}">'
            f'<figcaption>{w} · {k}</figcaption></figure>' for k in fd.ALL_KINDS for w in ("before", "after"))
        bid = html.escape(it["id"])
        dates = []
        for w, win in zip(("before", "after"), windows):
            covers = "".join(f'<label><input type="checkbox" name="c_{w}_{bid}" value="{c}"> {html.escape(COVER_TEXT[c])}</label>'
                             for c in COVERS)
            mains = "".join(f'<label><input type="radio" name="m_{w}_{bid}" value="{c}"> {c.replace("_", " ")}</label>' for c in COVERS)
            dates.append(f'<div class="date"><b>{w.upper()}</b> <span class="muted">(window {win[0][:7]} – {win[1][:7]})</span><br>'
                         f'Covers ≥ ~1/5 of the box: {covers}<br>Main cover: {mains}<br>'
                         f'<label><input type="checkbox" name="x_{w}_{bid}" value="1"> can\'t tell</label> '
                         f'Google Earth image date: <input type="month" name="d_{w}_{bid}"></div>')
        cards.append(f'<section data-id="{bid}"><h2>{n}. <a href="{earth_link(tuple(it["box"]))}" target="_blank">open in Google Earth</a>'
                     f'</h2><div class="imgs">{figs}</div>{"".join(dates)}</section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;max-width:1300px}}section{{border-top:2px solid #999;padding:8px 0}}
.imgs{{display:grid;grid-template-columns:repeat(6,1fr);gap:4px}}figure{{margin:0}}img{{width:100%}}figcaption{{font-size:11px;color:#555}}
.date{{margin:6px 0;padding:6px;background:#f4f4f4;border-radius:6px}}label{{margin-right:10px;white-space:nowrap;line-height:1.9}}
.muted{{color:#666}}button{{font-size:15px;padding:6px 14px;position:sticky;bottom:8px}}</style></head><body>
<h1>{html.escape(title)} ({len(items)} boxes)</h1>
<p>For each box, describe <b>what is inside the yellow box at each date</b>; do not decide "change" yourself.
Best: open the box in Google Earth (link, or this page's .kml in Google Earth Pro) and use the
<b>historical imagery</b> slider to find the clearest image <b>inside each window</b> (or the closest to it), and note its month.
The Sentinel-2 chips below are the same place at 10 m, for reference. Tick every cover taking up at least about
a fifth of the box, then the main one. Use "can't tell" only when no image lets you see the box.
<b>Aquaculture is water</b>: fish / shrimp ponds and floating cages (dots on the water) are water, never crops;
tick built-up as well only if rafts and walkways cover a fifth of the box; wide pond walls are bare.</p>
{''.join(cards)}
<p><button onclick="save()">Save labels</button> <span id="n"></span></p>
<script>
function save() {{
  const out = {{}};
  document.querySelectorAll('section[data-id]').forEach(s => {{
    const id = s.dataset.id, lab = {{}};
    for (const w of ['before', 'after']) {{
      const covers = [...s.querySelectorAll(`input[name="c_${{w}}_${{id}}"]:checked`)].map(c => c.value);
      const main = s.querySelector(`input[name="m_${{w}}_${{id}}"]:checked`);
      const cant = s.querySelector(`input[name="x_${{w}}_${{id}}"]`).checked;
      const date = s.querySelector(`input[name="d_${{w}}_${{id}}"]`).value;
      if (covers.length || main || cant) lab[w] = {{covers, main: main ? main.value : null, cant_tell: cant, image_date: date || null}};
    }}
    if (Object.keys(lab).length) out[id] = lab;
  }});
  document.getElementById('n').textContent = Object.keys(out).length + ' of {len(items)} boxes have answers';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}}));
  a.download = '{html.escape(title).replace(" ", "_").lower()}.json'; a.click();
}}
</script></body></html>
"""


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--set", choices=("calib", "holdout", "train"), default="train")
    ap.add_argument("--labeller", default="P2")
    ap.add_argument("--kappa", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    params = vlm_batch.analysis_params(fc)
    sets = box_sets(fc)
    if args.status or args.kappa:
        mine = {who: read_labels(who) for who in ("P2", "P3")}
        for name, items in sets.items():
            ids = {it["id"] for it in items}
            print(f"{name}: {len(items)} boxes; P2 {len(ids & set(mine['P2']))}, P3 {len(ids & set(mine['P3']))} labelled")
        both = set(mine["P2"]) & set(mine["P3"])
        if args.kappa and both:
            pairs = [(derive(mine["P2"][i])["verdict"], derive(mine["P3"][i])["verdict"]) for i in sorted(both)]
            print(f"both labelled {len(both)}: change / no change {kappa(pairs)}; main cover per date {cover_kappa(mine['P2'], mine['P3'])}")
        return
    if args.sheet:
        who = args.labeller.upper()
        done = set(read_labels(who))
        assigned = read_assigned()
        saved = {f.stem for f in LABEL_DIR.glob("*.json")} if LABEL_DIR.exists() else set()
        taken = {i for page, a in assigned.items() if a["labeller"] == who and page not in saved for i in a["ids"]}
        todo = [it for it in sets[args.set] if it["id"] not in done and it["id"] not in taken]
        if args.set == "train":
            todo = todo[:SHEET_SIZE]
        if not todo:
            raise SystemExit(f"nothing left in '{args.set}' for {who}")
        random.Random(f"{SEED}-{args.set}-{who}").shuffle(todo)
        n = 1 + sum(1 for k in assigned if k.startswith(f"lc_{args.set}_{who.lower()}_"))
        name = f"lc_{args.set}_{who.lower()}_{n}"
        title = name.replace("_", " ")
        (ROOT / f"{name}.html").write_text(sheet(todo, params, title, [params["before_window"], params["after_window"]]), encoding="utf-8")
        (ROOT / f"{name}.kml").write_text(kml(todo, title), encoding="utf-8")
        assigned[name] = {"labeller": who, "set": args.set, "ids": [it["id"] for it in todo]}
        ASSIGNED.write_text(json.dumps(assigned, indent=1), encoding="utf-8")
        print(f"{len(todo)} boxes -> {name}.html + {name}.kml  (Save, then put {name}.json in {LABEL_DIR})")


if __name__ == "__main__":
    main()
