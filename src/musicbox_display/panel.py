from __future__ import annotations

import time

from .planner import UpdatePlanner
from .types import DisplayFrame, Rect, UpdateAction

DISPLAY_IDLE_SLEEP_S = 30.0


class PanelCore:
    def __init__(self, *, epd_module=None, idle_sleep_s: float = DISPLAY_IDLE_SLEEP_S) -> None:
        if epd_module is None:
            from waveshare_epd import epd3in7

            epd_module = epd3in7

        self._epd3in7 = epd_module
        self._epd = None
        self._active_hw_mode: str | None = None
        self._planner = UpdatePlanner()
        self._idle_sleep_s = float(idle_sleep_s)
        self._last_activity_mono = 0.0

    def render(self, frame: DisplayFrame) -> UpdateAction:
        action = self._planner.plan(frame)
        if action.kind == 'skip':
            return action

        if action.kind == 'full_gray':
            epd = self._ensure_mode('quality_gray')
            epd.display_4Gray(epd.getbuffer_4Gray(frame.full_canvas))
        elif action.kind == 'full_mono':
            epd = self._ensure_mode('fast_bw')
            mono_canvas = _compose_mono_canvas(frame)
            epd.display_1Gray_full(epd.getbuffer(mono_canvas))
        elif action.kind == 'partial_mono':
            epd = self._ensure_mode('fast_bw')
            mono_canvas = _compose_mono_canvas(frame)
            packed = epd.getbuffer(mono_canvas)
            for rect in action.rects:
                panel_rect = canvas_rect_to_panel_rect(rect, canvas_size=mono_canvas.size, panel_width=epd.width, panel_height=epd.height)
                payload = extract_region_bytes(packed, panel_rect, panel_width=epd.width)
                epd.display_1Gray_part(payload, panel_rect.left, panel_rect.top, panel_rect.right, panel_rect.bottom)
        else:
            raise ValueError(f'unsupported action: {action.kind}')

        self._planner.commit(frame, action)
        self._last_activity_mono = time.monotonic()
        return action

    def idle_sleep_due(self, now_mono: float) -> bool:
        return bool(self._epd is not None and self._last_activity_mono > 0.0 and now_mono - self._last_activity_mono >= self._idle_sleep_s)

    def reset_device(self) -> None:
        if self._epd is not None:
            try:
                self._epd.sleep()
            except Exception:
                from waveshare_epd import epdconfig

                epdconfig.module_exit()
        self._epd = None
        self._active_hw_mode = None
        self._last_activity_mono = 0.0
        self._planner.reset()

    def _ensure_mode(self, render_mode: str):
        if self._epd is None:
            self._epd = self._epd3in7.EPD()

        if self._active_hw_mode == render_mode:
            return self._epd

        if render_mode == 'quality_gray':
            init_ok = self._epd.init_4Gray()
        elif render_mode == 'fast_bw':
            init_ok = self._epd.init_1Gray()
        else:
            raise ValueError(f'unsupported render mode: {render_mode}')

        if init_ok != 0:
            self.reset_device()
            raise RuntimeError('e-ink init failed')

        self._active_hw_mode = render_mode
        return self._epd


def _compose_mono_canvas(frame: DisplayFrame):
    if frame.overlays:
        from PIL import Image

        canvas = Image.new('1', frame.full_canvas.size, 1)
        for overlay in frame.overlays:
            canvas.paste(overlay.image.convert('1'), (overlay.rect.left, overlay.rect.top))
        return canvas
    return frame.full_canvas.convert('1')


def canvas_rect_to_panel_rect(rect: Rect, *, canvas_size: tuple[int, int], panel_width: int, panel_height: int) -> Rect:
    canvas_width, canvas_height = canvas_size
    if canvas_width != panel_height or canvas_height != panel_width:
        raise ValueError(f'unexpected canvas/panel sizes: canvas={canvas_size} panel={(panel_width, panel_height)}')
    return Rect(
        rect.top,
        panel_height - rect.right,
        rect.bottom,
        panel_height - rect.left,
    )


def extract_region_bytes(full_buffer: list[int], rect: Rect, *, panel_width: int) -> list[int]:
    bytes_per_row = panel_width // 8
    if panel_width % 8:
        bytes_per_row += 1

    byte_left = rect.left // 8
    byte_right = rect.right // 8
    if rect.right % 8:
        byte_right += 1

    payload: list[int] = []
    for y in range(rect.top, rect.bottom):
        row_start = y * bytes_per_row + byte_left
        row_end = y * bytes_per_row + byte_right
        payload.extend(full_buffer[row_start:row_end])
    return payload
