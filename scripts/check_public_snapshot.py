#!/usr/bin/env python3
"""Read-only checks for the explicit public source snapshot. SPDX-License-Identifier: MIT."""
import argparse
import ast
import json
import os
from pathlib import Path
import pwd
import re
import stat

PRIVATE_NAMES = {'public-release-audit.md', 'public-snapshot-plan.md', 'privacy-audit.md',
                 'preparation-report.md', 'SANITIZATION-PLAN.md', 'metadata-summary.json',
                 'bundle-verification.txt', 'verification.json'}
PRIVATE_PARTS = {'.git', '.dev-data', '.aws', '.ssh', '.codex', '.cache', '__pycache__',
                 'backups', 'worlds', 'saves', 'profiles', 'node_modules', '.venv'}
PUBLIC_URLS = {'https://learn.chatgpt.com/docs/sandboxing',
               'https://github.com/robwillhoff-Lab/ai-maker-lab-community',
               'https://github.com/robwillhoff-Lab/ai-maker-lab-community/issues/1',
               'https://github.com/github/gitignore/blob/main/LICENSE'}
FIXTURE_URLS = {'https://chatgpt.com/g/example', 'http://chatgpt.com/g/example',
                'https://chatgpt.com.evil.invalid/g/example',
                'https://chatgpt.com:bad/g/example',
                'https://chatgpt.com/g/example?token=value',
                'https://chatgpt.com/g/example' + chr(92) + 'n'}
PATTERNS = {
    'credential token': r'(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})',
    'private key': r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'email address': r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
    'credential assignment': r'''(?im)^\s*["']?(?:api_key|access_token|password|client_secret)["']?\s*[:=]\s*["']?[^\s"']{8,}''',
}


def inventory(root):
    manifest = root / 'release/public-files.txt'
    if manifest.is_symlink():
        raise ValueError('The file inventory must not be a symlink.')
    names = [line.strip() for line in manifest.read_text().splitlines() if line.strip()]
    if len(set(names)) != len(names) or not names:
        raise ValueError('Empty or duplicate inventory entries.')
    for name in names:
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != name
                or set(path.parts) & PRIVATE_PARTS or path.name in PRIVATE_NAMES
                or path.name.startswith('.env') or 'private-backup' in name
                or path.suffix in ('.bundle', '.pack', '.idx', '.rev', '.pyc')):
            raise ValueError('Forbidden path in public inventory.')
    if not {'LICENSE', 'README.md', 'pyproject.toml', 'release/public-files.txt'} <= set(names):
        raise ValueError('Missing required release inventory entries.')
    return names


def check(root, source=False, snapshot=False):
    root = Path(root).resolve()
    errors = []
    def fail(name, category):
        errors.append(name + ': ' + category)
    try:
        names = inventory(root)
    except (OSError, ValueError) as error:
        return ['release/public-files.txt: ' + str(error)]
    selected = set(names)
    if not source:
        found = set()
        for directory, dirs, files in os.walk(root, followlinks=False):
            base = Path(directory)
            if base == root and '.git' in dirs:
                if snapshot or (base / '.git').is_symlink():
                    fail('.git', 'Git metadata forbidden in a source snapshot')
                dirs.remove('.git')  # Never read original or future identity metadata here.
            for name in dirs:
                path = base / name
                if path.is_symlink():
                    fail(path.relative_to(root).as_posix(), 'symlink directory')
            for name in files:
                found.add((base / name).relative_to(root).as_posix())
        for name in sorted(found - selected):
            fail(name, 'file outside public inventory')
    accounts = {entry.pw_name for entry in pwd.getpwall() if 1000 <= entry.pw_uid < 65534
                and entry.pw_name not in ('learner1', 'learner2')}
    for name in names:
        path = root / name
        if any((root / parent).is_symlink() for parent in (Path(name), *Path(name).parents)):
            fail(name, 'symlink path')
            continue
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError('not a regular file')
            body = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError, ValueError):
            fail(name, 'missing, nonregular, or nontext file')
            continue
        if '\x00' in body:
            fail(name, 'binary content')
        for category, pattern in PATTERNS.items():
            if re.search(pattern, body):
                fail(name, category)
        public_body = body.replace('robwillhoff-Lab', 'PUBLIC_COPYRIGHT_HOLDER')
        if any(re.search(r'(?<![A-Za-z0-9_])' + re.escape(account) + r'(?![A-Za-z0-9_])',
                         public_body, re.IGNORECASE) for account in accounts):
            fail(name, 'local account identifier')
        if any(account not in ('learner1', 'learner2') for account in re.findall(r'/home/([A-Za-z0-9_.-]+)', body)):
            fail(name, 'personal home path')
        allowed = set(PUBLIC_URLS)
        if name in ('tests/test_portable.py', 'scripts/check_public_snapshot.py'):
            allowed |= FIXTURE_URLS
        for url in re.findall(r'''https?://[A-Za-z0-9][^\s)<>"']*''', body):
            if url not in allowed:
                fail(name, 'URL requires review')
        if path.suffix == '.py':
            try:
                ast.parse(body, filename=name)
            except SyntaxError:
                fail(name, 'Python syntax')
        if path.suffix == '.json':
            try:
                json.loads(body)
            except ValueError:
                fail(name, 'JSON syntax')
        if path.suffix == '.md':
            if sum(line.startswith('```') for line in body.splitlines()) % 2:
                fail(name, 'unbalanced code fences')
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', body):
                if target.startswith('https://'):
                    continue
                destination = (path.parent / target.split('#')[0]).resolve()
                if not destination.is_relative_to(root) or destination.relative_to(root).as_posix() not in selected:
                    fail(name, 'link outside public inventory')
        if not body.endswith('\n') or any(line.rstrip() != line for line in body.splitlines()):
            fail(name, 'text formatting')
        if name == 'LICENSE' and not all(marker in body for marker in (
                'MIT License', 'Copyright (c) 2026 robwillhoff-Lab',
                'Permission is hereby granted, free of charge', 'THE SOFTWARE IS PROVIDED "AS IS"')):
            fail(name, 'MIT license or notice missing')
        if name.startswith('src/') and 'MIT' not in '\n'.join(body.splitlines()[:4]):
            fail(name, 'project license marker missing')
        if name == 'pyproject.toml' and not re.search(r'(?m)^version = "0\.1\.0a0"$', body):
            fail(name, 'alpha package version mismatch')
        if name == 'README.md' and 'v0.1.0-alpha' not in body:
            fail(name, 'human release name missing')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--source', action='store_true', help='Validate only selected files in a private source tree')
    mode.add_argument('--snapshot', action='store_true', help='Require exact inventory and no Git metadata')
    args = parser.parse_args()
    errors = check(args.root, source=args.source, snapshot=args.snapshot)
    if errors:
        print('FAIL\n' + '\n'.join(errors))
        return 1
    print('PASS: ' + str(len(inventory(args.root))) + ' public files; inventory, privacy, notices, syntax, links, version')
    if args.source:
        print('Source mode excludes all non-allowlisted records; it does not certify Git history for publication.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
