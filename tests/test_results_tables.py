"""scripts/results_tables.py on a synthetic 30-site study: every table, the LaTeX table and the figure."""
import json
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import results_tables as rt  # noqa: E402
from eval import metrics  # noqa: E402

RATES = {"template": 0.15, "ungated": 0.5, "gated": 0.2, "ungated_gpt": 0.4}


def synthetic(tmp: Path, conds=tuple(RATES)) -> tuple[Path, Path]:
    _, key = metrics.load_phase3()
    rng = random.Random(1)
    claims, runs = [], []
    for site in sorted(key):
        for cond in conds:
            n = rng.randint(1, 5)
            for i in range(n):
                bad = rng.random() < RATES[cond]
                claims.append({"site_id": site, "condition": cond, "claim_id": f"c{i}", "type": rng.choice(["presence", "change_type"]),
                               "level": "L3", "text": "Vegetation loss here.", "truth": "false" if bad else "true",
                               "support": "unsupported" if bad and cond.startswith("ungated") else "supported",
                               "verdict": "unsupported" if bad and rng.random() < 0.6 else "supported"})
            runs.append({"site_id": site, "condition": cond, "n_claims": n, "n_parse_failures": 0})
    cp, rp = tmp / "claims.jsonl", tmp / "runs.jsonl"
    cp.write_text("".join(json.dumps(c) + "\n" for c in claims))
    rp.write_text("".join(json.dumps(r) + "\n" for r in runs))
    return cp, rp


def test_all_outputs(tmp_path):
    cp, rp = synthetic(tmp_path)
    out = tmp_path / "results"
    rep = rt.write_all(cp, rp, out, reps=200)
    md = (out / "results.md").read_text(encoding="utf-8")
    for n in range(1, 8):
        assert f"## Table {n}." in md
    assert md.count("| Gated (Qwen) |") >= 5 and "Gated (Qwen) − Ungated (Qwen)" in md and "secondary (D16)" in md
    tex = (out / "table_main.tex").read_text(encoding="utf-8")
    assert tex.startswith(r"\begin{tabular}{lrrrrrr}") and r"\%" in tex and "%" not in tex.replace(r"\%", "")
    assert len([ln for ln in tex.splitlines() if ln.endswith(r"\\")]) == 5        # head + 4 conditions
    svg = ET.fromstring((out / "figure_rates.svg").read_text(encoding="utf-8"))
    titles = [t.text for t in svg.iter("{http://www.w3.org/2000/svg}title")]
    assert len(titles) == 4 * 2 + 1                                                # 2 marks per condition + the effect
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))["comparisons"]["primary"]["a"] == "gated"
    assert rep["conditions"]["ungated"]["pooled"]["hallucination"][0] > rep["conditions"]["gated"]["pooled"]["hallucination"][0]


def test_without_a_comparison(tmp_path):
    cp, rp = synthetic(tmp_path, conds=("template",))
    out = tmp_path / "r"
    rt.write_all(cp, rp, out, reps=100)
    assert "not available" in (out / "figure_rates.svg").read_text(encoding="utf-8")
    assert "## Table 6." in (out / "results.md").read_text(encoding="utf-8")


def test_formatting():
    assert rt.pct((0.123, 0.041, 0.2)) == "12.3 % [4.1, 20.0]" and rt.pct((None, None, None)) == "n/a"
    assert rt.p(0.0004) == "< 0.001" and rt.p(None) == "n/a" and rt.num(None) == "n/a"
