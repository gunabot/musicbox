from __future__ import annotations

import textwrap
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import EINK_BOOT_DELAY_S, EINK_ERROR_RETRY_S, EINK_MIN_REFRESH_S, EINK_POLL_INTERVAL_S
from .media import safe_rel_to_abs

ARTWORK_FILENAMES = ('cover', 'folder', 'front', 'artwork', 'album', 'thumb')
ARTWORK_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')
ARTWORK_CACHE_LIMIT = 12
ALBUM_ART_SIZE = (200, 200)


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


def _battery_bucket(percent: Any) -> int | None:
    try:
        value = max(0.0, min(100.0, float(percent)))
    except Exception:
        return None
    return int(value // 10) * 10


def _artwork_key(path: Path | None) -> tuple[str, int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except Exception:
        return None
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def resolve_album_art(relpath: str | None) -> Path | None:
    if not relpath:
        return None
    try:
        target = safe_rel_to_abs(relpath)
    except Exception:
        return None

    folder = target if target.is_dir() else target.parent
    if not folder.exists():
        return None

    preferred_stems = (folder.name.strip(), *ARTWORK_FILENAMES)
    for stem in preferred_stems:
        if not stem:
            continue
        for ext in ARTWORK_EXTENSIONS:
            candidate = folder / f'{stem}{ext}'
            if candidate.is_file():
                return candidate

    for candidate in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
        if candidate.is_file() and candidate.suffix.lower() in ARTWORK_EXTENSIONS and not candidate.name.startswith('.'):
            return candidate
    return None


@dataclass(frozen=True)
class DisplayPlan:
    scene: str
    render_mode: str
    signature: tuple[Any, ...]
    artwork_path: str | None = None


class ArtworkCache:
    def __init__(self, *, max_entries: int = ARTWORK_CACHE_LIMIT) -> None:
        self._max_entries = max(1, int(max_entries))
        self._cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

    def get(self, path: Path, *, size: tuple[int, int]):
        key = (*(_artwork_key(path) or (str(path), 0, 0)), *size)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached.copy()

        prepared = self._prepare(path, size=size)
        self._cache[key] = prepared
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
        return prepared.copy()

    def _prepare(self, path: Path, *, size: tuple[int, int]):
        from PIL import Image, ImageOps

        resample = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.LANCZOS)
        dither = getattr(getattr(Image, 'Dither', Image), 'FLOYDSTEINBERG', Image.FLOYDSTEINBERG)

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image = ImageOps.fit(image, size, method=resample, centering=(0.5, 0.5))
            image = ImageOps.autocontrast(image.convert('L'))

        palette = Image.new('P', (1, 1))
        raw_palette = []
        for value in (0x00, 0x80, 0xC0, 0xFF):
            raw_palette.extend([value, value, value])
        raw_palette.extend([0, 0, 0] * (256 - 4))
        palette.putpalette(raw_palette)
        return image.convert('RGB').quantize(palette=palette, dither=dither).convert('L')


class DisplayCoordinator:
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
        self._art_cache = ArtworkCache()

    def build_plan(self, snapshot: dict[str, Any]) -> DisplayPlan:
        player = snapshot.get('player') or {}
        health = snapshot.get('health') or {}
        status = str(player.get('status') or 'stopped').strip().lower() or 'stopped'
        relpath = str(player.get('file') or '').strip() or None
        charging = bool(health.get('battery_charging'))
        battery_bucket = _battery_bucket(health.get('battery_percent'))
        last_card = str(snapshot.get('last_card') or '').strip() or None

        artwork_path = resolve_album_art(relpath)
        artwork_key = _artwork_key(artwork_path)
        active_status = status if status in {'playing', 'paused', 'loading'} else 'stopped'

        if relpath and artwork_path and active_status != 'stopped':
            return DisplayPlan(
                scene='album_art',
                render_mode='quality_gray',
                signature=('album_art', active_status, relpath, artwork_key),
                artwork_path=str(artwork_path),
            )

        return DisplayPlan(
            scene='status',
            render_mode='quality_gray',
            signature=(
                'status',
                active_status,
                relpath or '',
                last_card or '',
                battery_bucket,
                charging,
            ),
        )

    def render(self, plan: DisplayPlan, snapshot: dict[str, Any]) -> None:
        epd = self._epd3in7.EPD()
        if epd.init(0) != 0:
            raise RuntimeError('e-ink init failed')

        try:
            canvas = self._Image.new('L', (epd.height, epd.width), 0xFF)
            draw = self._ImageDraw.Draw(canvas)
            if plan.scene == 'album_art' and plan.artwork_path:
                self._draw_album_art(canvas, draw, snapshot, Path(plan.artwork_path))
            else:
                self._draw_status(draw, canvas.size, snapshot)

            self._render_canvas(epd, plan.render_mode, canvas)
        finally:
            try:
                epd.sleep()
            except Exception:
                from waveshare_epd import epdconfig

                epdconfig.module_exit()

    def _render_canvas(self, epd, render_mode: str, canvas) -> None:
        if render_mode == 'quality_gray':
            epd.Clear(0xFF, 0)
            epd.display_4Gray(epd.getbuffer_4Gray(canvas))
            return
        raise ValueError(f'unsupported render mode: {render_mode}')

    def _draw_header(self, draw, *, width: int, status: str, battery: Any, charging: bool) -> None:
        draw.rectangle((0, 0, width, 48), fill=0x00)
        draw.text((18, 10), status.upper(), font=self._meta_font, fill=0xFF)
        battery_text = '--%'
        if battery is not None:
            battery_text = f'{int(round(float(battery)))}%'
        if charging:
            battery_text += ' +'
        battery_width = int(draw.textlength(battery_text, font=self._meta_font))
        draw.text((width - battery_width - 18, 10), battery_text, font=self._meta_font, fill=0xFF)

    def _draw_status(self, draw, size: tuple[int, int], snapshot: dict[str, Any]) -> None:
        width, height = size
        player = snapshot.get('player') or {}
        health = snapshot.get('health') or {}

        status = str(player.get('status') or 'stopped').strip().lower()
        battery = health.get('battery_percent')
        charging = bool(health.get('battery_charging'))
        last_card = str(snapshot.get('last_card') or '').strip()
        title, subtitle = _player_title(player.get('file'))

        self._draw_header(draw, width=width, status=status, battery=battery, charging=charging)

        top = 72
        for line in textwrap.wrap(title, width=24)[:3]:
            draw.text((18, top), line, font=self._title_font, fill=0x00)
            top += 38

        if subtitle:
            for line in textwrap.wrap(subtitle, width=34)[:2]:
                draw.text((18, top + 4), line, font=self._body_font, fill=0x40)
                top += 28

        if last_card:
            draw.text((18, height - 52), f'Card {last_card}', font=self._small_font, fill=0x40)
        else:
            draw.text((18, height - 52), 'RFID ready', font=self._small_font, fill=0x40)

        draw.line((18, height - 24, width - 18, height - 24), fill=0x80, width=2)

    def _draw_album_art(self, canvas, draw, snapshot: dict[str, Any], artwork_path: Path) -> None:
        width, height = canvas.size
        player = snapshot.get('player') or {}
        health = snapshot.get('health') or {}

        status = str(player.get('status') or 'stopped').strip().lower()
        battery = health.get('battery_percent')
        charging = bool(health.get('battery_charging'))
        title, subtitle = _player_title(player.get('file'))

        self._draw_header(draw, width=width, status=status, battery=battery, charging=charging)

        art_x, art_y = 18, 64
        art = self._art_cache.get(artwork_path, size=ALBUM_ART_SIZE)
        canvas.paste(art, (art_x, art_y))
        draw.rectangle((art_x, art_y, art_x + ALBUM_ART_SIZE[0], art_y + ALBUM_ART_SIZE[1]), outline=0x80, width=2)

        text_x = art_x + ALBUM_ART_SIZE[0] + 22
        top = 74
        for line in textwrap.wrap(title, width=16)[:4]:
            draw.text((text_x, top), line, font=self._title_font, fill=0x00)
            top += 34

        if subtitle:
            top += 6
            for line in textwrap.wrap(subtitle, width=19)[:3]:
                draw.text((text_x, top), line, font=self._body_font, fill=0x40)
                top += 26

        draw.text((text_x, height - 74), 'Album art', font=self._meta_font, fill=0x80)
        draw.line((text_x, height - 24, width - 18, height - 24), fill=0x80, width=2)


def eink_worker(store) -> None:
    if EINK_BOOT_DELAY_S > 0:
        time.sleep(EINK_BOOT_DELAY_S)

    coordinator: DisplayCoordinator | None = None
    last_signature: tuple[Any, ...] | None = None
    last_render_mono = 0.0
    last_failed_signature: tuple[Any, ...] | None = None
    last_failed_mono = 0.0
    ready_logged = False
    last_error: str | None = None

    while True:
        snapshot = store.snapshot(since_id=0, event_limit=1)

        try:
            if coordinator is None:
                coordinator = DisplayCoordinator()
            plan = coordinator.build_plan(snapshot)
            now = time.monotonic()

            if plan.signature == last_signature or now - last_render_mono < EINK_MIN_REFRESH_S:
                time.sleep(EINK_POLL_INTERVAL_S)
                continue
            if plan.signature == last_failed_signature and now - last_failed_mono < EINK_ERROR_RETRY_S:
                time.sleep(EINK_POLL_INTERVAL_S)
                continue

            coordinator.render(plan, snapshot)
            last_signature = plan.signature
            last_render_mono = now
            last_failed_signature = None
            last_failed_mono = 0.0
            if not ready_logged:
                store.add_event('EINK_READY')
                ready_logged = True
            last_error = None
        except Exception as exc:
            last_failed_signature = plan.signature if 'plan' in locals() else None
            last_failed_mono = time.monotonic()
            message = str(exc).strip() or exc.__class__.__name__
            if message != last_error:
                store.add_event(f'EINK_ERR {message}', level='warning')
                last_error = message
        time.sleep(EINK_POLL_INTERVAL_S)
