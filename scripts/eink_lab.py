#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from PIL import Image, ImageDraw

from musicbox_display import DisplayFrame, DisplayOverlay, PanelCore, Rect


def build_status_frame(text: str) -> DisplayFrame:
    size = (480, 280)
    canvas = Image.new('L', size, 0xFF)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, size[0], 48), fill=0x00)
    draw.text((18, 10), 'LAB', fill=0xFF)
    draw.text((18, 80), text, fill=0x00)

    overlay = Image.new('1', size, 1)
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 0, size[0], 48), fill=0)
    overlay_draw.text((18, 10), 'LAB', fill=1)
    overlay_draw.text((18, 80), text, fill=0)
    return DisplayFrame(
        render_mode='fast_bw',
        full_canvas=canvas,
        signature=('lab_status', text),
        overlays=(DisplayOverlay('status', Rect(0, 0, size[0], size[1]), overlay),),
    )


def build_album_frame(label: str) -> DisplayFrame:
    size = (480, 280)
    canvas = Image.new('L', size, 0xFF)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, size[0], 48), fill=0x00)
    draw.text((18, 10), 'ALBUM', fill=0xFF)
    draw.rectangle((18, 64, 218, 264), fill=0x80, outline=0x00, width=2)
    draw.rectangle((42, 88, 194, 240), fill=0xC0)
    draw.text((240, 74), label, fill=0x00)
    draw.text((240, 118), 'overlay update lab', fill=0x40)
    draw.line((240, 246, 462, 246), fill=0x80, width=2)

    header = Image.new('1', (480, 48), 1)
    header_draw = ImageDraw.Draw(header)
    header_draw.rectangle((0, 0, 480, 48), fill=0)
    header_draw.text((18, 10), 'ALBUM', fill=1)

    meta = Image.new('1', (222, 178), 1)
    meta_draw = ImageDraw.Draw(meta)
    meta_draw.text((0, 6), label, fill=0)
    meta_draw.text((0, 46), 'overlay update lab', fill=0)
    meta_draw.line((0, 172, 222, 172), fill=0, width=2)

    return DisplayFrame(
        render_mode='quality_gray',
        full_canvas=canvas,
        signature=('lab_album', label),
        base_key=('lab_album_base', 'v1'),
        overlays=(
            DisplayOverlay('header', Rect(0, 0, 480, 48), header),
            DisplayOverlay('meta', Rect(240, 68, 462, 246), meta),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Panel-core lab script for the Waveshare 3.7" e-ink panel.')
    parser.add_argument('mode', choices=('status', 'album', 'sequence'))
    parser.add_argument('--text', default='musicbox display lab')
    parser.add_argument('--delay', type=float, default=2.0)
    args = parser.parse_args()

    panel = PanelCore()
    try:
        if args.mode == 'status':
            panel.render(build_status_frame(args.text))
        elif args.mode == 'album':
            panel.render(build_album_frame(args.text))
        else:
            panel.render(build_album_frame('Track A'))
            time.sleep(max(0.0, args.delay))
            panel.render(build_album_frame('Track B'))
            time.sleep(max(0.0, args.delay))
            panel.render(build_status_frame('Stopped'))
        return 0
    finally:
        panel.reset_device()


if __name__ == '__main__':
    raise SystemExit(main())
