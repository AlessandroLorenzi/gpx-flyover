"""Download (con cache) di tile Web Mercator: quote Terrarium e ortofoto Esri."""

from __future__ import annotations

import io
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

SOURCES = {
    "terrarium": ("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "png", 15),
    "esri": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "jpg",
        19,
    ),
}
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gpx-flyover" / "tiles"


def merc(lat, lon):
    """Coordinate Web Mercator normalizzate in [0, 1)."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    x = (lon + 180) / 360
    y = (1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2
    return x, y


@dataclass
class Mosaic:
    """Mosaico di tile. x0, y0 = coordinate mercator normalizzate dell'angolo in alto a sinistra."""

    image: Image.Image
    zoom: int
    x0: float
    y0: float

    @property
    def scale(self) -> float:
        """Pixel per unità mercator normalizzata."""
        return 256 * 2**self.zoom

    @property
    def x1(self) -> float:
        return self.x0 + self.image.size[0] / self.scale

    @property
    def y1(self) -> float:
        return self.y0 + self.image.size[1] / self.scale


_session = requests.Session()
_session.headers["User-Agent"] = "gpx-flyover/0.1 (personal use)"


def _tile(source: str, z: int, x: int, y: int) -> Image.Image:
    url, ext, _ = SOURCES[source]
    path = CACHE / source / str(z) / str(x) / f"{y}.{ext}"
    if not path.exists():
        err: Exception | None = None
        for _ in range(4):
            try:
                r = _session.get(url.format(z=z, x=x, y=y), timeout=30)
                r.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
                break
            except requests.RequestException as e:
                err = e
        else:
            raise RuntimeError(f"Download fallito per {source} {z}/{x}/{y}: {err}")
    return Image.open(path).convert("RGB")


def tile_count(bbox: tuple[float, float, float, float], z: int) -> int:
    lat0, lat1, lon0, lon1 = bbox
    (xa, xb), (ya, yb) = merc([lat1, lat0], [lon0, lon1])
    n = 2**z
    return (int(xb * n) - int(xa * n) + 1) * (int(yb * n) - int(ya * n) + 1)


def mosaic(source: str, bbox: tuple[float, float, float, float], z: int) -> Mosaic:
    """Scarica e incolla tutte le tile che coprono bbox = (lat_min, lat_max, lon_min, lon_max)."""
    lat0, lat1, lon0, lon1 = bbox
    (xa, xb), (ya, yb) = merc([lat1, lat0], [lon0, lon1])
    n = 2**z
    xs = range(int(xa * n), int(xb * n) + 1)
    ys = range(int(ya * n), int(yb * n) + 1)
    jobs = [(x, y) for x in xs for y in ys]
    print(f"  {source} z{z}: {len(jobs)} tile", file=sys.stderr)
    with ThreadPoolExecutor(8) as ex:
        tiles = list(ex.map(lambda xy: _tile(source, z, *xy), jobs))
    out = Image.new("RGB", (256 * len(xs), 256 * len(ys)))
    for (x, y), im in zip(jobs, tiles):
        out.paste(im, (256 * (x - xs[0]), 256 * (y - ys[0])))
    return Mosaic(out, z, xs[0] / n, ys[0] / n)


def terrarium_to_height(m: Mosaic) -> np.ndarray:
    a = np.asarray(m.image).astype(np.float64)
    return (a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768).astype(np.float32)


def pick_zoom(bbox, max_px: int, z_max: int, z_min: int = 8) -> int:
    """Zoom più alto il cui mosaico resta entro max_px pixel per lato."""
    lat0, lat1, lon0, lon1 = bbox
    (xa, xb), (ya, yb) = merc([lat1, lat0], [lon0, lon1])
    for z in range(z_max, z_min - 1, -1):
        if max(xb - xa, yb - ya) * 256 * 2**z <= max_px:
            return z
    return z_min
