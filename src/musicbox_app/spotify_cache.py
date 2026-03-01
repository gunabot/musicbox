import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .config import (
    MEDIA_DIR,
    SPOTIFY_CACHE_BITRATE,
    SPOTIFY_CACHE_DIR,
    SPOTIFY_CACHE_FORMAT,
    SPOTIFY_CACHE_INDEX_PATH,
    SPOTIFY_FETCH_COMMAND,
    SPOTIFY_OAUTH_PATH,
)
from .mappings import normalize_spotify_target
from .spotify_auth import SpotifyAuthManager
from .store import AppStore


class SpotifyCacheResolver:
    def __init__(self, store: AppStore, spotify_auth: SpotifyAuthManager) -> None:
        self.store = store
        self.spotify_auth = spotify_auth
        self.persistence = store.persistence
        self.import_root = SPOTIFY_CACHE_DIR
        self.index_path = SPOTIFY_CACHE_INDEX_PATH
        self.fetch_command = SPOTIFY_FETCH_COMMAND
        self._lock = threading.RLock()
        self._fetch_lock = threading.Lock()

    def _safe_relpath(self, path_value: str) -> str:
        path = Path(path_value)
        if not path.is_absolute():
            path = (MEDIA_DIR / path).resolve()
        else:
            path = path.resolve()

        media_root = MEDIA_DIR.resolve()
        try:
            rel = path.relative_to(media_root)
        except Exception:
            raise ValueError(f'path is outside media root: {path}')

        if not path.exists():
            raise FileNotFoundError(path)

        return str(rel)

    def _build_cmd(self, uri: str) -> list[str]:
        command = (self.fetch_command or '').strip()
        if not command:
            raise RuntimeError('spotify fetch command is not configured')
        parts = shlex.split(command)
        if not parts:
            raise RuntimeError('spotify fetch command is empty')
        return [*parts, uri, str(self.import_root), str(MEDIA_DIR)]

    def _build_env(self, *, access_token: str, expires_at: int) -> Dict[str, str]:
        status = self.spotify_auth.status()
        env = dict(os.environ)
        env['MUSICBOX_SPOTIFY_OAUTH_PATH'] = str(SPOTIFY_OAUTH_PATH)
        env['MUSICBOX_SPOTIFY_CACHE_INDEX_PATH'] = str(self.index_path)
        env['MUSICBOX_SPOTIFY_CACHE_DIR'] = str(self.import_root)
        env['MUSICBOX_SPOTIFY_IMPORT_ROOT'] = str(self.import_root)
        env['MUSICBOX_SPOTIFY_MEDIA_DIR'] = str(MEDIA_DIR)
        env['MUSICBOX_SPOTIFY_DEVICE_NAME'] = str(status.get('device_name', '') or '')
        env['MUSICBOX_SPOTIFY_CACHE_FORMAT'] = str(SPOTIFY_CACHE_FORMAT)
        env['MUSICBOX_SPOTIFY_CACHE_BITRATE'] = str(SPOTIFY_CACHE_BITRATE)
        env['MUSICBOX_SPOTIFY_ACCESS_TOKEN'] = str(access_token or '').strip()
        env['MUSICBOX_SPOTIFY_ACCESS_EXPIRES_AT'] = str(int(expires_at or 0))
        # Keep token lifecycle centralized in the web service. The fetch worker
        # consumes a provided access token and does not refresh/write OAuth state.
        env['MUSICBOX_SPOTIFY_ENABLE_REFRESH'] = '0'
        env['MUSICBOX_SPOTIFY_MIN_ACCESS_TTL_SECONDS'] = '15'
        return env

    def resolve(self, target: str, *, refresh: bool = False) -> str:
        uri = normalize_spotify_target(target)
        media_type = uri.split(':', 2)[1] if uri.count(':') >= 2 else ''
        refresh_playlist = bool(refresh and media_type == 'playlist')

        if not refresh_playlist:
            cached = self.persistence.get_spotify_cache(uri)
            relpath = str((cached or {}).get('relpath', '')).strip()
            if relpath:
                try:
                    resolved = self._safe_relpath(relpath)
                    self.store.add_event(f'SPOTIFY_CACHE_HIT {uri} -> {resolved}')
                    return resolved
                except Exception:
                    pass

        with self._fetch_lock:
            # Another thread may have completed this while we waited.
            if not refresh_playlist:
                cached = self.persistence.get_spotify_cache(uri)
                relpath = str((cached or {}).get('relpath', '')).strip()
                if relpath:
                    try:
                        resolved = self._safe_relpath(relpath)
                        self.store.add_event(f'SPOTIFY_CACHE_HIT {uri} -> {resolved}')
                        return resolved
                    except Exception:
                        pass

            self.import_root.mkdir(parents=True, exist_ok=True)
            cmd = self._build_cmd(uri)
            token_ctx = self.spotify_auth.get_access_context(force_refresh=True, min_ttl_seconds=300)
            access_token = str(token_ctx.get('access_token', '')).strip()
            expires_at = int(token_ctx.get('expires_at', 0) or 0)
            if not access_token:
                raise RuntimeError('Spotify access token unavailable. Please reconnect Spotify.')
            self.store.add_event(f'SPOTIFY_CACHE_MISS {uri}')
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                env=self._build_env(access_token=access_token, expires_at=expires_at),
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or '').strip()
                raise RuntimeError(stderr or f'fetch command failed with code {proc.returncode}')

            lines = [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]
            if not lines:
                raise RuntimeError('fetch command returned no path')

            relpath = self._safe_relpath(lines[-1])

            self.persistence.set_spotify_cache(uri, relpath=relpath, updated_at=int(time.time()))

        self.store.add_event(f'SPOTIFY_CACHE_WRITE {uri} -> {relpath}')
        return relpath
