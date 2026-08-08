# Dropship — art-to-marketplace pipeline

Drop drawings into `input/`, run one command, and get print-ready files plus a
listings sheet for four print-on-demand marketplaces.

This is a standalone utility. It has nothing to do with the CAN SLIM stock
research in the rest of this repository — it just lives here for convenience.

## Setup

```bash
pip install Pillow
```

## Use

```bash
python3 art_pipeline.py                       # audit + write everything
python3 art_pipeline.py --audit-only          # report only, writes nothing
python3 art_pipeline.py --upscale             # allow 2x Lanczos upscale (RB/TP only)
python3 art_pipeline.py --platforms displate,teepublic
```

Output lands in `output/<design>/<platform>/`, with `output/listings.csv`
carrying drafted titles, tags and descriptions. The four rightmost CSV columns
are left blank on purpose — fill them with `listed` as you upload, and the sheet
doubles as your tracker. `qualified_for` records which platforms the design
actually passed.

To try it without real art:

```bash
python3 make_samples.py && python3 art_pipeline.py
```

## Platform targets

| Key | Platform | Output | Notes |
|---|---|---|---|
| `redbubble_wall_art` | Redbubble | 3840×3840 PNG | fits inside a transparent square |
| `redbubble_apparel` | Redbubble | 3873×4814 PNG | transparent tee print |
| `teepublic` | TeePublic | 5000×5500 PNG, 150dpi | min source 1500×1995 |
| `displate` | Displate | 2900×4060 JPEG, 300dpi | 1:1.4, center-cropped, never upscaled |
| `fineartamerica` | FineArtAmerica | original ratio JPEG, 300dpi | kept under 25MB |

Displate's canvas flips to 4060×2900 for landscape sources. Verify the current
requirements on each platform before a big upload — these specs move.

## Behaviour worth knowing

- **Upscaling is opt-in and never applied to Displate or FineArtAmerica.** Both
  sell physical prints where a 2x Lanczos upscale is visible; `--upscale` only
  affects Redbubble and TeePublic.
- **`fit` never enlarges a design to fill the canvas.** A small source is centered
  at its native size on the full platform canvas, so nothing is softened. The
  audit tells you when the source is below the platform's recommendation.
- **Transparency is composited onto white for JPEG platforms**, not discarded.
- **An unreadable file is reported and skipped**; the rest of the run continues.
- **Sources are EXIF-rotated and promoted out of palette mode** before resampling.
  Pillow silently falls back to nearest-neighbour when resizing a `P`-mode image,
  which visibly aliases the result.
- If a FineArtAmerica JPEG cannot get under 25MB by quality reduction alone, the
  file is still written and the run prints a warning so you can downsize by hand.

## Testing

`make_samples.py` writes fixtures covering each branch: an oversized transparent
PNG, a landscape JPEG, a square 3000px file that fills no Displate canvas, an
undersized sketch, a palette-mode PNG, and a corrupt file.
