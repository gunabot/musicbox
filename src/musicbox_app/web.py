import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from .config import DEFAULT_SETTINGS, MEDIA_DIR
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


def create_app() -> Flask:
    ensure_media_root()

    app = Flask(__name__, template_folder='templates', static_folder='static')
    store = AppStore()
    player = PlayerManager(store)
    start_background_monitors(store, player)
    store.add_event('musicbox service started')

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/status')
    def api_status():
        since_id = _int_query('since', 0)
        snapshot = store.snapshot(since_id=since_id)
        return jsonify({'ok': True, **snapshot})

    @app.get('/api/stream')
    def api_stream():
        @stream_with_context
        def event_stream():
            last_event_id = 0
            while True:
                payload = store.snapshot(since_id=last_event_id)
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
        relpath = str(data.get('file', '')).strip()
        if not relpath:
            return _json_error('file required')

        try:
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
            if 'rotary_led_step_ms' in data:
                value = int(data['rotary_led_step_ms'])
                value = max(5, min(250, value))
                store.set_setting('rotary_led_step_ms', value)
                store.save_settings()
                store.add_event(f'SET rotary_led_step_ms={value}')
            snapshot = store.snapshot(since_id=0, event_limit=1)
            return jsonify({'ok': True, 'settings': snapshot['settings']})
        except Exception as exc:
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
        target = str(data.get('target', '')).strip().lstrip('/')
        if not card:
            return _json_error('card required')

        mappings = store.load_mappings()
        if target:
            safe_rel_to_abs(target)
            mappings[card] = target
            store.add_event(f'MAP_SET {card} -> {target}')
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
        })

    return app
