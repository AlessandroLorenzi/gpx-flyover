"""flyover: da una o più tracce GPX a un video 3D di sorvolo."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from . import gpx, overlay, scene

INTRO_S = 4.0
OUTRO_S = 6.0


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "flyover"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="flyover", description=__doc__)
    p.add_argument("gpx", nargs="+", help="file GPX o URL diretti a file GPX (vengono uniti in ordine di orario)")
    p.add_argument("-o", "--output", type=Path, help="video di uscita (default: <titolo>.mp4)")
    p.add_argument("-t", "--title", help="titolo del video (default: nome della prima traccia)")
    p.add_argument("-d", "--duration", type=float, help="secondi di sorvolo, esclusi intro e finale (default: 3 s/km, 30-120)")
    p.add_argument("--hold", type=float, default=8.0, help="secondi di pausa finale sulla vista d'insieme (default: 8)")
    p.add_argument("--fps", type=int, help="fotogrammi al secondo (default: 30, in anteprima 15)")
    p.add_argument("--preview", action="store_true", help="anteprima veloce: 960x540, 15 fps, meno campioni")
    p.add_argument("--crf", type=int, default=26, help="qualità x264: più basso = migliore e più pesante (default: 26)")
    p.add_argument("--reencode", action="store_true", help="rigenera solo il video dai fotogrammi già in --workdir")
    p.add_argument("--merged-gpx", type=Path, help="salva anche il GPX unito in questo percorso")
    p.add_argument("--workdir", type=Path, help="cartella di lavoro (default: temporanea, cancellata alla fine)")
    p.add_argument("--no-colorfix", action="store_true", help="non uniformare i colori delle ortofoto")
    p.add_argument("--tz", default="Europe/Rome", help="fuso orario per date e giorni (default: Europe/Rome)")
    p.add_argument("--blender", default=shutil.which("blender") or "blender", help="eseguibile di Blender")
    return p.parse_args(argv)


def _render(blender: str, workdir: Path, width: int, height: int, samples: int, frames: int) -> None:
    script = Path(__file__).with_name("blender_render.py")
    cmd = [blender, "-b", "--factory-startup", "--python", str(script), "--",
           str(workdir), str(width), str(height), str(samples)]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tty = sys.stderr.isatty()
    done = 0
    tail: list[str] = []
    for line in proc.stdout:
        tail = (tail + [line])[-30:]
        if "Saved:" in line:
            done += 1
            if tty or done % max(1, frames // 20) == 0 or done == frames:
                lead, end = ("\r", "") if tty else ("", "\n")
                print(f"{lead}  render {done}/{frames}", end=end, file=sys.stderr, flush=True)
    if tty:
        print(file=sys.stderr)
    if proc.wait() != 0 or done < frames:
        sys.stderr.write("".join(tail))
        raise SystemExit(f"Blender è terminato con errore ({done}/{frames} fotogrammi)")


def _encode(a, segs, tl, workdir, out, height, title, total_km, tz, seg_frac) -> None:
    print("Codifica video...", file=sys.stderr)
    fps = tl.fps
    labels = overlay.stage_labels(segs, seg_frac, tz, tl.intro / fps, (tl.intro + tl.main) / fps)
    overlay.encode(workdir, out, fps, tl.frames / fps, height, title, overlay.subtitle(segs, total_km * 1000, tz),
                   labels, end_title_at=(tl.intro + tl.main) / fps + 0.5, crf=a.crf)


def main(argv: list[str] | None = None) -> None:
    a = parse_args(argv)
    if not shutil.which(a.blender):
        raise SystemExit("Blender non trovato: installalo o indica il percorso con --blender")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg non trovato")
    tz = ZoneInfo(a.tz)

    segs = gpx.load(a.gpx)
    title = a.title or segs[0].name or "Sorvolo"
    out = a.output or Path(f"{_slug(title)}.mp4")
    if a.merged_gpx:
        gpx.write(segs, title, a.merged_gpx)
        print(f"GPX unito: {a.merged_gpx}", file=sys.stderr)

    total_km = sum(gpx.length_m(s) for s in segs) / 1000
    main_s = a.duration or min(120.0, max(30.0, 3 * total_km))
    fps, (w, h), samples = (15, (960, 540), 4) if a.preview else (30, (1920, 1080), 16)
    fps = a.fps or fps
    tl = scene.Timeline(fps, round(INTRO_S * fps), round(main_s * fps), round(OUTRO_S * fps), round(a.hold * fps))
    print(f"{len(segs)} tratti, {total_km:.1f} km -> {tl.frames / fps:.0f} s di video, {tl.frames} fotogrammi", file=sys.stderr)

    if a.reencode:
        frames = sorted((a.workdir / "frames").glob("f_*.png")) if a.workdir else []
        if len(frames) != tl.frames:
            raise SystemExit(f"--reencode: attesi {tl.frames} fotogrammi in --workdir/frames, trovati {len(frames)} "
                             "(usa le stesse opzioni -d/--fps/--hold del render)")
        with Image.open(frames[0]) as im:
            h = im.size[1]
        _encode(a, segs, tl, a.workdir, out, h, title, total_km, tz, scene.segment_fractions(segs))
        print(f"Video pronto: {out}", file=sys.stderr)
        return

    tmp = None
    if a.workdir:
        workdir = a.workdir
        workdir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(workdir / "frames", ignore_errors=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="flyover-")
        workdir = Path(tmp.name)
    try:
        meta = scene.build(segs, tl, workdir, fix_colors=not a.no_colorfix)
        print("Render 3D con Blender...", file=sys.stderr)
        _render(a.blender, workdir.resolve(), w, h, samples, tl.frames)
        _encode(a, segs, tl, workdir, out, h, title, total_km, tz, meta["seg_frac"])
    finally:
        if tmp:
            tmp.cleanup()
    print(f"Video pronto: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
