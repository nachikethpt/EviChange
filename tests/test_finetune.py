"""Phase 4b fine-tuning data (D17): box draw guards, blind labelling page, label merging, training
targets, and the GPU-free parts of the training script. No Earth Engine, no model."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import finetune_build as fb  # noqa: E402
import finetune_data as fd  # noqa: E402
import finetune_train as ft  # noqa: E402
import vlm_batch as vb  # noqa: E402
from agents import gated, vlm_check  # noqa: E402
from webapp.backend.report import build_report  # noqa: E402


# ---------- the committed draw ----------
def test_committed_training_boxes_respect_the_guards():
    boxes = json.loads(fd.BOXES.read_text(encoding="utf-8"))["boxes"]
    held, held_boxes = fd.holdout_ids(), fd.holdout_boxes()
    first = [b for b in boxes if b.get("draw", 1) == 1]
    assert len(boxes) == len({b["id"] for b in boxes}) and sum(b["kind"] == "detected" for b in first) == fd.N_DETECTED
    assert all(b["kind"] == "detected" for b in boxes if b.get("draw") == 2)
    for b in boxes:
        box = tuple(b["box"])
        assert not fd.near_labelled_site(box), b["id"]
        assert b["id"] not in held
        if b["kind"] != "detected":
            assert not any(vb._overlaps(box, h) for h in held_boxes)


def test_site_buffer_is_500_m(monkeypatch):
    monkeypatch.setattr(vlm_check, "_site_boxes", [(107.30, 21.00, 107.301, 21.001)])
    deg = 1 / 111_320
    just_outside = (107.301 + 520 * deg / 0.934, 21.0, 107.301 + 600 * deg / 0.934, 21.001)   # ~520 m east
    inside = (107.301 + 400 * deg / 0.934, 21.0, 107.301 + 450 * deg / 0.934, 21.001)          # ~400 m east
    assert not fd.near_labelled_site(just_outside) and fd.near_labelled_site(inside)


# ---------- labels and the labelling page ----------
def test_read_labels_later_file_wins_and_drops_junk(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"r1": {"verdict": "change", "types": ["vegetation_loss", "bogus"]},
                                                 "r2": {"verdict": "maybe"}, "r3": {"verdict": "no_change", "types": ["vegetation_loss"]}}))
    time.sleep(0.05)
    (tmp_path / "b.json").write_text(json.dumps({"r1": {"verdict": "unsure", "types": []}}))
    os.utime(tmp_path / "b.json")
    labels = fd.read_labels(tmp_path)
    assert labels == {"r1": {"verdict": "unsure", "types": [], "labeller": "P2"},
                      "r3": {"verdict": "no_change", "types": [], "labeller": "P2"}}


def test_repeats_for_agreement_never_replace_the_first_label(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "ASSIGNED", tmp_path / "assigned.json")
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    (labels_dir / "ft_label_1.json").write_text(json.dumps({"r1": {"verdict": "change", "types": []}}))
    fd.assign("ft_label_p3_1", "P3", ["r2"], overlap=["r1"])
    time.sleep(0.05)
    (labels_dir / "ft_label_p3_1.json").write_text(json.dumps({"r1": {"verdict": "no_change", "types": []},
                                                               "r2": {"verdict": "change", "types": ["other"]}}))
    os.utime(labels_dir / "ft_label_p3_1.json")
    train = fd.read_labels(labels_dir)
    assert train["r1"] == {"verdict": "change", "types": [], "labeller": "P2"}          # P2's label kept for training
    assert train["r2"]["labeller"] == "P3"
    assert fd.read_labels(labels_dir, overlap=True) == {"r1": {"verdict": "no_change", "types": [], "labeller": "P3"}}
    assert fd.labeller_of("ft_label_2.json") == "P2" and fd.labeller_of("ft_label_holdout.json") == "P2"


def test_labelling_page_is_blind(tmp_path, monkeypatch):
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path)
    params = {"aoi": {}, "before_window": ["a", "b"], "after_window": ["c", "d"], "max_cloud_pct": 30.0}
    items = [{"id": "r200", "kind": "detected", "box": [1, 2, 3, 4]}, {"id": "t7", "kind": "no_detection", "box": [5, 6, 7, 8]}]
    for it in items:
        folder = vb.chip_dir(params, tuple(it["box"]))
        folder.mkdir(parents=True)
        for k in fd.ALL_KINDS:
            for w in ("before", "after"):
                (folder / f"{w}_{k}.png").write_bytes(b"png")
    page = fd.sheet(items, params, "ft label 1")
    assert page.count("<section") == 2 and page.count("<img") == 12
    assert "no_detection" not in page and "detected" not in page.replace("whether a box was detected", "")
    assert ">r200<" not in page and 'data-id="r200"' in page            # ids only as keys for the saved file


# ---------- training targets ----------
EV_CHANGE = {"pair_id": "p", "dates": [["a", "b"], ["c", "d"]], "source": "t", "change_frac": 0.4,
             "regions": [{"id": "r1", "area_ha": 3.0, "location": "centre", "mean_conf": 0.5, "dNDVI": -0.3, "dNDBI": 0.2,
                          "dMNDWI": 0.0}]}
EV_EMPTY = {**EV_CHANGE, "change_frac": 0.0, "regions": []}


def verified(ev, target):
    claims, abstain, ok, dropped = gated.parse_report(json.dumps(target))
    assert ok and dropped == 0
    return build_report(ev, "gated", gated={"raw": "", "model": "t", "claims": claims, "abstain": abstain,
                                            "parse_ok": ok, "dropped": dropped, "prompt_version": "x"})


@pytest.mark.parametrize("ev,label", [
    (EV_CHANGE, {"verdict": "change", "types": ["vegetation_loss"]}),
    (EV_CHANGE, {"verdict": "change", "types": ["water_increase", "other"]}),
    (EV_CHANGE, {"verdict": "no_change", "types": []}),
    (EV_EMPTY, {"verdict": "no_change", "types": []}),
    (EV_EMPTY, {"verdict": "change", "types": ["vegetation_loss"]}),
])
def test_gated_targets_never_hold_an_unsupported_claim(ev, label):
    rep = verified(ev, fb.gated_target(ev, label))
    assert all(c["verdict"] != "unsupported" for c in rep["claims"])
    assert {a["topic"] for a in fb.ALWAYS_ABSTAIN} <= {a["topic"] for a in rep["abstain"]}


def test_gated_target_follows_the_label():
    agree = fb.gated_target(EV_CHANGE, {"verdict": "change", "types": ["vegetation_loss"]})
    types = [c.get("change_type") for c in agree["claims"] if c["type"] == "change_type"]
    assert types == ["vegetation_loss"]                                    # in evidence AND in the label
    assert any("built-up" in a["topic"] for a in agree["abstain"])       # in evidence, not seen: abstain
    seen_not_measured = fb.gated_target(EV_CHANGE, {"verdict": "change", "types": ["water_increase"]})
    assert any(a["topic"] == "increase in surface water" for a in seen_not_measured["abstain"])
    veto = fb.gated_target(EV_CHANGE, {"verdict": "no_change", "types": []})
    assert veto["claims"] == [] and veto["abstain"][0]["topic"] == "change in the box"
    assert fb.gated_target(EV_EMPTY, {"verdict": "no_change", "types": []})["claims"][0]["text"].startswith("No change")


def test_check_target():
    assert fb.check_target({"verdict": "change", "types": ["other"]}) == {"verdict": "change", "change_types": ["other"]}
    assert fb.check_target({"verdict": "no_change", "types": ["other"]}) == {"verdict": "no_change", "change_types": []}


# ---------- training script, GPU-free parts ----------
def test_lora_targets_skip_the_vision_encoder():
    names = ["model.visual.blocks.0.attn.qkv", "model.visual.blocks.0.mlp.gate_proj", "model.language_model.layers.0.self_attn.q_proj",
             "model.language_model.layers.0.mlp.down_proj", "lm_head", "model.language_model.layers.0.self_attn.rotary_emb"]
    assert ft.lora_targets(names) == ["model.language_model.layers.0.self_attn.q_proj", "model.language_model.layers.0.mlp.down_proj"]


def test_balanced_accuracy_and_scoring(tmp_path):
    assert ft.balanced_accuracy([("change", "change"), ("change", "no_change"), ("no_change", "no_change"), ("no_change", "unsure")]) == \
        {"n": 4, "on_change": 0.5, "on_no_change": 0.5, "balanced": 0.5}
    assert ft.balanced_accuracy([("change", "change")])["balanced"] is None
    rows = [{"id": "a", "target": json.dumps({"verdict": "change", "change_types": []})},
            {"id": "b", "target": json.dumps({"verdict": "no_change", "change_types": []})}]
    preds = {"a": '{"verdict": "change", "change_types": [], "reason": "x"}', "b": "garbage"}
    s = ft.score("check", rows, preds)
    assert s["parse_failures"] == 1 and s["on_change"] == 1.0 and s["on_no_change"] == 0.0
    (tmp_path / "check_train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [r["id"] for r in ft.load_examples(tmp_path, "check", "train")] == ["a", "b"]


def test_blanks_on_a_saved_page_return_to_the_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "ASSIGNED", tmp_path / "assigned.json")
    monkeypatch.setattr(fd, "LABEL_DIR", tmp_path / "labels")
    monkeypatch.setattr(fd, "ROOT", tmp_path)
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path / "chips")
    boxes = [{"id": f"b{i}", "kind": "detected", "box": [107.2 + i * 0.01, 21.0, 107.205 + i * 0.01, 21.005]} for i in range(4)]
    monkeypatch.setattr(fd, "BOXES", tmp_path / "boxes.json")
    (tmp_path / "boxes.json").write_text(json.dumps({"boxes": boxes}))
    monkeypatch.setattr(fd, "rendered", lambda params, box: True)
    monkeypatch.setattr(fd, "sheet", lambda items, params, title: " ".join(it["id"] for it in items))
    fd.LABEL_DIR.mkdir()
    fd.assign("ft_label_1", "P2", ["b0", "b1"])                       # open page: b0, b1 are taken
    fd.assign("ft_label_p3_1", "P3", ["b2"])                          # open page: b2 is taken
    fd.main(["--sheet"])
    assert (tmp_path / "ft_label_2.html").read_text() == "b3"
    (fd.LABEL_DIR / "ft_label_1.json").write_text(json.dumps({"b0": {"verdict": "change", "types": []}}))   # b1 left blank
    fd.main(["--sheet"])
    assert (tmp_path / "ft_label_3.html").read_text() == "b1"         # the blank comes back; b2 still with P3
