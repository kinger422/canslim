#!/usr/bin/env python3
"""Generate synthetic test art in ./input to exercise the pipeline.

Not part of the pipeline itself — this just produces fixtures that hit every
qualification branch, so you can verify a change without hunting for real art.

  python3 make_samples.py && python3 art_pipeline.py --audit-only
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw

INPUT_DIR = Path(__file__).parent / "input"


def art(w, h, alpha=False, seed=7):
    rng = random.Random(seed)
    img = Image.new("RGBA" if alpha else "RGB", (w, h),
                    (0, 0, 0, 0) if alpha else (250, 246, 238))
    draw = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = rng.randrange(w), rng.randrange(h)
        draw.ellipse([x, y, x + w // 6, y + h // 6],
                     outline=(rng.randrange(256), 40, 90, 255),
                     width=max(2, w // 300))
    return img


def main():
    INPUT_DIR.mkdir(exist_ok=True)

    # clears every platform
    art(5200, 6000, alpha=True).save(INPUT_DIR / "big-transparent-owl.png")
    # landscape — Displate canvas should flip to 4060x2900
    art(5000, 3600, seed=11).save(INPUT_DIR / "wide-desert-sunset.jpg", quality=92)
    # square 3000px — passes a naive short-side check but cannot fill 2900x4060
    art(3000, 3000, alpha=True, seed=3).save(INPUT_DIR / "square-three-thousand.png")
    # too small for most platforms without --upscale
    art(1600, 2100, alpha=True, seed=5).save(INPUT_DIR / "small_sketch_moth.png")
    # palette mode — must be promoted before resampling
    art(4200, 4900, alpha=True, seed=9).convert(
        "P", palette=Image.ADAPTIVE).save(INPUT_DIR / "palette-mode-fox.png")
    # unreadable file — the run must survive it
    (INPUT_DIR / "broken-file.png").write_bytes(b"not a png at all")

    for p in sorted(INPUT_DIR.iterdir()):
        print(f"  {p.name}")
    print(f"\nWrote fixtures to {INPUT_DIR}/")


if __name__ == "__main__":
    main()
