import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict

from .config import AUDIO_DEVICE, MEDIA_DIR, MPV_SOCKET, PLAYLIST_PATH
from .media import list_audio_files_recursive, safe_rel_to_abs
from .spotify_auth import SpotifyAuthManager
from .spotify_cache import SpotifyCacheResolver
from .store import AppStore


class PlayerManager:
    def __init__(self, store: AppStore, spotify_auth: SpotifyAuthManager) -> None:
        self.store = store
        self.spotify_auth = spotify_auth
        self.spotify_cache = SpotifyCacheResolver(store, spotify_auth)
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None

    def _mpv_cmd(self, command: list[Any]) -> Dict[str, Any] | None:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(MPV_SOCKET)
            payload = json.dumps({'command': command}) + '\n'
            sock.sendall(payload.encode())
            data = sock.recv(4096)
            sock.close()
            if not data:
                return None
            return json.loads(data.decode(errors='ignore'))
        except Exception:
            return None

    def _cleanup_socket(self) -> None:
        if os.path.exists(MPV_SOCKET):
            try:
                os.unlink(MPV_SOCKET)
            except Exception:
                pass

    def _spawn(self, args: list[str], rel_display_path: str, source: str, spotify_uri: str | None = None) -> None:
        self._cleanup_socket()
        self._proc = subprocess.Popen(args)
        self.store.set_player_state({
            'status': 'playing',
            'source': source,
            'file': rel_display_path,
            'spotify_uri': spotify_uri,
        })
        self.store.update_health(mpv_running=True)

    def _desired_volume(self) -> int:
        snap = self.store.snapshot(since_id=0, event_limit=1)
        player = snap.get('player') if isinstance(snap.get('player'), dict) else {}
        try:
            value = int(round(float(player.get('volume', 50))))
        except Exception:
            value = 50
        return max(0, min(self._volume_max(), value))

    def _volume_max(self) -> int:
        value = self.store.get_setting('player_volume_max', 130)
        return max(100, min(200, int(value)))

    def _start_target(self, target: Path, source: str, spotify_uri: str | None = None) -> None:
        self.stop()
        volume = self._desired_volume()
        volume_max = self._volume_max()

        if target.is_dir():
            files = list_audio_files_recursive(target)
            if not files:
                raise FileNotFoundError('no audio files in folder')
            PLAYLIST_PATH.write_text('\n'.join(str(item) for item in files) + '\n')
            args = [
                'mpv',
                '--no-video',
                '--really-quiet',
                f'--audio-device={AUDIO_DEVICE}',
                f'--volume={volume}',
                f'--volume-max={volume_max}',
                f'--input-ipc-server={MPV_SOCKET}',
                f'--playlist={PLAYLIST_PATH}',
            ]
        else:
            args = [
                'mpv',
                '--no-video',
                '--really-quiet',
                f'--audio-device={AUDIO_DEVICE}',
                f'--volume={volume}',
                f'--volume-max={volume_max}',
                f'--input-ipc-server={MPV_SOCKET}',
                str(target),
            ]

        rel = str(target.relative_to(MEDIA_DIR))
        self._spawn(args, rel, source=source, spotify_uri=spotify_uri)

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except Exception:
                    self._proc.kill()
            self._proc = None
            self._cleanup_socket()
            self.store.set_player_state({'status': 'stopped', 'file': None, 'spotify_uri': None})
            self.store.update_health(mpv_running=False)

    def play(self, relpath: str) -> None:
        target = safe_rel_to_abs(relpath)
        if not target.exists():
            raise FileNotFoundError(relpath)

        with self._lock:
            self._start_target(target, source='local', spotify_uri=None)
            self.store.add_event(f'PLAY {relpath}')

    def play_spotify(self, target: str) -> str:
        with self._lock:
            # Validate auth early so the user gets a clear error if Spotify is not connected.
            self.spotify_auth.get_access_token(force_refresh=False)
            relpath = self.spotify_cache.resolve(target)
            resolved = safe_rel_to_abs(relpath)
            if not resolved.exists():
                raise FileNotFoundError(relpath)

            self._start_target(resolved, source='spotify', spotify_uri=target)
            self.store.add_event(f'SPOTIFY_PLAY {target} -> {relpath}')
            return relpath

    def play_pause(self) -> bool:
        response = self._mpv_cmd(['cycle', 'pause'])
        if response is not None:
            self.store.add_event('PLAY_PAUSE')
            return True
        return False

    def next(self) -> bool:
        response = self._mpv_cmd(['playlist-next', 'force'])
        if response is not None:
            self.store.add_event('NEXT')
            return True
        return False

    def prev(self) -> bool:
        response = self._mpv_cmd(['playlist-prev', 'force'])
        if response is not None:
            self.store.add_event('PREV')
            return True
        return False

    def add_volume(self, delta: float) -> bool:
        delta_value = float(delta)
        current = self._mpv_cmd(['get_property', 'volume'])
        if current and isinstance(current.get('data'), (int, float)):
            base = float(current['data'])
        else:
            base = float(self._desired_volume())
        target = max(0.0, min(float(self._volume_max()), base + delta_value))

        # Best effort live apply if MPV IPC is available; otherwise keep the
        # desired volume in state and apply on the next playback start.
        self._mpv_cmd(['set_property', 'volume', float(target)])
        self.store.set_player_state({'volume': int(round(target))})
        self.store.add_event(f'VOLUME {delta_value:+.2f} -> {int(round(target))}')
        return True

    def action(self, action: str) -> bool:
        action = (action or '').strip().lower()
        if action == 'playpause':
            return self.play_pause()
        if action == 'next':
            return self.next()
        if action == 'prev':
            return self.prev()
        if action == 'stop':
            self.stop()
            self.store.add_event('STOP')
            return True
        if action in {'volup', 'volumeup', 'vol+'}:
            return self.add_volume(+5)
        if action in {'voldown', 'volumedown', 'vol-'}:
            return self.add_volume(-5)
        return False

    def watchdog_tick(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is not None:
                rc = self._proc.returncode
                self._proc = None
                self._cleanup_socket()
                self.store.set_player_state({'status': 'stopped', 'file': None, 'spotify_uri': None})
                self.store.update_health(mpv_running=False)
                self.store.add_event(f'PLAYER_EXIT rc={rc}')
            elif self._proc and self._proc.poll() is None:
                self.store.update_health(mpv_running=True)
