"""Preparazione dei dati di scena: terreno, ortofoto, traccia e percorso della telecamera."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates

from . import colorfix, tiles
from .gpx import Segment

EARTH_CIRC = 40075016.686
INNER_PAD_KM = 2.0
OUTER_PAD_KM = 20.0
TRACK_LIFT_M = 3.0  # la traccia galleggia appena sopra il terreno
RESAMPLE_M = 4.0

# Telecamera: distanze in metri, smoothing espresso in metri di traccia
CAM_BACK_M = 650
CAM_UP_M = 420
CAM_MIN_CLEARANCE_M = 180
SMOOTH_LOOK_M = 280
SMOOTH_HEADING_PATH_M = 1000
SMOOTH_HEADING_ANGLE_M = 680
SMOOTH_HEIGHT_M = 230
HOLD_ORBIT_DEG = 25  # rotazione attorno al percorso durante la pausa finale


@dataclass
class Timeline:
    fps: int
    intro: int
    main: int
    outro: int
    hold: int = 0  # pausa finale sulla vista d'insieme

    @property
    def frames(self) -> int:
        return self.intro + self.main + self.outro + self.hold


def _pad_bbox(lat: np.ndarray, lon: np.ndarray, km: float) -> tuple[float, float, float, float]:
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians(lat.mean())))
    return lat.min() - dlat, lat.max() + dlat, lon.min() - dlon, lon.max() + dlon


def _sampler(m: tiles.Mosaic, h: np.ndarray):
    def at(mx, my):
        c = (np.asarray(mx) - m.x0) * m.scale
        r = (np.asarray(my) - m.y0) * m.scale
        return map_coordinates(h, [np.atleast_1d(r).ravel(), np.atleast_1d(c).ravel()], order=1, mode="nearest").reshape(
            np.shape(mx)
        )

    return at


def _ease(n: int) -> np.ndarray:
    return ((1 - np.cos(np.pi * np.linspace(0, 1, n))) / 2)[:, None]


def build(segs: list[Segment], tl: Timeline, workdir: Path, fix_colors: bool = True) -> dict:
    """Scarica i dati, scrive scene.npz e le ortofoto in workdir. Restituisce i metadati per gli overlay."""
    lat = np.concatenate([s.lat for s in segs])
    lon = np.concatenate([s.lon for s in segs])

    print("Download quote e ortofoto...", file=sys.stderr)
    ib = _pad_bbox(lat, lon, INNER_PAD_KM)
    ob = _pad_bbox(lat, lon, OUTER_PAD_KM)
    sat_i = tiles.mosaic("esri", ib, tiles.pick_zoom(ib, 12000, 17))
    dem_i_m = tiles.mosaic("terrarium", ib, tiles.pick_zoom(ib, 4096, 15))
    sat_o = tiles.mosaic("esri", ob, tiles.pick_zoom(ob, 8000, 14))
    dem_o_m = tiles.mosaic("terrarium", ob, tiles.pick_zoom(ob, 2048, 12))
    dem_i = _sampler(dem_i_m, tiles.terrarium_to_height(dem_i_m))
    dem_o = _sampler(dem_o_m, tiles.terrarium_to_height(dem_o_m))

    if fix_colors:
        sat_i.image, n = colorfix.fix(sat_i.image)
        print(f"  correzione colore: {n} tile ritoccate", file=sys.stderr)
    sat_i.image.save(workdir / "sat_inner.jpg", quality=92)
    sat_o.image.save(workdir / "sat_outer.jpg", quality=92)

    # sistema metrico locale centrato sulla traccia (x verso est, y verso nord)
    tmx, tmy = tiles.merc(lat, lon)
    cx, cy = tmx.mean(), tmy.mean()
    mpu = EARTH_CIRC * math.cos(math.radians(lat.mean()))
    to_m = lambda mx, my: ((np.asarray(mx) - cx) * mpu, -(np.asarray(my) - cy) * mpu)  # noqa: E731
    to_merc = lambda x, y: (np.asarray(x) / mpu + cx, -np.asarray(y) / mpu + cy)  # noqa: E731

    # terreno interno
    n = 700
    gx = np.linspace(sat_i.x0, sat_i.x1, n)
    gy = np.linspace(sat_i.y0, sat_i.y1, max(2, int(n * (sat_i.y1 - sat_i.y0) / (sat_i.x1 - sat_i.x0))))
    GX, GY = np.meshgrid(gx, gy)
    z_in = dem_i(GX, GY)
    ext_in = np.array([*to_m(gx[[0, -1]], gy[[0, -1]])]).ravel()  # x0, x1, y0, y1

    # terreno esterno: dentro l'area interna usa le quote fini (abbassate) per evitare gradini
    gxo = np.linspace(sat_o.x0, sat_o.x1, 640)
    gyo = np.linspace(sat_o.y0, sat_o.y1, 640)
    GXo, GYo = np.meshgrid(gxo, gyo)
    z_out = dem_o(GXo, GYo)
    inside = (GXo >= gx[0]) & (GXo <= gx[-1]) & (GYo >= gy[0]) & (GYo <= gy[-1])
    z_out[inside] = dem_i(GXo[inside], GYo[inside])
    z_out -= 4
    ext_out = np.array([*to_m(gxo[[0, -1]], gyo[[0, -1]])]).ravel()

    # traccia ricampionata a passo costante
    px, py = to_m(tmx, tmy)
    P = np.c_[px, py]
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    # frazione di percorso a cui inizia ogni tratto
    starts = np.cumsum([0] + [len(sg.lat) for sg in segs[:-1]])
    seg_frac = (d[starts] / d[-1]).tolist()
    keep = np.r_[True, np.diff(d) > 0]
    P, d = P[keep], d[keep]
    total = float(d[-1])
    s = np.arange(0, total, RESAMPLE_M)
    T = gaussian_filter1d(np.c_[np.interp(s, d, P[:, 0]), np.interp(s, d, P[:, 1])], 1.5, axis=0)
    track = np.c_[T, dem_i(*to_merc(T[:, 0], T[:, 1])) + TRACK_LIFT_M]

    # telecamera
    per_m = tl.main / total  # frame per metro
    sig = lambda m: max(1.0, m * per_m)  # noqa: E731
    u = np.linspace(0, 1, tl.main)
    idx = u * (len(track) - 1)
    look = np.c_[[np.interp(idx, np.arange(len(track)), track[:, k]) for k in range(3)]].T
    look = gaussian_filter1d(look, sig(SMOOTH_LOOK_M), axis=0, mode="nearest")
    hp = gaussian_filter1d(look[:, :2], sig(SMOOTH_HEADING_PATH_M), axis=0, mode="nearest")
    dv = np.gradient(hp, axis=0)
    ang = gaussian_filter1d(np.unwrap(np.arctan2(dv[:, 1], dv[:, 0])), sig(SMOOTH_HEADING_ANGLE_M), mode="nearest")
    cam = np.c_[look[:, 0] - CAM_BACK_M * np.cos(ang), look[:, 1] - CAM_BACK_M * np.sin(ang), look[:, 2] + CAM_UP_M]
    ground = dem_o(*to_merc(cam[:, 0], cam[:, 1]))
    inner = (cam[:, 0] > ext_in[0]) & (cam[:, 0] < ext_in[1]) & (cam[:, 1] < ext_in[2]) & (cam[:, 1] > ext_in[3])
    ground[inner] = dem_i(*to_merc(cam[inner, 0], cam[inner, 1]))
    cam[:, 2] = gaussian_filter1d(np.maximum(cam[:, 2], ground + CAM_MIN_CLEARANCE_M), sig(SMOOTH_HEIGHT_M), mode="nearest")

    # intro e finale: vista d'insieme
    span = float(np.ptp(track[:, :2], axis=0).max())
    ctr = np.r_[track[:, :2].mean(0), track[:, 2].mean()]
    dist = max(2600.0, 1.1 * span)
    ov_in = ctr + np.array([-dist * np.cos(ang[0]), -dist * np.sin(ang[0]), dist])
    ov_out = ctr + np.array([-1.08 * dist * np.cos(ang[-1]), -1.08 * dist * np.sin(ang[-1]), 1.15 * dist])
    e = _ease(tl.intro)
    ci, li = ov_in * (1 - e) + cam[0] * e, ctr * (1 - e) + look[0] * e
    e = _ease(tl.outro)
    co, lo = cam[-1] * (1 - e) + ov_out * e, look[-1] * (1 - e) + ctr * e
    th = np.radians(HOLD_ORBIT_DEG) * _ease(tl.hold)[:, 0]
    rel = ov_out - ctr
    ch = ctr + np.c_[rel[0] * np.cos(th) - rel[1] * np.sin(th), rel[0] * np.sin(th) + rel[1] * np.cos(th), np.full(tl.hold, rel[2])]
    lh = np.tile(ctr, (tl.hold, 1))

    np.savez(
        workdir / "scene.npz",
        Z=z_in.astype(np.float32),
        ext=ext_in,
        Zo=z_out.astype(np.float32),
        exto=ext_out,
        track=track,
        cam=np.r_[ci, cam, co, ch],
        look=np.r_[li, look, lo, lh],
        reveal=np.r_[np.zeros(tl.intro), u, np.ones(tl.outro + tl.hold)],
        fps=tl.fps,
    )
    return {"total_m": total, "seg_frac": seg_frac}
