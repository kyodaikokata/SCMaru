"""Copy selected, unmodified KotobaLive fonts and licenses into SCDesk assets."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
source = root.parent / 'KotobaLive'
manifest = json.loads((source / 'web/fonts/manifest.json').read_text(encoding='utf-8'))
families = {'M PLUS Rounded 1c', 'M PLUS 1p', 'Zen Maru Gothic', 'Zen Kaku Gothic New',
            'Noto Sans JP', 'Yusei Magic', 'Kaisei Decol', 'Nico Moji'}
target = root / 'assets/fonts'
target.mkdir(parents=True, exist_ok=True)
entries = []
for item in manifest['fonts']:
    if item['family'] not in families: continue
    path = source / 'web/fonts' / item['file']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise ValueError(f'Font hash mismatch: {path.name}')
    shutil.copyfile(path, target / path.name)
    license_source = source / item['license']
    license_target = target / 'licenses' / license_source.parent.name / license_source.name
    license_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_source, license_target)
    entries.append(dict(item, license=license_target.relative_to(target).as_posix()))
(target / 'manifest.json').write_text(json.dumps(dict(revision=manifest['revision'], fonts=entries), ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Imported {len(families)} families / {len(entries)} font faces with licenses')
