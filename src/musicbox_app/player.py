import json
import os
import socket
import subprocess
import threading
from typing import Any, Dict

from .config import AUDIO_DEVICE, MEDIA_DIR, MPV_SOCKET, PLAYLIST_PATH
from .media import list_audio_files_recursive, safe_rel_to_abs
from .store import AppStore


class PlayerManager:
    def __init__(self, store: AppStore) -> None:
        self.store = store
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

    def _spawn(self, args: list[str], rel_display_path: str) -> None:
        self._cleanup_socket()
        self._proc = subprocess.Popen(args)
        self.store.set_player_state({'status': 'playing', 'file': rel_display_path})
        self.store.update_health(mpv_running=True)

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
            self.store.set_player_state({'status': 'stopped', 'file': None})
            self.store.update_health(mpv_running=False)

    def play(self, relpath: str) -> None:
        target = safe_rel_to_abs(relpath)
        if not target.exists():
            raise FileNotFoundError(relpath)

        with self._lock:
            self.stop()

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
                    f'--input-ipc-server={MPV_SOCKET}',
                    f'--playlist={PLAYLIST_PATH}',
                ]
            else:
                args = [
                    'mpv',
                    '--no-video',
                    '--really-quiet',
                    f'--audio-device={AUDIO_DEVICE}',
                    f'--input-ipc-server={MPV_SOCKET}',
                    str(target),
                ]

            self._spawn(args, str(target.relative_to(MEDIA_DIR)))
            self.store.add_event(f'PLAY {relpath}')

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

    def add_volume(self, delta: int) -> bool:
        response = self._mpv_cmd(['add', 'volume', int(delta)])
        if response is None:
            return False

        current = self._mpv_cmd(['get_property', 'volume'])
        if current and isinstance(current.get('data'), (int, float)):
            self.store.set_player_state({'volume': round(float(current['data']))})
        self.store.add_event(f'VOLUME {delta:+d}')
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
        if action == 'volup':
            return self.add_volume(+5)
        if action == 'voldown':
            return self.add_volume(-5)
        return False

    def watchdog_tick(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is not None:
                rc = self._proc.returncode
                self._proc = None
                self._cleanup_socket()
                self.store.set_player_state({'status': 'stopped', 'file': None})
                self.store.update_health(mpv_running=False)
                self.store.add_event(f'PLAYER_EXIT rc={rc}')
            elif self._proc and self._proc.poll() is None:
                self.store.update_health(mpv_running=True)
