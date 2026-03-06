#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd3in7


def main() -> None:
    epd = epd3in7.EPD()
    epd.init(0)

    canvas = Image.new('L', (epd.height, epd.width), 0xFF)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    draw.text((16, 16), 'musicbox', font=font, fill=0)
    draw.text((16, 40), 'e-ink wiring OK', font=font, fill=0)
    draw.text((16, 64), time.strftime('%Y-%m-%d %H:%M:%S'), font=font, fill=0)
    draw.rectangle((16, 96, 160, 176), outline=0, width=2)
    draw.text((28, 122), '3.7 in', font=font, fill=0)
    draw.text((196, 122), 'ready', font=font, fill=0x80)
    draw.line((16, 208, 240, 208), fill=0x00, width=2)
    draw.line((16, 224, 240, 224), fill=0x80, width=2)
    draw.line((16, 240, 240, 240), fill=0xC0, width=2)

    epd.Clear(0xFF, 0)
    epd.display_4Gray(epd.getbuffer_4Gray(canvas))
    epd.sleep()


if __name__ == '__main__':
    main()
