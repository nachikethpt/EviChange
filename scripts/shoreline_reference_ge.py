r"""Phase 14 (b) on Google Earth (D13, 2026-10-28): trace the shoreline on the 30 reference transects
for 4 dry seasons on Google Earth Pro's historical imagery, then score the yearly shorelines against it.

    python scripts\shoreline_reference_ge.py --page --labeller P2            # shoreline_ge_p2.html + .kml
    python scripts\shoreline_reference_ge.py --import shoreline_ge_p2.json --labeller P2
    python scripts\shoreline_reference_ge.py --score                         # only after every labeller is done

The page and KML number the transects 1-30 and draw each one extended by a random length at both ends,
so neither the ids nor the baseline can be read off them (labels14.drawn_segment). The labeller reads
the metres along the drawn line where the water edge crosses it; --import turns that into a position
from the baseline (labels14.drawn_to_baseline) and writes data/quangninh/labels/phase14/shoreline_ge_<l>.jsonl.
Google Earth imagery is only looked at to make labels; it never goes into training (D17).
"""
import argparse
import html
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import labels14, shoreline   # noqa: E402

SEASON_TEXT = {s: f"Oct {s[:4]} – Mar 20{s[5:]}" for s in labels14.GE_SEASONS}


def page(n_refs: int, labeller: str, title: str) -> str:
    rows = []
    for n in range(1, n_refs + 1):
        seasons = "".join(
            f'<tr><td>{s}<br><span class="muted">{SEASON_TEXT[s]}</span></td>'
            f'<td><select name="st_{n}_{s}"><option value=""></option><option value="edge">water edge found</option>'
            f'<option value="no_edge">no edge: all land or all water</option><option value="not_visible">can\'t see (cloud, no image)</option></select></td>'
            f'<td><input type="number" name="m_{n}_{s}" min="0" step="1" style="width:6em"> m</td>'
            f'<td><input type="month" name="d_{n}_{s}"></td>'
            f'<td><select name="c_{n}_{s}"><option value=""></option>{"".join(f"<option>{c}</option>" for c in labels14.CONFIDENCE)}</select></td></tr>'
            for s in labels14.GE_SEASONS)
        rows.append(f'<section data-n="{n}"><h2>Transect {n}</h2><table><tr><th>Dry season</th><th>Status</th>'
                    f'<th>Edge at (metres along the line)</th><th>Image date</th><th>Confidence</th></tr>{seasons}</table>'
                    f'<label>Notes: <input type="text" name="n_{n}" size="90"></label></section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;max-width:1100px}}section{{border-top:2px solid #999;padding:8px 0}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}.muted{{color:#666;font-size:12px}}
button{{font-size:15px;padding:6px 14px;position:sticky;bottom:8px}}</style></head><body>
<h1>{html.escape(title)} (30 transects × 4 dry seasons)</h1>
<ol>
<li>Open <b>{html.escape(title.replace(' ', '_'))}.kml</b> in <b>Google Earth Pro</b>. Each yellow line is numbered as below, with a tick every
25 m and a label every 50 m, counting from its <b>landward</b> end (0).</li>
<li>Turn on <b>historical imagery</b> (clock icon) and pick the clearest image <b>inside the dry season</b> (Oct–Mar). If none is clear,
use the closest image within 6 months and write its month.</li>
<li>Find where the <b>water edge</b> crosses the yellow line and read the metres from the ticks (the ruler tool helps). The water edge is
the line between water and land in that image: sea, river mouth or pond connected to the sea. Fish and shrimp ponds count as water only
if they are open to the sea; otherwise use the outer sea edge.</li>
<li>Wide mud flats at low tide: take the edge of the water in the image and set confidence to low. If the line crosses no edge
(all land or all water), choose "no edge". Never look at the EviChange map's shoreline layer while doing this.</li>
</ol>
{''.join(rows)}
<p><button onclick="save()">Save</button> <span id="n"></span>
<label class="muted" style="margin-left:12px">Load a saved file: <input type="file" accept=".json" onchange="load(this.files[0])"></label></p>
<p class="muted">Every answer is also kept in this browser as you type, so closing the tab loses nothing (same browser only).
Press Save to get the file for the import.</p>
<script>
const KEY = 'evichange-ge-' + {json.dumps(labeller)};
function answers() {{
  const out = [];
  document.querySelectorAll('section[data-n]').forEach(sec => {{
    const n = +sec.dataset.n, note = sec.querySelector(`input[name="n_${{n}}"]`).value;
    for (const s of {json.dumps(list(labels14.GE_SEASONS))}) {{
      const v = k => sec.querySelector(`[name="${{k}}_${{n}}_${{s}}"]`).value;
      if (!v('st')) continue;
      out.push({{n, season: s, status: v('st'), drawn_m: v('m') === '' ? null : +v('m'), month: v('d') || null,
                 confidence: v('c') || null, notes: note || null}});
    }}
  }});
  return out;
}}
function fill(list) {{
  for (const r of list) {{
    const sec = document.querySelector(`section[data-n="${{r.n}}"]`); if (!sec) continue;
    const set = (k, v) => {{ const el = sec.querySelector(`[name="${{k}}_${{r.n}}_${{r.season}}"]`); if (el && v !== null && v !== undefined) el.value = v; }};
    set('st', r.status); set('m', r.drawn_m); set('d', r.month); set('c', r.confidence);
    if (r.notes) sec.querySelector(`input[name="n_${{r.n}}"]`).value = r.notes;
  }}
  count();
}}
function count() {{ document.getElementById('n').textContent = answers().length + ' of {n_refs * len(labels14.GE_SEASONS)} answers'; }}
function keep() {{ try {{ localStorage.setItem(KEY, JSON.stringify(answers())); }} catch (e) {{}} count(); }}
function load(file) {{ if (!file) return; file.text().then(t => {{ fill(JSON.parse(t).answers || []); keep(); }}); }}
document.addEventListener('input', keep); document.addEventListener('change', keep);
try {{ fill(JSON.parse(localStorage.getItem(KEY) || '[]')); }} catch (e) {{}}
function save() {{
  const out = answers();
  count();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({{labeller: {json.dumps(labeller)}, answers: out}}, null, 1)], {{type: 'application/json'}}));
  a.download = '{html.escape(title.replace(' ', '_'))}.json'; a.click();
}}
</script></body></html>
"""


def to_records(saved: dict, refs: list[dict], labeller: str) -> list[dict]:
    """Page answers -> labels14 shoreline records (validated)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for a in saved["answers"]:
        ref = refs[a["n"] - 1]
        if a["status"] != "edge" and not a["month"]:
            a["month"] = f"{a['season'][:4]}-10"             # nothing seen: the season's first month stands in
        rec = {"protocol": labels14.PROTOCOL, "labeler": labeller, "labeled_at": now, "source": "google_earth",
               "transect_id": ref["transect_id"], "season": a["season"], "month": a["month"], "status": a["status"],
               "drawn_m": a["drawn_m"] if a["status"] == "edge" else None,
               "pos_m": labels14.drawn_to_baseline(ref, a["drawn_m"]) if a["status"] == "edge" and a["drawn_m"] is not None else None,
               "confidence": a["confidence"], "notes": a["notes"]}
        errs = labels14.validate_record("shoreline", rec)
        if errs:
            raise SystemExit(f"transect {a['n']}, {a['season']}: {'; '.join(errs)}")
        out.append(rec)
    return out


def score(records: list[dict], years: dict) -> dict:
    """Yearly shoreline position minus the traced one (m, seaward +) where both exist."""
    labels = [s[0] for s in years["seasons"]]
    errs, by_season, missing = [], {}, 0
    for r in records:
        if r["status"] != "edge" or r.get("season") not in labels:
            continue
        model = (years["positions"].get(r["transect_id"]) or [None] * len(labels))[labels.index(r["season"])]
        if model is None:
            missing += 1
            continue
        e = model - r["pos_m"]
        errs.append(e)
        by_season.setdefault(r["season"], []).append(e)
    stats = lambda v: {"n": len(v), "bias_m": round(sum(v) / len(v), 1), "rmse_m": round(math.sqrt(sum(x * x for x in v) / len(v)), 1),
                       "mae_m": round(sum(map(abs, v)) / len(v), 1),
                       "within_20m": round(sum(abs(x) <= 20 for x in v) / len(v), 2),
                       "within_30m": round(sum(abs(x) <= 30 for x in v) / len(v), 2)} if v else {"n": 0}
    return {"all": stats(errs), "by_season": {s: stats(v) for s, v in sorted(by_season.items())},
            "traced_but_no_model_position": missing}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", action="store_true")
    ap.add_argument("--import", dest="imp", type=Path)
    ap.add_argument("--labeller", default="P2")
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    refs = labels14.load_samples(labels14.TRANSECTS_FILE)
    if refs is None:
        sys.exit("no reference transects: run scripts/make_phase14_samples.py first")
    who = args.labeller.upper()
    if args.page:
        name = f"shoreline_ge_{who.lower()}"
        (ROOT / f"{name}.html").write_text(page(len(refs), who, name.replace("_", " ")), encoding="utf-8")
        (ROOT / f"{name}.kml").write_text(labels14.ge_kml(refs, name.replace("_", " ")), encoding="utf-8")
        print(f"{len(refs)} transects -> {name}.html + {name}.kml (Save, then --import {name}.json --labeller {who})")
    if args.imp:
        recs = to_records(json.loads(args.imp.read_text(encoding="utf-8")), refs, who)
        out = labels14.LABELS_DIR / f"shoreline_ge_{who.lower()}.jsonl"
        out.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        print(f"{len(recs)} records -> {out}")
    if args.score:
        years = shoreline.load("years.json")
        if years is None:
            sys.exit("no yearly shorelines: run scripts/make_shoreline_years.py first")
        for f in sorted(labels14.LABELS_DIR.glob("shoreline_ge_*.jsonl")):
            print(f.stem, json.dumps(score(labels14.load_labels(f, "shoreline"), years), indent=1))


if __name__ == "__main__":
    main()
