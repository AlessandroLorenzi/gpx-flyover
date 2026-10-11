from datetime import date
from zoneinfo import ZoneInfo

from gpx_flyover import gpx, overlay
from tests.test_gpx import make_gpx

TZ = ZoneInfo("Europe/Rome")


def test_date_range_formats():
    assert overlay.date_range([date(2026, 10, 10)]) == "10 ottobre 2026"
    assert overlay.date_range([date(2026, 10, 10), date(2026, 10, 11)]) == "10-11 ottobre 2026"
    assert overlay.date_range([date(2026, 9, 30), date(2026, 10, 1)]) == "30 settembre - 1 ottobre 2026"


def test_km_uses_italian_decimal_comma():
    assert overlay.km(25412) == "25,4 km"


def test_stage_labels_number_days_and_merge_same_stage():
    segs = (
        gpx.parse(make_gpx("Salita", "2026-10-10T09:00:00Z"))
        + gpx.parse(make_gpx("Salita", "2026-10-10T11:00:00Z"))
        + gpx.parse(make_gpx("Discesa", "2026-10-11T08:00:00Z"))
    )
    labels = overlay.stage_labels(segs, [0.0, 0.3, 0.5], TZ, t0=4, t1=84)
    assert [lb.text for lb in labels] == ["Giorno 1  ·  Salita", "Giorno 2  ·  Discesa"]
    assert labels[0].end == labels[1].start == 44
    assert labels[1].end == 84


def test_single_day_has_no_day_prefix():
    segs = gpx.parse(make_gpx("Giro", "2026-10-10T09:00:00Z"))
    (lb,) = overlay.stage_labels(segs, [0.0], TZ, t0=4, t1=60)
    assert lb.text == "Giro"
