import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(tempfile.mkdtemp(prefix='musicbox-recorder-tests-')).resolve()
os.environ['MUSICBOX_BASE_DIR'] = str(TEST_ROOT / 'base')
os.environ['MUSICBOX_MEDIA_DIR'] = str(TEST_ROOT / 'media')
os.environ['MUSICBOX_CONFIG_DIR'] = str(TEST_ROOT / 'config')
os.environ['MUSICBOX_LOG_DIR'] = str(TEST_ROOT / 'logs')
os.environ['MUSICBOX_DB_PATH'] = str(TEST_ROOT / 'config' / 'musicbox.db')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from musicbox_app.config import DB_PATH, LOG_DIR, MEDIA_DIR
from musicbox_app.recorder import RecorderManager
from musicbox_app.store import AppStore


class FakeProc:
    def __init__(self) -> None:
        self.signals: list[int] = []
        self.terminated = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def send_signal(self, value: int) -> None:
        self.signals.append(int(value))
        self.returncode = 0

    def wait(self, timeout=None):
        del timeout
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = 0


class RecorderManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        media_root = MEDIA_DIR.resolve()
        for directory in (media_root, DB_PATH.resolve().parent, LOG_DIR.resolve()):
            directory.mkdir(parents=True, exist_ok=True)
        db_path = DB_PATH.resolve()
        if db_path.exists():
            db_path.unlink()
        for path in media_root.rglob('*'):
            if path.is_file():
                path.unlink()
        for path in sorted(media_root.rglob('*'), reverse=True):
            if path.is_dir():
                path.rmdir()
        media_root.mkdir(parents=True, exist_ok=True)
        self.store = AppStore()

    def test_start_sets_recording_active_and_builds_arecord_command(self) -> None:
        fake_proc = FakeProc()
        recordings_dir = MEDIA_DIR / '_recordings'

        with (
            patch('musicbox_app.recorder.shutil.which', return_value='/usr/bin/arecord'),
            patch('musicbox_app.recorder.subprocess.Popen', return_value=fake_proc) as popen,
        ):
            recorder = RecorderManager(self.store, recordings_dir=recordings_dir, preview_name='preview.wav', device='plughw:0,0')
            self.assertTrue(recorder.start())

        self.assertTrue(self.store.snapshot()['recording']['active'])
        args = popen.call_args.args[0]
        self.assertEqual(args[:8], ['/usr/bin/arecord', '-q', '-D', 'plughw:0,0', '-f', 'S16_LE', '-r', '16000'])
        self.assertEqual(args[-2:], ['wav', str(recordings_dir / '.preview.wav.part')])

    def test_stop_saves_preview_file_and_updates_store(self) -> None:
        fake_proc = FakeProc()
        recordings_dir = MEDIA_DIR / '_recordings'
        preview_path = recordings_dir / 'preview.wav'
        tmp_path = recordings_dir / '.preview.wav.part'

        with (
            patch('musicbox_app.recorder.shutil.which', return_value='/usr/bin/arecord'),
            patch('musicbox_app.recorder.subprocess.Popen', return_value=fake_proc),
        ):
            recorder = RecorderManager(self.store, recordings_dir=recordings_dir, preview_name='preview.wav', device='plughw:0,0')
            self.assertTrue(recorder.start())
            recordings_dir.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(b'RIFF' + (b'\x00' * 128))
            relpath = recorder.stop()

        self.assertEqual(relpath, '_recordings/preview.wav')
        self.assertTrue(preview_path.exists())
        snapshot = self.store.snapshot()
        self.assertFalse(snapshot['recording']['active'])
        self.assertEqual(snapshot['recording']['file'], '_recordings/preview.wav')

    def test_resolve_device_uses_audio_device_card_index(self) -> None:
        with (
            patch('musicbox_app.recorder.shutil.which', return_value='/usr/bin/arecord'),
            patch('musicbox_app.recorder.AUDIO_DEVICE', 'alsa/plughw:2,0'),
        ):
            recorder = RecorderManager(self.store, device='')
            self.assertEqual(recorder._resolve_device(), 'plughw:2,0')

    def test_is_recording_clears_state_after_process_exit(self) -> None:
        fake_proc = FakeProc()
        recordings_dir = MEDIA_DIR / '_recordings'

        with (
            patch('musicbox_app.recorder.shutil.which', return_value='/usr/bin/arecord'),
            patch('musicbox_app.recorder.subprocess.Popen', return_value=fake_proc),
        ):
            recorder = RecorderManager(self.store, recordings_dir=recordings_dir, device='plughw:0,0')
            self.assertTrue(recorder.start())
            fake_proc.returncode = 1
            self.assertFalse(recorder.is_recording())

        self.assertFalse(self.store.snapshot()['recording']['active'])


if __name__ == '__main__':
    unittest.main()
