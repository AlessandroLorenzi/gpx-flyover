"""Preparazione dei dati di scena: terreno, ortofoto, traccia e percorso della telecamera."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates

from . import colorfix, tiles
from .gpx import Segment, haversine

EARTH_CIRC = 40075016.686
INNER_PAD_KM = 2.0
OUTER_PAD_KM = 20.0
TRACK_LIFT_M = 3.0  # la traccia galleggia appena sopra il terreno
RESAMPLE_M = 4.0
MAX_GAP_M = 500.0  # oltre questa distanza tra due tratti consecutivi non si traccia la linea: stacco

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


def pieces(segs: list[Segment], max_gap_m: float = MAX_GAP_M) -> list[list[int]]:
    """Raggruppa i tratti consecutivi distanti al più max_gap_m: ogni gruppo è una linea continua."""
    groups = [[0]]
    for i in range(1, len(segs)):
        a, b = segs[i - 1], segs[i]
        if haversine(a.lat[-1], a.lon[-1], b.lat[0], b.lon[0]) > max_gap_m:
            groups.append([])
        groups[-1].append(i)
    return groups


def segment_fractions(segs: list[Segment], max_gap_m: float = MAX_GAP_M) -> list[float]:
    """Frazione di percorso (in pianta) a cui inizia ogni tratto, esclusi i salti tra un gruppo e l'altro."""
    lat = np.concatenate([s.lat for s in segs])
    lon = np.concatenate([s.lon for s in segs])
    mx, my = tiles.merc(lat, lon)
    step = np.hypot(np.diff(mx), np.diff(my))
    starts = np.cumsum([0] + [len(sg.lat) for sg in segs[:-1]])
    for g in pieces(segs, max_gap_m)[1:]:
        step[starts[g[0]] - 1] = 0
    d = np.r_[0, np.cumsum(step)]
    return (d[starts] / d[-1]).tolist()


def _resample(P: np.ndarray) -> np.ndarray:
    """Polilinea in pianta ricampionata a passo costante e appena smussata."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    keep = np.r_[True, np.diff(d) > 0]
    P, d = P[keep], d[keep]
    s = np.arange(0, d[-1], RESAMPLE_M)
    if len(s) < 2:
        return np.empty((0, 2))
    return gaussian_filter1d(np.c_[np.interp(s, d, P[:, 0]), np.interp(s, d, P[:, 1])], 1.5, axis=0)


def build(segs: list[Segment], tl: Timeline, workdir: Path, fix_colors: bool = True,
          max_gap_m: float = MAX_GAP_M) -> dict:  # fmt: skip
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

    # traccia ricampionata a passo costante, un pezzo per ogni gruppo di tratti vicini
    px, py = to_m(tmx, tmy)
    starts = np.cumsum([0] + [len(sg.lat) for sg in segs])
    parts = [_resample(np.c_[px, py][starts[g[0]] : starts[g[-1] + 1]]) for g in pieces(segs, max_gap_m)]
    parts = [T for T in parts if len(T) >= 2]
    if not parts:
        raise ValueError("Traccia troppo corta")
    T = np.concatenate(parts)
    breaks = np.cumsum([0] + [len(T) for T in parts[:-1]])  # indice del primo punto di ogni pezzo
    track = np.c_[T, dem_i(*to_merc(T[:, 0], T[:, 1])) + TRACK_LIFT_M]
    total = (len(track) - len(parts)) * RESAMPLE_M

    def ground(x, y):
        g = dem_o(*to_merc(x, y))
        inner = (x > ext_in[0]) & (x < ext_in[1]) & (y < ext_in[2]) & (y > ext_in[3])
        g[inner] = dem_i(*to_merc(x[inner], y[inner]))
        return g

    # telecamera: i fotogrammi sono ripartiti tra i pezzi in proporzione alla lunghezza e ogni pezzo
    # ha il suo inseguimento, così al passaggio da un pezzo all'altro c'è uno stacco netto
    per_m = tl.main / total  # frame per metro
    sig = lambda m: max(1.0, m * per_m)  # noqa: E731
    u = np.linspace(0, 1, tl.main)
    idx = u * (len(track) - 1)
    piece = np.searchsorted(breaks, idx, side="right") - 1
    ends = np.r_[breaks[1:], len(track)] - 1
    idx = np.minimum(idx, ends[piece])  # niente interpolazione attraverso il salto
    look_all = np.c_[[np.interp(idx, np.arange(len(track)), track[:, k]) for k in range(3)]].T
    looks, cams, angs = [], [], []
    for p in range(len(parts)):
        look = look_all[piece == p]
        if not len(look):
            continue
        look = gaussian_filter1d(look, sig(SMOOTH_LOOK_M), axis=0, mode="nearest")
        hp = gaussian_filter1d(look[:, :2], sig(SMOOTH_HEADING_PATH_M), axis=0, mode="nearest")
        dv = np.gradient(hp, axis=0) if len(hp) > 1 else np.ones_like(hp)
        ang = gaussian_filter1d(np.unwrap(np.arctan2(dv[:, 1], dv[:, 0])), sig(SMOOTH_HEADING_ANGLE_M), mode="nearest")
        cam = np.c_[look[:, 0] - CAM_BACK_M * np.cos(ang), look[:, 1] - CAM_BACK_M * np.sin(ang), look[:, 2] + CAM_UP_M]
        cam[:, 2] = gaussian_filter1d(
            np.maximum(cam[:, 2], ground(cam[:, 0], cam[:, 1]) + CAM_MIN_CLEARANCE_M), sig(SMOOTH_HEIGHT_M), mode="nearest"
        )
        looks.append(look), cams.append(cam), angs.append(ang)
    look, cam, ang = np.concatenate(looks), np.concatenate(cams), np.concatenate(angs)

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
        breaks=breaks,
        cam=np.r_[ci, cam, co, ch],
        look=np.r_[li, look, lo, lh],
        reveal=np.r_[np.zeros(tl.intro), u, np.ones(tl.outro + tl.hold)],
        fps=tl.fps,
    )
    return {"total_m": total, "seg_frac": segment_fractions(segs, max_gap_m)}
