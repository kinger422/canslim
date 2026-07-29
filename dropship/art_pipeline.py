#!/usr/bin/env python3
"""
Art-to-Marketplace Pipeline
===========================
Drop drawings into ./input, run this script, and get back:
  1. An AUDIT of which platforms each drawing qualifies for (resolution check)
  2. Print-ready files per platform in ./output/<design>/<platform>/
  3. A listings.csv metadata sheet to copy/paste titles, tags & descriptions from

Platforms covered (all free to join):
  - Redbubble   (full product catalog: apparel, stickers, wall art, home goods)
  - TeePublic   (apparel-focused, fixed royalties)
  - Displate    (metal posters — strict quality bar, NO upscaling allowed)
  - FineArtAmerica (art prints — free tier: 25 images)

Usage:
  python3 art_pipeline.py                # audit + prepare everything
  python3 art_pipeline.py --audit-only   # just report, write nothing
  python3 art_pipeline.py --upscale      # allow 2x Lanczos upscale for RB/TP
                                         # (never for Displate or FineArtAmerica —
                                         #  both reject or penalise upscaled art)
  python3 art_pipeline.py --platforms displate,teepublic
"""

import argparse
import csv
import sys
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

Image.MAX_IMAGE_PIXELS = None  # trust our own files

# Pillow buffers a whole optimized/progressive JPEG scan in memory, and the
# default 64KB ceiling overflows on large, detailed art saved at 4:4:4 —
# "broken data stream when writing image file". Raise it, and fall back to
# baseline encoding for anything still too big (see save_image).
ImageFile.MAXBLOCK = 2 ** 26

BASE = Path(__file__).parent
INPUT_DIR = BASE / "input"
OUTPUT_DIR = BASE / "output"

UPSCALE_FACTOR = 2
JPEG_QUALITY = 95
JPEG_QUALITY_FLOOR = 70  # don't degrade past this chasing a file-size cap

# ---------------------------------------------------------------- platform specs
# Minimums below are *source pixel* requirements. "canvas" = exact output canvas.
SPECS = {
    "redbubble_wall_art": {
        "platform": "Redbubble",
        "note": "Covers RB art prints up to XL (3840x3840 recommended)",
        "min_side": 3840,          # longest side must reach the square canvas
        "canvas": (3840, 3840),
        "mode": "fit",             # centered on a transparent square canvas
        "format": "PNG",
    },
    "redbubble_apparel": {
        "platform": "Redbubble",
        "note": "RB graphic tees want ~3873x4814; transparent PNG",
        "min_w": 2875, "min_h": 3900,
        "canvas": (3873, 4814),
        "mode": "fit",
        "format": "PNG",
    },
    "teepublic": {
        "platform": "TeePublic",
        "note": "Min 1500x1995, ideal 5000x5500, transparent PNG 150dpi",
        "min_w": 1500, "min_h": 1995,
        "canvas": (5000, 5500),
        "mode": "fit",
        "format": "PNG",
        "dpi": (150, 150),
    },
    "displate": {
        "platform": "Displate",
        "note": "Short side >=2900px, 1:1.4 ratio, 300dpi, NO upscaling ever",
        "canvas": (2900, 4060),    # 1:1.4 portrait (auto-flipped for landscape art)
        "mode": "cover_crop",      # fill the canvas, center-crop overflow
        "format": "JPEG",
        "dpi": (300, 300),
        "no_upscale": True,
    },
    "fineartamerica": {
        "platform": "FineArtAmerica",
        "note": "Bigger is better; keep original aspect ratio; JPEG under 25MB",
        "min_side_any": 2500,
        "mode": "original",        # ship the original (converted to JPEG)
        "format": "JPEG",
        "dpi": (300, 300),
        "max_bytes": 25 * 1024 * 1024,
        "no_upscale": True,
    },
}

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def load_images():
    files = sorted(
        p for p in INPUT_DIR.iterdir()
        if p.suffix.lower() in SUPPORTED_EXT and p.is_file()
    ) if INPUT_DIR.exists() else []
    return files


def normalize(img):
    """Apply EXIF rotation and land on a mode we can resize cleanly.

    Palette and grayscale sources get promoted first — resampling a P-mode
    image with LANCZOS interpolates palette *indices*, which produces garbage.
    """
    img = ImageOps.exif_transpose(img)
    if img.mode in ("P", "LA", "PA"):
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def flatten(img, bg=(255, 255, 255)):
    """RGB copy with any transparency composited onto a solid background.

    Straight .convert('RGB') on an RGBA image drops the alpha channel and
    leaves transparent pixels as black, which turns a cut-out design into a
    black box on Displate/FineArtAmerica.
    """
    if img.mode == "RGBA":
        base = Image.new("RGB", img.size, bg)
        base.paste(img, mask=img.getchannel("A"))
        return base
    return img.convert("RGB")


def upscale_factor(spec, upscale_ok):
    return UPSCALE_FACTOR if (upscale_ok and not spec.get("no_upscale")) else 1


def canvas_for(spec, w, h):
    """Output canvas, flipped to match the source orientation for cover_crop."""
    cw, ch = spec["canvas"]
    if spec["mode"] == "cover_crop" and (w > h) != (cw > ch):
        cw, ch = ch, cw
    return cw, ch


def qualifies(img_w, img_h, spec, upscale_ok):
    """Return (ok, reason). Upscale doubles effective resolution for platforms
    that tolerate it (never Displate or FineArtAmerica)."""
    factor = upscale_factor(spec, upscale_ok)
    w, h = img_w * factor, img_h * factor
    suffix = f" (with {factor}x upscale)" if factor > 1 else ""

    if spec["mode"] == "cover_crop":
        # Exact test: the source must fill the oriented canvas outright, since
        # cover_crop refuses to upscale. A short-side-only check passes images
        # that prepare() then has to reject.
        cw, ch = canvas_for(spec, w, h)
        if w < cw or h < ch:
            return False, f"{img_w}x{img_h} cannot fill {cw}x{ch} without upscaling"
        return True, "ok" + suffix

    if "min_side" in spec:
        if max(w, h) < spec["min_side"]:
            return False, f"longest side {max(img_w, img_h)}px < {spec['min_side']}px needed"
    if "min_w" in spec:
        # allow either orientation
        if not ((w >= spec["min_w"] and h >= spec["min_h"]) or
                (h >= spec["min_w"] and w >= spec["min_h"])):
            return False, f"{img_w}x{img_h} < {spec['min_w']}x{spec['min_h']} needed"
    if "min_side_any" in spec:
        if max(w, h) < spec["min_side_any"]:
            return False, f"longest side {max(img_w, img_h)}px < {spec['min_side_any']}px recommended"
    return True, "ok" + suffix


def prepare(img, spec, upscale_ok):
    """Return a new PIL image formatted for the spec, or None if impossible."""
    work = img
    factor = upscale_factor(spec, upscale_ok)
    if factor > 1:
        work = work.resize((work.width * factor, work.height * factor), Image.LANCZOS)

    mode = spec["mode"]
    if mode == "original":
        out = work
    elif mode == "fit":
        cw, ch = spec["canvas"]
        ratio = min(cw / work.width, ch / work.height, 1.0)  # never upscale here
        nw = min(cw, max(1, round(work.width * ratio)))
        nh = min(ch, max(1, round(work.height * ratio)))
        resized = work if (nw, nh) == work.size else work.resize((nw, nh), Image.LANCZOS)
        if spec["format"] == "PNG":
            out = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            src = resized.convert("RGBA")
            out.paste(src, ((cw - nw) // 2, (ch - nh) // 2), src)
        else:
            out = Image.new("RGB", (cw, ch), (255, 255, 255))
            out.paste(flatten(resized), ((cw - nw) // 2, (ch - nh) // 2))
    elif mode == "cover_crop":
        cw, ch = canvas_for(spec, work.width, work.height)
        ratio = max(cw / work.width, ch / work.height)
        if ratio > 1.0:  # would require upscaling — not allowed
            return None
        nw = max(cw, round(work.width * ratio))
        nh = max(ch, round(work.height * ratio))
        resized = work.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - cw) // 2, (nh - ch) // 2
        out = resized.crop((left, top, left + cw, top + ch))
    else:
        raise ValueError(f"unknown mode {mode!r}")

    if spec["format"] == "JPEG":
        out = flatten(out)
    return out


def save_image(out, path, spec):
    """Write the file, stepping quality down if the platform caps file size.
    Returns the quality actually used (None for PNG)."""
    save_kw = {}
    if "dpi" in spec:
        save_kw["dpi"] = spec["dpi"]

    if spec["format"] != "JPEG":
        out.save(path, spec["format"], **save_kw)
        return None

    quality = JPEG_QUALITY
    save_kw.update(quality=quality, subsampling=0, optimize=True, progressive=True)

    def write():
        """Save at the current quality, degrading encoder options before
        quality — baseline 4:4:4 still beats a smaller optimized file."""
        try:
            out.save(path, "JPEG", **save_kw)
        except OSError:
            save_kw.pop("optimize", None)
            save_kw.pop("progressive", None)
            out.save(path, "JPEG", **save_kw)

    write()
    cap = spec.get("max_bytes")
    while cap and path.stat().st_size > cap and quality > JPEG_QUALITY_FLOOR:
        quality -= 5
        save_kw["quality"] = quality
        write()
    return quality


def join_limited(items, limit=250, sep=", "):
    """Join de-duplicated items without ever cutting one in half."""
    out, used = [], 0
    for item in dict.fromkeys(items):
        cost = len(item) + (len(sep) if out else 0)
        if used + cost > limit:
            continue
        out.append(item)
        used += cost
    return sep.join(out)


def draft_metadata(design_name):
    """Draft a title, tags and description from the filename.
    Filename convention:  my-cool-drawing.png  ->  'My Cool Drawing'"""
    pretty = design_name.replace("_", " ").replace("-", " ").strip().title()
    words = [w.lower() for w in pretty.split() if len(w) > 2]
    base_tags = words + [
        "art", "drawing", "illustration", "hand drawn", "artistic",
        "unique gift", "wall art", "original art",
    ]
    tags = join_limited(base_tags, limit=250)
    description = (
        f"{pretty} — an original illustration. "
        f"A distinctive piece for fans of hand-crafted art, available on "
        f"prints, apparel, stickers and more. Makes a great gift."
    )
    return pretty, tags, description


def selected_specs(raw):
    if not raw:
        return SPECS
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    unknown = [k for k in keys if k not in SPECS]
    if unknown:
        sys.exit(f"Unknown platform key(s): {', '.join(unknown)}\n"
                 f"Valid keys: {', '.join(SPECS)}")
    return {k: SPECS[k] for k in keys}


def main():
    ap = argparse.ArgumentParser(description="Prepare drawings for print-on-demand marketplaces.")
    ap.add_argument("--audit-only", action="store_true",
                    help="report qualification only; write no files")
    ap.add_argument("--upscale", action="store_true",
                    help="allow 2x Lanczos upscale for Redbubble/TeePublic")
    ap.add_argument("--platforms", default="",
                    help="comma-separated subset of: " + ", ".join(SPECS))
    args = ap.parse_args()

    specs = selected_specs(args.platforms)

    INPUT_DIR.mkdir(exist_ok=True)
    files = load_images()
    if not files:
        print(f"No images found in {INPUT_DIR}/ — drop your drawings there first.")
        sys.exit(0)

    if not args.audit_only:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"Found {len(files)} design(s)\n" + "=" * 60)

    for f in files:
        try:
            with Image.open(f) as raw:
                img = normalize(raw)
        except (OSError, ValueError) as exc:
            print(f"\n{f.name}  -- SKIPPED, could not read: {exc}")
            continue

        name = f.stem
        title, tags, desc = draft_metadata(name)
        print(f"\n{f.name}  ({img.width}x{img.height})")

        ready = []
        for key, spec in specs.items():
            ok, reason = qualifies(img.width, img.height, spec, args.upscale)
            status = "READY" if ok else "SKIP "
            print(f"  [{status}] {spec['platform']:<16} {key:<22} {reason}")
            if not ok or args.audit_only:
                continue

            out = prepare(img, spec, args.upscale)
            if out is None:
                print("          -> skipped (would need upscaling, not allowed)")
                continue
            dest = OUTPUT_DIR / name / key
            dest.mkdir(parents=True, exist_ok=True)
            ext = ".png" if spec["format"] == "PNG" else ".jpg"
            path = dest / f"{name}_{key}{ext}"
            quality = save_image(out, path, spec)
            ready.append(key)
            size = path.stat().st_size
            size_mb = size / (1024 * 1024)
            extra = f", q{quality}" if quality is not None and quality != JPEG_QUALITY else ""
            print(f"          -> {path.relative_to(BASE)}  "
                  f"({out.width}x{out.height}, {size_mb:.1f}MB{extra})")
            cap = spec.get("max_bytes")
            if cap and size > cap:
                print(f"          !! still over the {cap / (1024 * 1024):.0f}MB "
                      f"{spec['platform']} limit at quality floor q{JPEG_QUALITY_FLOOR} — "
                      f"downsize this one by hand before uploading")

        if args.audit_only:
            ready = [k for k, spec in specs.items()
                     if qualifies(img.width, img.height, spec, args.upscale)[0]]

        rows.append({
            "design": name, "title": title, "tags": tags, "description": desc,
            "source_px": f"{img.width}x{img.height}",
            "qualified_for": " ".join(ready),
            "redbubble": "", "teepublic": "", "displate": "", "fineartamerica": "",
        })

    if not rows:
        print("\nNo readable images — nothing to write.")
        sys.exit(1)

    if not args.audit_only:
        csv_path = OUTPUT_DIR / "listings.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print("\n" + "=" * 60)
        print(f"Metadata sheet: {csv_path.relative_to(BASE)}")
        print("Fill the platform columns with 'listed' as you upload — it's your tracker.")


if __name__ == "__main__":
    main()
