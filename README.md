# gpx-flyover

Generate a 3D flyover video from one or more GPX tracks: real terrain, satellite imagery,
a track that draws itself progressively and a camera that follows it.

```
flyover schignano.gpx gordona.gpx posa.gpx \
  --title "Due giorni al Rifugio Prabello" -o prabello.mp4
```

## Requirements

- Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/)
- [Blender](https://www.blender.org/) ≥ 4.2 in `PATH` (used headless as the render engine;
  its bundled Python must have `numpy`, which official builds already include)
- `ffmpeg` with `libx264` and `drawtext`
- Recommended font: Inter (otherwise whatever `fc-match` returns is used)

## Installation

```
uv tool install .
```

or, without installing: `uv run flyover ...`

## Usage

| Option | Effect |
|---|---|
| `gpx...` | one or more GPX files or direct URLs to GPX files; all segments are sorted by time |
| `-t, --title` | title shown at the opening and at the end (default: name of the first track) |
| `-o, --output` | output file (default: `<title>.mp4`) |
| `-d, --duration` | seconds of flyover, excluding intro (4 s), outro (6 s) and final hold. Default 3 s/km, between 30 and 120 |
| `--hold` | seconds of final hold on the overview, with a slow orbit (default 8) |
| `--fps` | frames per second (default 30; 24 cuts render time by 20%) |
| `--preview` | 960×540, 15 fps, fewer samples: useful to check framing in a few minutes |
| `--crf` | x264 video quality (default 26: ~50 MB for 90 s at 1080p; 18 = nearly lossless, ~2.5× larger) |
| `--reencode` | with `--workdir`: rebuild only the video from already-rendered frames (same `-d`/`--fps`/`--hold`) |
| `--max-gap` | metres between consecutive segments above which there is a cut instead of a connecting line (default 500) |
| `--merged-gpx FILE` | also save the merged track (one `<trk>` with one `<trkseg>` per segment) |
| `--workdir DIR` | keep downloaded data, frames and text files (useful for re-encoding) |
| `--no-colorfix` | disable color harmonization of the orthophotos |
| `--tz` | time zone for dates and day numbering (default `Europe/Rome`) |
| `--blender PATH` | Blender executable (default: `blender` found in `PATH`) |

The labels in the bottom-left corner show the name of each track; if the hike spans more
than one day they are prefixed with "Giorno N" (day N). The subtitle shows dates and total distance.
On-screen text is in Italian (see [docs/cli.md](docs/cli.md#on-screen-text)).

## How it works

1. **GPX**: parsing, sorting segments by time, distance.
2. **Tiles** (`~/.cache/gpx-flyover/tiles`): [Terrarium](https://registry.opendata.aws/terrain-tiles/)
   elevation and Esri World Imagery orthophotos, for a high-resolution inner area (track + 2 km)
   and a low-resolution outer area (+20 km) for the horizon.
3. **Color correction**: Esri orthophotos mix different sources (e.g. swisstopo), which show up
   as lighter blocks. These blocks are detected by saturation/brightness and brought to the colors
   of the rest of the image. It is a heuristic: blurry areas or strong shadows already present
   in the orthophotos remain.
4. **Scene**: terrain mesh, track resampled every 4 m, camera following the track from behind
   and above with a smoothed heading.
5. **Render** with Blender EEVEE in background, then **ffmpeg** adds title, stages and credits.

Indicative timings on an 8-core laptop: ~1.8 s per frame at 1080p (≈ 1 hour for 85 s of video).

## Documentation

- [Architecture](docs/architecture.md): pipeline, modules, data flow, work directory
- [CLI reference](docs/cli.md): every option in detail, video timeline, recipes
- [Internals](docs/internals.md): coordinates, tiles, terrain, camera, Blender scene, overlays, color correction
- [Development](docs/development.md): setup, tests, troubleshooting, known limitations

## Data licenses

Orthophotos © Esri and suppliers (personal use, with attribution); Mapzen Terrarium elevation
(various sources, see the AWS registry). Attribution is burned into the video.

## License

Code released under the [MIT License](LICENSE). Map and elevation data keep their own licenses (see above).
