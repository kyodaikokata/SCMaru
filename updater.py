"""Download and stage a verified Windows release next to the current app."""
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
from urllib.request import Request, urlopen
import zipfile


REPOSITORY = 'https://github.com/kyodaikokata/SCMaru'
LATEST = 'https://api.github.com/repos/kyodaikokata/SCMaru/releases/latest'


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


def install(release, parent):
    version, url, size, digest = release
    destination = parent / f'SCMaru-{version}'
    if destination.exists():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix='.scmaru-update-', dir=parent) as directory:
        staging = Path(directory)
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
                        or any(PureWindowsPath(part).is_reserved() or part.endswith(('.', ' '))
                               or re.search(r'[\\:<>|?*"]', part) for part in path.parts)):
                    raise ValueError('Unexpected ZIP path')
            package.extractall(staging)
        app = staging / 'SCMaru'
        if ((app / 'VERSION.txt').read_text(encoding='utf-8').strip() != version
                or not (app / 'SCMaru.exe').is_file() or not (app / '_internal').is_dir()):
            raise ValueError('Unexpected app layout')
        app.rename(destination)
    return destination / 'SCMaru.exe'
