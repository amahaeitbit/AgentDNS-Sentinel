#!/usr/bin/env python3
"""Export an SVG to a presentation-ready PNG.

The SVG is the editable source; this keeps the exported PNG in step with it.
Rendering uses macOS QuickLook (WebKit), so the CSS, gradients and web fonts in
the diagram come out exactly as a browser would draw them. The oversized square
thumbnail QuickLook produces is then cropped back to the artwork.

    python3 scripts/export_svg_png.py docs/agentdns-sentinel-reference-architecture.svg
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def svg_size(text: str) -> tuple[float, float]:
    """The drawing's own width and height, from the root tag or its viewBox."""
    root = text[: text.index(">") + 1]
    width = re.search(r'\bwidth="([\d.]+)', root)
    height = re.search(r'\bheight="([\d.]+)', root)
    if width and height:
        return float(width.group(1)), float(height.group(1))
    box = re.search(r'viewBox="[\d.\s-]*?([\d.]+)\s+([\d.]+)"', root)
    if box:
        return float(box.group(1)), float(box.group(2))
    raise SystemExit(f"Could not determine the SVG's size from: {root[:120]}")


def square_wrapper(text: str, background: str) -> tuple[str, float, float, float]:
    """Centre the drawing on a square canvas.

    QuickLook always renders into a square and crops anything wider, which
    silently loses the right-hand side of a landscape diagram. Padding first
    means the whole drawing survives, and the padding is cropped back off by
    exact arithmetic rather than by guessing at transparency.
    """
    width, height = svg_size(text)
    side = max(width, height)
    pad_x, pad_y = (side - width) / 2, (side - height) / 2
    inner = text.replace("<svg", f'<svg x="{pad_x}" y="{pad_y}"', 1)
    wrapper = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
        f'viewBox="0 0 {side} {side}">'
        f'<rect width="{side}" height="{side}" fill="{background}"/>'
        f"{inner}</svg>"
    )
    return wrapper, side, pad_x, pad_y


def render(svg: Path, output: Path, size: int, background: str | None) -> Path:
    if not shutil.which("qlmanage"):
        raise SystemExit(
            "qlmanage was not found. This exporter needs macOS QuickLook; on other "
            "platforms render the SVG with a browser or Inkscape instead."
        )
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow is required: python -m pip install 'pillow>=10'")

    text = svg.read_text()
    width, height = svg_size(text)
    padded, side, pad_x, pad_y = square_wrapper(text, background or "#ffffff")

    with tempfile.TemporaryDirectory() as tempdir:
        source = Path(tempdir) / f"{svg.stem}-square.svg"
        source.write_text(padded)
        subprocess.run(
            ["qlmanage", "-t", "-s", str(size), "-o", tempdir, str(source)],
            check=True,
            capture_output=True,
        )
        rendered = next(Path(tempdir).glob("*.png"), None)
        if rendered is None:
            raise SystemExit(f"QuickLook produced no thumbnail for {svg}")

        image = Image.open(rendered).convert("RGB")
        scale = image.width / side
        image = image.crop(
            (
                round(pad_x * scale),
                round(pad_y * scale),
                round((pad_x + width) * scale),
                round((pad_y + height) * scale),
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, "PNG", optimize=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("svg")
    parser.add_argument("--output", default=None, help="defaults to the SVG path with a .png suffix")
    parser.add_argument("--size", type=int, default=2400, help="longest edge before cropping")
    parser.add_argument("--background", default="#07111f", help="flattened behind any transparency")
    args = parser.parse_args()

    svg = Path(args.svg)
    output = Path(args.output) if args.output else svg.with_suffix(".png")
    path = render(svg, output, args.size, args.background)
    from PIL import Image

    with Image.open(path) as image:
        print(f"Wrote {path} ({image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
