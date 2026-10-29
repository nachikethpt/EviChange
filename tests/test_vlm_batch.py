"""scripts/vlm_batch.py (Phase 4, D15): sample draw, chip cache and resumable runs, with a fake model server."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vlm_batch as vb  # noqa: E402
from agents import vlm_check  # noqa: E402
from agents.schema import region_change_types  # noqa: E402

PARAMS_META = {"aoi": {"type": "Polygon", "coordinates": [[[107.2, 20.9], [107.5, 20.9], [107.5, 21.2], [107.2, 21.2], [107.2, 20.9]]]},
               "before_window": ["2018-11-01", "2019-03-31"], "after_window": ["2022-11-01", "2023-03-31"],
               "thresholds": {"max_cloud_pct": 30}}


def region(rid, x, dndvi=-0.3, before="trees", after="bare"):
    d = 0.001
    ring = [[x, 21.0], [x + d, 21.0], [x + d, 21.0 + d], [x, 21.0 + d], [x, 21.0]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"id": rid, "area_ha": 1.0, "mean_conf": 0.3, "dNDVI": dndvi, "dNDBI": 0.0, "dMNDWI": 0.0,
                           "location": "west", "class_before": before, "class_after": after}}


@pytest.fixture
def no_sites(monkeypatch):
    monkeypatch.setattr(vlm_check, "_site_boxes", [(107.3995, 20.99, 107.4005, 21.01)])   # one site, at x = 107.4


def test_draw_sample_halves_and_skips_sites(no_sites):
    feats = ([region(f"c{i}", 107.25 + i * 0.002) for i in range(10)]                                 # DW changed
             + [region(f"s{i}", 107.30 + i * 0.002, dndvi=0.3, before="trees", after="trees") for i in range(10)]
             + [region("site", 107.3998), region("unknown", 107.35, before=None)])
    ids = vb.draw_sample(feats, n=8, seed=1)
    assert len(ids) == 8 and len(set(ids)) == 8
    assert sum(i.startswith("c") for i in ids) == 4 and sum(i.startswith("s") for i in ids) == 4
    assert "site" not in ids and "unknown" not in ids
    assert ids == vb.draw_sample(feats, n=8, seed=1)                       # deterministic


def test_chips_rendered_once_then_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path)
    calls = []

    def render(aoi, bw, aw, cloud, box, kinds):
        calls.append(kinds)
        return {f"{w}_{k}": f"{w}{k}".encode() for k in kinds for w in ("before", "after")}

    params = vb.analysis_params({"metadata": PARAMS_META})
    first = vb.chips_for(params, (1, 2, 3, 4), ("rgb",), render)
    again = vb.chips_for(params, (1, 2, 3, 4), ("rgb", "swir", "cir"), render)
    assert first == {"before_rgb": b"beforergb", "after_rgb": b"afterrgb"}
    assert again["after_cir"] == b"aftercir" and len(calls) == 1        # every kind rendered on the first call


class FakeVLM:
    mode = "http"

    def __init__(self, model="Qwen/Qwen2.5-VL-7B-Instruct", available=True):
        self.model, self.available, self.prompts = model, available, []

    def status(self):
        return {"available": self.available, "mode": "http", "model": self.model, "detail": "down"}

    def generate(self, prompt, images, replay_key=None):
        self.prompts.append((replay_key, len(images)))
        return {"text": '{"verdict": "change", "change_types": ["vegetation_loss"], "reason": "cleared"}', "model": self.model}


def test_run_logs_then_resumes(tmp_path, monkeypatch, no_sites):
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path / "chips")
    render = lambda aoi, bw, aw, cloud, box, kinds: {f"{w}_{k}": b"png" for k in kinds for w in ("before", "after")}
    fc = {"metadata": PARAMS_META, "features": [region("r1", 107.25), region("r2", 107.26)]}
    log = tmp_path / "log.jsonl"
    quiet = lambda *_: None

    vlm = FakeVLM()
    assert vb.run(vlm, fc, ["r1", "r2"], ["rgb", "rgb_swir"], log, render, quiet) == {"done": 4, "skipped": 0, "failed": 0}
    recs = vlm_check.read_log(log)
    assert {(r["region_id"], r["chips"]) for r in recs} == {("r1", "rgb"), ("r2", "rgb"), ("r1", "rgb_swir"), ("r2", "rgb_swir")}
    assert recs[0]["agreement"] == "agrees" and recs[0]["seconds"] is not None
    assert (vlm.prompts[0][1], vlm.prompts[2][1]) == (2, 4)               # rgb: 2 images; rgb_swir: 4

    assert vb.run(FakeVLM(), fc, ["r1", "r2"], ["rgb", "rgb_swir"], log, render, quiet)["skipped"] == 4
    other = vb.run(FakeVLM("Qwen/Qwen3-VL-8B-Instruct"), fc, ["r1"], ["rgb"], log, render, quiet)
    assert other == {"done": 1, "skipped": 0, "failed": 0}                 # a new model checks again


def test_run_refuses_without_server_or_with_a_site_region(tmp_path, no_sites, monkeypatch):
    monkeypatch.setattr(vlm_check, "LABELLED_SITES_UNLOCKED", False)          # the lock as before the D19 freeze
    fc = {"metadata": PARAMS_META, "features": [region("r1", 107.25), region("site", 107.3998)]}
    with pytest.raises(SystemExit, match="not available"):
        vb.run(FakeVLM(available=False), fc, ["r1"], ["rgb"], tmp_path / "log.jsonl", None, lambda *_: None)
    with pytest.raises(SystemExit, match="labelled site"):
        vb.run(FakeVLM(), fc, ["site"], ["rgb"], tmp_path / "log.jsonl", None, lambda *_: None)


def test_committed_sample_is_outside_the_sites(monkeypatch):
    monkeypatch.setattr(vlm_check, "LABELLED_SITES_UNLOCKED", False)
    sample = json.loads(vb.SAMPLE.read_text(encoding="utf-8"))
    fc = json.loads((vb.ROOT / sample["regions_file"]).read_text(encoding="utf-8"))
    by_id = {f["properties"]["id"]: f for f in fc["features"]}
    assert len(sample["ids"]) == vb.SAMPLE_SIZE == len(set(sample["ids"]))
    assert not any(vlm_check.touches_labelled_site(vb.bbox(by_id[i]["geometry"])) for i in sample["ids"])


def test_run_retries_a_dropped_connection(tmp_path, monkeypatch, no_sites):
    from agents.vlm_client import VLMUnavailable
    monkeypatch.setattr(vb, "CHIP_DIR", tmp_path / "chips")
    render = lambda aoi, bw, aw, cloud, box, kinds: {f"{w}_{k}": b"png" for k in kinds for w in ("before", "after")}
    fc = {"metadata": PARAMS_META, "features": [region("r1", 107.25)]}

    class Flaky(FakeVLM):
        def __init__(self, drops):
            super().__init__()
            self.drops = drops

        def generate(self, prompt, images, replay_key=None):
            if self.drops:
                self.drops -= 1
                raise VLMUnavailable("connection reset")
            return super().generate(prompt, images, replay_key)

    waits = []
    out = vb.run(Flaky(drops=2), fc, ["r1"], ["rgb"], tmp_path / "log.jsonl", render, lambda *_: None, waits.append)
    assert out == {"done": 1, "skipped": 0, "failed": 0} and len(waits) == 2
    with pytest.raises(SystemExit, match="reconnect and rerun"):
        vb.run(Flaky(drops=vb.SERVER_TRIES), fc, ["r1"], ["rgb_swir"], tmp_path / "log.jsonl", render,
               lambda *_: None, lambda s: None)


def test_control_boxes_keep_away_from_detections_and_sites(no_sites):
    feats = [region(f"r{i}", 107.25 + i * 0.01) for i in range(5)]
    aoi_box = (107.22, 20.98, 107.40, 21.10)
    boxes = vb.control_candidates(feats, aoi_box, [(0.002, 0.002)], n=15, seed=3)
    assert len(boxes) == 15 and boxes == vb.control_candidates(feats, aoi_box, [(0.002, 0.002)], n=15, seed=3)
    near = [vb._expand(vb.bbox(f["geometry"]), vb.NEAR_M) for f in feats]
    for b in boxes:
        assert aoi_box[0] <= b[0] and b[2] <= aoi_box[2] and aoi_box[1] <= b[1] and b[3] <= aoi_box[3]
        assert not any(vb._overlaps(b, r) for r in near) and not vlm_check.touches_labelled_site(b)


def test_draw_controls_keeps_land_only(no_sites):
    fc = {"metadata": PARAMS_META, "features": [region("r1", 107.25)]}
    calls = []

    def fake_water(aoi, window, boxes):
        calls.append(window)
        return [0.9 if i % 2 else 0.1 for i in range(len(boxes))]             # every other box is water

    feats = vb.draw_controls(fc, ["r1"], n=5, water=fake_water)
    assert [f["properties"]["id"] for f in feats] == ["c1", "c2", "c3", "c4", "c5"] and len(calls) == 2
    p = feats[0]["properties"]
    assert p["control"] and region_change_types(p) == []                    # the detector saw nothing here


def test_committed_controls_are_clear_of_detections():
    fc = json.loads(vb.REGIONS.read_text(encoding="utf-8"))
    controls = json.loads(vb.CONTROLS.read_text(encoding="utf-8"))["features"]
    near = [vb._expand(vb.bbox(f["geometry"]), vb.NEAR_M) for f in fc["features"]]
    assert len(controls) == vb.N_CONTROLS
    for c in controls:
        box = vb.bbox(c["geometry"])
        assert not any(vb._overlaps(box, r) for r in near) and not vlm_check.touches_labelled_site(box)
