"""scripts/shoreline_figures.py: the SVGs parse, gaps stay gaps, and a hidden reference transect can't be a case."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import shoreline_figures as sf  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"
YEARS = {"seasons": [[f"20{15 + i}-{16 + i}"] for i in range(6)],
         "positions": {"t1": [0, 10, None, None, 40, 50]}, "optical": {"t1": [0, 5, 10, 20, 30, 45]},
         "transects": {"t1": {"change": "advancing", "lrr": 10.0, "ci95": 4.0, "nsm": 45.0}}}


def test_case_figure_breaks_lines_at_gaps():
    svg = ET.fromstring(sf.case_figure("t1", YEARS))
    radar = [pl for pl in svg.iter(f"{NS}polyline") if pl.get("stroke") == sf.ADVANCING]
    assert len(radar) == 2                                    # 2015-16..2016-17 and 2019-20..2020-21, not bridged
    assert len([c for c in svg.iter(f"{NS}circle")]) == 4 + 6


def test_map_figure_hides_reference_transects():
    feats = [{"id": f"t{i}", "geometry": {"type": "LineString", "coordinates": [[107.30 + i / 1000, 21.0], [107.30 + i / 1000, 21.01]]}}
             for i in range(3)]
    years = {"seasons": [["2015-16"], ["2025-26"]],
             "transects": {"t0": {"change": "advancing", "lrr": 5.0}, "t1": {"change": "retreating", "lrr": -3.0},
                           "t2": {"change": "stable", "lrr": 0.1}}}
    svg = sf.map_figure({"features": feats}, years, hidden={"t1"})
    titles = [t.text for t in ET.fromstring(svg).iter(f"{NS}title")]
    assert "t1: hidden (Phase 14 reference)" in titles and not any("t1: retreating" in t for t in titles)
    assert "-3.0" not in svg


def test_hidden_case_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(sf.shoreline, "hidden_transects", lambda transects=None: {"t0133"})
    with pytest.raises(SystemExit):
        sf.write_all(tmp_path, ["t0133"])


def test_reference_figure_panels_and_stats():
    matched = [("2016-17", 0.0, 10.0), ("2016-17", 50.0, 40.0), ("2022-23", -20.0, -20.0)]
    svg = ET.fromstring(sf.reference_figure(matched))
    texts = [t.text for t in svg.iter(f"{NS}text")]
    assert "2016-17" in texts and "2022-23" in texts
    assert "n 2 · bias +0 m · RMSE 10 m" in texts and "n 1 · bias +0 m · RMSE 0 m" in texts


def test_reference_figure_waits_for_the_unlock(monkeypatch, tmp_path):
    monkeypatch.setattr(sf.shoreline, "REFERENCE_TRANSECTS_UNLOCKED", False)
    assert not any(p.name == "figure_reference_accuracy.svg" for p in sf.write_all(tmp_path, []))


def test_committed_outputs_render(tmp_path):
    for path in sf.write_all(tmp_path, []):
        ET.fromstring(path.read_text(encoding="utf-8"))
