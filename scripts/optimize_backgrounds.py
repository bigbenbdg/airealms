"""Optimize Blender-rendered map backgrounds (dev tool, needs Pillow).

The backgrounds are flat-shaded stylized art, so palette quantization is
visually lossless but cuts file size dramatically.

    python scripts/optimize_backgrounds.py            # 128 colors, full res
    python scripts/optimize_backgrounds.py --colors 64 --width 1152
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG_DIR = os.path.join(ROOT, "assets", "backgrounds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colors", type=int, default=128)
    ap.add_argument("--width", type=int, default=0, help="resize width (0 = keep)")
    ap.add_argument("--dir", default=BG_DIR)
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed — skipping optimization (pip install pillow).")
        return 0

    files = sorted(f for f in os.listdir(args.dir) if f.endswith(".png"))
    if not files:
        print(f"No PNGs in {args.dir}")
        return 1

    total_before = total_after = 0
    for name in files:
        path = os.path.join(args.dir, name)
        before = os.path.getsize(path)
        total_before += before
        img = Image.open(path).convert("RGB")
        if args.width and img.width > args.width:
            h = round(img.height * args.width / img.width)
            img = img.resize((args.width, h), Image.LANCZOS)
        img = img.quantize(colors=args.colors, method=Image.MEDIANCUT,
                           dither=Image.Dither.NONE)
        img.save(path, format="PNG", optimize=True)
        after = os.path.getsize(path)
        total_after += after
        print(f"{name:24s} {before / 1024:7.1f} KB -> {after / 1024:6.1f} KB")
    print(f"{'TOTAL':24s} {total_before / 1024:7.1f} KB -> {total_after / 1024:6.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
