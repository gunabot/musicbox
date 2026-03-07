import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

TEST_ROOT = Path(tempfile.mkdtemp(prefix='musicbox-display-core-tests-')).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from musicbox_display import DisplayFrame, DisplayOverlay, PanelCore, Rect, UpdatePlanner, canvas_rect_to_panel_rect, extract_region_bytes


def make_overlay(size: tuple[int, int], *, text: str = ''):
    image = Image.new('1', size, 1)
    if text:
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, min(size[0] - 1, 40), min(size[1] - 1, 20)), fill=0)
        draw.text((2, 2), text, fill=1)
    return image


class DisplayCoreTests(unittest.TestCase):
    def test_canvas_rect_maps_to_panel_rect(self) -> None:
        rect = Rect(240, 64, 462, 246)
        panel_rect = canvas_rect_to_panel_rect(rect, canvas_size=(480, 280), panel_width=280, panel_height=480)
        self.assertEqual(panel_rect, Rect(64, 18, 246, 240))

    def test_extract_region_bytes_uses_panel_rows(self) -> None:
        panel_width = 8
        full_buffer = [0xAA, 0xBB, 0xCC, 0xDD]
        rect = Rect(0, 1, 8, 3)
        self.assertEqual(extract_region_bytes(full_buffer, rect, panel_width=panel_width), [0xBB, 0xCC])

    def test_planner_uses_partial_mono_for_small_fast_bw_change(self) -> None:
        planner = UpdatePlanner()
        full = Image.new('L', (480, 280), 0xFF)
        overlay_a = make_overlay((480, 280))
        frame_a = DisplayFrame(
            render_mode='fast_bw',
            full_canvas=full,
            signature=('status', 'a'),
            overlays=(DisplayOverlay('status', Rect(0, 0, 480, 280), overlay_a),),
        )
        action_a = planner.plan(frame_a)
        self.assertEqual(action_a.kind, 'full_mono')
        planner.commit(frame_a, action_a)

        overlay_b = overlay_a.copy()
        draw = ImageDraw.Draw(overlay_b)
        draw.rectangle((12, 12, 28, 24), fill=0)
        frame_b = DisplayFrame(
            render_mode='fast_bw',
            full_canvas=full,
            signature=('status', 'b'),
            overlays=(DisplayOverlay('status', Rect(0, 0, 480, 280), overlay_b),),
        )
        action_b = planner.plan(frame_b)
        self.assertEqual(action_b.kind, 'partial_mono')
        self.assertTrue(action_b.rects)

    def test_planner_uses_partial_mono_for_same_gray_base(self) -> None:
        planner = UpdatePlanner()
        full = Image.new('L', (480, 280), 0xFF)
        header_a = make_overlay((480, 48))
        meta_a = make_overlay((222, 178))
        frame_a = DisplayFrame(
            render_mode='quality_gray',
            full_canvas=full,
            signature=('album_art', 'song-a'),
            base_key=('album_art', 'cover-a'),
            overlays=(
                DisplayOverlay('header', Rect(0, 0, 480, 48), header_a),
                DisplayOverlay('meta', Rect(240, 68, 462, 246), meta_a),
            ),
        )
        action_a = planner.plan(frame_a)
        self.assertEqual(action_a.kind, 'full_gray')
        planner.commit(frame_a, action_a)

        meta_b = meta_a.copy()
        draw = ImageDraw.Draw(meta_b)
        draw.rectangle((10, 10, 60, 40), fill=0)
        frame_b = DisplayFrame(
            render_mode='quality_gray',
            full_canvas=full,
            signature=('album_art', 'song-b'),
            base_key=('album_art', 'cover-a'),
            overlays=(
                DisplayOverlay('header', Rect(0, 0, 480, 48), header_a),
                DisplayOverlay('meta', Rect(240, 68, 462, 246), meta_b),
            ),
        )
        action_b = planner.plan(frame_b)
        self.assertEqual(action_b.kind, 'partial_mono')
        self.assertEqual(len(action_b.rects), 1)

    def test_planner_marks_removed_overlay_dirty(self) -> None:
        planner = UpdatePlanner()
        full = Image.new('L', (480, 280), 0xFF)
        header = make_overlay((480, 48))
        meta = make_overlay((222, 178))
        frame_a = DisplayFrame(
            render_mode='quality_gray',
            full_canvas=full,
            signature=('album_art', 'song-a'),
            base_key=('album_art', 'cover-a'),
            overlays=(
                DisplayOverlay('header', Rect(0, 0, 480, 48), header),
                DisplayOverlay('meta', Rect(240, 68, 462, 246), meta),
            ),
        )
        action_a = planner.plan(frame_a)
        planner.commit(frame_a, action_a)

        frame_b = DisplayFrame(
            render_mode='quality_gray',
            full_canvas=full,
            signature=('album_art', 'song-b'),
            base_key=('album_art', 'cover-a'),
            overlays=(DisplayOverlay('header', Rect(0, 0, 480, 48), header),),
        )
        action_b = planner.plan(frame_b)
        self.assertEqual(action_b.kind, 'partial_mono')
        self.assertTrue(any(rect.left >= 200 and rect.right >= 440 for rect in action_b.rects))

    def test_panel_core_uses_partial_driver_method(self) -> None:
        class FakeEPD:
            def __init__(self) -> None:
                self.width = 280
                self.height = 480
                self.calls: list[str] = []

            def init_1Gray(self):
                self.calls.append('init_1Gray')
                return 0

            def init_4Gray(self):
                self.calls.append('init_4Gray')
                return 0

            def getbuffer(self, image):
                self.calls.append(f'getbuffer:{image.mode}')
                return [0xFF] * (35 * 480)

            def getbuffer_4Gray(self, image):
                self.calls.append(f'getbuffer_4Gray:{image.mode}')
                return [0xFF] * (70 * 480)

            def display_1Gray_full(self, image):
                self.calls.append(f'full:{len(image)}')

            def display_1Gray_part(self, image, x_start, y_start, x_end, y_end):
                self.calls.append(f'part:{x_start},{y_start},{x_end},{y_end}:{len(image)}')

            def display_4Gray(self, image):
                self.calls.append(f'gray:{len(image)}')

            def sleep(self):
                self.calls.append('sleep')

        class FakeModule:
            def __init__(self) -> None:
                self.instance = FakeEPD()

            def EPD(self):
                return self.instance

        panel = PanelCore(epd_module=FakeModule())
        full = Image.new('L', (480, 280), 0xFF)
        overlay_a = make_overlay((480, 280))
        frame_a = DisplayFrame(
            render_mode='fast_bw',
            full_canvas=full,
            signature=('status', 'a'),
            overlays=(DisplayOverlay('status', Rect(0, 0, 480, 280), overlay_a),),
        )
        action_a = panel.render(frame_a)
        self.assertEqual(action_a.kind, 'full_mono')

        overlay_b = overlay_a.copy()
        draw = ImageDraw.Draw(overlay_b)
        draw.rectangle((12, 12, 28, 28), fill=0)
        frame_b = DisplayFrame(
            render_mode='fast_bw',
            full_canvas=full,
            signature=('status', 'b'),
            overlays=(DisplayOverlay('status', Rect(0, 0, 480, 280), overlay_b),),
        )
        action_b = panel.render(frame_b)
        self.assertEqual(action_b.kind, 'partial_mono')
        self.assertTrue(any(call.startswith('part:') for call in panel._epd.calls))


if __name__ == '__main__':
    unittest.main()
