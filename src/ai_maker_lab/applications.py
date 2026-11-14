"""Read-only optional application discovery and validated argv. SPDX-License-Identifier: MIT."""
import configparser
from dataclasses import dataclass
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import stat


class LauncherError(ValueError):
    pass


SPECS = {
    'bambu': {'command': 'bambu_command', 'aliases': ('bambu-studio', 'BambuStudio', 'bambustudio'),
              'names': ('Bambu Studio', 'BambuStudio'), 'stem': 'bambu',
              'flatpak': 'com.bambulab.BambuStudio'},
    'minecraft': {'command': 'minecraft_command', 'aliases': ('prismlauncher', 'PrismLauncher'),
                  'names': ('Prism Launcher', 'PrismLauncher'), 'stem': 'prism',
                  'flatpak': 'org.prismlauncher.PrismLauncher'},
    'freedoom': {'command': 'doom_command', 'aliases': ('doomretro',),
                 'names': ('DOOM Retro',), 'stem': 'doomretro', 'flatpak': None},
}


def clean_string(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)


def validate_overrides(overrides):
    if not isinstance(overrides, dict) or set(overrides) - set(SPECS):
        raise LauncherError('Application launchers must be an object for bambu, minecraft, or freedoom.')
    for activity, launcher in overrides.items():
        if not isinstance(launcher, dict):
            raise LauncherError('Each application launcher must be an object.')
        kind = launcher.get('kind')
        if kind == 'executable' and set(launcher) == {'kind', 'path'}:
            value = launcher['path']
            if (not clean_string(value) or not (Path(value).is_absolute() or value.startswith('~/'))
                    or '..' in Path(value).parts or any(c in value for c in ('$', '`', '|', ';', '&'))):
                raise LauncherError('Executable paths must be absolute or start with ~/; no shell syntax or parent traversal.')
        elif kind == 'flatpak' and set(launcher) == {'kind', 'app_id', 'scope'}:
            if activity == 'freedoom':
                raise LauncherError('Freedoom currently needs a native executable for workspace file access.')
            if (not isinstance(launcher['app_id'], str)
                    or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){2,}', launcher['app_id'])
                    or launcher['scope'] not in ('user', 'system')):
                raise LauncherError('Flatpak needs a valid application ID and user/system scope.')
        else:
            raise LauncherError('Supported launcher kinds are executable and flatpak with the documented fields.')
    return overrides


def trusted_owner(path, owner):
    if owner in (0, os.getuid()):
        return True
    # Some managed user namespaces expose unmapped host-root files as overflowuid.
    # This exception requires both a missing inner-root mapping and an immutable
    # filesystem; ordinary foreign-owned mutable files remain rejected.
    try:
        overflow = int(Path('/proc/sys/kernel/overflowuid').read_text())
        ranges = [tuple(map(int, line.split())) for line in Path('/proc/self/uid_map').read_text().splitlines()]
        root_mapped = any(start == 0 and length > 0 for start, outer, length in ranges)
        return owner == overflow and not root_mapped and bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except (OSError, ValueError):
        return False


def executable(path):
    path = Path(path)
    if not path.is_absolute() or not clean_string(str(path)):
        raise LauncherError('Launcher did not resolve to an absolute executable path.')
    try:
        info = path.stat()  # Native executable symlinks are allowed if their target passes validation.
    except OSError as error:
        raise LauncherError('Executable was not found or cannot be read.') from error
    if not stat.S_ISREG(info.st_mode):
        raise LauncherError('Launcher target is not a regular file.')
    if not os.access(path, os.X_OK):
        raise LauncherError('Launcher target is not executable; no permissions were changed.')
    if info.st_mode & 0o022 or not trusted_owner(path, info.st_uid):
        raise LauncherError('Launcher target has untrusted ownership or is group/world writable.')
    return str(path)


def command(name, which=None):
    found = (shutil.which if which is None else which)(name)
    if not found:
        raise LauncherError('Command not found on PATH: ' + name)
    return executable(found)


@dataclass(frozen=True)
class Discovery:
    home: Path
    desktop_dirs: tuple
    appimage_dirs: tuple
    flatpak_roots: tuple
    binary_dirs: tuple

    @classmethod
    def current(cls):
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
        if not data.is_absolute():
            data = home / '.local/share'
        return cls(home,
                   (data / 'applications', Path('/usr/local/share/applications'), Path('/usr/share/applications'),
                    data / 'flatpak/exports/share/applications', Path('/var/lib/flatpak/exports/share/applications')),
                   (home / 'Applications', home / 'AppImages', home / '.local/bin'),
                   (('user', data / 'flatpak'), ('system', Path('/var/lib/flatpak'))),
                   (Path('/usr/local/bin'), Path('/usr/bin'), Path('/bin')))


@dataclass
class Resolution:
    argv: list
    method: str
    message: str
    evidence: str = ''

    def report(self):
        return {'available': bool(self.argv), 'method': self.method, 'argv': self.argv,
                'message': self.message, 'evidence': self.evidence}


def ini_file(path):
    try:
        info = path.stat()
    except OSError as error:
        raise LauncherError('Launcher metadata was not found or cannot be read.') from error
    if (not stat.S_ISREG(info.st_mode) or info.st_size > 65536
            or not trusted_owner(path, info.st_uid) or info.st_mode & 0o022):
        raise LauncherError('Launcher metadata must be a small, trusted regular file.')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text())
    except (OSError, UnicodeError, configparser.Error) as error:
        raise LauncherError('Launcher metadata is invalid.') from error
    return parser


def flatpak_launcher(app_id, scope, discovery, which):
    runtime = command('flatpak', which)
    root = dict(discovery.flatpak_roots).get(scope)
    if root is None:
        raise LauncherError('Requested Flatpak installation scope is not configured.')
    metadata = root / 'app' / app_id / 'current/active/metadata'
    parser = ini_file(metadata)
    if not parser.has_section('Application') or parser['Application'].get('name') != app_id:
        raise LauncherError('No matching installed Flatpak application metadata.')
    return Resolution([runtime, 'run', '--' + scope, app_id], 'flatpak',
                      'Installed Flatpak metadata found; runtime dependencies are not launch-tested.', str(metadata))


def desktop_target(path, spec, which):
    parser = ini_file(path)
    if not parser.has_section('Desktop Entry'):
        raise LauncherError('Desktop entry has no application section.')
    entry = parser['Desktop Entry']
    if entry.get('Name') not in spec['names']:
        return None
    if entry.get('Type') != 'Application' or any(entry.get(key, 'false').lower() == 'true'
            for key in ('Hidden', 'Terminal', 'DBusActivatable')):
        raise LauncherError('Hidden, terminal, or D-Bus desktop launchers are not auto-selected.')
    try:
        args = shlex.split(entry.get('Exec', ''), posix=True)
    except ValueError as error:
        raise LauncherError('Desktop executable quoting is invalid.') from error
    # Deliberately support a conservative subset, never evaluate arbitrary Exec text.
    if not args or any(arg not in ('%f', '%F', '%u', '%U') for arg in args[1:]) or '%' in args[0]:
        raise LauncherError('Desktop Exec uses unsupported flags, wrappers, or field codes; configure an executable path.')
    target = args[0]
    if spec['stem'] not in Path(target).name.lower():
        raise LauncherError('Desktop executable name does not match the expected application.')
    if entry.get('TryExec'):
        trial = entry['TryExec']
        executable(trial) if Path(trial).is_absolute() else command(trial, which)
    return executable(target) if Path(target).is_absolute() else command(target, which)


def resolve_application(activity, config, which=None, discovery=None):
    """Discovery only. No subprocesses, permission changes, installs, or writes."""
    discovery = Discovery.current() if discovery is None else discovery
    spec = SPECS[activity]
    overrides = validate_overrides(config.get('application_launchers', {}))
    override = overrides.get(activity)
    if override is not None:
        try:
            if override['kind'] == 'flatpak':
                return flatpak_launcher(override['app_id'], override['scope'], discovery, which)
            path = override['path']
            path = discovery.home / path[2:] if path.startswith('~/') else Path(path)
            return Resolution([executable(path)], 'configured-path', 'Configured executable validated.', str(path))
        except (LauncherError, OSError) as error:
            return Resolution([], 'configured-invalid', 'Configured launcher is unavailable: ' + str(error))
    configured = config[spec['command']]
    notes = []
    aliases = spec['aliases'] if configured == spec['aliases'][0] else (configured,)
    for name in aliases:
        try:
            return Resolution([command(name, which)], 'path-command', 'Executable validated on PATH.', name)
        except LauncherError as error:
            notes.append(str(error))
    if configured != spec['aliases'][0]:
        return Resolution([], 'missing', 'Configured command was not usable: ' + configured)
    for directory in discovery.binary_dirs:
        for name in aliases:
            candidate = directory / name
            if not candidate.exists():
                continue
            try:
                return Resolution([executable(candidate)], 'standard-location', 'Executable found in a standard binary directory.', str(candidate))
            except LauncherError as error:
                notes.append(str(error))
    targets = {}
    for directory in discovery.desktop_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.desktop'))[:256]:
            try:
                target = desktop_target(path, spec, which)
                if target:
                    targets[str(Path(target).resolve())] = (target, str(path))
            except (LauncherError, OSError) as error:
                # Only report relevant desktop metadata; never print untrusted Exec text.
                if spec['stem'] in path.name.lower():
                    notes.append(str(error))
    for directory in discovery.appimage_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*'))[:256]:
            if spec['stem'] not in path.name.lower() or path.suffix.lower() != '.appimage':
                continue
            try:
                target = executable(path)
                targets[str(path.resolve())] = (target, str(path))
            except LauncherError as error:
                notes.append(str(error))
    if len(targets) > 1:
        return Resolution([], 'ambiguous', 'Multiple application launchers found. Ask a parent to choose application_launchers.')
    if targets:
        target, evidence = next(iter(targets.values()))
        return Resolution([target], 'desktop-or-appimage', 'Local application executable validated; review its publisher before enabling launches.', evidence)
    if spec['flatpak']:
        for scope, root in discovery.flatpak_roots:
            try:
                return flatpak_launcher(spec['flatpak'], scope, discovery, which)
            except (LauncherError, OSError) as error:
                notes.append(str(error))
    preferred = next((note for note in notes if any(reason in note for reason in
                     ('not executable', 'not a regular', 'group/world', 'Desktop', 'quoting'))), None)
    suffix = ' ' + (preferred or notes[-1]) if notes else ''
    return Resolution([], 'missing', 'Optional application not available. Ask a parent to select an executable/AppImage or installed Flatpak in application_launchers.' + suffix)
