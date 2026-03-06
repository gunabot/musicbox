import json
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import (
    MEDIA_EXTENSIONS,
    PLAYER_TRANSPORT_RAMP_MS,
    PLAYER_TRANSPORT_RETURN_MS,
    PLAYER_TRANSPORT_TARGET_SPEED,
    TWINPEAKS_BINARY_CANDIDATES,
    TWINPEAKS_SOCKET,
    TWINPEAKS_STARTUP_TIMEOUT_S,
)
from .media import list_audio_files_recursive, rel_from_abs, safe_rel_to_abs
from .spotify_auth import SpotifyAuthManager
from .spotify_cache import SpotifyCacheResolver
from .store import AppStore


@dataclass
class BackendStatus:
    state: str = 'stopped'
    position_sec: float = 0.0
    duration_sec: float = 0.0
    speed: float = 1.0
    direction: str = 'forward'
    volume: int | None = None
    process_alive: bool = False


class PlaybackBackend(Protocol):
    def play_file(self, path: Path, *, volume: int) -> BackendStatus: ...

    def play(self) -> BackendStatus: ...

    def pause(self) -> BackendStatus: ...

    def stop(self) -> BackendStatus: ...

    def set_speed(self, speed: float, *, direction: str | None = None, ramp_ms: int = 0) -> BackendStatus: ...

    def set_volume(self, volume: int) -> BackendStatus: ...

    def status(self) -> BackendStatus: ...


class TwinPeaksBackend:
    def __init__(self, *, socket_path: str = TWINPEAKS_SOCKET, binary_candidates: tuple[str, ...] = TWINPEAKS_BINARY_CANDIDATES) -> None:
        self.socket_path = socket_path
        self.binary_candidates = tuple(str(item).strip() for item in binary_candidates if str(item).strip())
        self._proc: subprocess.Popen[str] | None = None

    def _is_proc_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _cleanup_socket(self) -> None:
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass

    def _resolve_binary(self) -> str:
        for candidate in self.binary_candidates:
            found = shutil.which(candidate)
            if found:
                return found
            path = Path(candidate).expanduser()
            if path.exists():
                return str(path)
        looked = ', '.join(self.binary_candidates) or '(none configured)'
        raise FileNotFoundError(f'twinpeaks binary not found. Looked in: {looked}')

    def _command(self, payload: dict[str, Any]) -> dict[str, Any]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.75)
        try:
            sock.connect(self.socket_path)
            body = json.dumps(payload) + '\n'
            sock.sendall(body.encode('utf-8'))
            data = bytearray()
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data.extend(chunk)
                if b'\n' in chunk:
                    break
        finally:
            sock.close()

        if not data:
            raise RuntimeError('empty response from twinpeaks')
        return json.loads(data.decode('utf-8', errors='ignore').strip())

    def _status_from_response(self, response: dict[str, Any], *, alive: bool) -> BackendStatus:
        payload = response.get('status') if isinstance(response.get('status'), dict) else {}
        state = str(payload.get('state', 'stopped')).strip().lower() or 'stopped'
        direction = str(payload.get('direction', 'forward')).strip().lower() or 'forward'
        try:
            position_sec = max(0.0, float(payload.get('position_sec', 0.0) or 0.0))
        except Exception:
            position_sec = 0.0
        try:
            duration_sec = max(0.0, float(payload.get('duration_sec', 0.0) or 0.0))
        except Exception:
            duration_sec = 0.0
        try:
            speed = max(0.0, float(payload.get('speed', 1.0) or 1.0))
        except Exception:
            speed = 1.0
        try:
            volume = int(round(float(payload.get('volume', 50))))
        except Exception:
            volume = None
        return BackendStatus(
            state=state,
            position_sec=position_sec,
            duration_sec=duration_sec,
            speed=speed,
            direction='reverse' if direction == 'reverse' else 'forward',
            volume=volume,
            process_alive=alive,
        )

    def _expect_ok(self, response: dict[str, Any]) -> BackendStatus:
        status = self._status_from_response(response, alive=self._is_proc_alive())
        if not bool(response.get('ok', False)):
            raise RuntimeError(str(response.get('error') or 'twinpeaks command failed'))
        return status

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + TWINPEAKS_STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(f'twinpeaks exited with code {self._proc.returncode}')
            if os.path.exists(self.socket_path):
                try:
                    self._command({'cmd': 'status'})
                    return
                except Exception:
                    pass
            time.sleep(0.05)
        raise TimeoutError('twinpeaks did not become ready in time')

    def ensure_running(self) -> None:
        if self._is_proc_alive():
            return

        binary = self._resolve_binary()
        self._cleanup_socket()
        env = dict(os.environ)
        env.setdefault('RUST_LOG', 'info')
        self._proc = subprocess.Popen([binary, self.socket_path], env=env)

        try:
            self._wait_until_ready()
        except Exception:
            self.terminate()
            raise

    def play_file(self, path: Path, *, volume: int) -> BackendStatus:
        self.ensure_running()
        self.set_volume(volume)
        response = self._command({'cmd': 'load', 'path': str(path)})
        return self._expect_ok(response)

    def play(self) -> BackendStatus:
        self.ensure_running()
        return self._expect_ok(self._command({'cmd': 'play'}))

    def pause(self) -> BackendStatus:
        self.ensure_running()
        return self._expect_ok(self._command({'cmd': 'pause'}))

    def stop(self) -> BackendStatus:
        if not self._is_proc_alive():
            return BackendStatus(volume=50, process_alive=False)
        return self._expect_ok(self._command({'cmd': 'stop'}))

    def set_speed(self, speed: float, *, direction: str | None = None, ramp_ms: int = 0) -> BackendStatus:
        self.ensure_running()
        payload: dict[str, Any] = {
            'cmd': 'set_speed',
            'speed': float(speed),
            'ramp_ms': max(0, int(ramp_ms)),
        }
        if direction in {'forward', 'reverse'}:
            payload['direction'] = direction
        return self._expect_ok(self._command(payload))

    def set_volume(self, volume: int) -> BackendStatus:
        self.ensure_running()
        payload = {'cmd': 'set_volume', 'volume': max(0, min(200, int(volume)))}
        return self._expect_ok(self._command(payload))

    def status(self) -> BackendStatus:
        if not self._is_proc_alive():
            self._cleanup_socket()
            return BackendStatus(volume=50, process_alive=False)
        try:
            response = self._command({'cmd': 'status'})
        except Exception:
            if not self._is_proc_alive():
                self._cleanup_socket()
                return BackendStatus(volume=50, process_alive=False)
            return BackendStatus(volume=50, process_alive=True)
        return self._status_from_response(response, alive=True)

    def terminate(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            self._cleanup_socket()
            return
        if proc.poll() is None:
            try:
                self._command({'cmd': 'quit'})
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        self._cleanup_socket()


class PlayerManager:
    def __init__(
        self,
        store: AppStore,
        spotify_auth: SpotifyAuthManager,
        *,
        backend: PlaybackBackend | None = None,
    ) -> None:
        self.store = store
        self.spotify_auth = spotify_auth
        self.spotify_cache = SpotifyCacheResolver(store, spotify_auth)
        self.backend = backend or TwinPeaksBackend()
        self._lock = threading.RLock()
        self._queue: list[str] = []
        self._queue_index = -1
        self._queue_source = 'local'
        self._queue_spotify_uri: str | None = None
        self._transport_direction: str | None = None
        self._last_backend_state = 'stopped'
        self._last_process_alive = False
        self.store.update_health(player_backend='twinpeaks', player_backend_running=False)

    def _volume_max(self) -> int:
        value = self.store.get_setting('player_volume_max', 130)
        return max(100, min(200, int(value)))

    def _desired_volume(self) -> int:
        current = self.store.get_player_value('volume', 50)
        try:
            value = int(round(float(current)))
        except Exception:
            value = 50
        return max(0, min(self._volume_max(), value))

    def _build_queue(self, target: Path) -> tuple[list[str], int]:
        if target.is_dir():
            files = [rel_from_abs(path) for path in list_audio_files_recursive(target)]
            if not files:
                raise FileNotFoundError('no audio files in folder')
            return files, 0
        if target.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError(f'unsupported audio file: {target.name}')
        return [rel_from_abs(target)], 0

    def _set_queue_locked(self, queue: list[str], index: int, *, source: str, spotify_uri: str | None) -> None:
        self._queue = list(queue)
        self._queue_index = index
        self._queue_source = source
        self._queue_spotify_uri = spotify_uri
        self._transport_direction = None

    def _clear_queue_locked(self) -> None:
        self._queue = []
        self._queue_index = -1
        self._queue_source = 'local'
        self._queue_spotify_uri = None
        self._transport_direction = None

    def _current_relpath_locked(self) -> str | None:
        if 0 <= self._queue_index < len(self._queue):
            return self._queue[self._queue_index]
        return None

    def _sync_state_locked(
        self,
        status: BackendStatus,
        *,
        keep_file_on_stop: bool = False,
        update_last: bool = True,
    ) -> None:
        current_rel = self._current_relpath_locked()
        keep_file = bool(current_rel and (status.state != 'stopped' or keep_file_on_stop))
        payload: dict[str, Any] = {
            'status': status.state,
            'volume': int(status.volume if status.volume is not None else self._desired_volume()),
            'speed': round(float(status.speed), 3),
            'direction': status.direction,
        }
        if keep_file and current_rel is not None:
            payload.update(
                {
                    'source': self._queue_source,
                    'file': current_rel,
                    'spotify_uri': self._queue_spotify_uri,
                }
            )
        else:
            payload.update(
                {
                    'source': 'local',
                    'file': None,
                    'spotify_uri': None,
                }
            )
        self.store.set_player_state(payload)
        self.store.update_health(player_backend='twinpeaks', player_backend_running=status.process_alive)
        if update_last:
            self._last_backend_state = status.state
            self._last_process_alive = status.process_alive

    def _load_current_locked(self) -> str:
        relpath = self._current_relpath_locked()
        if not relpath:
            raise RuntimeError('no active track selected')
        target = safe_rel_to_abs(relpath)
        status = self.backend.play_file(target, volume=self._desired_volume())
        self._transport_direction = None
        self._sync_state_locked(status, keep_file_on_stop=True)
        return relpath

    def play(self, relpath: str) -> None:
        target = safe_rel_to_abs(relpath)
        if not target.exists():
            raise FileNotFoundError(relpath)

        with self._lock:
            queue, index = self._build_queue(target)
            self._set_queue_locked(queue, index, source='local', spotify_uri=None)
            self._load_current_locked()
            self.store.add_event(f'PLAY {relpath}')

    def play_spotify(self, target: str) -> str:
        self.spotify_auth.get_access_token(force_refresh=False)
        relpath = self.spotify_cache.resolve(target)
        resolved = safe_rel_to_abs(relpath)
        if not resolved.exists():
            raise FileNotFoundError(relpath)

        with self._lock:
            queue, index = self._build_queue(resolved)
            self._set_queue_locked(queue, index, source='spotify', spotify_uri=target)
            self._load_current_locked()
            self.store.add_event(f'SPOTIFY_PLAY {target} -> {relpath}')
            return relpath

    def stop(self) -> None:
        with self._lock:
            try:
                status = self.backend.stop()
            except Exception:
                status = BackendStatus(volume=self._desired_volume(), process_alive=self._last_process_alive)
            self._clear_queue_locked()
            self._sync_state_locked(status)

    def play_pause(self) -> bool:
        with self._lock:
            status = self.backend.status()
            if status.state in {'playing', 'loading'}:
                status = self.backend.pause()
                self._sync_state_locked(status, keep_file_on_stop=True)
                self.store.add_event('PLAY_PAUSE pause')
                return True
            if status.state == 'paused':
                status = self.backend.play()
                self._sync_state_locked(status, keep_file_on_stop=True)
                self.store.add_event('PLAY_PAUSE play')
                return True
            if status.state == 'stopped' and self._current_relpath_locked():
                relpath = self._load_current_locked()
                self.store.add_event(f'PLAY_RESTART {relpath}')
                return True
        return False

    def next(self) -> bool:
        with self._lock:
            relpath = self._current_relpath_locked()
            if not relpath:
                return False
            if self._queue_index + 1 >= len(self._queue):
                self.store.add_event('NEXT end')
                return True
            self._queue_index += 1
            relpath = self._load_current_locked()
            self.store.add_event(f'NEXT {relpath}')
            return True

    def prev(self) -> bool:
        with self._lock:
            relpath = self._current_relpath_locked()
            if not relpath:
                return False
            status = self.backend.status()
            if self._queue_index <= 0 or status.position_sec > 3.0:
                relpath = self._load_current_locked()
                self.store.add_event(f'PREV restart {relpath}')
                return True
            self._queue_index -= 1
            relpath = self._load_current_locked()
            self.store.add_event(f'PREV {relpath}')
            return True

    def add_volume(self, delta: float) -> bool:
        delta_value = float(delta)
        with self._lock:
            status = self.backend.status()
            base = float(status.volume if status.volume is not None else self._desired_volume())
            target = max(0.0, min(float(self._volume_max()), base + delta_value))
            if status.process_alive:
                try:
                    status = self.backend.set_volume(int(round(target)))
                    self._sync_state_locked(
                        status,
                        keep_file_on_stop=bool(self._current_relpath_locked()),
                    )
                except Exception:
                    pass
            self.store.set_player_state({'volume': int(round(target))})
            self.store.add_event(f'VOLUME {delta_value:+.2f} -> {int(round(target))}')
            return True

    def begin_transport(self, *, reverse: bool) -> bool:
        direction = 'reverse' if reverse else 'forward'
        with self._lock:
            if not self._current_relpath_locked():
                return False
            status = self.backend.status()
            if not status.process_alive or status.state == 'stopped':
                return False
            if status.state == 'paused':
                status = self.backend.play()
            status = self.backend.set_speed(
                PLAYER_TRANSPORT_TARGET_SPEED,
                direction=direction,
                ramp_ms=PLAYER_TRANSPORT_RAMP_MS,
            )
            self._transport_direction = direction
            self._sync_state_locked(status, keep_file_on_stop=True)
            self.store.add_event(f'TRANSPORT {direction} -> {PLAYER_TRANSPORT_TARGET_SPEED:.2f}x')
            return True

    def end_transport(self) -> bool:
        with self._lock:
            direction = self._transport_direction
            if direction is None:
                return False
            status = self.backend.status()
            if not status.process_alive:
                self._transport_direction = None
                self._sync_state_locked(status, keep_file_on_stop=bool(self._current_relpath_locked()))
                return False
            if status.process_alive and status.state == 'paused':
                status = self.backend.play()
            status = self.backend.set_speed(
                1.0,
                direction='forward',
                ramp_ms=PLAYER_TRANSPORT_RETURN_MS,
            )
            self._transport_direction = None
            self._sync_state_locked(status, keep_file_on_stop=bool(self._current_relpath_locked()))
            self.store.add_event(f'TRANSPORT release {direction}')
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
            status = self.backend.status()
            previous_state = self._last_backend_state
            previous_alive = self._last_process_alive
            current_rel = self._current_relpath_locked()

            if not status.process_alive:
                self._transport_direction = None
                if previous_alive:
                    self.store.add_event('PLAYER_BACKEND_EXIT')
                self._sync_state_locked(
                    BackendStatus(volume=self._desired_volume(), process_alive=False),
                    keep_file_on_stop=bool(current_rel),
                )
                return

            if (
                status.state == 'stopped'
                and current_rel
                and previous_state in {'playing', 'loading', 'paused'}
                and status.duration_sec > 0.0
                and self._queue_index + 1 < len(self._queue)
            ):
                self._queue_index += 1
                relpath = self._load_current_locked()
                self.store.add_event(f'TRACK_AUTO_NEXT {relpath}')
                return

            keep_file_on_stop = bool(current_rel and status.state == 'stopped')
            self._sync_state_locked(status, keep_file_on_stop=keep_file_on_stop)
