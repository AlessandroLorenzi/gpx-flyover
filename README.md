# gpx-flyover

Genera un video 3D di sorvolo a partire da una o più tracce GPX: terreno reale, ortofoto
satellitari, traccia che si disegna progressivamente e telecamera che la segue.

```
flyover schignano.gpx gordona.gpx posa.gpx \
  --title "Due giorni al Rifugio Prabello" -o prabello.mp4
```

## Requisiti

- Python ≥ 3.11 e [uv](https://docs.astral.sh/uv/)
- [Blender](https://www.blender.org/) ≥ 4.2 nel `PATH` (usato in background come motore di render;
  il suo Python deve avere `numpy`, già incluso nelle build ufficiali)
- `ffmpeg` con `libx264` e `drawtext`
- Font consigliato: Inter (altrimenti viene usato quello trovato da `fc-match`)

## Installazione

```
uv tool install .
```

oppure, senza installare: `uv run flyover ...`

## Uso

| Opzione | Effetto |
|---|---|
| `gpx...` | uno o più file GPX o URL diretti a GPX; tutti i tratti vengono ordinati per orario |
| `-t, --title` | titolo mostrato in apertura e chiusura (default: nome della prima traccia) |
| `-o, --output` | file di uscita (default: `<titolo>.mp4`) |
| `-d, --duration` | secondi di sorvolo, esclusi intro (4 s), finale (6 s) e pausa finale. Default 3 s/km, tra 30 e 120 |
| `--hold` | secondi di pausa finale sulla vista d'insieme, con lenta rotazione (default 8) |
| `--fps` | fotogrammi al secondo (default 30; 24 riduce il render del 20%) |
| `--preview` | 960×540, 15 fps, meno campioni: utile per controllare l'inquadratura in pochi minuti |
| `--merged-gpx FILE` | salva anche la traccia unita (un `<trk>` con un `<trkseg>` per tratto) |
| `--workdir DIR` | conserva dati scaricati, fotogrammi e testi (utile per ricodificare) |
| `--no-colorfix` | disattiva l'uniformazione colore delle ortofoto |
| `--tz` | fuso orario per date e numerazione dei giorni (default `Europe/Rome`) |

Le etichette in basso a sinistra mostrano il nome di ogni traccia; se l'escursione dura più
giorni vengono precedute da "Giorno N". Il sottotitolo riporta date e distanza totale.

## Come funziona

1. **GPX**: lettura, ordinamento dei tratti per orario, distanza.
2. **Tile** (`~/.cache/gpx-flyover/tiles`): quote [Terrarium](https://registry.opendata.aws/terrain-tiles/)
   e ortofoto Esri World Imagery, per un'area interna ad alta risoluzione (traccia + 2 km) e una
   esterna a bassa risoluzione (+20 km) per l'orizzonte.
3. **Correzione colore**: le ortofoto Esri mescolano fonti diverse (es. swisstopo), che appaiono
   come blocchi più chiari. I blocchi vengono individuati per saturazione/luminosità e portati
   ai colori del resto dell'immagine. È euristica: zone sfocate o con ombre forti già presenti
   nelle ortofoto restano.
4. **Scena**: mesh del terreno, traccia ricampionata ogni 4 m, telecamera che segue la traccia
   da dietro e dall'alto con direzione smussata.
5. **Render** con Blender EEVEE in background, poi **ffmpeg** aggiunge titolo, tappe e crediti.

Tempi indicativi su un portatile a 8 core: ~1,8 s per fotogramma a 1080p (≈ 1 ora per 85 s di video).

## Licenze dei dati

Ortofoto © Esri e fornitori (uso personale, con attribuzione); quote Mapzen Terrarium
(fonti varie, vedi registry AWS). L'attribuzione viene inserita nel video.
