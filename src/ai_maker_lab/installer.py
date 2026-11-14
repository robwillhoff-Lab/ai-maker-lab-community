"""Offline zipapp installation with a strict ownership inventory. SPDX-License-Identifier: MIT."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from .paths import Layout, PathError, safe_path
from .system_check import inspect_system

PACKAGE_FILES = ('__init__.py', '__main__.py', 'core.py', 'gui.py',
                 'paths.py', 'system_check.py', 'installer.py', 'applications.py')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def regular_bytes(path, layout):
    safe_path(path, layout.home)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PathError('Expected a regular installation file with one link.')
    return path.read_bytes()


def source_bytes(repository, relative):
    repository = Path(repository).resolve(strict=True)
    source = repository / relative
    for candidate in (source, *source.parents):
        if candidate == repository:
            break
        if candidate.is_symlink():
            raise PathError('Symlinked package source or license is not supported.')
    if not source.is_file() or source.stat().st_nlink != 1:
        raise PathError('Package source must be a regular file with one link.')
    return source.read_bytes()


def zipapp_bytes(repository):
    """Explicit source allowlist; no build hooks, downloads, or recursive copies."""
    repository = Path(repository)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        bootstrap = ('from ai_maker_lab.__main__ import main\n'
                     'raise SystemExit(main(user_local=True))\n')
        entries = {'__main__.py': bootstrap.encode()}
        for name in PACKAGE_FILES:
            entries['ai_maker_lab/' + name] = source_bytes(repository, 'src/ai_maker_lab/' + name)
        entries['LICENSE'] = source_bytes(repository, 'LICENSE')
        for name, content in sorted(entries.items()):
            archive.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), content)
    return output.getvalue()


def desktop_quote(value):
    value = str(value)
    if any(c in value for c in ('\n', '\r', '\x00')):
        raise PathError('Invalid desktop command path.')
    value = value.replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value + '"'


def payloads(repository, layout):
    interpreter = Path(sys.executable)
    if not interpreter.is_absolute():
        raise PathError('Python interpreter path must be absolute.')
    command = ' '.join(desktop_quote(arg) for arg in
                       (interpreter, '-I', '-B', layout.owned_paths()['app.pyz']))
    desktop = ('[Desktop Entry]\nType=Application\nName=AI Maker Lab (Portable)\n'
               'Comment=Parent-guided creative learning\nExec=' + command + '\n'
               'Icon=applications-science\nTerminal=false\nCategories=Education;\n')
    return {'app.pyz': zipapp_bytes(repository),
            'LICENSE': source_bytes(repository, 'LICENSE'),
            'desktop': desktop.encode()}


def plan(layout, report, operation='install'):
    paths = layout.owned_paths()
    collisions = [str(path) for path in (*paths.values(), layout.manifest)
                  if path.exists() or path.is_symlink()]
    directories = set()
    for path in (*paths.values(), layout.manifest):
        parent = path.parent
        while parent != layout.home and not parent.exists():
            directories.add(str(parent))
            parent = parent.parent
    return {
        'operation': operation,
        'ready': not collisions and not layout.install_dir.exists() and not report['missing_required'],
        'package_source_files': list(PACKAGE_FILES),
        'files': {name: str(path) for name, path in paths.items()},
        'manifest': str(layout.manifest),
        'directories_may_create': sorted(directories),
        'preserved': [str(layout.workspace), str(layout.config_file), str(layout.state / 'ai-maker-lab')],
        'collisions': collisions,
        'missing_required': report['missing_required'],
        'missing_optional': report['missing_optional'],
        'existing_installations': report['existing_installations'],
    }


def validate_layout(layout):
    for path in (*layout.owned_paths().values(), layout.manifest, layout.workspace, layout.config_file):
        safe_path(path, layout.home)


def create_parents(path, layout, created):
    safe_path(path, layout.home)
    if path.exists():
        if not path.is_dir():
            raise PathError('Installation parent is not a directory.')
        return
    create_parents(path.parent, layout, created)
    path.mkdir()  # No chmod or changes to existing permissions.
    created.append(path)


def write_new(path, content, layout):
    safe_path(path, layout.home)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
    except Exception:
        # A failed write must not leave an unmanifested partial payload behind.
        # Only unlink the exact regular inode exclusively created above.
        safe_path(path, layout.home)
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_nlink) == (identity.st_dev, identity.st_ino, 1):
            path.unlink()
        raise


def install(repository, layout, report=None, dry_run=True):
    validate_layout(layout)
    report = inspect_system(layout) if report is None else report
    result = plan(layout, report)
    if dry_run:
        return result
    if os.geteuid() == 0:
        raise PathError('Run as an ordinary user, never root.')
    if result['collisions'] or layout.install_dir.exists():
        raise PathError('Existing destination detected; no files overwritten. Verify it before uninstall/reinstall.')
    if report['missing_required']:
        raise PathError('Required dependencies are missing. No files created.')
    content = payloads(repository, layout)
    manifest = {'schema': 1, 'files': {key: digest(value) for key, value in content.items()}}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    writes, directories = [], []
    try:
        for key, path in layout.owned_paths().items():
            create_parents(path.parent, layout, directories)
            write_new(path, content[key], layout)
            writes.append((path, content[key]))
        write_new(layout.manifest, manifest_bytes, layout)
        writes.append((layout.manifest, manifest_bytes))
    except Exception:
        # Roll back only byte-identical files this attempt successfully created.
        for path, original in reversed(writes):
            if regular_bytes(path, layout) == original:
                path.unlink()
        for directory in reversed(directories):
            try:
                directory.rmdir()  # Never recursive; preserve anything added later.
            except OSError:
                pass
        raise
    return result


def verify(layout):
    validate_layout(layout)
    raw = regular_bytes(layout.manifest, layout)
    if len(raw) > 16384:
        raise PathError('Oversized installation manifest.')
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise PathError('Invalid installation manifest.') from error
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'files'}
            or type(manifest['schema']) is not int or manifest['schema'] != 1
            or not isinstance(manifest['files'], dict)
            or set(manifest['files']) != set(layout.owned_paths())):
        raise PathError('Manifest does not match the fixed installation inventory.')
    for key, path in layout.owned_paths().items():
        if digest(regular_bytes(path, layout)) != manifest['files'][key]:
            raise PathError('Installed file was changed; nothing will be removed: ' + key)
    return manifest


def uninstall(layout, dry_run=True):
    manifest = verify(layout)  # Validate every file before removing any file.
    result = {'operation': 'uninstall',
              'files': [str(path) for path in (*layout.owned_paths().values(), layout.manifest)],
              'preserved': [str(layout.workspace), str(layout.config_file), str(layout.state / 'ai-maker-lab')]}
    if dry_run:
        return result
    if os.geteuid() == 0:
        raise PathError('Run as an ordinary user, never root.')
    for key, path in layout.owned_paths().items():
        if digest(regular_bytes(path, layout)) != manifest['files'][key]:
            raise PathError('Installation changed during removal; stop and inspect.')
        path.unlink()
    layout.manifest.unlink()
    try:
        layout.install_dir.rmdir()  # Leave unrelated files and all parent directories.
    except OSError:
        pass
    return result
