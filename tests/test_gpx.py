from datetime import datetime, timezone

import numpy as np

from gpx_flyover import gpx


def make_gpx(name: str, start: str, n: int = 3, lat0: float = 45.9) -> bytes:
    pts = "".join(
        f'<trkpt lat="{lat0 + i * 0.001}" lon="9.07"><ele>{1000 + i}</ele>'
        f"<time>{start[:-3]}{i:02d}Z</time></trkpt>"
        for i in range(n)
    )
    return (
        '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">'
        f"<trk><name>{name} - Wikiloc</name><trkseg>{pts}</trkseg></trk></gpx>"
    ).encode()


def test_parse_strips_wikiloc_suffix_and_reads_points():
    (seg,) = gpx.parse(make_gpx("Giro", "2026-10-10T09:00:00Z"))
    assert seg.name == "Giro"
    assert len(seg.lat) == 3
    assert seg.start == datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)


def test_load_orders_segments_by_start_time(tmp_path):
    late = tmp_path / "b.gpx"
    early = tmp_path / "a.gpx"
    late.write_bytes(make_gpx("Secondo", "2026-10-11T07:00:00Z"))
    early.write_bytes(make_gpx("Primo", "2026-10-10T09:00:00Z"))
    segs = gpx.load([str(late), str(early)])
    assert [s.name for s in segs] == ["Primo", "Secondo"]


def test_write_roundtrip_keeps_segments(tmp_path):
    segs = gpx.parse(make_gpx("A", "2026-10-10T09:00:00Z")) + gpx.parse(make_gpx("B", "2026-10-10T12:00:00Z"))
    out = tmp_path / "m.gpx"
    gpx.write(segs, "Unito", out)
    back = gpx.parse(out.read_bytes())
    assert len(back) == 2 and all(s.name == "Unito" for s in back)
    np.testing.assert_allclose(back[0].lat, segs[0].lat)


def test_length_m_is_about_111m_per_millidegree_lat():
    (seg,) = gpx.parse(make_gpx("A", "2026-10-10T09:00:00Z", n=2))
    assert abs(gpx.length_m(seg) - 111.2) < 1
