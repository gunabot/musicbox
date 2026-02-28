from pathlib import Path
from typing import Dict, List

from .config import MEDIA_DIR, MEDIA_EXTENSIONS


def ensure_media_root() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def safe_rel_to_abs(relpath: str) -> Path:
    relpath = (relpath or '').strip().replace('\\', '/').lstrip('/')
    target = (MEDIA_DIR / relpath).resolve()
    media_root = MEDIA_DIR.resolve()
    try:
        target.relative_to(media_root)
    except ValueError as exc:
        raise ValueError('invalid path') from exc
    return target


def list_media_entries(query: str = '', kind: str = 'all') -> List[Dict[str, str]]:
    query_lc = (query or '').strip().lower()
    entries: List[Dict[str, str]] = []

    for path in MEDIA_DIR.rglob('*'):
        rel = str(path.relative_to(MEDIA_DIR))
        entry_type = 'dir' if path.is_dir() else 'file'

        if kind == 'files' and entry_type != 'file':
            continue
        if kind == 'dirs' and entry_type != 'dir':
            continue

        if query_lc and query_lc not in rel.lower() and query_lc not in path.name.lower():
            continue

        entries.append({'path': rel, 'name': path.name, 'type': entry_type})

    entries.sort(key=lambda item: (item['type'] == 'file', item['path'].lower()))
    return entries


def list_audio_entries(query: str = '') -> List[Dict[str, str]]:
    query_lc = (query or '').strip().lower()
    entries: List[Dict[str, str]] = []

    for path in MEDIA_DIR.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue

        rel = str(path.relative_to(MEDIA_DIR))
        if query_lc and query_lc not in rel.lower():
            continue

        entries.append({'path': rel, 'name': path.name, 'type': 'file'})

    entries.sort(key=lambda item: item['path'].lower())
    return entries


def list_audio_files_recursive(folder: Path) -> List[Path]:
    files: List[Path] = []
    for path in folder.rglob('*'):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(path)
    files.sort()
    return files


def media_tree(base: Path | None = None) -> Dict[str, object]:
    node_base = MEDIA_DIR if base is None else base
    node: Dict[str, object] = {
        'name': node_base.name,
        'path': str(node_base.relative_to(MEDIA_DIR)) if node_base != MEDIA_DIR else '',
        'type': 'dir',
        'children': [],
    }
    children = sorted(node_base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for child in children:
        if child.is_dir():
            node['children'].append(media_tree(child))
        else:
            node['children'].append({
                'name': child.name,
                'path': str(child.relative_to(MEDIA_DIR)),
                'type': 'file',
            })
    return node
