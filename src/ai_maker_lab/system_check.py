"""Read-only platform and dependency inspection. SPDX-License-Identifier: MIT."""
import importlib
import os
from pathlib import Path
import platform
import shutil
import sys

from .paths import Layout


def gtk_available():
    try:
        gi = importlib.import_module('gi')
        gi.require_version('Gtk', '3.0')
        importlib.import_module('gi.repository.Gtk')
        return True
    except (ImportError, ValueError):
        return False


def inspect_system(layout=None, config=None, which=None, gtk_probe=None, env=None,
                   legacy_path=Path('/opt/maker-lab'), discovery=None):
    from .core import DEFAULTS
    layout = Layout.from_environment() if layout is None else layout
    config = DEFAULTS if config is None else config
    which = shutil.which if which is None else which
    env = os.environ if env is None else env
    try:
        os_name = platform.freedesktop_os_release().get('PRETTY_NAME', platform.system())
    except OSError:
        os_name = platform.system()
    gtk = (gtk_available if gtk_probe is None else gtk_probe)()
    from .applications import command, LauncherError, resolve_application
    apps, details = {}, {}
    choices = {
        'Codex CLI': [ 'codex' ],
        'Bambu Studio': [config['bambu_command'], 'BambuStudio', 'bambustudio'],
        'Prism Launcher': [config['minecraft_command']],
        'Terminal': [config['terminal']],
        'Desktop opener': ['xdg-open'],
        'DOOM Retro': [config['doom_command']],
    }
    optional = {'Bambu Studio': 'bambu', 'Prism Launcher': 'minecraft', 'DOOM Retro': 'freedoom'}
    for label, candidates in choices.items():
        if label in optional:
            resolution = resolve_application(optional[label], config, which=which, discovery=discovery)
            apps[label] = resolution.argv[0] if resolution.argv else None
            details[label] = resolution.report()
        else:
            try:
                apps[label] = command(candidates[0], which)
            except LauncherError:
                apps[label] = None
    missing = []
    if platform.system() != 'Linux':
        missing.append('Linux')
    if sys.version_info < (3, 10):
        missing.append('Python >= 3.10')
    if not gtk:
        missing.append('GTK 3 / PyGObject')
    return {
        'operating_system': os_name,
        'desktop': env.get('XDG_CURRENT_DESKTOP') or env.get('DESKTOP_SESSION') or 'unknown',
        'session_type': env.get('XDG_SESSION_TYPE', 'unknown'),
        'python': platform.python_version(),
        'python_executable': sys.executable,
        'gtk3': gtk,
        'applications': apps,
        'application_details': details,
        'missing_required': missing,
        'missing_optional': [label for label, found in apps.items() if not found],
        'existing_installations': {
            'legacy_shared': legacy_path.exists() or legacy_path.is_symlink(),
            'user_local': layout.install_dir.exists() or layout.install_dir.is_symlink(),
            'portable_desktop_entry': layout.owned_paths()['desktop'].exists(),
        },
        'freedoom_assets_configured': config['freedoom_wad'] is not None,
    }
