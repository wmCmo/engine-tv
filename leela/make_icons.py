"""Render the home-screen icons (PWA) from the terminal favicon design (favicons/terminal.svg):
a dark rounded square with a green "lc0" and a cursor block. Needs Pillow; run once:

    python make_icons.py

Writes icons/icon-192.png, icon-512.png (rounded, transparent corners), icon-maskable-512.png
(full-bleed background, content inside the 80% safe zone so launchers can crop it to any shape)
and apple-touch-icon.png (180 px).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "icons"
BG, GREEN = (15, 15, 14, 255), (129, 182, 76, 255)
FONT = r"C:\Windows\Fonts\consolab.ttf"


def draw_content(d, scale, ox=0.0, oy=0.0):
    """The favicon's 64-unit design: text 'lc0' at (7, 41) size 26, cursor rect (48, 44, 10x4)."""
    font = ImageFont.truetype(FONT, round(26 * scale))
    d.text((ox + 7 * scale, oy + 41 * scale), "lc0", font=font, fill=GREEN, anchor="ls")
    d.rectangle([ox + 48 * scale, oy + 44 * scale, ox + 58 * scale, oy + 48 * scale], fill=GREEN)


def rounded(size):
    ss = 4  # supersample for smooth edges
    big = size * ss
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = big / 64
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=14 * s, fill=BG)
    draw_content(d, s)
    return im.resize((size, size), Image.LANCZOS)


def maskable(size):
    ss = 4
    big = size * ss
    im = Image.new("RGBA", (big, big), BG)
    d = ImageDraw.Draw(im)
    # the design's content spans x 7..58, y ~22..48 of 64; fit it into the central 64% of the icon
    w, h, cx, cy = 51, 26, (7 + 58) / 2, (22 + 48) / 2
    s = big * 0.64 / w
    draw_content(d, s, big / 2 - cx * s, big / 2 - cy * s)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rounded(192).save(OUT / "icon-192.png")
    rounded(512).save(OUT / "icon-512.png")
    maskable(512).save(OUT / "icon-maskable-512.png")
    maskable(180).convert("RGB").save(OUT / "apple-touch-icon.png")
    for f in sorted(OUT.glob("*.png")):
        print(f.name, Image.open(f).size)
