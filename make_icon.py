"""
make_icon.py
====================
Generates icon.ico — a simple flat "download arrow" glyph (shaft + arrowhead
over a tray bar) — used as both the app window icon (main.py) and the built
exe's own icon (Solieu26.spec). Re-run after editing SIZE/COLOR/geometry below;
draws at 4x and downsamples for anti-aliased edges.

Run:  python make_icon.py
"""

from PIL import Image, ImageDraw

BASE = 256          # design grid
SUPERSAMPLE = 4      # draw at this multiple, then downsample for smooth edges
COLOR = (37, 99, 235, 255)   # flat blue, #2563EB


def build_icon() -> Image.Image:
    size = BASE * SUPERSAMPLE
    s = SUPERSAMPLE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Shaft
    draw.rectangle([108 * s, 40 * s, 148 * s, 132 * s], fill=COLOR)
    # Arrowhead
    draw.polygon([(128 * s, 182 * s), (70 * s, 118 * s), (186 * s, 118 * s)], fill=COLOR)
    # Tray
    draw.rounded_rectangle([50 * s, 200 * s, 206 * s, 228 * s], radius=10 * s, fill=COLOR)

    return img.resize((BASE, BASE), Image.LANCZOS)


if __name__ == "__main__":
    icon = build_icon()
    icon.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.ico written")
