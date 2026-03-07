from __future__ import annotations

from typing import Any

from PIL import ImageChops

from .types import DisplayFrame, DisplayOverlay, Rect, UpdateAction

PARTIAL_SCRUB_EVERY = 5
PARTIAL_AREA_RATIO_LIMIT = 0.38
PARTIAL_MERGE_GAP_PX = 6
PARTIAL_PADDING_PX = 2
MAX_PARTIAL_RECTS = 4


class UpdatePlanner:
    def __init__(self) -> None:
        self._last_mode: str | None = None
        self._last_base_key: tuple[Any, ...] | None = None
        self._last_overlays: dict[str, tuple[Rect, Any]] = {}
        self._partial_updates = 0

    def reset(self) -> None:
        self._last_mode = None
        self._last_base_key = None
        self._last_overlays = {}
        self._partial_updates = 0

    def plan(self, frame: DisplayFrame) -> UpdateAction:
        width, height = frame.full_canvas.size
        total_area = max(1, width * height)

        if frame.render_mode == 'quality_gray':
            if self._can_partial_gray(frame):
                rects = self._changed_overlay_rects(frame, width=width, height=height)
                if not rects:
                    return UpdateAction('skip', reason='unchanged')
                if self._partial_updates >= PARTIAL_SCRUB_EVERY:
                    return UpdateAction('full_gray', reason='partial_scrub_budget')
                dirty_area = sum(rect.area for rect in rects)
                if dirty_area / total_area > PARTIAL_AREA_RATIO_LIMIT or len(rects) > MAX_PARTIAL_RECTS:
                    return UpdateAction('full_gray', reason='dirty_area')
                return UpdateAction('partial_mono', rects=tuple(rects), reason='overlay_delta')
            return UpdateAction('full_gray', reason='mode_or_base_change')

        if frame.render_mode == 'fast_bw':
            if self._can_partial_mono(frame):
                rects = self._changed_overlay_rects(frame, width=width, height=height)
                if not rects:
                    return UpdateAction('skip', reason='unchanged')
                if self._partial_updates >= PARTIAL_SCRUB_EVERY:
                    return UpdateAction('full_mono', reason='partial_scrub_budget')
                dirty_area = sum(rect.area for rect in rects)
                if dirty_area / total_area > PARTIAL_AREA_RATIO_LIMIT or len(rects) > MAX_PARTIAL_RECTS:
                    return UpdateAction('full_mono', reason='dirty_area')
                return UpdateAction('partial_mono', rects=tuple(rects), reason='overlay_delta')
            return UpdateAction('full_mono', reason='mode_change')

        raise ValueError(f'unsupported render mode: {frame.render_mode}')

    def commit(self, frame: DisplayFrame, action: UpdateAction) -> None:
        if action.kind == 'skip':
            return
        self._last_mode = frame.render_mode
        self._last_base_key = frame.base_key
        self._last_overlays = {overlay.name: (overlay.rect, overlay.image.copy()) for overlay in frame.overlays}
        if action.kind == 'partial_mono':
            self._partial_updates += 1
            return
        self._partial_updates = 0

    def _can_partial_gray(self, frame: DisplayFrame) -> bool:
        return bool(
            frame.overlays
            and self._last_mode == 'quality_gray'
            and frame.base_key is not None
            and frame.base_key == self._last_base_key
            and self._last_overlays
        )

    def _can_partial_mono(self, frame: DisplayFrame) -> bool:
        return bool(frame.overlays and self._last_mode == 'fast_bw' and self._last_overlays)

    def _changed_overlay_rects(self, frame: DisplayFrame, *, width: int, height: int) -> list[Rect]:
        rects: list[Rect] = []
        seen: set[str] = set()
        for overlay in frame.overlays:
            seen.add(overlay.name)
            previous = self._last_overlays.get(overlay.name)
            if previous is None or previous[0] != overlay.rect:
                rects.append(self._normalize_rect(overlay.rect, width=width, height=height))
                continue
            local_bbox = ImageChops.difference(previous[1], overlay.image).getbbox()
            if local_bbox is None:
                continue
            delta_rect = Rect(*local_bbox).translate(overlay.rect.left, overlay.rect.top)
            rects.append(self._normalize_rect(delta_rect, width=width, height=height))
        for name, (previous_rect, _previous_image) in self._last_overlays.items():
            if name in seen:
                continue
            rects.append(self._normalize_rect(previous_rect, width=width, height=height))
        return _merge_rects(rects)

    @staticmethod
    def _normalize_rect(rect: Rect, *, width: int, height: int) -> Rect:
        return rect.expand(PARTIAL_PADDING_PX, PARTIAL_PADDING_PX, width=width, height=height).align_for_panel(
            canvas_width=width,
            canvas_height=height,
        )


def _merge_rects(rects: list[Rect]) -> list[Rect]:
    if not rects:
        return []

    pending = sorted(rects, key=lambda rect: (rect.top, rect.left))
    merged: list[Rect] = []
    for rect in pending:
        if not merged:
            merged.append(rect)
            continue
        last = merged[-1]
        if last.touches(rect, gap=PARTIAL_MERGE_GAP_PX):
            merged[-1] = last.union(rect)
            continue
        merged.append(rect)
    return merged
