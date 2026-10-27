"""Land-cover-per-date labelling (D17 v2): deriving change, kappa, labeller naming, blind page + KML."""
import json
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import finetune_mcq as fm  # noqa: E402
import vlm_batch as vb  # noqa: E402


def lab(before, after, mb=None, ma=None, cant=False):
    return {"before": {"covers": before, "main": mb or before[0], "cant_tell": cant},
            "after": {"covers": after, "main": ma or after[0], "cant_tell": False}}


def test_derive_change_types_from_the_two_dates():
    assert fm.derive(lab(["dense_vegetation"], ["dense_vegetation"])) == {"verdict": "no_change", "types": []}
    assert fm.derive(lab(["dense_vegetation"], ["bare"])) == {"verdict": "change", "types": ["vegetation_loss", "built_up_increase"]}
    assert fm.derive(lab(["dense_vegetation"], ["sparse_vegetation"]))["types"] == ["vegetation_loss"]
    assert fm.derive(lab(["sparse_vegetation"], ["dense_vegetation"]))["types"] == ["vegetation_gain"]
    assert fm.derive(lab(["water"], ["bare", "built"]))["types"] == ["built_up_increase", "water_decrease"]
    assert fm.derive(lab(["bare"], ["water"]))["types"] == ["built_up_decrease", "water_increase"]
    assert fm.derive(lab(["crops"], ["sparse_vegetation"]))["types"] == ["other"]
    assert fm.derive(lab(["dense_vegetation", "built"], ["dense_vegetation", "built"], "dense_vegetation", "built"))["verdict"] == "change"
    assert fm.derive(lab(["water"], ["water"], cant=True)) == {"verdict": "unsure", "types": []}
    assert fm.derive({"before": {"covers": ["water"], "main": "water"}}) == {"verdict": "unsure", "types": []}


def test_kappa():
    assert fm.kappa([("change", "change"), ("no_change", "no_change"), ("change", "unsure")]) == {"n": 2, "agreement": 1.0, "kappa": 1.0}
    k = fm.kappa([("change", "change")] * 8 + [("change", "no_change")] * 2 + [("no_change", "change")] * 3 + [("no_change", "no_change")])
    assert k == {"n": 14, "agreement": 0.64, "kappa": 0.05}          # the first scheme's numbers
    a = {"x": lab(["water"], ["bare"]), "y": lab(["built"], ["built"])}
    b = {"x": lab(["water"], ["built"]), "y": lab(["built"], ["built"])}
    assert fm.cover_kappa(a, b)["agreement"] == 0.75


def test_labeller_naming_and_p2_wins_for_training(tmp_path):
    assert fm.labeller_of("lc_calib_p3_1.json") == "P3" and fm.labeller_of("lc_holdout_p2_1.json") == "P2"
    (tmp_path / "lc_calib_p2_1.json").write_text(json.dumps({"b1": lab(["water"], ["water"])}))
    time.sleep(0.05)
    (tmp_path / "lc_calib_p3_1.json").write_text(json.dumps({"b1": lab(["water"], ["bare"]), "b2": lab(["bare"], ["bare"])}))
    os.utime(tmp_path / "lc_calib_p3_1.json")
    both = fm.read_labels(folder=tmp_path)
    assert both["b1"]["labeller"] == "P2" and fm.derive(both["b1"])["verdict"] == "no_change"   # P2's label kept
    assert both["b2"]["labeller"] == "P3"
    assert set(fm.read_labels("P3", tmp_path)) == {"b1", "b2"}


def test_page_and_kml_are_blind(tmp_path, monkeypatch):
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path)
    params = {"aoi": {}, "before_window": ["2018-11-01", "2019-03-31"], "after_window": ["2022-11-01", "2023-03-31"], "max_cloud_pct": 30.0}
    items = [{"id": "r200", "kind": "detected", "box": [107.30, 21.00, 107.31, 21.01]}]
    folder = vb.chip_dir(params, tuple(items[0]["box"]))
    folder.mkdir(parents=True)
    for k in ("rgb", "swir", "cir"):
        for w in ("before", "after"):
            (folder / f"{w}_{k}.png").write_bytes(b"png")
    page = fm.sheet(items, params, "lc calib p2 1", [params["before_window"], params["after_window"]])
    kml = fm.kml(items, "lc calib p2 1")
    assert "earth.google.com/web/@21.005000,107.305000" in page and page.count("<img") == 6
    assert ">r200<" not in page and "detected" not in page and 'data-id="r200"' in page
    assert "r200" not in kml and "<name>1</name>" in kml and "107.3,21.0,0" in kml
    assert "2018-11 – 2019-03" in page and "2022-11 – 2023-03" in page


def test_calibration_set_is_fixed_and_separate():
    fc = json.loads(vb.REGIONS.read_text(encoding="utf-8"))
    sets = fm.box_sets(fc)
    calib, train = {b["id"] for b in sets["calib"]}, {b["id"] for b in sets["train"]}
    assert len(calib) == fm.CALIB_N and not calib & train and len(sets["holdout"]) == 80
    assert calib == {b["id"] for b in fm.box_sets(fc)["calib"]}


def test_second_calibration_set_is_fixed_fresh_and_separate():
    fc = json.loads(vb.REGIONS.read_text(encoding="utf-8"))
    sets = fm.box_sets(fc)
    calib, calib2, train = ({b["id"] for b in sets[k]} for k in ("calib", "calib2", "train"))
    assert len(calib2) == fm.CALIB_N and not calib2 & calib and not calib2 & train
    assert calib2 == {b["id"] for b in fm.box_sets(fc)["calib2"]}


def test_agreement_is_per_set():
    a = {"x": lab(["water"], ["bare"]), "y": lab(["built"], ["built"]), "z": lab(["bare"], ["bare"])}
    b = {"x": lab(["water"], ["bare"]), "y": lab(["built"], ["built"]), "z": lab(["bare"], ["water"])}
    assert fm.agreement(a, b, {"x", "y"})["change"]["agreement"] == 1.0
    assert fm.agreement(a, b, {"x", "y", "z"})["n"] == 3


def test_kml_draws_the_cell_grid_and_review_shows_both(tmp_path, monkeypatch):
    items = [{"id": "r200", "kind": "detected", "box": [107.30, 21.00, 107.31, 21.01]}]
    kml = fm.kml(items, "t")
    assert kml.count("<LineString>") == 2 * (fm.GRID - 1) and "r200" not in kml
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path)
    params = {"aoi": {}, "before_window": ["2018-11-01", "2019-03-31"], "after_window": ["2022-11-01", "2023-03-31"], "max_cloud_pct": 30.0}
    folder = vb.chip_dir(params, tuple(items[0]["box"]))
    folder.mkdir(parents=True)
    for k in ("rgb", "swir", "cir"):
        for w in ("before", "after"):
            (folder / f"{w}_{k}.png").write_bytes(b"png")
    page = fm.review(items, params, {"r200": {"P2": lab(["water"], ["bare"]), "P3": lab(["water"], ["water"])}}, "review")
    assert "P2" in page and "P3" in page and "no change" in page and "Cell rule" in page
