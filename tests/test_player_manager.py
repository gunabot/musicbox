import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix='musicbox-tests-')).resolve()
os.environ['MUSICBOX_BASE_DIR'] = str(TEST_ROOT / 'base')
os.environ['MUSICBOX_MEDIA_DIR'] = str(TEST_ROOT / 'media')
os.environ['MUSICBOX_CONFIG_DIR'] = str(TEST_ROOT / 'config')
os.environ['MUSICBOX_LOG_DIR'] = str(TEST_ROOT / 'logs')
os.environ['MUSICBOX_DB_PATH'] = str(TEST_ROOT / 'config' / 'musicbox.db')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from musicbox_app.player import BackendStatus, PlayerManager
from musicbox_app.spotify_auth import SpotifyAuthManager
from musicbox_app.store import AppStore


class FakeBackend:
    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.current = BackendStatus(
            state='stopped',
            process_alive=False,
            volume=50,
            duration_sec=0.0,
        )

    def play_file(self, path: Path, *, volume: int) -> BackendStatus:
        self.commands.append(('load', str(path), int(volume)))
        self.current = BackendStatus(
            state='loading',
            process_alive=True,
            volume=int(volume),
            duration_sec=180.0,
            position_sec=0.0,
        )
        return self.current

    def play(self) -> BackendStatus:
        self.commands.append(('play',))
        self.current = BackendStatus(
            state='playing',
            process_alive=True,
            volume=self.current.volume,
            duration_sec=max(self.current.duration_sec, 1.0),
            position_sec=self.current.position_sec,
            speed=self.current.speed,
            direction=self.current.direction,
        )
        return self.current

    def pause(self) -> BackendStatus:
        self.commands.append(('pause',))
        self.current = BackendStatus(
            state='paused',
            process_alive=True,
            volume=self.current.volume,
            duration_sec=max(self.current.duration_sec, 1.0),
            position_sec=self.current.position_sec,
            speed=self.current.speed,
            direction=self.current.direction,
        )
        return self.current

    def stop(self) -> BackendStatus:
        self.commands.append(('stop',))
        self.current = BackendStatus(
            state='stopped',
            process_alive=True,
            volume=self.current.volume,
            duration_sec=self.current.duration_sec,
            position_sec=self.current.position_sec,
        )
        return self.current

    def set_speed(self, speed: float, *, direction: str | None = None, ramp_ms: int = 0) -> BackendStatus:
        self.commands.append(('set_speed', float(speed), direction, int(ramp_ms)))
        self.current = BackendStatus(
            state=self.current.state,
            process_alive=True,
            volume=self.current.volume,
            duration_sec=max(self.current.duration_sec, 1.0),
            position_sec=self.current.position_sec,
            speed=float(speed),
            direction=direction or self.current.direction,
        )
        return self.current

    def set_volume(self, volume: int) -> BackendStatus:
        self.commands.append(('set_volume', int(volume)))
        self.current = BackendStatus(
            state=self.current.state,
            process_alive=True,
            volume=int(volume),
            duration_sec=max(self.current.duration_sec, 1.0),
            position_sec=self.current.position_sec,
            speed=self.current.speed,
            direction=self.current.direction,
        )
        return self.current

    def status(self) -> BackendStatus:
        return self.current


class PlayerManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        for directory in (TEST_ROOT / 'media', TEST_ROOT / 'config', TEST_ROOT / 'logs'):
            directory.mkdir(parents=True, exist_ok=True)
        db_path = TEST_ROOT / 'config' / 'musicbox.db'
        if db_path.exists():
            db_path.unlink()
        for path in (TEST_ROOT / 'media').rglob('*'):
            if path.is_file():
                path.unlink()
        for path in sorted((TEST_ROOT / 'media').rglob('*'), reverse=True):
            if path.is_dir():
                path.rmdir()
        (TEST_ROOT / 'media').mkdir(parents=True, exist_ok=True)

        self.backend = FakeBackend()
        self.store = AppStore()
        self.auth = SpotifyAuthManager(self.store)
        self.player = PlayerManager(self.store, self.auth, backend=self.backend)

    def test_directory_play_queues_and_navigates_tracks(self) -> None:
        album = TEST_ROOT / 'media' / 'album'
        album.mkdir(parents=True, exist_ok=True)
        for name in ['02-second.mp3', '01-first.mp3', 'notes.txt']:
            (album / name).write_text(name, encoding='utf-8')

        self.player.play('album')
        snapshot = self.store.snapshot(event_limit=10)
        self.assertEqual(snapshot['player']['file'], 'album/01-first.mp3')

        self.player.next()
        snapshot = self.store.snapshot(event_limit=10)
        self.assertEqual(snapshot['player']['file'], 'album/02-second.mp3')

        self.backend.current = BackendStatus(
            state='playing',
            process_alive=True,
            volume=50,
            duration_sec=180.0,
            position_sec=4.0,
        )
        self.player.prev()
        snapshot = self.store.snapshot(event_limit=10)
        self.assertEqual(snapshot['player']['file'], 'album/02-second.mp3')
        self.assertEqual(self.backend.commands[-1][0], 'load')

    def test_watchdog_auto_advances_to_next_track(self) -> None:
        album = TEST_ROOT / 'media' / 'mix'
        album.mkdir(parents=True, exist_ok=True)
        for name in ['a.mp3', 'b.mp3']:
            (album / name).write_text(name, encoding='utf-8')

        self.player.play('mix')
        self.backend.current = BackendStatus(
            state='stopped',
            process_alive=True,
            volume=50,
            duration_sec=120.0,
            position_sec=120.0,
        )

        self.player.watchdog_tick()
        snapshot = self.store.snapshot(event_limit=10)
        self.assertEqual(snapshot['player']['file'], 'mix/b.mp3')

    def test_transport_hold_uses_turntable_ramps(self) -> None:
        track = TEST_ROOT / 'media' / 'song.mp3'
        track.write_text('song', encoding='utf-8')

        self.player.play('song.mp3')
        self.backend.current = BackendStatus(
            state='playing',
            process_alive=True,
            volume=50,
            duration_sec=90.0,
            position_sec=12.0,
        )

        self.assertTrue(self.player.begin_transport(reverse=True))
        self.assertEqual(self.backend.commands[-1], ('set_speed', 1.5, 'reverse', 2000))

        self.backend.current = BackendStatus(
            state='paused',
            process_alive=True,
            volume=50,
            duration_sec=90.0,
            position_sec=0.0,
            speed=1.5,
            direction='reverse',
        )
        self.assertTrue(self.player.end_transport())
        self.assertEqual(self.backend.commands[-2], ('play',))
        self.assertEqual(self.backend.commands[-1], ('set_speed', 1.0, 'forward', 700))


if __name__ == '__main__':
    unittest.main()
