import copy
import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .config import DEFAULT_SETTINGS, EVENTS_MAX, MAPPINGS_PATH, SETTINGS_PATH
from .mappings import normalize_mappings_payload


class AppStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._events: deque[Dict[str, Any]] = deque(maxlen=EVENTS_MAX)
        self._event_id = 0
        self._settings = self._load_settings()
        self.state: Dict[str, Any] = {
            'buttons': [0, 0, 0, 0],
            'rotary_sw': 0,
            'rotary_last': '-',
            'rotary_pos': 0,
            'last_card': None,
            'player': {'status': 'stopped', 'source': 'local', 'file': None, 'spotify_uri': None, 'volume': 50},
            'settings': copy.deepcopy(self._settings),
            'health': {
                'seesaw': False,
                'rfid_device': None,
                'audio_device': None,
                'mpv_running': False,
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

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def _load_settings(self) -> Dict[str, int]:
        settings = dict(DEFAULT_SETTINGS)
        raw = self._load_json(SETTINGS_PATH)
        for key in DEFAULT_SETTINGS:
            if key in raw:
                try:
                    settings[key] = int(raw[key])
                except Exception:
                    pass
        return settings

    def save_settings(self) -> None:
        with self.lock:
            self._write_json(SETTINGS_PATH, self.state['settings'])

    def load_mappings(self) -> Dict[str, Dict[str, str]]:
        raw = self._load_json(MAPPINGS_PATH)
        return normalize_mappings_payload(raw)

    def save_mappings(self, mappings: Dict[str, Any]) -> None:
        self._write_json(MAPPINGS_PATH, normalize_mappings_payload(mappings))

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

    def update_health(self, **kwargs: Any) -> None:
        with self.lock:
            self.state['health'].update(kwargs)

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
