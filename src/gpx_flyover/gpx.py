"""Lettura, unione e scrittura di tracce GPX."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

NS = "http://www.topografix.com/GPX/1/1"
_NAME_SUFFIX = re.compile(r"\s*-\s*Wikiloc\s*$", re.IGNORECASE)


@dataclass
class Segment:
    """Un tratto continuo di traccia (un <trkseg>)."""

    name: str
    lat: np.ndarray
    lon: np.ndarray
    ele: np.ndarray
    time: list[datetime | None]

    @property
    def start(self) -> datetime | None:
        return next((t for t in self.time if t is not None), None)


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _tag(c) == name), None)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def read_source(src: str) -> bytes:
    """Legge un GPX da percorso locale o da URL http(s)."""
    if re.match(r"^https?://", src):
        r = requests.get(src, timeout=60, headers={"User-Agent": "gpx-flyover/0.1"})
        r.raise_for_status()
        return r.content
    return Path(src).expanduser().read_bytes()


def parse(data: bytes, fallback_name: str = "") -> list[Segment]:
    root = ET.parse(io.BytesIO(data)).getroot()
    segs: list[Segment] = []
    for trk in (e for e in root.iter() if _tag(e) == "trk"):
        n = _child(trk, "name")
        name = _NAME_SUFFIX.sub("", n.text.strip()) if n is not None and n.text else fallback_name
        for seg in (e for e in trk if _tag(e) == "trkseg"):
            pts = [p for p in seg if _tag(p) == "trkpt"]
            if len(pts) < 2:
                continue
            ele = [_child(p, "ele") for p in pts]
            tim = [_child(p, "time") for p in pts]
            segs.append(
                Segment(
                    name=name,
                    lat=np.array([float(p.get("lat")) for p in pts]),
                    lon=np.array([float(p.get("lon")) for p in pts]),
                    ele=np.array([float(e.text) if e is not None and e.text else np.nan for e in ele]),
                    time=[_parse_time(t.text if t is not None else None) for t in tim],
                )
            )
    return segs


def load(sources: list[str]) -> list[Segment]:
    """Carica tutte le sorgenti e ordina i tratti per orario di partenza.

    I tratti senza orario restano nell'ordine in cui sono stati passati, dopo quelli datati.
    """
    segs: list[Segment] = []
    for src in sources:
        segs += parse(read_source(src), fallback_name=Path(src).stem)
    if not segs:
        raise ValueError("Nessun punto traccia trovato nei GPX forniti")
    timed = sorted((s for s in segs if s.start), key=lambda s: s.start)
    return timed + [s for s in segs if not s.start]


def haversine(lat1, lon1, lat2, lon2) -> np.ndarray:
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * np.arcsin(np.sqrt(a))


def length_m(seg: Segment) -> float:
    return float(haversine(seg.lat[:-1], seg.lon[:-1], seg.lat[1:], seg.lon[1:]).sum())


def write(segs: list[Segment], name: str, path: Path) -> None:
    """Scrive un unico <trk> con un <trkseg> per ogni tratto."""
    ET.register_namespace("", NS)
    q = lambda t: f"{{{NS}}}{t}"  # noqa: E731
    gpx = ET.Element(q("gpx"), {"version": "1.1", "creator": "gpx-flyover"})
    md = ET.SubElement(gpx, q("metadata"))
    ET.SubElement(md, q("name")).text = name
    if segs[0].start:
        ET.SubElement(md, q("time")).text = segs[0].start.isoformat().replace("+00:00", "Z")
    trk = ET.SubElement(gpx, q("trk"))
    ET.SubElement(trk, q("name")).text = name
    for s in segs:
        ts = ET.SubElement(trk, q("trkseg"))
        for i in range(len(s.lat)):
            p = ET.SubElement(ts, q("trkpt"), {"lat": f"{s.lat[i]:.6f}", "lon": f"{s.lon[i]:.6f}"})
            if not np.isnan(s.ele[i]):
                ET.SubElement(p, q("ele")).text = f"{s.ele[i]:.3f}"
            if s.time[i]:
                ET.SubElement(p, q("time")).text = s.time[i].isoformat().replace("+00:00", "Z")
    ET.indent(gpx)
    ET.ElementTree(gpx).write(path, encoding="UTF-8", xml_declaration=True)
