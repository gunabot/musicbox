import copy
import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List

from .config import (
    DB_PATH,
    DEFAULT_SETTINGS,
    EVENTS_MAX,
    MAPPINGS_PATH,
    SETTINGS_PATH,
    SPOTIFY_CACHE_INDEX_PATH,
    SPOTIFY_OAUTH_PATH,
)
from .mappings import normalize_mappings_payload
from .persistence import MusicboxPersistence


class AppStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.persistence = MusicboxPersistence(
            db_path=DB_PATH,
            settings_path=SETTINGS_PATH,
            mappings_path=MAPPINGS_PATH,
            spotify_oauth_path=SPOTIFY_OAUTH_PATH,
            spotify_cache_index_path=SPOTIFY_CACHE_INDEX_PATH,
        )
        self.persistence.migrate_legacy_json(archive=False)
        self._events: deque[Dict[str, Any]] = deque(maxlen=EVENTS_MAX)
        self._event_id = 0
        self._mappings_cache: Dict[str, Dict[str, str]] | None = None
        self._settings = self._load_settings()
        self.state: Dict[str, Any] = {
            'buttons': [0, 0, 0, 0],
            'rotary_sw': 0,
            'rotary_last': '-',
            'rotary_pos': 0,
            'last_card': None,
            'player': {
                'status': 'stopped',
                'source': 'local',
                'file': None,
                'spotify_uri': None,
                'volume': 50,
                'speed': 1.0,
                'direction': 'forward',
            },
            'settings': copy.deepcopy(self._settings),
            'health': {
                'seesaw': False,
                'rfid_device': None,
                'audio_device': None,
                'player_backend': 'twinpeaks',
                'player_backend_running': False,
                'ups_connected': False,
                'battery_percent': None,
                'battery_voltage': None,
                'battery_current_ma': None,
                'battery_power_w': None,
                'battery_charging': None,
                'cpu_temp_c': None,
                'uptime_s': None,
                'disk_total_bytes': None,
                'disk_free_bytes': None,
                'disk_used_pct': None,
                'load_1': None,
                'load_5': None,
                'load_15': None,
            },
        }

    def _load_settings(self) -> Dict[str, int]:
        return self.persistence.load_settings(DEFAULT_SETTINGS)

    def save_settings(self) -> None:
        with self.lock:
            self.persistence.save_settings(self.state['settings'])

    def load_mappings(self, *, use_cache: bool = False) -> Dict[str, Dict[str, str]]:
        with self.lock:
            if use_cache and self._mappings_cache is not None:
                return copy.deepcopy(self._mappings_cache)
            mappings = self.persistence.load_mappings()
            self._mappings_cache = mappings
            return copy.deepcopy(mappings)

    def save_mappings(self, mappings: Dict[str, Any]) -> None:
        normalized = normalize_mappings_payload(mappings)
        with self.lock:
            self.persistence.save_mappings(normalized)
            self._mappings_cache = normalized

    def _new_event(self, message: str, level: str = 'info') -> Dict[str, Any]:
        self._event_id += 1
        event = {
            'id': self._event_id,
            'ts': datetime.now().strftime('%H:%M:%S'),
            'msg': message,
            'level': level,
        }
        self._events.append(event)
        return event

    def add_event(self, message: str, level: str = 'info') -> Dict[str, Any]:
        with self.lock:
            return self._new_event(message, level)

    def set_buttons(self, buttons: List[int]) -> None:
        with self.lock:
            self.state['buttons'] = list(buttons)

    def set_rotary(self, *, sw: int | None = None, direction: str | None = None, pos_delta: int = 0) -> None:
        with self.lock:
            if sw is not None:
                self.state['rotary_sw'] = 1 if sw else 0
            if direction is not None:
                self.state['rotary_last'] = direction
            if pos_delta:
                self.state['rotary_pos'] += int(pos_delta)

    def set_last_card(self, card: str | None) -> None:
        with self.lock:
            self.state['last_card'] = card

    def set_player_state(self, payload: Dict[str, Any]) -> None:
        with self.lock:
            current = dict(self.state.get('player', {}))
            current.update(payload)
            self.state['player'] = current

    def get_player_value(self, key: str, default: Any = None) -> Any:
        with self.lock:
            player = self.state.get('player')
            if not isinstance(player, dict):
                return default
            return player.get(key, default)

    def update_health(self, **kwargs: Any) -> None:
        with self.lock:
            self.state['health'].update(kwargs)

    def get_health_value(self, key: str, default: Any = None) -> Any:
        with self.lock:
            health = self.state.get('health')
            if not isinstance(health, dict):
                return default
            return health.get(key, default)

    def set_setting(self, key: str, value: int) -> None:
        with self.lock:
            self.state['settings'][key] = int(value)

    def get_setting(self, key: str, default: int) -> int:
        with self.lock:
            try:
                return int(self.state['settings'].get(key, default))
            except Exception:
                return default

    def snapshot(self, since_id: int = 0, event_limit: int = 80) -> Dict[str, Any]:
        with self.lock:
            if since_id > 0:
                events = [ev for ev in self._events if ev['id'] > since_id]
            else:
                events = list(self._events)[-event_limit:]
            return {
                'buttons': list(self.state['buttons']),
                'rotary_sw': self.state['rotary_sw'],
                'rotary_last': self.state['rotary_last'],
                'rotary_pos': self.state['rotary_pos'],
                'last_card': self.state['last_card'],
                'player': copy.deepcopy(self.state['player']),
                'settings': copy.deepcopy(self.state['settings']),
                'health': copy.deepcopy(self.state['health']),
                'events': events,
                'last_event_id': self._event_id,
            }
