import pytest

from gpx_flyover import gpx, scene
from tests.test_gpx import make_gpx


def _segs(*lat0s: float):
    return [gpx.parse(make_gpx(f"T{i}", f"2026-10-10T0{i}:00:00Z", lat0=la))[0] for i, la in enumerate(lat0s)]


def test_pieces_split_only_on_large_gaps():
    # ogni tratto è lungo ~222 m verso nord; il secondo parte dalla fine del primo, il terzo 11 km più in là
    segs = _segs(45.9, 45.902, 46.0)
    assert scene.pieces(segs) == [[0, 1], [2]]
    assert scene.pieces(segs, max_gap_m=1e6) == [[0, 1, 2]]


def test_segment_fractions_ignore_the_gap_between_pieces():
    segs = _segs(45.9, 46.0)
    assert scene.segment_fractions(segs) == pytest.approx([0.0, 0.5], abs=0.01)
    # senza stacco il salto di ~11 km domina la lunghezza totale
    assert scene.segment_fractions(segs, max_gap_m=1e6)[1] > 0.9
