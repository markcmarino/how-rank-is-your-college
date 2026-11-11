"""Makes the Retort's link preview card (bot/static/retort-card.png) and the web-sized netprov logo.

Run once by hand when the design changes; the PNGs are committed, so the bot doesn't need Pillow.

    pip install pillow
    python -m scripts.make_card path/to/how-rank-logo-square.png
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

STATIC = Path(__file__).resolve().parent.parent / "bot" / "static"
FONTS = Path("/System/Library/Fonts/Supplemental")
PAPER, INK, MUTED, RULE, ACCENT, UP, DOWN = "#fbf8f1", "#1d1b18", "#6b645a", "#d9d1c3", "#8c1c13", "#1f6b3a", "#a1261b"


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


def centered(draw, y, text, f, fill, width):
    w = draw.textlength(text, font=f)
    draw.text(((width - w) / 2, y), text, font=f, fill=fill)


def spaced(text: str) -> str:
    return " ".join(text)


def card(logo: Image.Image | None) -> Image.Image:
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    left = 60
    text_w = W - 2 * left
    if logo:
        size = 230
        img.paste(logo.resize((size, size), Image.LANCZOS), (W - left - size, 150))
        text_w = W - 2 * left - size - 40

    def center_x(text, f):
        return left + (text_w - d.textlength(text, font=f)) / 2

    over = font("Courier New Bold.ttf", 22)
    for y, text in ((70, "THE UNDERACADEMY EXCHANGE PRESENTS"),):
        d.text((center_x(text, over), y), text, font=over, fill=MUTED)
    title = font("Georgia Bold.ttf", 92)
    d.text((center_x("US Snooze &", title), 120), "US Snooze &", font=title, fill=INK)
    d.text((center_x("Whirled Retort", title), 222), "Whirled Retort", font=title, fill=INK)
    for y in (350, 357):
        d.line([(left, y), (left + text_w, y)], fill=INK, width=2)
    sub = font("Georgia Italic.ttf", 34)
    line = "Big Digit Conference Rankings"
    d.text((center_x(line, sub), 378), line, font=sub, fill=ACCENT)
    q = font("Georgia Bold.ttf", 30)
    line = "How Rank is Your College?"
    d.text((center_x(line, q), 428), line, font=q, fill=INK)

    # The ticker strip
    d.rectangle([(0, 520), (W, 630)], fill=INK)
    mono = font("Courier New Bold.ttf", 30)
    x = left
    for code, arrow, move, colour in (("UAC", "▲", "∞", "#6fcf8f"), ("HRVD", "▼", "3.2%", "#ff8a7a"),
                                      ("PIG", "▲", "12.0%", "#6fcf8f"), ("WAITLIST", "▲", "41%", "#6fcf8f"),
                                      ("MIT", "▼", "1.1%", "#ff8a7a")):
        d.text((x, 556), code, font=mono, fill=PAPER)
        x += d.textlength(code + " ", font=mono)
        d.text((x, 556), f"{arrow} {move}", font=mono, fill=colour)
        x += d.textlength(f"{arrow} {move}", font=mono) + 30
    return img


def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    logo = None
    if len(sys.argv) > 1:
        logo = Image.open(sys.argv[1]).convert("RGB")
        logo.resize((480, 480), Image.LANCZOS).save(STATIC / "how-rank-logo.png", optimize=True)
    elif (STATIC / "how-rank-logo.png").exists():
        logo = Image.open(STATIC / "how-rank-logo.png").convert("RGB")
    card(logo).save(STATIC / "retort-card.png", optimize=True)
    print("Wrote", STATIC)


if __name__ == "__main__":
    main()
