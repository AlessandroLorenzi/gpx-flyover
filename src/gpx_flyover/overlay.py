"""Testi sovrapposti (titolo, tappe, crediti) e codifica finale con ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, tzinfo
from pathlib import Path

from .gpx import Segment

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]  # fmt: skip
ATTRIBUTION = "Immagini: Esri World Imagery  ·  Quote: Mapzen Terrarium (AWS)"
FADE_S = 0.6
TITLE_END_S = 5.5


@dataclass
class Label:
    text: str
    start: float  # secondi
    end: float


def date_range(days: list[date]) -> str:
    if not days:
        return ""
    a, b = min(days), max(days)
    if a == b:
        return f"{a.day} {MESI[a.month - 1]} {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}-{b.day} {MESI[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day} {MESI[a.month - 1]} - {b.day} {MESI[b.month - 1]} {a.year}"
    return f"{a.day} {MESI[a.month - 1]} {a.year} - {b.day} {MESI[b.month - 1]} {b.year}"


def km(meters: float) -> str:
    return f"{meters / 1000:.1f}".replace(".", ",") + " km"


def subtitle(segs: list[Segment], total_m: float, tz: tzinfo) -> str:
    days = [s.start.astimezone(tz).date() for s in segs if s.start]
    return "  ·  ".join(p for p in (date_range(days), km(total_m)) if p)


def stage_labels(segs: list[Segment], seg_frac: list[float], tz: tzinfo, t0: float, t1: float) -> list[Label]:
    """Un'etichetta per ogni gruppo di tratti consecutivi con stesso nome e stesso giorno.

    t0/t1 sono gli istanti (s) in cui la traccia inizia e finisce di disegnarsi.
    """
    days = sorted({s.start.astimezone(tz).date() for s in segs if s.start})
    multi_day = len(days) > 1
    texts = []
    for s in segs:
        prefix = ""
        if multi_day and s.start:
            prefix = f"Giorno {days.index(s.start.astimezone(tz).date()) + 1}  ·  "
        texts.append(prefix + s.name)
    labels: list[Label] = []
    for i, text in enumerate(texts):
        start = t0 + seg_frac[i] * (t1 - t0)
        if labels and labels[-1].text == text:
            continue
        if labels:
            labels[-1].end = start
        labels.append(Label(text, start, t1))
    if labels:  # la prima etichetta compare dopo che il titolo è sparito
        labels[0].start = max(labels[0].start, TITLE_END_S - 0.5)
    return [lb for lb in labels if lb.text.strip() and lb.end - lb.start > 1.5]


def _alpha(a: float, b: float) -> str:
    f = FADE_S
    return (f"if(lt(t,{a:.2f}),0,if(lt(t,{a + f:.2f}),(t-{a:.2f})/{f},"
            f"if(lt(t,{b - f:.2f}),1,if(lt(t,{b:.2f}),({b:.2f}-t)/{f},0))))")  # fmt: skip


def _font(pattern: str) -> str:
    if shutil.which("fc-match"):
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout.strip()
        if out:
            return out
    return "DejaVuSans.ttf"


def encode(workdir: Path, out: Path, fps: int, duration: float, height: int,
           title: str, sub: str, labels: list[Label], end_title_at: float) -> None:  # fmt: skip
    txt = workdir / "txt"
    txt.mkdir(exist_ok=True)
    bold, medium = _font("Inter:bold"), _font("Inter:medium")
    k = height / 1080  # scala dei font rispetto al 1080p
    files: dict[str, str] = {}

    def tf(key: str, text: str) -> str:
        p = txt / key
        p.write_text(text, encoding="utf-8")
        files[key] = str(p)
        return str(p)

    shadow = "shadowcolor=black@0.6:shadowx=3:shadowy=3"
    end = duration
    filters = [
        f"drawtext=fontfile={bold}:textfile={tf('title', title)}:fontsize={84 * k:.0f}:fontcolor=white:"
        f"x=(w-tw)/2:y=h/2-{90 * k:.0f}:{shadow}:alpha='{_alpha(0.3, TITLE_END_S)}'",
        f"drawtext=fontfile={bold}:textfile={files['title']}:fontsize={72 * k:.0f}:fontcolor=white:"
        f"x=(w-tw)/2:y={80 * k:.0f}:{shadow}:alpha='{_alpha(end_title_at, end + 1)}'",
    ]
    if sub:
        tf("sub", sub)
        filters += [
            f"drawtext=fontfile={medium}:textfile={files['sub']}:fontsize={44 * k:.0f}:fontcolor=white:"
            f"x=(w-tw)/2:y=h/2+{20 * k:.0f}:{shadow}:alpha='{_alpha(0.8, TITLE_END_S)}'",
            f"drawtext=fontfile={medium}:textfile={files['sub']}:fontsize={40 * k:.0f}:fontcolor=white:"
            f"x=(w-tw)/2:y={175 * k:.0f}:{shadow}:alpha='{_alpha(end_title_at + 0.4, end + 1)}'",
        ]
    for i, lb in enumerate(labels):
        filters.append(
            f"drawtext=fontfile={medium}:textfile={tf(f'stage{i}', lb.text)}:fontsize={40 * k:.0f}:fontcolor=white:"
            f"x={60 * k:.0f}:y=h-{120 * k:.0f}:box=1:boxcolor=black@0.45:boxborderw={18 * k:.0f}:"
            f"alpha='{_alpha(lb.start, lb.end)}'"
        )
    filters += [
        f"drawtext=fontfile={medium}:textfile={tf('att', ATTRIBUTION)}:fontsize={20 * k:.0f}:fontcolor=white@0.8:"
        f"x=w-tw-{24 * k:.0f}:y=h-{40 * k:.0f}:shadowcolor=black@0.7:shadowx=1:shadowy=1",
        f"fade=t=in:st=0:d=0.8,fade=t=out:st={end - 0.8:.2f}:d=0.8",
    ]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
           "-i", str(workdir / "frames" / "f_%04d.png"), "-vf", ",".join(filters),
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]  # fmt: skip
    subprocess.run(cmd, check=True)
