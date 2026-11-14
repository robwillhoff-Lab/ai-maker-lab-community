"""User-local XDG layout and conservative path validation. SPDX-License-Identifier: MIT."""
from dataclasses import dataclass
import os
from pathlib import Path
import pwd
import stat


class PathError(ValueError):
    pass


def safe_path(path, home):
    """Reject escapes, symlink ancestors, and foreign-owned existing paths."""
    path, home = Path(path), Path(home)
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(home):
        raise PathError('Destination must be an absolute path within the current user home.')
    if any(c in str(path) for c in ('\n', '\r', '\x00')):
        raise PathError('Control characters are not permitted in installation paths.')
    for candidate in (home, *reversed(path.relative_to(home).parents), path):
        candidate = candidate if candidate.is_absolute() else home / candidate
        if candidate.is_symlink():
            raise PathError('Symlink destinations or ancestors are not supported.')
        if candidate.exists():
            info = candidate.lstat()
            if info.st_uid != os.getuid():
                raise PathError('Destination is owned by another account.')
            if candidate != path and not stat.S_ISDIR(info.st_mode):
                raise PathError('Destination ancestor is not a directory.')
    return path


@dataclass(frozen=True)
class Layout:
    home: Path
    data: Path
    config: Path
    state: Path

    @classmethod
    def from_environment(cls, env=None, home=None):
        env = os.environ if env is None else env
        # CLI always uses the OS account home. Tests inject synthetic homes.
        home = Path(pwd.getpwuid(os.getuid()).pw_dir if home is None else home)
        if not home.is_absolute() or home.is_symlink() or not home.is_dir() or '..' in home.parts:
            raise PathError('Expected a real absolute account home.')
        safe_path(home, home)
        values = []
        for variable, fallback in [('XDG_DATA_HOME', home / '.local/share'),
                                   ('XDG_CONFIG_HOME', home / '.config'),
                                   ('XDG_STATE_HOME', home / '.local/state')]:
            value = Path(env.get(variable) or fallback)
            values.append(safe_path(value, home))
        result = cls(home, *values)
        # Do not allow configurable roots to put preserved data in the install area.
        for preserved in (result.workspace, result.config_file, result.state / 'ai-maker-lab'):
            safe_path(preserved, home)
            if preserved.is_relative_to(result.install_dir) or result.install_dir.is_relative_to(preserved):
                raise PathError('Install files and preserved data must be separate.')
        for target in result.owned_paths().values():
            safe_path(target, home)
        return result

    @property
    def install_dir(self):
        return self.data / 'ai-maker-lab/installation'

    @property
    def workspace(self):
        return self.data / 'ai-maker-lab/workspace'

    @property
    def config_file(self):
        return self.config / 'ai-maker-lab/dashboard.json'

    @property
    def manifest(self):
        return self.install_dir / 'install-manifest.json'

    def owned_paths(self):
        return {'app.pyz': self.install_dir / 'app.pyz',
                'LICENSE': self.install_dir / 'LICENSE',
                'desktop': self.data / 'applications/ai-maker-lab-portable.desktop'}
