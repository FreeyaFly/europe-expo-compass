"""Draw the app icon (a compass in the page's blue) -> app/icon.ico + app/icon-192.png.

    python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BLUE, DARK, PAPER = (46, 109, 180), (27, 79, 140), (220, 232, 247)


def draw(size):
    s = size * 4  # draw large, then shrink for smooth edges
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = s * 0.04
    d.ellipse([m, m, s - m, s - m], fill=PAPER, outline=DARK, width=max(4, int(s * 0.06)))
    c, r = s / 2, s * 0.36
    d.polygon([(c, c - r), (c + r * 0.28, c), (c, c + r * 0.12), (c - r * 0.28, c)], fill=BLUE)      # north half
    d.polygon([(c, c + r), (c + r * 0.28, c), (c, c - r * 0.12), (c - r * 0.28, c)], fill=(150, 175, 205))  # south half
    d.ellipse([c - s * 0.045, c - s * 0.045, c + s * 0.045, c + s * 0.045], fill=DARK)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    big = draw(256)
    big.save(ROOT / 'app' / 'icon.ico', sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw(192).save(ROOT / 'app' / 'icon-192.png')
    print('wrote app/icon.ico and app/icon-192.png')
