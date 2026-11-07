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
from agents import cover_check, gated, vlm_check  # noqa: E402
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



# ---------- the main-cover task (D17, 2026-11-02) ----------
def test_cover_target_needs_a_main_cover_at_both_dates():
    lab = {"before": {"covers": ["water", "bare"], "main": "water", "cant_tell": False},
           "after": {"covers": ["bare"], "main": "bare", "cant_tell": False}}
    assert cover_check.target(lab) == {"before": "water", "after": "bare"}
    assert cover_check.target({**lab, "after": {"covers": ["bare"], "main": None, "cant_tell": False}}) is None
    assert cover_check.target({**lab, "before": {"covers": [], "main": "water", "cant_tell": True}}) is None
    assert cover_check.target({"before": lab["before"]}) is None


def test_cover_prompt_lists_every_cover_and_the_chips_like_the_check():
    p = cover_check.build_prompt(["2018-11-01", "2019-02-28"], ["2022-11-01", "2023-02-28"])
    assert all(f'"{c}"' in p for c in (*cover_check.COVERS, "cant_tell"))
    assert "Before: 2018-11-01 to 2019-02-28" in p and "yellow box" in p
    check = vlm_check.build_prompt(["2018-11-01", "2019-02-28"], ["2022-11-01", "2023-02-28"])
    assert p.splitlines()[1] == check.splitlines()[1]          # the same image list as the region check
    assert "{" in p and "{{" not in p


def test_cover_answers_parse_and_derive_change():
    ans = cover_check.parse_answer('Sure: {"before": "water", "after": "built"}')
    assert ans == {"before": "water", "after": "built", "parse_ok": True}
    assert cover_check.derived_change(ans) == "change"
    assert cover_check.derived_change({"before": "bare", "after": "bare"}) == "no_change"
    assert cover_check.derived_change({"before": "cant_tell", "after": "bare"}) == "unsure"
    for bad in ("", "no json", '{"before": "forest", "after": "bare"}', '{"before": "bare"}'):
        assert cover_check.parse_answer(bad) == {"before": "cant_tell", "after": "cant_tell", "parse_ok": False}


def test_cover_scoring():
    rows = [{"id": "a", "target": json.dumps({"before": "water", "after": "built"})},
            {"id": "b", "target": json.dumps({"before": "bare", "after": "bare"})}]
    preds = {"a": '{"before": "water", "after": "built"}', "b": '{"before": "bare", "after": "cant_tell"}'}
    s = ft.score("cover", rows, preds)
    assert s["parse_failures"] == 0 and s["main_cover_accuracy"] == 0.75
    assert s["derived_change"]["on_change"] == 1.0 and s["derived_change"]["on_no_change"] == 0.0

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


def test_change_weight_repeats_only_change_boxes():
    import json as _json
    same = {"id": "a", "target": _json.dumps({"before": "water", "after": "water"})}
    change = {"id": "b", "target": _json.dumps({"before": "bare", "after": "built"})}
    junk = {"id": "c", "target": "not json"}
    assert ft.is_change(change) and not ft.is_change(same) and not ft.is_change(junk)
    out = ft.weighted([same, change, junk], "cover", 3)
    assert [e["id"] for e in out] == ["a", "b", "b", "b", "c"]
    assert ft.weighted([same, change], "cover", 1) == [same, change]
    assert ft.weighted([same, change], "check", 3) == [same, change]      # other tasks are never reweighted
    assert ft.DEFAULTS["change_weight"] == 1                               # the default run is as labelled


def test_compare_models_get_their_own_prediction_files():
    assert ft.model_tag(ft.BASE_MODEL) == "base"                      # run 1's file name is kept
    tags = [ft.model_tag(m["base"]) for m in ft.COMPARE_MODELS]
    assert len(set(tags)) == len(tags) and "base" not in tags
    assert ft.model_tag("Qwen/Qwen2.5-VL-32B-Instruct") == "qwen2_5-vl-32b-instruct"
    assert ft.processor_kwargs("Qwen/Qwen3-VL-8B-Instruct") and ft.processor_kwargs("OpenGVLab/InternVL3-8B-hf") == {}


def test_baselines_map_dynamic_world_and_read_features():
    import baselines_cover as bc
    assert bc.dw_main({"1": 30, "0": 10, "5": 25}) == "dense_vegetation"   # trees 30 vs water 10, scrub 25
    assert bc.dw_main({"2": 20, "5": 15, "1": 30}) == "sparse_vegetation"  # grass + scrub 35 beat trees 30
    assert bc.dw_main({}) == bc.cover_check.CANT_TELL
    props = {"b_" + f: 0.1 for f in bc.FEATURES}
    assert len(bc.feature_vector(props, "b_")) == 16 and bc.feature_vector(props, "a_") is None
    assert set(c for c in bc.DW_TO_COVER.values() if c) == set(bc.cover_check.COVERS)


def test_folds_are_disjoint_stratified_and_fixed():
    import json as _json
    ex = [{"id": f"c{i}", "target": _json.dumps({"before": "bare", "after": "built"})} for i in range(10)]
    ex += [{"id": f"n{i}", "target": _json.dumps({"before": "water", "after": "water"})} for i in range(40)]
    folds = ft.split_folds(ex, 5)
    ids = [i for f in folds for i in f]
    assert len(ids) == len(set(ids)) == 50
    assert all(sum(i.startswith("c") for i in f) == 2 for f in folds)      # every fold has change boxes
    assert folds == ft.split_folds(list(reversed(ex)), 5)                  # same folds whatever the order


def test_dw_evidence_goes_before_the_answer_line(tmp_path):
    import json as _json
    import finetune_dw_prompts as fdp
    from agents import cover_check
    p = cover_check.build_prompt(["2018-11-01", "2019-03-31"], ["2022-11-01", "2023-03-31"])
    shares = {"before": {"built": 0.55, "bare": 0.42, "water": 0.03}, "after": {}}
    q = cover_check.with_dw(p, shares)
    assert "BEFORE: built 55 %, bare 42 %" in q and "water 3" not in q            # under 5 % left out
    assert "AFTER: no Dynamic World image" in q
    assert q.index("Evidence from Dynamic World") < q.index("Answer with JSON only")
    rows = [{"id": "a", "prompt": p, "target": "{}"}, {"id": "b", "prompt": p, "target": "{}"}]
    out = fdp.dw_rows(rows, {"a": shares})
    assert "built 55 %" in out[0]["prompt"] and out[1]["prompt"].count("no Dynamic World image") == 2
    (tmp_path / "cover_dw_train.jsonl").write_text(_json.dumps(out[0]) + "\n", encoding="utf-8")
    assert ft.load_examples(tmp_path, "cover", "train", "dw")[0]["id"] == "a"


def test_dw_shares_from_a_histogram():
    import baselines_cover as bc
    s = bc.dw_shares({"6": 30, "7": 10, "8": 60})          # built 30, bare 10, snow 60 (left out)
    assert s == {"built": 0.75, "bare": 0.25} and bc.dw_shares({}) == {}
