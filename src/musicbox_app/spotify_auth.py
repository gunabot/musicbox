import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import SPOTIFY_CAPTURE_DEVICE_NAME, SPOTIFY_OAUTH_PATH, SPOTIFY_SCOPE
from .store import AppStore

_AUTH_URL = 'https://accounts.spotify.com/authorize'
_TOKEN_URL = 'https://accounts.spotify.com/api/token'
_API_BASE = 'https://api.spotify.com/v1'


class SpotifyAuthManager:
    def __init__(self, store: AppStore) -> None:
        self.store = store
        self.path = SPOTIFY_OAUTH_PATH
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def _save(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def _http_json(
        self,
        method: str,
        url: str,
        *,
        headers: Dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: int = 20,
    ) -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(url=url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            status = int(exc.code)
        except Exception as exc:
            return 599, {'error': str(exc)}

        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {'raw': body}
        return status, payload

    def _now(self) -> int:
        return int(time.time())

    def _refresh_with_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(payload.get('client_id', '')).strip()
        refresh_token = str(payload.get('refresh_token', '')).strip()
        if not client_id or not refresh_token:
            raise RuntimeError('spotify refresh token is missing')

        form = urllib.parse.urlencode(
            {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': client_id,
            }
        ).encode('utf-8')
        status, data = self._http_json(
            'POST',
            _TOKEN_URL,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form,
        )
        if status >= 300:
            raise RuntimeError(data.get('error_description') or data.get('error') or f'token refresh failed ({status})')

        access_token = str(data.get('access_token', '')).strip()
        if not access_token:
            raise RuntimeError('token refresh response did not include access_token')
        expires_in = int(data.get('expires_in', 3600))
        payload['access_token'] = access_token
        payload['expires_at'] = self._now() + max(60, expires_in - 15)
        if data.get('refresh_token'):
            if str(payload.get('refresh_token', '')).strip():
                payload['refresh_token_prev'] = str(payload.get('refresh_token', '')).strip()
            payload['refresh_token'] = str(data['refresh_token'])
        payload['token_type'] = str(data.get('token_type', payload.get('token_type', 'Bearer')))
        payload['updated_at'] = self._now()
        return payload

    def _is_revoked_refresh_error(self, message: str) -> bool:
        text = str(message or '').strip().lower()
        if not text:
            return False
        return 'invalid_grant' in text or 'refresh token revoked' in text or 'revoked' in text

    def set_client_id(self, client_id: str) -> Dict[str, Any]:
        value = str(client_id or '').strip()
        if not value:
            raise ValueError('spotify client id required')
        with self._lock:
            payload = self._load()
            old = str(payload.get('client_id', '')).strip()
            payload['client_id'] = value
            if old and old != value:
                for key in ['access_token', 'refresh_token', 'expires_at', 'token_type', 'scope', 'profile', 'pending']:
                    payload.pop(key, None)
            payload.setdefault('device_name', SPOTIFY_CAPTURE_DEVICE_NAME)
            payload['updated_at'] = self._now()
            self._save(payload)
        self.store.add_event('SPOTIFY_CLIENT_ID_SET')
        return self.status()

    def set_device_name(self, device_name: str) -> Dict[str, Any]:
        value = str(device_name or '').strip()
        if not value:
            raise ValueError('spotify device name required')
        with self._lock:
            payload = self._load()
            payload.setdefault('client_id', '')
            payload['device_name'] = value
            payload['updated_at'] = self._now()
            self._save(payload)
        self.store.add_event(f'SPOTIFY_DEVICE_SET {value}')
        return self.status()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
        now = self._now()
        expires_at = int(payload.get('expires_at', 0) or 0)
        connected = bool(payload.get('refresh_token'))
        access_valid = bool(payload.get('access_token')) and expires_at > now + 30
        client_id = str(payload.get('client_id', '')).strip()
        profile = payload.get('profile') if isinstance(payload.get('profile'), dict) else {}
        scope = str(payload.get('scope', '')).strip()
        scope_items = {item.strip() for item in scope.split(' ') if item.strip()}
        return {
            'configured': bool(client_id),
            'connected': connected,
            'access_valid': access_valid,
            'client_id_set': bool(client_id),
            'client_id': client_id,
            'device_name': str(payload.get('device_name', SPOTIFY_CAPTURE_DEVICE_NAME)),
            'expires_at': expires_at or None,
            'scope': scope,
            'has_streaming_scope': 'streaming' in scope_items,
            'user': {
                'id': str(profile.get('id', '')).strip() or None,
                'display_name': str(profile.get('display_name', '')).strip() or None,
                'country': str(profile.get('country', '')).strip() or None,
                'product': str(profile.get('product', '')).strip() or None,
            },
        }

    def start_login(self, host_url: str) -> str:
        host = str(host_url or '').strip()
        if not host:
            raise ValueError('host_url required')
        host = host.rstrip('/')
        with self._lock:
            payload = self._load()
            client_id = str(payload.get('client_id', '')).strip()
            if not client_id:
                raise ValueError('spotify client id is not configured')

            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('utf-8')).digest()).decode('ascii').rstrip('=')
            state = secrets.token_urlsafe(32)
            redirect_uri = f'{host}/api/spotify/callback'
            payload['pending'] = {
                'state': state,
                'code_verifier': verifier,
                'redirect_uri': redirect_uri,
                'created_at': self._now(),
            }
            payload.setdefault('device_name', SPOTIFY_CAPTURE_DEVICE_NAME)
            payload['updated_at'] = self._now()
            self._save(payload)

        query = urllib.parse.urlencode(
            {
                'client_id': client_id,
                'response_type': 'code',
                'redirect_uri': redirect_uri,
                'code_challenge_method': 'S256',
                'code_challenge': challenge,
                'scope': SPOTIFY_SCOPE,
                'state': state,
                'show_dialog': 'true',
            }
        )
        self.store.add_event('SPOTIFY_LOGIN_STARTED')
        return f'{_AUTH_URL}?{query}'

    def _fetch_profile(self, access_token: str) -> Dict[str, Any]:
        status, payload = self._http_json(
            'GET',
            f'{_API_BASE}/me',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if status >= 300:
            return {}
        return payload if isinstance(payload, dict) else {}

    def handle_callback(self, *, code: str, state: str) -> Dict[str, Any]:
        code = str(code or '').strip()
        state = str(state or '').strip()
        if not code:
            raise ValueError('spotify callback missing code')
        if not state:
            raise ValueError('spotify callback missing state')

        with self._lock:
            payload = self._load()
            client_id = str(payload.get('client_id', '')).strip()
            pending = payload.get('pending') if isinstance(payload.get('pending'), dict) else {}
            expected_state = str(pending.get('state', '')).strip()
            verifier = str(pending.get('code_verifier', '')).strip()
            redirect_uri = str(pending.get('redirect_uri', '')).strip()

            if not client_id:
                raise RuntimeError('spotify client id is not configured')
            if not pending or not expected_state or not verifier or not redirect_uri:
                raise RuntimeError('spotify login session is missing or expired')
            if expected_state != state:
                raise RuntimeError('spotify state mismatch')

            form = urllib.parse.urlencode(
                {
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri,
                    'client_id': client_id,
                    'code_verifier': verifier,
                }
            ).encode('utf-8')

            status, data = self._http_json(
                'POST',
                _TOKEN_URL,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=form,
            )
            if status >= 300:
                raise RuntimeError(data.get('error_description') or data.get('error') or f'token exchange failed ({status})')

            access_token = str(data.get('access_token', '')).strip()
            refresh_token = str(data.get('refresh_token', '')).strip()
            if not access_token or not refresh_token:
                raise RuntimeError('spotify token response missing access or refresh token')

            expires_in = int(data.get('expires_in', 3600))
            payload['access_token'] = access_token
            payload['refresh_token'] = refresh_token
            payload['expires_at'] = self._now() + max(60, expires_in - 15)
            payload['token_type'] = str(data.get('token_type', 'Bearer'))
            payload['scope'] = str(data.get('scope', SPOTIFY_SCOPE))
            payload.pop('pending', None)
            profile = self._fetch_profile(access_token)
            if profile:
                payload['profile'] = profile
            payload.setdefault('device_name', SPOTIFY_CAPTURE_DEVICE_NAME)
            payload['updated_at'] = self._now()
            self._save(payload)

        display_name = str(payload.get('profile', {}).get('display_name', '')).strip() if isinstance(payload.get('profile'), dict) else ''
        self.store.add_event(f"SPOTIFY_LOGIN_OK user={display_name or 'unknown'}")
        return self.status()

    def disconnect(self) -> Dict[str, Any]:
        with self._lock:
            payload = self._load()
            for key in ['access_token', 'refresh_token', 'expires_at', 'token_type', 'scope', 'profile', 'pending']:
                payload.pop(key, None)
            payload['updated_at'] = self._now()
            self._save(payload)
        self.store.add_event('SPOTIFY_DISCONNECTED')
        return self.status()

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        context = self.get_access_context(force_refresh=force_refresh)
        return str(context.get('access_token', '')).strip()

    def get_access_context(
        self,
        *,
        force_refresh: bool = False,
        min_ttl_seconds: int = 30,
    ) -> Dict[str, Any]:
        ttl = max(5, int(min_ttl_seconds))
        with self._lock:
            payload = self._load()
            access_token = str(payload.get('access_token', '')).strip()
            expires_at = int(payload.get('expires_at', 0) or 0)
            now = self._now()
            if access_token and not force_refresh and expires_at > now + ttl:
                return {
                    'access_token': access_token,
                    'expires_at': expires_at,
                }

            attempted_refresh = str(payload.get('refresh_token', '')).strip()
            try:
                payload = self._refresh_with_payload(payload)
            except Exception as exc:
                message = str(exc).strip()
                if self._is_revoked_refresh_error(message):
                    # A concurrent writer could have rotated the refresh token.
                    # Try once with the latest on-disk token (or backup token)
                    # before declaring the auth session dead.
                    latest = self._load()
                    latest_refresh = str(latest.get('refresh_token', '')).strip()
                    backup_refresh = str(latest.get('refresh_token_prev', '')).strip()
                    candidates = []
                    if latest_refresh and latest_refresh != attempted_refresh:
                        candidates.append(latest_refresh)
                    if backup_refresh and backup_refresh not in candidates and backup_refresh != attempted_refresh:
                        candidates.append(backup_refresh)

                    for candidate in candidates:
                        probe = dict(latest)
                        probe['refresh_token'] = candidate
                        try:
                            probe = self._refresh_with_payload(probe)
                        except Exception:
                            continue
                        self._save(probe)
                        self.store.add_event('SPOTIFY_TOKEN_REFRESH_RECOVERED')
                        return {
                            'access_token': str(probe.get('access_token', '')).strip(),
                            'expires_at': int(probe.get('expires_at', 0) or 0),
                        }

                    for key in ['access_token', 'refresh_token', 'expires_at', 'token_type', 'scope', 'profile', 'pending']:
                        payload.pop(key, None)
                    payload['updated_at'] = self._now()
                    self._save(payload)
                    self.store.add_event('SPOTIFY_REFRESH_REVOKED reconnect required', level='error')
                    raise RuntimeError('Spotify authorization expired. Please reconnect Spotify in Settings.')
                raise

            self._save(payload)
            self.store.add_event('SPOTIFY_TOKEN_REFRESHED')
            return {
                'access_token': str(payload.get('access_token', '')).strip(),
                'expires_at': int(payload.get('expires_at', 0) or 0),
            }

    def spotify_api_request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
    ) -> Tuple[int, Dict[str, Any]]:
        if path.startswith('http://') or path.startswith('https://'):
            url = path
        else:
            url = f'{_API_BASE}{path}'
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            url = f'{url}?{query}'

        token = self.get_access_token(force_refresh=False)
        headers = {'Authorization': f'Bearer {token}'}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        status, payload = self._http_json(method.upper(), url, headers=headers, data=data)
        if status == 401:
            token = self.get_access_token(force_refresh=True)
            headers['Authorization'] = f'Bearer {token}'
            status, payload = self._http_json(method.upper(), url, headers=headers, data=data)
        return status, payload if isinstance(payload, dict) else {}
