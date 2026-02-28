from pathlib import Path
from typing import Dict, Iterator, List

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


def rel_from_abs(path: Path) -> str:
    return str(path.resolve().relative_to(MEDIA_DIR.resolve()))


def _entry_type(path: Path) -> str:
    return 'dir' if path.is_dir() else 'file'


def _iter_entries(base: Path, recursive: bool) -> Iterator[Path]:
    if not base.exists() or not base.is_dir():
        return iter(())
    if recursive:
        return base.rglob('*')
    return base.iterdir()


def list_media_entries(
    query: str = '',
    kind: str = 'all',
    relpath: str = '',
    recursive: bool = True,
) -> List[Dict[str, object]]:
    query_lc = (query or '').strip().lower()
    entries: List[Dict[str, object]] = []
    base = safe_rel_to_abs(relpath)

    for path in _iter_entries(base, recursive=recursive):
        entry_type = _entry_type(path)
        if kind == 'files' and entry_type != 'file':
            continue
        if kind == 'dirs' and entry_type != 'dir':
            continue

        rel = rel_from_abs(path)
        if query_lc and query_lc not in rel.lower() and query_lc not in path.name.lower():
            continue

        item: Dict[str, object] = {
            'path': rel,
            'name': path.name,
            'type': entry_type,
        }
        if path.is_file():
            try:
                item['size_bytes'] = path.stat().st_size
            except Exception:
                item['size_bytes'] = None
        entries.append(item)

    entries.sort(key=lambda item: (item['type'] == 'file', str(item['path']).lower()))
    return entries


def list_audio_entries(query: str = '', relpath: str = '') -> List[Dict[str, object]]:
    query_lc = (query or '').strip().lower()
    entries: List[Dict[str, object]] = []
    base = safe_rel_to_abs(relpath)
    if not base.exists() or not base.is_dir():
        return entries

    for path in base.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue

        rel = rel_from_abs(path)
        if query_lc and query_lc not in rel.lower() and query_lc not in path.name.lower():
            continue

        entries.append({'path': rel, 'name': path.name, 'type': 'file'})

    entries.sort(key=lambda item: str(item['path']).lower())
    return entries


def list_audio_files_recursive(folder: Path) -> List[Path]:
    files: List[Path] = []
    for path in folder.rglob('*'):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(path)
    files.sort()
    return files


def tree_node(relpath: str = '', include_files: bool = False) -> Dict[str, object]:
    base = safe_rel_to_abs(relpath)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(relpath or '.')

    node: Dict[str, object] = {
        'name': base.name if relpath else 'media',
        'path': rel_from_abs(base) if relpath else '',
        'type': 'dir',
        'children': [],
    }

    children = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for child in children:
        if child.is_file() and not include_files:
            continue

        child_item: Dict[str, object] = {
            'name': child.name,
            'path': rel_from_abs(child),
            'type': _entry_type(child),
        }

        if child.is_dir():
            try:
                child_item['has_children'] = any(grand.is_dir() for grand in child.iterdir())
            except Exception:
                child_item['has_children'] = False
        else:
            try:
                child_item['size_bytes'] = child.stat().st_size
            except Exception:
                child_item['size_bytes'] = None

        node['children'].append(child_item)

    return node


def path_info(relpath: str) -> Dict[str, object]:
    relpath = (relpath or '').strip().lstrip('/')
    target = safe_rel_to_abs(relpath)
    if not target.exists():
        return {'path': relpath, 'exists': False}

    if target.is_file():
        try:
            size_bytes = target.stat().st_size
        except Exception:
            size_bytes = None
        return {
            'path': rel_from_abs(target),
            'exists': True,
            'type': 'file',
            'size_bytes': size_bytes,
            'file_count': 1,
            'dir_count': 0,
        }

    file_count = 0
    dir_count = 0
    total_size = 0
    for item in target.rglob('*'):
        if item.is_dir():
            dir_count += 1
            continue
        if item.is_file():
            file_count += 1
            try:
                total_size += item.stat().st_size
            except Exception:
                pass

    try:
        child_count = sum(1 for _ in target.iterdir())
    except Exception:
        child_count = 0

    return {
        'path': rel_from_abs(target),
        'exists': True,
        'type': 'dir',
        'size_bytes': total_size,
        'file_count': file_count,
        'dir_count': dir_count,
        'child_count': child_count,
    }
