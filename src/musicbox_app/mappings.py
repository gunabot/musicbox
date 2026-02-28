import re
from typing import Any, Dict
from urllib.parse import urlparse

_SPOTIFY_URI_RE = re.compile(r'^spotify:(track|album|playlist):([A-Za-z0-9]+)$')


def normalize_local_target(target: str) -> str:
    normalized = str(target or '').strip().replace('\\', '/').lstrip('/').rstrip('/')
    if not normalized:
        raise ValueError('local target required')
    return normalized


def normalize_spotify_target(target: str) -> str:
    value = str(target or '').strip()
    if not value:
        raise ValueError('spotify target required')

    match = _SPOTIFY_URI_RE.match(value)
    if match:
        return f"spotify:{match.group(1)}:{match.group(2)}"

    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'}:
        raise ValueError('spotify target must be URI or open.spotify.com URL')
    if parsed.netloc not in {'open.spotify.com', 'www.open.spotify.com'}:
        raise ValueError('spotify URL must use open.spotify.com')

    parts = [chunk for chunk in parsed.path.split('/') if chunk]
    if len(parts) < 2:
        raise ValueError('spotify URL path is invalid')
    media_type = parts[0].lower()
    media_id = parts[1]
    if media_type not in {'track', 'album', 'playlist'}:
        raise ValueError('spotify URL type must be track, album, or playlist')
    if not re.fullmatch(r'[A-Za-z0-9]+', media_id):
        raise ValueError('spotify URL id is invalid')
    return f'spotify:{media_type}:{media_id}'


def normalize_mapping_value(value: Any, *, strict: bool = False) -> Dict[str, str] | None:
    try:
        if isinstance(value, str):
            return {'type': 'local', 'target': normalize_local_target(value)}

        if not isinstance(value, dict):
            raise ValueError('mapping value must be string or object')

        mapping_type = str(value.get('type', 'local')).strip().lower() or 'local'
        target = value.get('target', '')
        if mapping_type == 'local':
            normalized_target = normalize_local_target(str(target))
        elif mapping_type == 'spotify':
            normalized_target = normalize_spotify_target(str(target))
        else:
            raise ValueError(f'unsupported mapping type: {mapping_type}')

        return {'type': mapping_type, 'target': normalized_target}
    except Exception:
        if strict:
            raise
        return None


def normalize_mappings_payload(raw: Any) -> Dict[str, Dict[str, str]]:
    if not isinstance(raw, dict):
        return {}

    normalized: Dict[str, Dict[str, str]] = {}
    for card, value in raw.items():
        key = str(card).strip()
        if not key:
            continue
        entry = normalize_mapping_value(value, strict=False)
        if entry is None:
            continue
        normalized[key] = entry
    return normalized
