"""Use one per-user data directory across versions; import portable data once."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from contextlib import closing


def legacy_directories(base):
    base = Path(base).resolve()
    candidates = [base / 'data']
    # Recognize the development workspace only; never scan unrelated user folders.
    for root in (base, *base.parents):
        if (root / 'build_release.py').is_file() and (root / 'app.py').is_file():
            candidates += [root / 'data', root / 'dist/SCMaru/data', root / 'dist/SCDesk/data']
            candidates += list(root.glob('package-stage*/SCMaru/data'))
            candidates += list(root.glob('package-stage*/SCDesk/data'))
            break
    return [p for p in dict.fromkeys(candidates) if (p / 'config.json').is_file() or (p / 'scdesk.sqlite3').is_file()]


def import_legacy(source, target):
    """Backup SQLite (including WAL), copy settings/exports, never alter the source."""
    source, target = Path(source), Path(target)
    if target.exists() and any(target.iterdir()): return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / ('.SCMaru-import-' + uuid.uuid4().hex)
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns('scdesk.sqlite3*', '*.tmp'))
        db = source / 'scdesk.sqlite3'
        if db.is_file():
            with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as old:
                with closing(sqlite3.connect(staging / 'scdesk.sqlite3')) as new:
                    with new: old.backup(new)
        (staging / 'migration.json').write_text(json.dumps(dict(source=str(source.resolve()), version='0.3.0'), ensure_ascii=False), encoding='utf-8')
        if target.exists(): target.rmdir()  # Empty only; concurrent writes cause a safe failure.
        staging.rename(target)
    finally:
        if staging.exists():
            assert staging.resolve().parent == target.parent.resolve() and staging.name.startswith('.SCMaru-import-')
            shutil.rmtree(staging)


def data_directory(base, override=None, demo=False, appdata=None):
    base = Path(base)
    if override is not None: return Path(override)
    if demo: return base / 'demo-data'
    parent = Path(appdata or os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData/Local'))
    target = parent / 'SCMaru'
    if not target.exists() or not any(target.iterdir()):
        candidates = legacy_directories(base)
        if candidates:
            def modified(path):
                return max(p.stat().st_mtime_ns for p in (path / 'config.json', path / 'scdesk.sqlite3') if p.is_file())
            import_legacy(max(candidates, key=modified), target)
    return target
