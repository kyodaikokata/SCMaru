"""Download and stage a verified Windows release for in-place replacement."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen
import zipfile


REPOSITORY = 'https://github.com/kyodaikokata/SCMaru'
LATEST = 'https://api.github.com/repos/kyodaikokata/SCMaru/releases/latest'
PACKAGE_ENTRIES = {
    'SCMaru.exe', '_internal', 'VERSION.txt', 'README.md', 'CHANGELOG.md',
    'IDENTITY_CODE_GUIDE.md', 'LIVEHIME.md', 'FONT_LICENSES.txt', 'THIRD_PARTY_LICENSES.txt',
}


def check(current):
    request = Request(LATEST, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'SCMaru'})
    with urlopen(request, timeout=15) as response:
        release = json.load(response)
    tag = release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Unexpected release tag')
    version = tag[1:]
    if tuple(map(int, version.split('.'))) <= tuple(map(int, current.split('.'))):
        return None
    name = f'SCMaru-{version}-Windows-x64.zip'
    url = f'{REPOSITORY}/releases/download/{tag}/{name}'
    for asset in release['assets']:
        digest = asset.get('digest') or ''
        if (asset['name'] == name and asset['browser_download_url'] == url
                and asset['state'] == 'uploaded' and re.fullmatch(r'sha256:[a-f0-9]{64}', digest)):
            return version, url, asset['size'], digest[7:]
    raise ValueError('Verified Windows asset missing')


def stage_update(release, install_dir):
    version, url, size, digest = release
    install_dir = install_dir.resolve()
    staging = Path(tempfile.mkdtemp(prefix='.scmaru-update-', dir=install_dir))
    try:
        archive = staging / 'release.zip'
        checksum = hashlib.sha256()
        total = 0
        with urlopen(url, timeout=30) as response, archive.open('wb') as output:
            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > size:
                    raise ValueError('Unexpected download size')
                checksum.update(chunk)
                output.write(chunk)
        if total != size or checksum.hexdigest() != digest:
            raise ValueError('Download checksum mismatch')
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                path = PurePosixPath(entry.filename)
                if (not path.parts or path.parts[0] != 'SCMaru' or '..' in path.parts
                        or (len(path.parts) > 1 and path.parts[1] not in PACKAGE_ENTRIES)
                        or any(PureWindowsPath(part).is_reserved() or part.endswith(('.', ' '))
                               or re.search(r'[\\:<>|?*"]', part) for part in path.parts)):
                    raise ValueError('Unexpected ZIP path')
            package.extractall(staging)
        app = staging / 'SCMaru'
        if ((app / 'VERSION.txt').read_text(encoding='utf-8').strip() != version
                or not (app / 'SCMaru.exe').is_file() or not (app / '_internal').is_dir()):
            raise ValueError('Unexpected app layout')
        archive.unlink()
        shutil.copyfile(Path(__file__).parent / 'assets' / 'apply_update.ps1', staging / 'apply_update.ps1')
    except Exception:
        if staging.resolve().parent == install_dir:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def launch_update(staging, data_dir, failure_message):
    install_dir = staging.parent
    data_dir = data_dir.resolve()
    if any(data_dir.is_relative_to(install_dir / name) for name in PACKAGE_ENTRIES):
        raise OSError('Data directory overlaps the program files')
    env = dict(os.environ,
               SCMARU_UPDATE_STAGE=str(staging),
               SCMARU_UPDATE_PID=str(os.getpid()),
               SCMARU_UPDATE_ARGS=subprocess.list2cmdline(['--data-dir', str(data_dir)]),
               SCMARU_UPDATE_FAILURE=failure_message,
               PYINSTALLER_RESET_ENVIRONMENT='1')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen(
        [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-File', str(staging / 'apply_update.ps1')],
        cwd=install_dir, env=env, creationflags=subprocess.CREATE_NO_WINDOW,
    )
