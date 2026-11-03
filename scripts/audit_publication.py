"""扫描待发布文件和 Git 历史，可对照本机私人配置；不输出或保存密钥值。"""
from __future__ import annotations
import argparse
import ast
import base64
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, quote_plus

TOKEN_PATTERNS = [re.compile(rb'gh[pousr]_[A-Za-z0-9]{24,}'),
                  re.compile(rb'github_pat_[A-Za-z0-9_]{35,}'),
                  re.compile(rb'(?<![A-Za-z0-9_-])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}'),
                  re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{32,}'),
                  re.compile(rb'AKIA[0-9A-Z]{16}')]
FORBIDDEN = re.compile(r'(^|/)(?:\.env(?:\..*)?|config(?:\.[^/]*)?\.json(?:\..*)?|[^/]+\.(?:pem|pfx|p12|key))$', re.I)
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', '_tmp_cfg', 'dist', 'build'}


def git(root, *arguments):
    result = subprocess.run(['git', '-C', str(root), *arguments], capture_output=True)
    return result.returncode, result.stdout


def defaults(root):
    tree = ast.parse((root/'core'/'config.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'DEFAULTS':
            return ast.literal_eval(node.value)
    raise RuntimeError('Cannot locate literal DEFAULTS')


def flatten(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from flatten(item, path+(str(key),))
    elif isinstance(value, str):
        yield path, value
        if value.lstrip().startswith(('{', '[')):
            try:
                yield from flatten(json.loads(value), path+('embedded_json',))
            except (ValueError, TypeError):
                pass
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from flatten(item, path+(str(index),))


def private_values(paths, standard):
    known = {value for _path, value in flatten(standard.get('api', {}))}
    sensitive = set()
    loaded = 0
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        loaded += 1
        for _field, value in flatten(data.get('api', {})):
            if len(value) >= 6 and value not in known:
                sensitive.add(value)
        for _field, value in flatten(data):
            for pattern in TOKEN_PATTERNS:
                sensitive.update(match.decode('ascii') for match in pattern.findall(value.encode('utf-8')))
    variations = set()
    for value in sensitive:
        raw = value.encode('utf-8')
        variations.update((raw, quote(value, safe='').encode(), quote_plus(value).encode(),
                           json.dumps(value, ensure_ascii=True)[1:-1].encode(), base64.b64encode(raw)))
    return {value for value in variations if len(value) >= 6}, loaded, len(sensitive)


def scan_blob(name, data, sensitive, findings):
    if any(value in data for value in sensitive):
        findings.append({'path': name, 'reason': 'matches private configuration material'})
    if any(pattern.search(data) for pattern in TOKEN_PATTERNS):
        findings.append({'path': name, 'reason': 'credential-like literal'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--private-config', type=Path, action='append', default=[])
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    standard = defaults(root)
    sensitive, count, protected = private_values(args.private_config, standard)
    findings = []
    for field, value in flatten(standard['api']):
        if field[-1] in {'api_key', 'key', 'appid', 'url'} and value:
            findings.append({'path': 'core/config.py', 'reason': 'non-empty credential default'})
    tracked = False
    if (root/'.git').exists():
        status, names = git(root, 'ls-files', '-z')
        if status:
            raise RuntimeError('Cannot inspect Git index')
        paths = [name.decode('utf-8') for name in names.split(b'\0') if name]
        tracked = bool(paths)
    if not tracked:
        paths = [str(path.relative_to(root)).replace('\\', '/') for path in root.rglob('*')
                 if path.is_file() and not any(part in SKIP or part.startswith('_backup') for part in path.relative_to(root).parts)]
    for name in sorted(paths):
        if FORBIDDEN.search(name) or any(part in SKIP or part.startswith('_backup') for part in Path(name).parts):
            findings.append({'path': name, 'reason': 'private or generated path in publication'})
        path = root/name
        if path.is_symlink():
            findings.append({'path': name, 'reason': 'symlink'})
            continue
        if tracked:
            status, data = git(root, 'show', ':'+name)
            if status:
                raise RuntimeError('Cannot read staged publication data')
        else:
            data = path.read_bytes()
        scan_blob(name, data, sensitive, findings)
    history_count = 0
    if tracked:
        status, objects = git(root, 'rev-list', '--objects', '--all')
        if status:
            raise RuntimeError('Cannot inspect repository history')
        for record in objects.decode('utf-8', errors='replace').splitlines():
            parts = record.split(' ', 1)
            if len(parts) != 2:
                continue
            oid, name = parts
            status, kind = git(root, 'cat-file', '-t', oid)
            if status == 0 and kind.strip() == b'blob':
                status, data = git(root, 'cat-file', '-p', oid)
                if status:
                    raise RuntimeError('Cannot read history blob')
                scan_blob('history:'+name, data, sensitive, findings)
                if FORBIDDEN.search(name):
                    findings.append({'path': 'history:'+name, 'reason': 'private file in history'})
                history_count += 1
    report = {'passed': not findings, 'files_checked': len(paths), 'history_blobs_checked': history_count,
              'private_configurations_compared': count, 'private_values_protected': protected,
              'findings': findings, 'note': 'No credential values or private configuration contents are written to this report.'}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
