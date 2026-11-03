"""Conservative storage maintenance. Unknown files and resumable tasks are retained."""
import argparse
from contextlib import closing, nullcontext
from dataclasses import dataclass, fields
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from src.core.cache_io import try_directory_lock


CACHE_NAME = re.compile(r'v2_[0-9a-f]{64}\Z')
TASK_DIRECTORY = re.compile(r'[0-9a-f]{64}\Z')
TASK_ID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
TASK_PREFIX = re.compile('(' + TASK_ID + ')_')


@dataclass(frozen=True)
class StoragePolicy:
    storage_retention_seconds: int = 86400
    storage_orphan_grace_seconds: int = 604800
    storage_max_bytes: int = 0  # Optional admission threshold, not a filesystem quota.
    storage_min_free_bytes: int = 256 * 1024 * 1024
    storage_cleanup_enabled: bool = False

    @classmethod
    def from_env(cls):
        values = {}
        for field in fields(cls):
            name = field.name.upper()
            raw = os.getenv(name, str(field.default))
            if field.name == 'storage_cleanup_enabled':
                if raw.lower() not in ('true', 'false', '1', '0'):
                    raise ValueError(f'{name} must be true/false or 1/0')
                values[field.name] = raw.lower() in ('true', '1')
                continue
            try:
                value = int(raw)
            except ValueError:
                raise ValueError(f'{name} must be an integer') from None
            minimum = 0 if field.name in ('storage_max_bytes', 'storage_min_free_bytes') else 1
            if value < minimum:
                raise ValueError(f'{name} has an invalid limit')
            values[field.name] = value
        return cls(**values)


class StorageBudgetExceeded(RuntimeError):
    pass


def _tree_info(path, root, *, ignore_missing=False):
    """Return logical bytes and newest mtime; refuse links instead of following them."""
    if root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Refusing storage path outside its root or a symbolic link')
    # Also reject links in intermediate paths, even if they point inside storage.
    if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
        raise ValueError('Refusing a symbolic link inside storage')
    info = path.lstat()
    if not path.is_dir():
        return info.st_size, info.st_mtime
    size, modified = 0, info.st_mtime
    for child in path.iterdir():
        try:
            child_size, child_modified = _tree_info(child, root, ignore_missing=ignore_missing)
        except FileNotFoundError:
            if ignore_missing:
                continue  # Concurrent atomic publication/cleanup during quota measurement.
            raise
        size += child_size
        if child.name != '.cache.lock':
            modified = max(modified, child_modified)
    return size, modified


def check_storage_budget(root=Path('storage'), *, additional_bytes=0, policy=None):
    policy = policy or StoragePolicy.from_env()
    root = Path(root)
    existing = root
    while not existing.exists():
        existing = existing.parent
    if shutil.disk_usage(existing).free < policy.storage_min_free_bytes + additional_bytes:
        raise StorageBudgetExceeded('Insufficient free disk space for generation')
    if policy.storage_max_bytes and root.exists():
        try:
            used, _ = _tree_info(root, root, ignore_missing=True)
        except ValueError:
            raise StorageBudgetExceeded('Storage contains unsupported symbolic links; inspect it before generation') from None
        if used + additional_bytes >= policy.storage_max_bytes:
            raise StorageBudgetExceeded('STORAGE_MAX_BYTES reached; archive completed outputs or inspect retention dry-run')


def _tasks(database):
    # Read-only even for command-line dry-run: no database creation or migration.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute('SELECT id,status,completed,finished_at,audio_file FROM tasks')]


def _expired(task, cutoff):
    return bool((task['completed'] or task['status'] == 'Completed')
                and task['finished_at'] is not None and task['finished_at'] < cutoff)


def _cache_pins(root, tasks, cutoff):
    pins = set()
    for task in tasks:
        if _expired(task, cutoff):
            continue
        directory = root / 'tasks' / hashlib.sha256(task['id'].encode()).hexdigest()
        marker = directory / 'cache.json'
        try:
            _tree_info(marker, root)
            if marker.stat().st_size > 4096:
                return None
            key = json.loads(marker.read_text(encoding='utf-8'))['cache_key']
            if not isinstance(key, str) or not CACHE_NAME.fullmatch(key):
                return None
            pins.add(key)
        except (OSError, ValueError, KeyError, TypeError):
            # Legacy/early-stage jobs have no cache reference: keep every cache.
            return None
    return pins


def _active(tasks):
    return any(not task['completed'] and task['status'] not in ('Completed', 'Failed', 'Interrupted') for task in tasks)


def sweep_storage(root, database, *, policy=None, dry_run=True, now=None):
    """Plan or apply one sweep. Apply always re-plans and rechecks under OS locks."""
    root = Path(root).absolute()
    policy = policy or StoragePolicy.from_env()
    now = time.time() if now is None else now
    cutoff = now - policy.storage_retention_seconds
    orphan_cutoff = now - policy.storage_orphan_grace_seconds
    if root.is_symlink():
        raise ValueError('Storage root must not be a symbolic link')
    _tree_info(Path(database).absolute(), root)
    report = {'dry_run': dry_run, 'candidates': [], 'expired_tasks': [], 'skipped': []}
    lease = nullcontext(True) if dry_run else try_directory_lock(root, '.retention.lock')
    with lease as acquired:
        if not acquired:
            report['skipped'].append('Another retention sweep is running')
            return report
        tasks = _tasks(database)
        by_id = {task['id']: task for task in tasks}
        by_hash = {hashlib.sha256(task['id'].encode()).hexdigest(): task for task in tasks}
        pins = _cache_pins(root, tasks, cutoff)

        def owner_cutoff(task_id):
            task = by_id.get(task_id)
            return cutoff if task and _expired(task, cutoff) else (orphan_cutoff if task is None else None)

        for area in ('tasks', 'cache', 'output', 'translations'):
            parent = root / area
            if not parent.exists():
                continue
            if parent.is_symlink():
                report['skipped'].append(str(parent.relative_to(root)))
                continue
            for path in sorted(parent.iterdir()):
                limit, kind = None, 'artifact'
                match = TASK_PREFIX.match(path.name)
                if area == 'tasks' and TASK_DIRECTORY.fullmatch(path.name) and path.is_dir():
                    task = by_hash.get(path.name)
                    limit = cutoff if task and _expired(task, cutoff) else (orphan_cutoff if task is None else None)
                elif area == 'cache' and re.fullmatch('task_' + TASK_ID, path.name) and path.is_dir():
                    limit = owner_cutoff(path.name[5:])
                elif area == 'cache' and CACHE_NAME.fullmatch(path.name):
                    if pins is not None and path.name not in pins:
                        limit, kind = orphan_cutoff, 'cache'
                elif area == 'output' and path.name.startswith('.compile-'):
                    if not _active(tasks):
                        limit, kind = orphan_cutoff, 'compiler'
                elif area in ('output', 'translations') and match:
                    limit = owner_cutoff(match[1])
                elif area == 'output':
                    owners = [task for task in tasks if task['audio_file'] == path.name]
                    if owners and all(_expired(task, cutoff) for task in owners):
                        limit = cutoff
                if limit is None:
                    continue
                try:
                    if kind == 'cache' and not any(child.name != '.cache.lock' for child in path.iterdir()):
                        continue
                    size, modified = _tree_info(path, root)
                    if modified >= limit:
                        continue
                    entry = {'path': str(path.relative_to(root)), 'bytes': size, 'kind': kind}
                    if dry_run:
                        report['candidates'].append(entry)
                        continue
                    guard = try_directory_lock(path) if kind in ('cache', 'compiler') else nullcontext(True)
                    with guard as available:
                        if not available:
                            report['skipped'].append(entry['path'])
                            continue
                        if kind == 'cache':
                            current_pins = _cache_pins(root, _tasks(database), cutoff)
                            if current_pins is None or path.name in current_pins:
                                continue
                        elif kind == 'compiler' and _active(_tasks(database)):
                            continue
                        # Re-read timestamps and links after acquiring the resource lock.
                        if _tree_info(path, root)[1] >= limit:
                            continue
                        if kind in ('cache', 'compiler'):
                            for child in path.iterdir():
                                if child.name != '.cache.lock':
                                    shutil.rmtree(child) if child.is_dir() else child.unlink()
                        elif path.is_dir():
                            shutil.rmtree(path)
                        else:
                            path.unlink()
                    if kind == 'compiler':
                        (path / '.cache.lock').unlink()
                        path.rmdir()
                    report['candidates'].append(entry)
                except (OSError, ValueError):
                    report['skipped'].append(str(path.relative_to(root)))

        # Drop completed metadata only after its named artifacts are gone.
        for task in tasks:
            if not _expired(task, cutoff):
                continue
            owned = [root / 'tasks' / hashlib.sha256(task['id'].encode()).hexdigest(),
                     root / 'cache' / ('task_' + task['id'])]
            if task['audio_file']:
                if Path(task['audio_file']).name != task['audio_file']:
                    continue
                owned.append(root / 'output' / task['audio_file'])
            for area in ('output', 'translations'):
                parent = root / area
                if parent.exists() and not parent.is_symlink():
                    owned.extend(path for path in parent.iterdir() if path.name.startswith(task['id'] + '_'))
            planned = {entry['path'] for entry in report['candidates']}
            if any((path.exists() or path.is_symlink())
                   and (not dry_run or str(path.relative_to(root)) not in planned) for path in owned):
                continue
            if not dry_run:
                with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=rw',
                                             uri=True, timeout=30)) as connection, connection:
                    connection.execute('PRAGMA foreign_keys=ON')
                    connection.execute("DELETE FROM tasks WHERE id=? AND finished_at < ? "
                                       "AND (completed=1 OR status='Completed')", (task['id'], cutoff))
            report['expired_tasks'].append(task['id'])
    return report


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=Path('storage'))
    parser.add_argument('--apply', action='store_true', help='Delete eligible artifacts; default is read-only dry-run')
    args = parser.parse_args()
    try:
        report = sweep_storage(args.storage, args.storage / 'state.db', dry_run=not args.apply)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Storage maintenance failed: {error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
