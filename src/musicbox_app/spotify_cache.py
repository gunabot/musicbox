import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .config import MEDIA_DIR, SPOTIFY_CACHE_DIR, SPOTIFY_CACHE_INDEX_PATH, SPOTIFY_FETCH_COMMAND, SPOTIFY_OAUTH_PATH
from .mappings import normalize_spotify_target
from .spotify_auth import SpotifyAuthManager
from .store import AppStore


class SpotifyCacheResolver:
    def __init__(self, store: AppStore, spotify_auth: SpotifyAuthManager) -> None:
        self.store = store
        self.spotify_auth = spotify_auth
        self.cache_dir = SPOTIFY_CACHE_DIR
        self.index_path = SPOTIFY_CACHE_INDEX_PATH
        self.fetch_command = SPOTIFY_FETCH_COMMAND
        self._lock = threading.RLock()

    def _load_index(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text())
        except Exception:
            return {}

    def _save_index(self, payload: Dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

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
        return [*parts, uri, str(self.cache_dir), str(MEDIA_DIR)]

    def _build_env(self) -> Dict[str, str]:
        status = self.spotify_auth.status()
        env = dict(os.environ)
        env['MUSICBOX_SPOTIFY_OAUTH_PATH'] = str(SPOTIFY_OAUTH_PATH)
        env['MUSICBOX_SPOTIFY_CACHE_INDEX_PATH'] = str(self.index_path)
        env['MUSICBOX_SPOTIFY_CACHE_DIR'] = str(self.cache_dir)
        env['MUSICBOX_SPOTIFY_MEDIA_DIR'] = str(MEDIA_DIR)
        env['MUSICBOX_SPOTIFY_DEVICE_NAME'] = str(status.get('device_name', '') or '')
        return env

    def resolve(self, target: str) -> str:
        uri = normalize_spotify_target(target)

        with self._lock:
            index = self._load_index()
            existing = index.get(uri, {})
            relpath = str(existing.get('relpath', '')).strip()
            if relpath:
                try:
                    resolved = self._safe_relpath(relpath)
                    self.store.add_event(f'SPOTIFY_CACHE_HIT {uri} -> {resolved}')
                    return resolved
                except Exception:
                    pass

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cmd = self._build_cmd(uri)
        self.store.add_event(f'SPOTIFY_CACHE_MISS {uri}')
        proc = subprocess.run(cmd, text=True, capture_output=True, env=self._build_env())
        if proc.returncode != 0:
            stderr = (proc.stderr or '').strip()
            raise RuntimeError(stderr or f'fetch command failed with code {proc.returncode}')

        lines = [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]
        if not lines:
            raise RuntimeError('fetch command returned no path')

        relpath = self._safe_relpath(lines[-1])

        with self._lock:
            index = self._load_index()
            index[uri] = {
                'relpath': relpath,
                'updated_at': int(time.time()),
            }
            self._save_index(index)

        self.store.add_event(f'SPOTIFY_CACHE_WRITE {uri} -> {relpath}')
        return relpath
