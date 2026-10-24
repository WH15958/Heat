"""Rasterize the existing frontend icon; generated assets stay outside source control."""
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from resvg_py import svg_to_bytes


def main():
    root = Path(__file__).resolve().parents[2]
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    png = svg_to_bytes(svg_string=(root / "frontend/public/favicon.svg").read_text("utf-8"),
                       width=256, height=256)
    with Image.open(BytesIO(png)) as icon:
        canvas = Image.new("RGBA", (256, 256))
        canvas.alpha_composite(icon.convert("RGBA"), ((256-icon.width)//2, (256-icon.height)//2))
        canvas.save(destination, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])


if __name__ == "__main__":
    main()
