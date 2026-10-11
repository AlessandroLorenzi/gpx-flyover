"""Uniforma i riquadri di ortofoto provenienti da fonti diverse (es. swisstopo dentro Esri).

Le ortofoto Esri sono un mosaico di fonti: alcune zone (tipicamente la Svizzera) risultano
più chiare e meno sature, a blocchi allineati alla griglia delle tile. Qui si individuano
quei blocchi e si porta la loro media/deviazione colore su quella del resto dell'immagine.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, label, median_filter

WATER_SAT = 140  # saturazione media (0-255) sopra cui una tile è considerata acqua
PALE_SAT = 86  # sotto questa saturazione la tile è candidata "sbiadita"
PALE_VAL = 66  # ...ma solo se anche abbastanza luminosa (esclude bosco in ombra)
MIN_BLOCK = 6  # tile minime di un blocco connesso, per scartare falsi positivi isolati


def pale_mask(tile_hsv_mean: np.ndarray) -> np.ndarray:
    """Maschera booleana (per tile) delle zone da correggere."""
    s, v = tile_hsv_mean[..., 1], tile_hsv_mean[..., 2]
    water = s > WATER_SAT
    pale = (s < PALE_SAT) & (v > PALE_VAL) & ~water
    pale = median_filter(pale.astype(np.uint8), 3).astype(bool) & ~water
    lab, n = label(pale)
    if n:
        sizes = np.bincount(lab.ravel())
        pale = np.isin(lab, np.nonzero(sizes >= MIN_BLOCK)[0]) & (lab > 0)
    return pale


def fix(img: Image.Image, tile: int = 256) -> tuple[Image.Image, int]:
    """Restituisce l'immagine corretta e il numero di tile ritoccate."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    hsv = np.asarray(img.convert("HSV")).astype(np.float32)
    h, w, _ = rgb.shape
    ty, tx = h // tile, w // tile
    means = hsv[: ty * tile, : tx * tile].reshape(ty, tile, tx, tile, 3).mean((1, 3))
    pale = pale_mask(means)
    good = ~pale & (means[..., 1] <= WATER_SAT)
    if pale.sum() == 0 or good.sum() == 0:
        return img, 0

    def expand(m: np.ndarray) -> np.ndarray:
        big = np.kron(m, np.ones((tile, tile), dtype=m.dtype))
        return np.pad(big, ((0, h - big.shape[0]), (0, w - big.shape[1])), mode="edge")

    pm, gm = expand(pale), expand(good)
    mp, sp = rgb[pm].mean(0), rgb[pm].std(0) + 1e-3
    mg, sg = rgb[gm].mean(0), rgb[gm].std(0)
    fixed = (rgb - mp) / sp * sg + mg
    weight = gaussian_filter(pm.astype(np.float32), tile / 12)[..., None]
    out = np.clip(rgb * (1 - weight) + fixed * weight, 0, 255).astype(np.uint8)
    return Image.fromarray(out), int(pale.sum())
