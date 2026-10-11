import numpy as np

from gpx_flyover import colorfix


def tiles(s, v):
    m = np.zeros((s.shape[0], s.shape[1], 3))
    m[..., 1], m[..., 2] = s, v
    return m


def test_large_pale_block_detected_isolated_tile_ignored():
    s = np.full((10, 10), 110.0)
    v = np.full((10, 10), 45.0)
    s[0:4, 0:4], v[0:4, 0:4] = 60, 85  # blocco sbiadito 4x4
    s[8, 8], v[8, 8] = 60, 85  # tile isolata
    mask = colorfix.pale_mask(tiles(s, v))
    assert mask[1:3, 1:3].all()
    assert not mask[8, 8]


def test_water_never_pale():
    s = np.full((6, 6), 200.0)
    v = np.full((6, 6), 90.0)
    assert not colorfix.pale_mask(tiles(s, v)).any()
