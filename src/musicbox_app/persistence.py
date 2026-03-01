import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .mappings import normalize_mappings_payload


class MusicboxPersistence:
    def __init__(
        self,
        *,
        db_path: Path,
        settings_path: Path,
        mappings_path: Path,
        spotify_oauth_path: Path,
        spotify_cache_index_path: Path,
    ) -> None:
        self.db_path = db_path
        self.settings_path = settings_path
        self.mappings_path = mappings_path
        self.spotify_oauth_path = spotify_oauth_path
        self.spotify_cache_index_path = spotify_cache_index_path
        self._lock = threading.RLock()
        self._conn = self._open()
        self._setup_schema()
        self._bootstrapped: set[str] = set()

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Keep sync safety while avoiding extra WAL files on SD by default.
        conn.execute('PRAGMA journal_mode=TRUNCATE')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _setup_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                '''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mappings (
                    card TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS spotify_oauth (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS spotify_cache (
                    uri TEXT PRIMARY KEY,
                    relpath TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                '''
            )
            self._conn.commit()

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _archive_legacy_file(self, path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        stamp = time.strftime('%Y%m%d-%H%M%S')
        archived = path.with_name(f'{path.name}.legacy-migrated-{stamp}.json')
        index = 1
        while archived.exists():
            archived = path.with_name(f'{path.name}.legacy-migrated-{stamp}-{index}.json')
            index += 1
        path.replace(archived)
        return True

    def migrate_legacy_json(self, *, archive: bool = True) -> Dict[str, int]:
        stats = {
            'settings_upserts': 0,
            'mappings_upserts': 0,
            'oauth_upserts': 0,
            'cache_upserts': 0,
            'files_archived': 0,
        }
        with self._lock:
            settings = self._read_json(self.settings_path)
            if settings:
                rows = []
                for key, value in settings.items():
                    try:
                        rows.append((str(key), str(int(value))))
                    except Exception:
                        continue
                if rows:
                    self._conn.executemany(
                        'INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)',
                        rows,
                    )
                    stats['settings_upserts'] = len(rows)

            mappings = normalize_mappings_payload(self._read_json(self.mappings_path))
            if mappings:
                now = int(time.time())
                rows = [(card, row['type'], row['target'], now) for card, row in mappings.items()]
                self._conn.executemany(
                    'INSERT OR REPLACE INTO mappings(card, type, target, updated_at) VALUES (?, ?, ?, ?)',
                    rows,
                )
                stats['mappings_upserts'] = len(rows)

            oauth = self._read_json(self.spotify_oauth_path)
            if oauth:
                row = self._conn.execute('SELECT payload FROM spotify_oauth WHERE id = 1').fetchone()
                current: Dict[str, Any] = {}
                if row is not None:
                    try:
                        maybe = json.loads(str(row['payload']))
                        if isinstance(maybe, dict):
                            current = maybe
                    except Exception:
                        current = {}
                merged = dict(current)
                for key, value in oauth.items():
                    if value is None:
                        continue
                    merged[key] = value
                self._conn.execute(
                    'INSERT OR REPLACE INTO spotify_oauth(id, payload, updated_at) VALUES (1, ?, ?)',
                    (json.dumps(merged, sort_keys=True), int(time.time())),
                )
                stats['oauth_upserts'] = 1

            cache = self._read_json(self.spotify_cache_index_path)
            if cache:
                now = int(time.time())
                rows = []
                for uri, value in cache.items():
                    if not isinstance(value, dict):
                        continue
                    key = str(uri).strip()
                    relpath = str(value.get('relpath', '')).strip()
                    updated_at = int(value.get('updated_at', now) or now)
                    if not key or not relpath:
                        continue
                    rows.append((key, relpath, updated_at))
                if rows:
                    self._conn.executemany(
                        'INSERT OR REPLACE INTO spotify_cache(uri, relpath, updated_at) VALUES (?, ?, ?)',
                        rows,
                    )
                    stats['cache_upserts'] = len(rows)

            self._conn.commit()

            if archive:
                for path in (
                    self.settings_path,
                    self.mappings_path,
                    self.spotify_oauth_path,
                    self.spotify_cache_index_path,
                ):
                    if self._archive_legacy_file(path):
                        stats['files_archived'] += 1

            self._bootstrapped.update({'settings', 'mappings', 'spotify_oauth', 'spotify_cache'})
        return stats

    def _bootstrap_once(self, key: str, fn) -> None:
        if key in self._bootstrapped:
            return
        fn()
        self._bootstrapped.add(key)

    def _bootstrap_spotify_cache_locked(self) -> None:
        if 'spotify_cache' in self._bootstrapped:
            return
        count = int(self._conn.execute('SELECT COUNT(*) FROM spotify_cache').fetchone()[0])
        if count == 0:
            raw = self._read_json(self.spotify_cache_index_path)
            now = int(time.time())
            rows = []
            for uri, value in raw.items():
                if not isinstance(value, dict):
                    continue
                uri_text = str(uri).strip()
                relpath = str(value.get('relpath', '')).strip()
                updated_at = int(value.get('updated_at', now) or now)
                if not uri_text or not relpath:
                    continue
                rows.append((uri_text, relpath, updated_at))
            self._conn.executemany(
                'INSERT OR REPLACE INTO spotify_cache(uri, relpath, updated_at) VALUES (?, ?, ?)',
                rows,
            )
            self._conn.commit()
        self._bootstrapped.add('spotify_cache')

    def load_settings(self, defaults: Dict[str, int]) -> Dict[str, int]:
        with self._lock:
            def bootstrap() -> None:
                count = int(self._conn.execute('SELECT COUNT(*) FROM settings').fetchone()[0])
                if count > 0:
                    return
                raw = self._read_json(self.settings_path)
                merged = dict(defaults)
                for key in defaults:
                    if key in raw:
                        try:
                            merged[key] = int(raw[key])
                        except Exception:
                            continue
                self._conn.executemany(
                    'INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)',
                    [(str(key), str(int(value))) for key, value in merged.items()],
                )
                self._conn.commit()

            self._bootstrap_once('settings', bootstrap)

            out = dict(defaults)
            rows = self._conn.execute('SELECT key, value FROM settings').fetchall()
            for row in rows:
                key = str(row['key'])
                try:
                    out[key] = int(str(row['value']))
                except Exception:
                    continue
            return out

    def save_settings(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            items: Dict[str, int] = {}
            for key, value in dict(payload or {}).items():
                try:
                    items[str(key)] = int(value)
                except Exception:
                    continue
            self._conn.execute('BEGIN')
            try:
                for key, value in items.items():
                    self._conn.execute(
                        'INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)',
                        (key, str(int(value))),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def load_mappings(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            def bootstrap() -> None:
                count = int(self._conn.execute('SELECT COUNT(*) FROM mappings').fetchone()[0])
                if count > 0:
                    return
                raw = self._read_json(self.mappings_path)
                normalized = normalize_mappings_payload(raw)
                now = int(time.time())
                self._conn.executemany(
                    'INSERT OR REPLACE INTO mappings(card, type, target, updated_at) VALUES (?, ?, ?, ?)',
                    [(card, row['type'], row['target'], now) for card, row in normalized.items()],
                )
                self._conn.commit()

            self._bootstrap_once('mappings', bootstrap)

            out: Dict[str, Dict[str, str]] = {}
            rows = self._conn.execute('SELECT card, type, target FROM mappings ORDER BY card').fetchall()
            for row in rows:
                card = str(row['card']).strip()
                mapping_type = str(row['type']).strip().lower() or 'local'
                target = str(row['target']).strip()
                if not card or not target:
                    continue
                out[card] = {'type': mapping_type, 'target': target}
            return normalize_mappings_payload(out)

    def save_mappings(self, mappings: Dict[str, Any]) -> None:
        normalized = normalize_mappings_payload(mappings)
        now = int(time.time())
        with self._lock:
            self._conn.execute('BEGIN')
            try:
                self._conn.execute('DELETE FROM mappings')
                self._conn.executemany(
                    'INSERT INTO mappings(card, type, target, updated_at) VALUES (?, ?, ?, ?)',
                    [(card, row['type'], row['target'], now) for card, row in normalized.items()],
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def load_spotify_oauth(self) -> Dict[str, Any]:
        with self._lock:
            def bootstrap() -> None:
                row = self._conn.execute('SELECT payload FROM spotify_oauth WHERE id = 1').fetchone()
                if row is not None:
                    return
                raw = self._read_json(self.spotify_oauth_path)
                payload = raw if isinstance(raw, dict) else {}
                now = int(time.time())
                self._conn.execute(
                    'INSERT OR REPLACE INTO spotify_oauth(id, payload, updated_at) VALUES (1, ?, ?)',
                    (json.dumps(payload, sort_keys=True), now),
                )
                self._conn.commit()

            self._bootstrap_once('spotify_oauth', bootstrap)

            row = self._conn.execute('SELECT payload FROM spotify_oauth WHERE id = 1').fetchone()
            if row is None:
                return {}
            try:
                payload = json.loads(str(row['payload']))
            except Exception:
                return {}
            return payload if isinstance(payload, dict) else {}

    def save_spotify_oauth(self, payload: Dict[str, Any]) -> None:
        data = payload if isinstance(payload, dict) else {}
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                'INSERT OR REPLACE INTO spotify_oauth(id, payload, updated_at) VALUES (1, ?, ?)',
                (json.dumps(data, sort_keys=True), now),
            )
            self._conn.commit()

    def load_spotify_cache_index(self) -> Dict[str, Any]:
        with self._lock:
            self._bootstrap_spotify_cache_locked()
            return self._spotify_cache_dict_locked()

    def _spotify_cache_dict_locked(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        rows = self._conn.execute('SELECT uri, relpath, updated_at FROM spotify_cache ORDER BY uri').fetchall()
        for row in rows:
            uri = str(row['uri']).strip()
            relpath = str(row['relpath']).strip()
            if not uri or not relpath:
                continue
            out[uri] = {
                'relpath': relpath,
                'updated_at': int(row['updated_at'] or 0),
            }
        return out

    def get_spotify_cache(self, uri: str) -> Dict[str, Any] | None:
        key = str(uri or '').strip()
        if not key:
            return None
        with self._lock:
            self._bootstrap_spotify_cache_locked()
            row = self._conn.execute(
                'SELECT relpath, updated_at FROM spotify_cache WHERE uri = ?',
                (key,),
            ).fetchone()
            if row is None:
                return None
            relpath = str(row['relpath']).strip()
            if not relpath:
                return None
            return {
                'relpath': relpath,
                'updated_at': int(row['updated_at'] or 0),
            }

    def set_spotify_cache(self, uri: str, *, relpath: str, updated_at: int | None = None) -> None:
        key = str(uri or '').strip()
        rel = str(relpath or '').strip()
        if not key or not rel:
            return
        ts = int(updated_at or int(time.time()))
        with self._lock:
            self._bootstrap_spotify_cache_locked()
            self._conn.execute(
                'INSERT OR REPLACE INTO spotify_cache(uri, relpath, updated_at) VALUES (?, ?, ?)',
                (key, rel, ts),
            )
            self._conn.commit()

    def save_spotify_cache_index(self, payload: Dict[str, Any]) -> None:
        data = payload if isinstance(payload, dict) else {}
        now = int(time.time())
        with self._lock:
            self._conn.execute('BEGIN')
            try:
                self._conn.execute('DELETE FROM spotify_cache')
                rows = []
                for uri, value in data.items():
                    if not isinstance(value, dict):
                        continue
                    key = str(uri).strip()
                    rel = str(value.get('relpath', '')).strip()
                    ts = int(value.get('updated_at', now) or now)
                    if not key or not rel:
                        continue
                    rows.append((key, rel, ts))
                self._conn.executemany(
                    'INSERT INTO spotify_cache(uri, relpath, updated_at) VALUES (?, ?, ?)',
                    rows,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
