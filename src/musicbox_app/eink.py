from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any

from .config import EINK_BOOT_DELAY_S, EINK_MIN_REFRESH_S, EINK_POLL_INTERVAL_S


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _player_title(relpath: str | None) -> tuple[str, str]:
    if not relpath:
        return 'musicbox', 'Tap a card to play'
    path = Path(relpath)
    title = path.stem.replace('_', ' ').strip() or path.name
    subtitle = path.parent.name.strip() if path.parent != Path('.') else ''
    return title, subtitle


def _signature(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    player = snapshot.get('player') or {}
    health = snapshot.get('health') or {}
    return (
        str(player.get('status') or ''),
        str(player.get('file') or ''),
        str(player.get('direction') or ''),
        round(float(player.get('speed') or 1.0), 2),
        int(player.get('volume') or 0),
        str(snapshot.get('last_card') or ''),
        int(round(float(health.get('battery_percent') or 0.0))),
        bool(health.get('battery_charging')),
    )


class EInkStatusDisplay:
    def __init__(self) -> None:
        from PIL import Image, ImageDraw
        from waveshare_epd import epd3in7

        self._Image = Image
        self._ImageDraw = ImageDraw
        self._epd3in7 = epd3in7
        self._title_font = _load_font(30, bold=True)
        self._body_font = _load_font(20)
        self._meta_font = _load_font(18)
        self._small_font = _load_font(16)

    def render(self, snapshot: dict[str, Any]) -> None:
        epd = self._epd3in7.EPD()
        epd.init(0)

        canvas = self._Image.new('L', (epd.height, epd.width), 0xFF)
        draw = self._ImageDraw.Draw(canvas)
        self._draw(draw, canvas.size, snapshot)

        epd.Clear(0xFF, 0)
        epd.display_4Gray(epd.getbuffer_4Gray(canvas))
        epd.sleep()

    def _draw(self, draw, size: tuple[int, int], snapshot: dict[str, Any]) -> None:
        width, height = size
        player = snapshot.get('player') or {}
        health = snapshot.get('health') or {}

        status = str(player.get('status') or 'stopped').strip().lower()
        volume = int(player.get('volume') or 0)
        speed = float(player.get('speed') or 1.0)
        direction = str(player.get('direction') or 'forward')
        battery = health.get('battery_percent')
        charging = bool(health.get('battery_charging'))
        last_card = str(snapshot.get('last_card') or '').strip()
        title, subtitle = _player_title(player.get('file'))

        draw.rectangle((0, 0, width, 48), fill=0x00)
        draw.text((18, 10), status.upper(), font=self._meta_font, fill=0xFF)
        battery_text = '--%'
        if battery is not None:
            battery_text = f'{int(round(float(battery)))}%'
        if charging:
            battery_text += ' +'
        battery_width = int(draw.textlength(battery_text, font=self._meta_font))
        draw.text((width - battery_width - 18, 10), battery_text, font=self._meta_font, fill=0xFF)

        top = 72
        for line in textwrap.wrap(title, width=24)[:3]:
            draw.text((18, top), line, font=self._title_font, fill=0x00)
            top += 38

        if subtitle:
            for line in textwrap.wrap(subtitle, width=34)[:2]:
                draw.text((18, top + 4), line, font=self._body_font, fill=0x40)
                top += 28

        meta = f'Vol {volume}%   {speed:.1f}x'
        if direction == 'reverse':
            meta += ' rev'
        draw.text((18, height - 84), meta, font=self._body_font, fill=0x00)

        if last_card:
            draw.text((18, height - 52), f'Card {last_card}', font=self._small_font, fill=0x40)
        else:
            draw.text((18, height - 52), 'RFID ready', font=self._small_font, fill=0x40)

        draw.line((18, height - 24, width - 18, height - 24), fill=0x80, width=2)


def eink_worker(store) -> None:
    if EINK_BOOT_DELAY_S > 0:
        time.sleep(EINK_BOOT_DELAY_S)

    display: EInkStatusDisplay | None = None
    last_signature: tuple[Any, ...] | None = None
    last_render_mono = 0.0
    ready_logged = False
    last_error: str | None = None

    while True:
        snapshot = store.snapshot(since_id=0, event_limit=1)
        signature = _signature(snapshot)
        now = time.monotonic()

        if signature == last_signature or now - last_render_mono < EINK_MIN_REFRESH_S:
            time.sleep(EINK_POLL_INTERVAL_S)
            continue

        try:
            if display is None:
                display = EInkStatusDisplay()
            display.render(snapshot)
            last_signature = signature
            last_render_mono = now
            if not ready_logged:
                store.add_event('EINK_READY')
                ready_logged = True
            last_error = None
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            if message != last_error:
                store.add_event(f'EINK_ERR {message}', level='warning')
                last_error = message
        time.sleep(EINK_POLL_INTERVAL_S)
