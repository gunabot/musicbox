from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.right < self.left or self.bottom < self.top:
            raise ValueError(f'invalid rect: {self}')

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return self.width * self.height

    def translate(self, dx: int = 0, dy: int = 0) -> 'Rect':
        return Rect(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)

    def clamp(self, *, width: int, height: int) -> 'Rect':
        return Rect(
            max(0, min(self.left, width)),
            max(0, min(self.top, height)),
            max(0, min(self.right, width)),
            max(0, min(self.bottom, height)),
        )

    def expand(self, pad_x: int, pad_y: int, *, width: int, height: int) -> 'Rect':
        return Rect(
            max(0, self.left - max(0, pad_x)),
            max(0, self.top - max(0, pad_y)),
            min(width, self.right + max(0, pad_x)),
            min(height, self.bottom + max(0, pad_y)),
        )

    def align_for_panel(self, *, canvas_width: int, canvas_height: int) -> 'Rect':
        del canvas_width
        top = max(0, (self.top // 8) * 8)
        bottom = min(canvas_height, ((self.bottom + 7) // 8) * 8)
        return Rect(self.left, top, self.right, bottom)

    def union(self, other: 'Rect') -> 'Rect':
        return Rect(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )

    def touches(self, other: 'Rect', *, gap: int = 0) -> bool:
        return not (
            self.right + gap < other.left
            or other.right + gap < self.left
            or self.bottom + gap < other.top
            or other.bottom + gap < self.top
        )


@dataclass(frozen=True)
class DisplayOverlay:
    name: str
    rect: Rect
    image: Any


@dataclass(frozen=True)
class DisplayFrame:
    render_mode: str
    full_canvas: Any
    signature: tuple[Any, ...]
    base_key: tuple[Any, ...] | None = None
    overlays: tuple[DisplayOverlay, ...] = ()
    # Overlays define the retained mono surfaces used for partial updates.
    # If a scene wants pixels to be correct after a partial update, those
    # pixels must be represented by one of these overlay surfaces.


@dataclass(frozen=True)
class UpdateAction:
    kind: str
    rects: tuple[Rect, ...] = ()
    reason: str = ''
