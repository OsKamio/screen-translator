"""Build an offline-capable Windows x64 bundle and optional per-user installer.

Usage: python scripts/build_windows.py --iscc ".../ISCC.exe" --out dist
Requires requirements.txt, requirements-build.txt and Inno Setup 6.7+.
Only explicit source assets and installed dependency resources are collected.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.2.0'
DEPENDENCIES = ['PySide6', 'mss', 'onnxruntime', 'rapidocr-onnxruntime',
                'requests', 'opencv-python', 'numpy']


def prepare_notices():
    from packaging.requirements import Requirement
    dest = ROOT/'packaging'/'generated'/'licenses'
    assert dest.resolve().is_relative_to((ROOT/'packaging'/'generated').resolve())
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT/'packaging'/'licenses', dest, dirs_exist_ok=True)
    queue = list(DEPENDENCIES)
    seen = set()
    inventory = []
    while queue:
        name = queue.pop(0)
        dist = metadata.distribution(name)
        key = dist.metadata['Name'].lower().replace('_', '-')
        if key in seen: continue
        seen.add(key)
        inventory.append({'name': dist.metadata['Name'], 'version': dist.version,
                          'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', '')})
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ('license', 'copying', 'copyright', 'notice')):
                source = Path(dist.locate_file(item))
                if source.is_file() and source.suffix.lower() not in ('.py', '.pyi', '.pyc', '.pyd', '.dll'):
                    target = dest/key/str(item).replace('../', '')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        for text in dist.requires or []:
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate({'extra': ''}): queue.append(req.name)
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file(): raise RuntimeError('Python license was not found')
    shutil.copyfile(python_license, dest/'Python-LICENSE.txt')
    (dest/'dependency-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT/'dist')
    parser.add_argument('--bundle-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize < 2**32: raise SystemExit('Windows x64 Python is required')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    prepare_notices()
    # Desktop tooling can prepend unrelated native DLLs to PATH (e.g. Poppler's
    # ICU). Restrict discovery to Python and Windows so they cannot shadow Qt's
    # Windows ICU API in the delivered application.
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix,
        str(Path(sys.base_prefix)/'DLLs'), str(Path(os.environ['WINDIR'])/'System32'),
        os.environ['WINDIR']])
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(out), '--workpath', str(ROOT/'build'/'pyinstaller'),
        str(ROOT/'packaging'/'windows.spec')], cwd=ROOT, check=True, env=env)
    bundle = out/'ScreenTranslator'
    # Never collect runtime user settings or developer environments.
    forbidden = [p for p in bundle.rglob('*') if p.name.lower() in ('config.json', '.env')]
    if forbidden: raise RuntimeError('Unexpected user configuration in bundle')
    archive = out/f'ScreenTranslator-{VERSION}-Portable-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(bundle.rglob('*')):
            if path.is_file(): z.write(path, path.relative_to(out))
    artifacts = [archive]
    if not args.bundle_only:
        if not args.iscc or not args.iscc.is_file(): raise SystemExit('Use --iscc to specify the Inno Setup compiler')
        subprocess.run([str(args.iscc.resolve()), '/Qp', f'/DBundleDir={bundle}',
            f'/DOutputDir={out}', str(ROOT/'packaging'/'windows.iss')], check=True, cwd=ROOT)
        artifacts.append(out/f'ScreenTranslator-{VERSION}-Setup-x64.exe')
    lines = [f'{hashlib.file_digest(path.open("rb"), "sha256").hexdigest()}  {path.name}' for path in artifacts]
    (out/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n', encoding='ascii')
    print('BUILD_DONE '+str(out), flush=True)


if __name__ == '__main__': main()
