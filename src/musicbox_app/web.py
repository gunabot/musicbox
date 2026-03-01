import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from .config import (
    DEFAULT_SETTINGS,
    MEDIA_DIR,
    SPOTIFY_CACHE_BITRATE,
    SPOTIFY_CAPTURE_DEVICE_NAME,
    SPOTIFY_CACHE_DIR,
    SPOTIFY_CACHE_FORMAT,
    SPOTIFY_CACHE_INDEX_PATH,
    SPOTIFY_FETCH_COMMAND,
    SPOTIFY_OAUTH_PATH,
)
from .mappings import normalize_mapping_value
from .media import (
    ensure_media_root,
    list_audio_entries,
    list_media_entries,
    path_info,
    safe_rel_to_abs,
    tree_node,
)
from .monitors import start_background_monitors
from .player import PlayerManager
from .spotify_auth import SpotifyAuthManager
from .spotify_jobs import SpotifyCacheJobManager
from .store import AppStore


def _json_error(message: str, status_code: int = 400):
    return jsonify({'ok': False, 'error': message}), status_code


def _int_query(name: str, default: int = 0) -> int:
    value = request.args.get(name, '').strip()
    if not value:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _bool_query(name: str, default: bool = False) -> bool:
    value = request.args.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _int_param(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def create_app() -> Flask:
    ensure_media_root()

    app = Flask(__name__, template_folder='templates', static_folder='static')
    store = AppStore()
    spotify_auth = SpotifyAuthManager(store)
    player = PlayerManager(store, spotify_auth)
    spotify_jobs = SpotifyCacheJobManager(store, player.spotify_cache)
    start_background_monitors(store, player)
    store.add_event('musicbox service started')

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def api_status():
        since_id = _int_query('since', 0)
        snapshot = store.snapshot(since_id=since_id)
        return jsonify({'ok': True, **snapshot, 'spotify': spotify_auth.status(), 'spotify_jobs': spotify_jobs.list_jobs(limit=40)})

    @app.get('/api/stream')
    def api_stream():
        @stream_with_context
        def event_stream():
            last_event_id = 0
            while True:
                payload = store.snapshot(since_id=last_event_id)
                payload['spotify'] = spotify_auth.status()
                payload['spotify_jobs'] = spotify_jobs.list_jobs(limit=40)
                events = payload.get('events', [])
                if events:
                    last_event_id = int(events[-1]['id'])
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
                time.sleep(1.0)

        headers = {
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
        return Response(event_stream(), mimetype='text/event-stream', headers=headers)

    @app.get('/api/files')
    def api_files():
        query = request.args.get('q', '').strip()
        kind = request.args.get('kind', 'all').strip().lower()
        relpath = request.args.get('path', '').strip().lstrip('/')
        recursive = _bool_query('recursive', default=bool(query))
        include_tree = _bool_query('include_tree', default=False)

        if kind not in {'all', 'files', 'dirs'}:
            kind = 'all'

        try:
            entries = list_media_entries(query=query, kind=kind, relpath=relpath, recursive=recursive)
            audio_entries = list_audio_entries(query=query, relpath=relpath)
        except Exception as exc:
            return _json_error(str(exc))

        payload: Dict[str, Any] = {
            'ok': True,
            'media_dir': str(MEDIA_DIR),
            'cwd': relpath,
            'entries': entries,
            'audio': audio_entries,
            'recursive': recursive,
        }
        if include_tree:
            payload['tree'] = tree_node('', include_files=False)
        return jsonify(payload)

    @app.get('/api/tree')
    def api_tree():
        relpath = request.args.get('path', '').strip().lstrip('/')
        include_files = _bool_query('include_files', default=False)
        try:
            node = tree_node(relpath=relpath, include_files=include_files)
            return jsonify({'ok': True, 'node': node})
        except Exception as exc:
            return _json_error(str(exc), 404)

    @app.get('/api/pathinfo')
    def api_pathinfo():
        relpath = request.args.get('path', '').strip().lstrip('/')
        if not relpath:
            return _json_error('path required')
        try:
            return jsonify({'ok': True, 'info': path_info(relpath)})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/play')
    def api_play():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        source_type = str(data.get('type', '')).strip().lower()

        try:
            if source_type == 'spotify':
                target = str(data.get('target', '')).strip()
                if not target:
                    return _json_error('target required for spotify')
                relpath = player.play_spotify(target)
                return jsonify({'ok': True, 'source': 'spotify', 'cached_path': relpath})

            relpath = str(data.get('file', '')).strip()
            if not relpath:
                return _json_error('file required')
            player.play(relpath)
            return jsonify({'ok': True})
        except Exception as exc:
            store.add_event(f'PLAY_ERR {exc}', level='error')
            return _json_error(str(exc))

    @app.post('/api/stop')
    def api_stop():
        player.stop()
        store.add_event('STOP')
        return jsonify({'ok': True})

    @app.post('/api/player/action')
    def api_player_action():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        action = str(data.get('action', '')).strip().lower()
        ok = player.action(action)
        if not ok:
            return _json_error(f'unknown or failed action: {action}')
        return jsonify({'ok': True, 'action': action})

    @app.get('/api/settings')
    def api_settings_get():
        snapshot = store.snapshot(since_id=0, event_limit=1)
        return jsonify({'ok': True, 'settings': snapshot['settings']})

    @app.post('/api/settings')
    def api_settings_set():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        try:
            changed = False
            if 'rotary_led_step_ms' in data:
                value = int(data['rotary_led_step_ms'])
                value = max(5, min(250, value))
                store.set_setting('rotary_led_step_ms', value)
                store.add_event(f'SET rotary_led_step_ms={value}')
                changed = True
            if 'rotary_volume_per_turn' in data:
                value = int(data['rotary_volume_per_turn'])
                value = max(20, min(300, value))
                store.set_setting('rotary_volume_per_turn', value)
                store.add_event(f'SET rotary_volume_per_turn={value}')
                changed = True
            if changed:
                store.save_settings()
            snapshot = store.snapshot(since_id=0, event_limit=1)
            return jsonify({'ok': True, 'settings': snapshot['settings']})
        except Exception as exc:
            return _json_error(str(exc))

    @app.get('/api/spotify/status')
    def api_spotify_status():
        return jsonify({'ok': True, 'spotify': spotify_auth.status()})

    @app.post('/api/spotify/config')
    def api_spotify_config():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        try:
            if 'client_id' in data:
                spotify_auth.set_client_id(str(data.get('client_id', '')).strip())
            if 'device_name' in data:
                spotify_auth.set_device_name(str(data.get('device_name', '')).strip())
            return jsonify({'ok': True, 'spotify': spotify_auth.status()})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/spotify/login/start')
    def api_spotify_login_start():
        try:
            host_url = request.host_url.rstrip('/')
            auth_url = spotify_auth.start_login(host_url)
            return jsonify({'ok': True, 'auth_url': auth_url})
        except Exception as exc:
            return _json_error(str(exc))

    @app.get('/api/spotify/callback')
    def api_spotify_callback():
        error = str(request.args.get('error', '')).strip()
        if error:
            store.add_event(f'SPOTIFY_LOGIN_ERR {error}', level='error')
            return (
                "<!doctype html><html><body><h3>Spotify login failed</h3>"
                f"<p>{error}</p><p>You can close this tab.</p></body></html>"
            )

        code = str(request.args.get('code', '')).strip()
        state = str(request.args.get('state', '')).strip()
        try:
            spotify_auth.handle_callback(code=code, state=state)
            return (
                "<!doctype html><html><body><h3>Spotify connected</h3>"
                "<p>You can close this tab and return to Musicbox.</p>"
                "<script>setTimeout(()=>window.close(), 500);</script>"
                "</body></html>"
            )
        except Exception as exc:
            store.add_event(f'SPOTIFY_LOGIN_ERR {exc}', level='error')
            return (
                "<!doctype html><html><body><h3>Spotify login failed</h3>"
                f"<p>{exc}</p><p>You can close this tab.</p></body></html>"
            )

    @app.post('/api/spotify/disconnect')
    def api_spotify_disconnect():
        try:
            status = spotify_auth.disconnect()
            return jsonify({'ok': True, 'spotify': status})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/spotify/cache')
    def api_spotify_cache():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        target = str(data.get('target', '')).strip()
        if not target:
            return _json_error('spotify target required')
        refresh = bool(data.get('refresh', False))
        try:
            # Force-refresh before long-running capture/import jobs so we fail fast
            # on revoked credentials instead of dying mid-job.
            spotify_auth.get_access_token(force_refresh=True)
            async_mode = bool(data.get('async', False))
            if async_mode:
                job = spotify_jobs.enqueue(target, refresh=refresh)
                return jsonify({'ok': True, 'async': True, 'job': job})
            relpath = player.spotify_cache.resolve(target, refresh=refresh)
            return jsonify({'ok': True, 'cached_path': relpath})
        except Exception as exc:
            store.add_event(f'SPOTIFY_CACHE_ERR {exc}', level='error')
            return _json_error(str(exc))

    @app.get('/api/spotify/jobs')
    def api_spotify_jobs():
        limit = max(1, min(200, _int_query('limit', 40)))
        return jsonify({'ok': True, 'jobs': spotify_jobs.list_jobs(limit=limit)})

    @app.get('/api/spotify/search')
    def api_spotify_search():
        query = str(request.args.get('q', '')).strip()
        if not query:
            return _json_error('query required')

        raw_type = str(request.args.get('type', 'track,album,playlist')).strip().lower()
        requested = [part.strip() for part in raw_type.split(',') if part.strip()]
        allowed_types = ['track', 'album', 'playlist']
        search_types = [item for item in requested if item in allowed_types] or ['track', 'album', 'playlist']
        limit = max(1, min(25, _int_param(request.args.get('limit'), 12)))

        try:
            payload_status = spotify_auth.status()
            market = (
                str((payload_status.get('user') or {}).get('country', '')).strip().upper()
                if isinstance(payload_status.get('user'), dict)
                else ''
            )
            params: Dict[str, Any] = {
                'q': query,
                'type': ','.join(search_types),
                'limit': limit,
            }
            if market:
                params['market'] = market

            status, payload = spotify_auth.spotify_api_request('GET', '/search', params=params)
            if status >= 300:
                return _json_error(payload.get('error', {}).get('message') or payload.get('error') or 'spotify search failed')

            items: list[Dict[str, Any]] = []

            for item in (payload.get('tracks') or {}).get('items', []) or []:
                if not isinstance(item, dict):
                    continue
                artists = [
                    str(artist.get('name', '')).strip()
                    for artist in (item.get('artists') or [])
                    if isinstance(artist, dict)
                ]
                artists = [artist for artist in artists if artist]
                image = None
                album = item.get('album') if isinstance(item.get('album'), dict) else {}
                images = album.get('images') if isinstance(album.get('images'), list) else []
                if images:
                    first_image = images[0] if isinstance(images[0], dict) else {}
                    image = str(first_image.get('url', '')).strip() or None
                items.append({
                    'type': 'track',
                    'uri': str(item.get('uri', '')).strip(),
                    'name': str(item.get('name', '')).strip(),
                    'subtitle': ', '.join(artists) or str(album.get('name', '')).strip(),
                    'album': str(album.get('name', '')).strip() or None,
                    'duration_ms': _int_param(item.get('duration_ms'), 0) or None,
                    'image': image,
                })

            for item in (payload.get('albums') or {}).get('items', []) or []:
                if not isinstance(item, dict):
                    continue
                artists = [
                    str(artist.get('name', '')).strip()
                    for artist in (item.get('artists') or [])
                    if isinstance(artist, dict)
                ]
                artists = [artist for artist in artists if artist]
                images = item.get('images') if isinstance(item.get('images'), list) else []
                first_image = images[0] if images and isinstance(images[0], dict) else {}
                image = str(first_image.get('url', '')).strip()
                items.append({
                    'type': 'album',
                    'uri': str(item.get('uri', '')).strip(),
                    'name': str(item.get('name', '')).strip(),
                    'subtitle': ', '.join(artists),
                    'album': None,
                    'duration_ms': None,
                    'image': image or None,
                })

            for item in (payload.get('playlists') or {}).get('items', []) or []:
                if not isinstance(item, dict):
                    continue
                owner = item.get('owner') if isinstance(item.get('owner'), dict) else {}
                owner_name = str(owner.get('display_name', '')).strip() or str(owner.get('id', '')).strip()
                images = item.get('images') if isinstance(item.get('images'), list) else []
                first_image = images[0] if images and isinstance(images[0], dict) else {}
                image = str(first_image.get('url', '')).strip()
                tracks_obj = item.get('tracks') if isinstance(item.get('tracks'), dict) else {}
                count = _int_param(tracks_obj.get('total'), 0)
                count_text = f'{count} tracks' if count > 0 else ''
                subtitle = ' • '.join([part for part in [owner_name, count_text] if part])
                items.append({
                    'type': 'playlist',
                    'uri': str(item.get('uri', '')).strip(),
                    'name': str(item.get('name', '')).strip(),
                    'subtitle': subtitle,
                    'album': None,
                    'duration_ms': None,
                    'image': image or None,
                })

            filtered = [item for item in items if item.get('uri') and item.get('name')]
            return jsonify({'ok': True, 'items': filtered, 'query': query, 'types': search_types})
        except Exception as exc:
            store.add_event(f'SPOTIFY_SEARCH_ERR {exc}', level='error')
            return _json_error(str(exc))

    @app.post('/api/mkdir')
    def api_mkdir():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        relpath = str(data.get('path', '')).strip()
        if not relpath:
            return _json_error('path required')

        try:
            target = safe_rel_to_abs(relpath)
            target.mkdir(parents=True, exist_ok=True)
            store.add_event(f'MKDIR {target.relative_to(MEDIA_DIR)}')
            return jsonify({'ok': True})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/delete')
    def api_delete():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        relpath = str(data.get('path', '')).strip()
        if not relpath:
            return _json_error('path required')

        try:
            target = safe_rel_to_abs(relpath)
            if not target.exists():
                return _json_error('not found', 404)

            rel = str(target.relative_to(MEDIA_DIR))
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

            store.add_event(f'DELETE {rel}')
            return jsonify({'ok': True})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/move')
    def api_move():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        src = str(data.get('src', '')).strip()
        dst = str(data.get('dst', '')).strip()
        if not src or not dst:
            return _json_error('src and dst required')

        try:
            source = safe_rel_to_abs(src)
            target = safe_rel_to_abs(dst)
            if not source.exists():
                return _json_error('source not found', 404)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            store.add_event(f'MOVE {src} -> {dst}')
            return jsonify({'ok': True})
        except Exception as exc:
            return _json_error(str(exc))

    @app.post('/api/upload')
    def api_upload():
        try:
            target_dir = request.form.get('dir', '').strip().lstrip('/')
            base = safe_rel_to_abs(target_dir)
            base.mkdir(parents=True, exist_ok=True)

            files = request.files.getlist('files')
            relpaths = request.form.getlist('relpath')
            if not files:
                return _json_error('no files')

            saved: list[str] = []
            skipped = 0
            for index, upload in enumerate(files):
                if not upload or not getattr(upload, 'filename', ''):
                    skipped += 1
                    continue

                rel = relpaths[index] if index < len(relpaths) and relpaths[index] else upload.filename
                rel = str(Path(rel.replace('\\', '/').lstrip('/')))
                if rel.lower().startswith('c:/fakepath/'):
                    rel = rel.split('/', 2)[-1]
                if rel in {'', '.'}:
                    skipped += 1
                    continue

                out_path = safe_rel_to_abs(str(Path(target_dir) / rel))
                out_path.parent.mkdir(parents=True, exist_ok=True)
                upload.save(out_path)
                saved.append(str(out_path.relative_to(MEDIA_DIR)))

            if not saved:
                msg = f'no valid files in upload payload (skipped={skipped})'
                store.add_event(f'UPLOAD_ERR {msg}', level='error')
                return _json_error(msg)

            store.add_event(f'UPLOAD {len(saved)} file(s), skipped={skipped}')
            return jsonify({'ok': True, 'saved': saved, 'skipped': skipped})
        except Exception as exc:
            store.add_event(f'UPLOAD_ERR {exc}', level='error')
            return _json_error(str(exc))

    @app.get('/api/mappings')
    def api_mappings_get():
        mappings = store.load_mappings()
        return jsonify({'ok': True, 'mappings': mappings})

    @app.post('/api/mappings')
    def api_mappings_set():
        data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        card = str(data.get('card', '')).strip()
        if not card:
            return _json_error('card required')

        mappings = store.load_mappings()
        target_raw = str(data.get('target', '')).strip()
        mapping_type = str(data.get('type', '')).strip().lower() or 'local'

        if mapping_type == 'local':
            target_raw = target_raw.lstrip('/')

        if target_raw:
            try:
                normalized = normalize_mapping_value(
                    {'type': mapping_type, 'target': target_raw},
                    strict=True,
                )
            except Exception as exc:
                return _json_error(str(exc))

            if normalized is None:
                return _json_error('invalid mapping payload')

            if normalized['type'] == 'local':
                safe_rel_to_abs(normalized['target'])

            mappings[card] = normalized
            store.add_event(f"MAP_SET {card} -> {normalized['type']}:{normalized['target']}")
        else:
            mappings.pop(card, None)
            store.add_event(f'MAP_DEL {card}')

        store.save_mappings(mappings)
        return jsonify({'ok': True, 'mappings': mappings})

    @app.get('/api/config')
    def api_config():
        return jsonify({
            'ok': True,
            'settings_defaults': DEFAULT_SETTINGS,
            'media_dir': str(MEDIA_DIR),
            'spotify': {
                'cache_dir': str(SPOTIFY_CACHE_DIR),
                'import_root': str(SPOTIFY_CACHE_DIR),
                'cache_index_path': str(SPOTIFY_CACHE_INDEX_PATH),
                'fetch_command': SPOTIFY_FETCH_COMMAND,
                'oauth_path': str(SPOTIFY_OAUTH_PATH),
                'default_device_name': SPOTIFY_CAPTURE_DEVICE_NAME,
                'cache_format': SPOTIFY_CACHE_FORMAT,
                'cache_bitrate': SPOTIFY_CACHE_BITRATE,
            },
        })

    return app
