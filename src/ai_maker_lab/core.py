"""Configuration, isolated development storage, and side-effect-free launch plans.
SPDX-License-Identifier: MIT
"""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from urllib.parse import urlsplit


class SetupError(ValueError):
    pass


DEFAULTS = {
    'display_name': 'Learner',
    'coach_url': None,
    'terminal': 'foot',
    'bambu_command': 'bambu-studio',
    'minecraft_command': 'prismlauncher',
    'doom_command': 'doomretro',
    'freedoom_wad': None,
    'application_launchers': {},
}


def validate_config(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise SetupError('Unknown configuration fields or invalid object.')
    result = dict(DEFAULTS, **data)
    from .applications import LauncherError, validate_overrides
    try:
        overrides = result['application_launchers']
        validate_overrides(overrides)
        result['application_launchers'] = {key: dict(value) for key, value in overrides.items()}
    except LauncherError as error:
        raise SetupError(str(error)) from error
    name = result['display_name']
    if not isinstance(name, str) or not name.strip() or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise SetupError('Use a short display name without control characters.')
    for key in ('terminal', 'bambu_command', 'minecraft_command', 'doom_command'):
        value = result[key]
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', value):
            raise SetupError('Application commands must be executable names, without arguments or paths.')
    if result['terminal'] not in ('foot', 'xterm'):
        raise SetupError('Supported development terminals: foot, xterm.')
    url = result['coach_url']
    if url is not None:
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise SetupError('Invalid Coach URL.')
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == 'https' and parsed.hostname == 'chatgpt.com'
                     and parsed.port in (None, 443) and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment
                     and parsed.path.startswith(('/g/', '/project/')))
        except ValueError:
            valid = False
        if not valid:
            raise SetupError('Coach needs a parent-approved HTTPS ChatGPT project or GPT URL.')
    wad = result['freedoom_wad']
    if wad is not None:
        if not isinstance(wad, str) or not Path(wad).is_absolute() or Path(wad).suffix.lower() != '.wad':
            raise SetupError('Freedoom requires an absolute local .wad path.')
    return result


def load_config(path=None):
    if path is None:
        return validate_config({})
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise SetupError('Configuration must be a small regular file, not a symlink.')
    try:
        return validate_config(json.loads(path.read_text()))
    except (OSError, ValueError) as error:
        raise SetupError('Configuration could not be read or validated.') from error


class Workspace:
    """Only the current OS user's development directory; never selects another account."""
    def __init__(self, repository):
        self.repository = Path(repository).resolve(strict=True)
        self.storage = self.repository / '.dev-data'
        self.root = self.storage / ('user-' + str(os.getuid()))

    def path(self, relative):
        part = Path(relative)
        if part.is_absolute() or not part.parts or any(p in ('.', '..') for p in part.parts):
            raise SetupError('Workspace paths must be relative and cannot traverse parents.')
        dest = self.root / part
        for item in [self.storage, self.root, *dest.relative_to(self.root).parents]:
            candidate = item if item.is_absolute() else self.root / item
            if candidate.is_symlink():
                raise SetupError('Symlinks are not allowed in development storage.')
            if candidate.exists() and candidate.stat().st_uid != os.getuid():
                raise SetupError('Development storage belongs to another account.')
        if dest.is_symlink() or (dest.exists() and dest.stat().st_uid != os.getuid()):
            raise SetupError('Unsafe workspace destination.')
        if not dest.resolve().is_relative_to(self.root):
            raise SetupError('Path escaped the workspace.')
        return dest

    def initialize(self):
        self.path('Code')  # Validate existing ancestors before creating anything.
        self.root.parent.mkdir(mode=0o700, exist_ok=True)
        self.root.mkdir(mode=0o700, exist_ok=True)
        for name in ('Code', 'Projects', 'Journal', 'Games', 'Games/saves', 'Games/shots'):
            self.path(name).mkdir(parents=True, exist_ok=True, mode=0o700)
        journal = self.path('Journal/Maker-Journal.md')
        if not journal.exists():
            self.save_journal('# Maker Journal\n\nImagine → Predict → Build → Test → Explain\n')

    def read_journal(self):
        return self.path('Journal/Maker-Journal.md').read_text(encoding='utf-8')

    def save_journal(self, text, expected=None):
        """Commit a complete, synced UTF-8 journal by same-directory replacement."""
        if not isinstance(text, str):
            raise SetupError('Journal content must be text.')
        path = self.path('Journal/Maker-Journal.md')

        def revision():
            checked = self.path('Journal/Maker-Journal.md')
            if not checked.exists():
                if expected is not None:
                    raise SetupError('Journal changed outside this window. Reopen before saving.')
                return None
            info = checked.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SetupError('Journal must be a regular file with one link.')
            if expected is not None and checked.read_text(encoding='utf-8') != expected:
                raise SetupError('Journal changed outside this window. Reopen before saving.')
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

        before = revision()
        descriptor, temporary, identity = None, None, None
        try:
            descriptor, name = tempfile.mkstemp(prefix='.maker-journal-', suffix='.tmp', dir=path.parent)
            temporary = Path(name)
            info = os.fstat(descriptor)
            identity = info.st_dev, info.st_ino
            stream = os.fdopen(descriptor, 'w', encoding='utf-8')
            descriptor = None  # The stream now owns the descriptor, including on error.
            with stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            # Recheck conflicts, ownership, links and ancestor paths before commit.
            if revision() != before:
                raise SetupError('Journal changed while saving. Your previous file was not replaced.')
            info = temporary.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != identity):
                raise SetupError('Temporary journal changed unexpectedly. Save cancelled.')
            os.replace(temporary, path)
            temporary = None
        except (OSError, UnicodeError) as error:
            raise SetupError('Journal save failed; the existing file was not replaced. ' + str(error)) from error
        finally:
            cleanup_error = None
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as error:
                    cleanup_error = error
            if temporary is not None:
                try:
                    info = temporary.lstat()
                    if identity is None or (info.st_dev, info.st_ino) != identity:
                        raise OSError('Temporary journal identity changed; refusing to remove another file.')
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError as error:
                    cleanup_error = error
            if cleanup_error is not None:
                raise SetupError('Journal was not saved; temporary-file cleanup also failed. '
                                 'Ask a parent to inspect the journal directory.') from cleanup_error


def launch_plan(activity, config, workspace, which=None, discovery=None):
    """Return argv and cwd only. Never executes a command or writes files."""
    which = shutil.which if which is None else which
    from .applications import LauncherError, command, resolve_application
    def optional(name):
        result = resolve_application(name, config, which=which, discovery=discovery)
        if not result.argv:
            raise SetupError(result.message)
        return result.argv
    if activity == 'coach':
        if not config['coach_url']:
            raise SetupError('Ask a parent to configure Maker Coach.')
        argv = ['xdg-open', config['coach_url']]
    elif activity == 'code':
        code = workspace.path('Code')
        if not code.is_dir():
            raise SetupError('Initialize the development workspace first.')
        try:
            codex = command('codex', which)
        except LauncherError as error:
            raise SetupError('Codex CLI is unavailable: ' + str(error)) from error
        argv = [config['terminal'], '-e', codex, '--cd', str(code)]
    elif activity == 'bambu':
        argv = optional('bambu')
    elif activity == 'minecraft':
        argv = optional('minecraft')
    elif activity == 'freedoom':
        wad = config['freedoom_wad']
        if not wad or not Path(wad).is_file() or Path(wad).is_symlink():
            raise SetupError('Ask a parent to select separately installed Freedoom assets.')
        argv = [*optional('freedoom'), '-iwad', wad, '-noautoload',
                '-savedir', str(workspace.path('Games/saves')),
                '-shotdir', str(workspace.path('Games/shots')),
                '-config', str(workspace.path('Games/doom.cfg'))]
    elif activity == 'projects':
        projects = workspace.path('Projects')
        if not projects.is_dir():
            raise SetupError('Initialize the development workspace first.')
        argv = ['xdg-open', str(projects)]
    else:
        raise SetupError('Unknown activity.')
    try:
        resolved = command(argv[0], which) if not Path(argv[0]).is_absolute() else command(argv[0], lambda name: name)
    except LauncherError as error:
        raise SetupError('Ask a parent to check the application launcher: ' + str(error)) from error
    return [resolved, *argv[1:]], workspace.root


class UserWorkspace(Workspace):
    """Installed-mode storage in the current user's XDG data directory."""
    def __init__(self, layout):
        self.layout = layout
        self.repository = layout.data / 'ai-maker-lab'
        self.storage = self.repository
        self.root = layout.workspace

    def path(self, relative):
        from .paths import PathError, safe_path
        try:
            safe_path(self.root / relative, self.layout.home)
        except PathError as error:
            raise SetupError(str(error)) from error
        return super().path(relative)

    def initialize(self):
        from .paths import safe_path
        safe_path(self.root, self.layout.home)
        self.storage.mkdir(parents=True, exist_ok=True)
        super().initialize()
