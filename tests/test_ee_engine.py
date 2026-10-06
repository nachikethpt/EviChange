from agents.ee_engine import _change_bands


class FakeImage:
    """The few ee.Image operations _change_bands uses, on a flat list of pixels (None = masked)."""

    def __init__(self, pixels):
        self.pixels = list(pixels)

    def _map(self, fn):
        return FakeImage(None if p is None else fn(p) for p in self.pixels)

    def abs(self):
        return self._map(abs)

    def gt(self, value):
        return self._map(lambda p: int(p > value))

    def gte(self, value):
        return self._map(lambda p: int(p >= value))

    def add(self, other):
        return FakeImage(None if a is None or b is None else a + b for a, b in zip(self.pixels, other.pixels))

    def selfMask(self):
        return self._map(lambda p: p or None)

    def rename(self, name):
        return self


def region_mean_conf(d_ndvi, d_ndbi, d_mndwi, index_delta=0.1):
    """Mean of the agreement band over the pixels the change mask keeps, like reduceToVectors."""
    mask, agreement = _change_bands(FakeImage(d_ndvi), FakeImage(d_ndbi), FakeImage(d_mndwi), index_delta)
    kept = [a for m, a in zip(mask.pixels, agreement.pixels) if m is not None]
    return len(kept), sum(kept) / len(kept)


def test_change_mask_keeps_pixels_where_two_of_three_indices_change():
    # Votes per pixel: 0, 1, 2, 3. A single index over the threshold is not change.
    mask, _ = _change_bands(FakeImage([0.0, 0.3, 0.3, 0.3]), FakeImage([0.0, 0.0, -0.2, 0.2]),
                            FakeImage([0.0, 0.0, 0.0, 0.5]), 0.1)
    assert mask.pixels == [None, None, 1, 1]


def test_mean_conf_is_share_of_pixels_where_all_three_agree():
    # 4 changed pixels (2+ votes each); all three agree on the last two only.
    count, conf = region_mean_conf([0.3, 0.3, 0.3, -0.4], [0.2, 0.2, 0.2, 0.15], [0.0, 0.0, 0.5, -0.3])
    assert count == 4 and conf == 0.5


def test_mean_conf_varies_between_regions():
    _, weak = region_mean_conf([0.3, 0.3, 0.3], [0.2, 0.2, 0.2], [0.0, 0.0, 0.2])
    _, strong = region_mean_conf([0.3, 0.3, 0.3], [0.2, 0.2, 0.2], [0.4, 0.4, 0.4])
    assert weak == 1 / 3 and strong == 1.0
