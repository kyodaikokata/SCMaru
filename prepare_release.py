"""Add documentation and third-party license texts to an existing PyInstaller build."""
import importlib.metadata
from pathlib import Path
import shutil
import sys
import zipfile
from version import VERSION

root = Path(__file__).resolve().parent
release = Path(globals().get('RELEASE_DIR', root / 'releases' / VERSION / 'SCMaru')).resolve()
assert release.is_relative_to(root)
if not (release / 'SCMaru.exe').is_file():
    raise SystemExit('Build SCMaru.exe first')
shutil.copyfile(root / 'README.md', release / 'README.md')
shutil.copyfile(root / 'CHANGELOG.md', release / 'CHANGELOG.md')
(release / 'VERSION.txt').write_text(VERSION + '\n', encoding='utf-8')
shutil.copyfile(root / 'IDENTITY_CODE_GUIDE.md', release / 'IDENTITY_CODE_GUIDE.md')
shutil.copyfile(root / 'LIVEHIME.md', release / 'LIVEHIME.md')
font_manifest = root / 'assets/fonts/manifest.json'
if font_manifest.is_file():
    import json
    manifest = json.loads(font_manifest.read_text(encoding='utf-8'))
    font_notes = ['Bundled unmodified fonts copied from KotobaLive.\n']
    done = set()
    for entry in manifest['fonts']:
        if entry['license'] in done: continue
        done.add(entry['license'])
        font_notes.append('\n' + entry['family'] + '\nSource: ' + entry['source'] + '\n' +
                          (root / 'assets/fonts' / entry['license']).read_text(encoding='utf-8'))
    (release / 'FONT_LICENSES.txt').write_text('\n'.join(font_notes), encoding='utf-8')
parts = ['SCMaru third-party components\n',
         'blivedm source: https://github.com/xfgryujk/blivedm\nCommit: 3bf17fe862b8c2fc6bc04c81c3f0c5db95de93d6\n',
         'Connection approach reference: https://github.com/xfgryujk/blivechat\n']
for package in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    texts = []
    for file in package.files or []:
        if any(x in file.name.lower() for x in ('license', 'copying', 'notice')) and file.suffix.lower() in ('', '.txt', '.md', '.rst'):
            path = Path(package.locate_file(file))
            if path.is_file(): texts.append(path.read_text(encoding='utf-8', errors='replace'))
    if texts:
        parts.append(f"\n{'=' * 72}\n{package.metadata['Name']} {package.version}\n" + '\n'.join(texts))
for name in ('LICENSE.txt', 'LICENSE'):
    path = Path(sys.base_prefix) / name
    if path.is_file():
        parts.append('\nPython runtime\n' + path.read_text(encoding='utf-8', errors='replace'))
        break
(release / 'THIRD_PARTY_LICENSES.txt').write_text('\n'.join(parts), encoding='utf-8')
archive = root / 'releases' / VERSION / f'SCMaru-{VERSION}-Windows-x64.zip'
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(release.rglob('*')):
        if path.is_file() and not any(p in ('data', 'demo-data') for p in path.relative_to(release).parts):
            z.write(path, Path('SCMaru') / path.relative_to(release))
print(archive)
