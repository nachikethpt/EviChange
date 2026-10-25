"""scripts/phase14_report.py on synthetic Phase 14 labels: complete sets are scored, incomplete ones are
not (blindness), and two labellers' files give agreement."""
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import phase14_report as p14  # noqa: E402
from agents import labels14 as l14  # noqa: E402

KEY = json.loads((Path(l14.LABELS_DIR).parent / "sites_key.json").read_text(encoding="utf-8"))
SITES = sorted(KEY)
BASE = {"protocol": l14.PROTOCOL, "confidence": "medium", "labeled_at": "2026-11-01T10:00:00"}


def write(folder: Path, task: str, rows: list[dict], labeler: str | None = None):
    p14.label_file(task, labeler, folder).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    for f in (l14.TRANSECTS_FILE, l14.CELLS_FILE):
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


def classes(labeler, flip=()):
    return [{**BASE, "labeler": labeler, "site_id": s, "class_before": "trees", "class_after": "crops" if s in flip else "bare"}
            for s in SITES]


def regions():
    return {KEY[s]["region_id"]: {"id": KEY[s]["region_id"], "class_before": "trees", "class_after": "bare"}
            for s in SITES if KEY[s]["region_id"]}


def test_complete_classes_are_scored(folder, tmp_path):
    write(folder, "classes", classes("labeler1"))
    reg = tmp_path / "regions.json"
    reg.write_text(json.dumps({"features": [{"properties": r} for r in regions().values()]}))
    rep = p14.report(folder=folder, regions_path=reg, positions_path=tmp_path / "none.json")
    a = rep["classes"]["accuracy"]
    assert rep["classes"]["status"] == "complete"
    assert a["n"] == 20 and a["dropped"] == 10                     # random sites have no DW region
    assert a["transition"]["agreement"][0] == 1.0
    assert rep["shoreline"]["status"].startswith("no labels")


def test_incomplete_sets_are_not_scored(folder, tmp_path):
    write(folder, "classes", classes("labeler1")[:12])
    rep = p14.report(folder=folder, regions_path=tmp_path / "none.json", positions_path=tmp_path / "none.json")
    assert rep["classes"]["status"].startswith("incomplete: 18 to go")
    assert "accuracy" not in rep["classes"] and len(rep["classes"]["missing"]) == 11     # 10 shown + "..."


def test_shoreline_needs_both_dates_then_rmse(folder, tmp_path):
    refs = [t["transect_id"] for t in l14.load_samples(folder / l14.TRANSECTS_FILE.name)]
    rows = [{**BASE, "labeler": "labeler1", "transect_id": t, "month": m, "status": "edge", "drawn_m": 100.0, "pos_m": 10.0}
            for t in refs for m in l14.REF_DATES]
    write(folder, "shoreline", rows[:-1])
    pos = tmp_path / "positions.json"
    pos.write_text(json.dumps({"months": list(l14.REF_DATES), "positions": {t: [13.0, 7.0] for t in refs}}))
    rep = p14.report(folder=folder, regions_path=tmp_path / "none.json", positions_path=pos)
    assert rep["shoreline"]["status"].startswith("incomplete: 1 to go")
    write(folder, "shoreline", rows)
    rep = p14.report(folder=folder, regions_path=tmp_path / "none.json", positions_path=pos)
    acc = rep["shoreline"]["accuracy"]
    assert acc["n"] == 2 * len(refs) and acc["rmse_m"] == pytest.approx(3.0) and acc["bias_m"] == pytest.approx(0.0)


def test_cells_and_change_month_need_system_files(folder, tmp_path):
    cells = [c["cell_id"] for c in l14.load_samples(folder / l14.CELLS_FILE.name)]
    write(folder, "cells", [{**BASE, "labeler": "labeler1", "cell_id": c, "dates": list(l14.REF_DATES),
                             "months": {m: "built" for m in l14.REF_DATES}} for c in cells])
    write(folder, "change_month", [{**BASE, "labeler": "labeler1", "site_id": s, "lasting_change": "yes",
                                    "change_window": ["2025-03", "2025-04"]} for s in SITES])
    none = tmp_path / "none.json"
    rep = p14.report(folder=folder, regions_path=none, positions_path=none)
    assert "--cells-dw" in rep["cells"]["accuracy"] and "--ccdc" in rep["change_month"]["accuracy"]
    dw = {c: {m: i % 2 == 0 for m in l14.REF_DATES} for i, c in enumerate(cells)}
    ccdc = {s: ["2025-03", "2025-04"] for s in SITES[:10]}
    rep = p14.report(folder=folder, regions_path=none, positions_path=none, cells_dw=dw, ccdc=ccdc)
    assert rep["cells"]["accuracy"]["accuracy"][0] == pytest.approx(0.5)
    assert rep["change_month"]["accuracy"]["n"] == 10 and rep["change_month"]["accuracy"]["within_1_month"][0] == 1.0


def test_two_labellers_agreement(folder, tmp_path):
    write(folder, "classes", classes("labeler1"))
    write(folder, "classes", classes("p3", flip=SITES[:6])[:10], labeler="p3")
    none = tmp_path / "none.json"
    rep = p14.report(second="p3", folder=folder, regions_path=none, positions_path=none)
    ag = rep["classes"]["agreement"]
    assert ag["n_common"] == 10 and ag["before"]["agreement"][0] == 1.0 and ag["after"]["agreement"][0] == pytest.approx(0.4)
    assert rep["shoreline"].get("agreement") is None               # no first-labeller file, nothing to compare


def test_cli_prints_and_writes(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(p14, "report", lambda *a, **k: {"classes": {"status": "complete", "accuracy": {"n": 3}}})
    p14.main(["--out", str(tmp_path / "r.md")])
    assert "## classes" in capsys.readouterr().out and "n: 3" in (tmp_path / "r.md").read_text()
