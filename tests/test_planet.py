import pytest

from agents import planet


def test_asset_ids_round_trip():
    a = planet.asset_id("2024-10", "projects/p/assets/planet_qn")
    assert a == "projects/p/assets/planet_qn/m2024_10"
    assert planet.month_of_asset(a) == "2024-10"
    assert planet.month_of_asset("projects/p/assets/planet_qn/other") is None


@pytest.mark.parametrize("bad", ["2024-13", "2024-1", "24-10", "", "2024/10"])
def test_bad_months_rejected(bad):
    with pytest.raises(ValueError):
        planet.asset_id(bad)


def test_asset_properties():
    p = planet.asset_properties("2024-10", "2024-10-05", ["a", "b"], 0.98765)
    assert p["month"] == "2024-10" and p["scene_count"] == 2 and p["item_ids"] == "a,b"
    assert p["clear_share"] == 0.9877 and "Planet Labs" in p["attribution"]
    with pytest.raises(ValueError, match="not in"):
        planet.asset_properties("2024-10", "2024-11-01", ["a"], 1.0)


def test_ingestion_manifest_has_nine_bands_with_zero_as_no_data():
    m = planet.ingestion_manifest("2025-03", "2025-03-20", "gs://b/planet_qn_2025-03.tif", {"month": "2025-03"},
                                  collection="projects/p/assets/planet_qn")
    assert m["name"] == "projects/p/assets/planet_qn/m2025_03"
    assert [b["id"] for b in m["bands"]] == list(planet.BANDS) and len(m["bands"]) == 9
    assert all(b["missingData"] == {"values": [0]} for b in m["bands"])
    assert m["startTime"] == "2025-03-20T00:00:00Z"
    assert m["tilesets"][0]["sources"][0]["uris"] == ["gs://b/planet_qn_2025-03.tif"]


def test_missing_months_skips_february():
    expected = [f"2024-{m}" for m in ("10", "11", "12")] + [f"2025-{m:02d}" for m in range(1, 10)]
    have = [m for m in expected if m != "2025-02"]
    assert planet.missing_months(expected, have) == ["2025-02"]


def test_no_swir_on_planet():
    assert "swir" not in " ".join(planet.BANDS)
    assert all(bands[0] in planet.SR_BANDS for bands, *_ in planet.CHIP_VIS.values())


class FakeImage:
    """Records ee.Image calls that month_image() makes."""
    def __init__(self, log, name="img"):
        self.log, self.name = log, name

    def select(self, *args):
        self.log.append(("select", args)); return self

    def multiply(self, v):
        self.log.append(("multiply", v)); return self

    def eq(self, v):
        self.log.append(("eq", v)); return self

    def updateMask(self, m):
        self.log.append(("updateMask",)); return self

    def set(self, k, v):
        self.log.append(("set", k, v)); return self


class FakeEE:
    def __init__(self):
        self.log = []

    def Image(self, asset):
        self.log.append(("Image", asset)); return FakeImage(self.log)


def test_month_image_selects_bands_by_position_and_masks_clear():
    ee = FakeEE()
    planet.month_image(ee, "2025-06")
    assert ee.log[0] == ("Image", planet.asset_id("2025-06"))
    assert ee.log[1] == ("select", (list(range(9)), list(planet.BANDS)))     # works for b1..b9 or named bands
    assert ("multiply", planet.SR_SCALE) in ee.log and ("eq", 1) in ee.log and ("set", "month", "2025-06") in ee.log


def test_available_months_is_empty_without_collection():
    class Broken:
        def ImageCollection(self, _):
            raise RuntimeError("asset not found")
    assert planet.available_months(Broken()) == []


def test_month_catalog_reads_metadata_and_preserves_gaps():
    class Value:
        def __init__(self, value):
            self.value = value

        def getInfo(self):
            return self.value

    class Rows(Value):
        def map(self, fn):
            return Value([fn(row) for row in self.value])

    class Image:
        def __init__(self, row):
            self.row = row

        def toDictionary(self, keys):
            return {k: self.row[k] for k in keys if k in self.row}

    class Collection:
        def size(self):
            return Value(2)

        def toList(self, count):
            assert count == 2
            return Rows([{"month": "2025-03", "date": "2025-03-12", "clear_share": 0.6},
                         {"month": "2025-01", "date": "2025-01-03", "clear_share": 0.9}])

    class EE:
        def ImageCollection(self, name):
            assert name == planet.PLANET_COLLECTION
            return Collection()

    EE.Image = Image
    catalog = planet.month_catalog(EE())
    assert [m["month"] for m in catalog["months"]] == ["2025-01", "2025-03"]
    assert catalog["months"][0]["date"] == "2025-01-03"
    assert catalog["months"][0]["asset_id"] == planet.asset_id("2025-01")


def test_empty_month_catalog_does_not_call_to_list_zero():
    class Empty:
        def size(self):
            return self

        def getInfo(self):
            return 0

    class EE:
        def ImageCollection(self, _):
            return Empty()

    assert planet.month_catalog(EE())["months"] == []
