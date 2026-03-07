import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix='musicbox-eink-tests-')).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def _eink_module():
    return importlib.import_module('musicbox_app.eink')


class EInkTests(unittest.TestCase):
    def setUp(self) -> None:
        media = TEST_ROOT / 'media'
        if media.exists():
            for path in media.rglob('*'):
                if path.is_file():
                    path.unlink()
            for path in sorted(media.rglob('*'), reverse=True):
                if path.is_dir():
                    path.rmdir()
        media.mkdir(parents=True, exist_ok=True)

    def test_resolve_album_art_prefers_cover_names(self) -> None:
        album = TEST_ROOT / 'media' / 'album'
        album.mkdir(parents=True, exist_ok=True)
        (album / 'random.png').write_text('x', encoding='utf-8')
        cover = album / 'cover.jpg'
        cover.write_text('x', encoding='utf-8')

        eink = _eink_module()
        with patch('musicbox_app.eink.safe_rel_to_abs', return_value=album / 'song.mp3'):
            self.assertEqual(eink.resolve_album_art('album/song.mp3'), cover)

    def test_resolve_album_art_prefers_directory_named_jpg(self) -> None:
        album = TEST_ROOT / 'media' / 'Morcheeba - 1998 - Big Calm'
        album.mkdir(parents=True, exist_ok=True)
        named = album / 'Morcheeba - 1998 - Big Calm.jpg'
        named.write_text('x', encoding='utf-8')
        (album / 'cover.jpg').write_text('x', encoding='utf-8')

        eink = _eink_module()
        with patch('musicbox_app.eink.safe_rel_to_abs', return_value=album / '01 - Morcheeba - The Sea.mp3'):
            self.assertEqual(eink.resolve_album_art('album/song.mp3'), named)

    def test_build_plan_uses_album_art_for_active_track(self) -> None:
        album = TEST_ROOT / 'media' / 'album'
        album.mkdir(parents=True, exist_ok=True)
        track = album / 'song.mp3'
        track.write_text('x', encoding='utf-8')
        cover = album / 'folder.png'
        cover.write_text('x', encoding='utf-8')

        coordinator = _eink_module().DisplayCoordinator()
        with patch('musicbox_app.eink.safe_rel_to_abs', return_value=track):
            plan = coordinator.build_plan(
                {
                    'player': {'status': 'playing', 'file': 'album/song.mp3', 'volume': 50, 'speed': 1.0, 'direction': 'forward'},
                    'health': {'battery_percent': 76.0, 'battery_charging': False},
                    'last_card': None,
                }
            )

        self.assertEqual(plan.scene, 'album_art')
        self.assertEqual(plan.render_mode, 'quality_gray')
        self.assertEqual(Path(plan.artwork_path), cover)

    def test_album_art_signature_ignores_volume_changes(self) -> None:
        album = TEST_ROOT / 'media' / 'album'
        album.mkdir(parents=True, exist_ok=True)
        (album / 'song.mp3').write_text('x', encoding='utf-8')
        (album / 'cover.jpg').write_text('x', encoding='utf-8')

        coordinator = _eink_module().DisplayCoordinator()
        base = {
            'player': {'status': 'playing', 'file': 'album/song.mp3', 'speed': 1.0, 'direction': 'forward'},
            'health': {'battery_percent': 71.0, 'battery_charging': False},
            'last_card': None,
        }

        with patch('musicbox_app.eink.safe_rel_to_abs', return_value=album / 'song.mp3'):
            plan_a = coordinator.build_plan({**base, 'player': {**base['player'], 'volume': 20}})
            plan_b = coordinator.build_plan({**base, 'player': {**base['player'], 'volume': 80}})
        self.assertEqual(plan_a.signature, plan_b.signature)


if __name__ == '__main__':
    unittest.main()
