"""Build the portable app while preserving an existing user's adjacent data directory."""
from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys
import runpy
import argparse
from version import VERSION

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--staging', action='store_true', help='Build separately while the installed app keeps running')
parser.add_argument('--stage-dir', default='package-stage', help='Workspace-relative staging directory')
options = parser.parse_args()
dist_root = root / options.stage_dir if options.staging else root / 'releases' / VERSION
output = dist_root / 'SCMaru'
assert output.resolve().is_relative_to(root)
data = output / 'data'
backup = None
if data.is_dir():
    backup = root / 'data-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    shutil.copytree(data, backup)
version_file = root / 'build' / 'version-info.txt'
version_file.parent.mkdir(exist_ok=True)
numbers = tuple(map(int, VERSION.split('.'))) + (0,)
version_file.write_text(f"""VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r},prodvers={numbers!r},mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','SCMaru · SC丸'),StringStruct('FileVersion','{VERSION}'),StringStruct('ProductName','SCMaru'),StringStruct('ProductVersion','{VERSION}'),StringStruct('OriginalFilename','SCMaru.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])""", encoding='utf-8')
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir', '--name', 'SCMaru', '--version-file', str(version_file),
        '--distpath', str(dist_root), '--collect-all', 'blivedm', '--collect-all', 'qrcode', '--collect-all','pypinyin', '--icon', 'assets/icon.ico', '--add-data', 'assets;assets', 'app.py']
result = subprocess.run(args, cwd=root)
if backup:
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(backup, data, dirs_exist_ok=True)
if result.returncode: raise SystemExit(result.returncode)
runpy.run_path(str(root / 'prepare_release.py'), init_globals={'RELEASE_DIR': output}, run_name='__main__')
