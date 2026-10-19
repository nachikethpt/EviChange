"""scripts/planet_order.py against a fake Planet API: no network, nothing ordered."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import planet_order as po  # noqa: E402

AOI = {"type": "Polygon", "coordinates": [[[107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]]]}
WEST_HALF = {"type": "Polygon", "coordinates": [[[107.0, 20.9], [107.31, 20.9], [107.31, 21.2], [107.0, 21.2], [107.0, 20.9]]]}
EAST_HALF = {"type": "Polygon", "coordinates": [[[107.31, 20.9], [107.6, 20.9], [107.6, 21.2], [107.31, 21.2], [107.31, 20.9]]]}
ALL = {"type": "Polygon", "coordinates": [[[107.0, 20.9], [107.6, 20.9], [107.6, 21.2], [107.0, 21.2], [107.0, 20.9]]]}


def item(id_, acquired, geom, clear=90):
    return {"id": id_, "geometry": geom, "properties": {"acquired": acquired, "clear_percent": clear, "cloud_cover": 0.1}}


class Resp:
    def __init__(self, body, code=200):
        self.body, self.status_code, self.text = body, code, json.dumps(body)

    def json(self):
        return self.body


class FakePlanet:
    """Answers quick-search from a {month: [items]} table and records order POSTs."""
    def __init__(self, by_month):
        self.by_month, self.orders = by_month, []

    def post(self, url, json=None):
        if url == po.SEARCH_URL:
            gte = next(c for c in json["filter"]["config"] if c["type"] == "DateRangeFilter")["config"]["gte"]
            return Resp({"features": self.by_month.get(gte[:7], []), "_links": {}})
        self.orders.append(json)
        return Resp({"id": f"order-{len(self.orders)}"})

    def get(self, url):
        return Resp({"state": "running"})


def test_months():
    assert po.months("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
    assert po.month_bounds("2024-12") == ("2024-12-01T00:00:00Z", "2025-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        po.months("2025-02", "2024-11")


def test_coverage():
    grid = po.aoi_grid(AOI)
    assert po.coverage(grid, [ALL]) == 1.0
    assert 0.45 < po.coverage(grid, [WEST_HALF]) < 0.55
    assert po.coverage(grid, [WEST_HALF, EAST_HALF]) == 1.0


def test_pick_day_prefers_full_clear_coverage():
    grid = po.aoi_grid(AOI)
    items = [item("a", "2024-10-03T03:00:00Z", WEST_HALF, clear=100),                  # half the AOI
             item("b", "2024-10-10T03:00:00Z", WEST_HALF), item("c", "2024-10-10T03:00:05Z", EAST_HALF),   # all of it
             item("d", "2024-10-20T03:00:00Z", ALL, clear=40)]                         # all of it, cloudy
    best = po.pick_day(items, grid)
    assert best["date"] == "2024-10-10" and best["item_ids"] == ["b", "c"] and best["coverage"] == 1.0
    assert best["days_found"] == 3
    assert po.pick_day([], grid) is None


def test_plan_and_dry_run_orders_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(po, "OUT", tmp_path); monkeypatch.setattr(po, "ORDERS_LOG", tmp_path / "orders.json")
    fake = FakePlanet({"2024-10": [item("x", "2024-10-05T03:00:00Z", ALL)]})
    plan = po.make_plan(fake, AOI, ["2024-10", "2024-11"], 0.3, today=date(2026, 10, 11))
    assert plan["months"][0]["km2"] == plan["aoi_km2"] and 240 < plan["aoi_km2"] < 260
    assert plan["months"][1]["date"] is None and plan["total_km2"] == plan["aoi_km2"]
    assert po.place_orders(fake, plan, confirm=False, max_km2=3000) == [] and fake.orders == []
    assert "Dry run" in capsys.readouterr().out


def test_confirmed_order_is_logged_and_not_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "OUT", tmp_path); monkeypatch.setattr(po, "ORDERS_LOG", tmp_path / "orders.json")
    fake = FakePlanet({"2024-10": [item("x", "2024-10-05T03:00:00Z", ALL)]})
    plan = po.make_plan(fake, AOI, ["2024-10"], 0.3, today=date(2026, 10, 11))
    assert po.place_orders(fake, plan, confirm=True, max_km2=3000) == ["order-1"]
    sent = fake.orders[0]
    assert sent["products"][0] == {"item_ids": ["x"], "item_type": "PSScene", "product_bundle": "analytic_8b_sr_udm2"}
    assert sent["tools"] == [{"clip": {"aoi": AOI}}, {"harmonize": {"target_sensor": "Sentinel-2"}}]
    assert po.load_log()["2024-10"]["order_id"] == "order-1"
    assert po.place_orders(fake, plan, confirm=True, max_km2=3000) == [] and len(fake.orders) == 1


def test_quota_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "OUT", tmp_path); monkeypatch.setattr(po, "ORDERS_LOG", tmp_path / "orders.json")
    fake = FakePlanet({m: [item("x" + m, m + "-05T03:00:00Z", ALL)] for m in po.months("2024-10", "2025-12")})
    plan = po.make_plan(fake, AOI, po.months("2024-10", "2025-12"), 0.3, today=date(2026, 10, 11))   # 15 months ≈ 3,750 km²
    with pytest.raises(SystemExit, match="over --max-km2"):
        po.place_orders(fake, plan, confirm=True, max_km2=3000)
    assert fake.orders == []


def test_recent_months_flagged_for_delay(tmp_path):
    fake = FakePlanet({})
    plan = po.make_plan(fake, AOI, ["2026-09", "2026-10"], 0.3, today=date(2026, 10, 11))
    assert "delay" not in plan["months"][0].get("note", "") and "delay" in plan["months"][1]["note"]


def test_thin_months_are_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(po, "OUT", tmp_path); monkeypatch.setattr(po, "ORDERS_LOG", tmp_path / "orders.json")
    sliver = {"type": "Polygon", "coordinates": [[[107.0, 20.9], [107.225, 20.9], [107.225, 21.2], [107.0, 21.2], [107.0, 20.9]]]}
    fake = FakePlanet({"2025-01": [item("full", "2025-01-12T03:00:00Z", ALL)], "2025-02": [item("thin", "2025-02-13T03:00:00Z", sliver)]})
    plan = po.make_plan(fake, AOI, ["2025-01", "2025-02"], 0.3, today=date(2026, 10, 11))
    assert plan["months"][1]["coverage"] < 0.5
    po.place_orders(fake, plan, confirm=True, max_km2=3000)
    assert [o["products"][0]["item_ids"] for o in fake.orders] == [["full"]]
    assert "2025-02" not in po.load_log() and "under 50% of the AOI, skipped" in capsys.readouterr().out


def test_mirror_copies_new_and_changed_files_only(tmp_path):
    src, dst = tmp_path / "raw", tmp_path / "drive"
    src.mkdir()
    (src / "a_SR.tif").write_bytes(b"1234"); (src / "b.json").write_text("{}"); (src / "c.tif.part").write_bytes(b"x")
    assert po.mirror(src, dst) == 2 and not (dst / "c.tif.part").exists()
    assert po.mirror(src, dst) == 0                                   # nothing new
    (src / "b.json").write_text('{"x": 1}')
    assert po.mirror(src, dst) == 1 and (dst / "b.json").read_text() == '{"x": 1}'


class Stream:
    """A streamed download that can break after `cut` bytes, like Planet's dropped connection."""
    def __init__(self, data, code=200, cut=None):
        self.data, self.status_code, self.cut, self.text = data, code, cut, ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        import requests
        sent = self.data if self.cut is None else self.data[:self.cut]
        for i in range(0, len(sent), 4):
            yield sent[i:i + 4]
        if self.cut is not None:
            raise requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead")


class FlakyHost:
    def __init__(self, data, honour_range=True):
        self.data, self.honour_range, self.calls = data, honour_range, []

    def get(self, url, stream=False, headers=None, timeout=None):
        self.calls.append(dict(headers or {}))
        if len(self.calls) == 1:
            return Stream(self.data, cut=10)                      # first try breaks after 10 bytes
        start = int(headers["Range"][6:-1]) if headers and self.honour_range else 0
        return Stream(self.data[start:], code=206 if start else 200)


@pytest.mark.parametrize("honour_range", [True, False])
def test_fetch_resumes_after_dropped_connection(tmp_path, monkeypatch, honour_range):
    monkeypatch.setattr(po.time, "sleep", lambda s: None)
    data = bytes(range(40))
    host, target = FlakyHost(data, honour_range), tmp_path / "scene_SR.tif"
    assert po.fetch(host, "https://x/scene", target)
    assert target.read_bytes() == data and not (tmp_path / "scene_SR.tif.part").exists()
    assert host.calls[1] == {"Range": "bytes=10-"}               # asked for the rest, not the whole file


def test_fetch_gives_up_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(po.time, "sleep", lambda s: None)

    class Dead:
        def get(self, *a, **k):
            return Stream(b"0123456789", cut=0)
    target = tmp_path / "x.tif"
    assert po.fetch(Dead(), "https://x", target, attempts=3) is False and not target.exists()
