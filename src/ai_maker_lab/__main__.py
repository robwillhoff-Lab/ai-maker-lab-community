"""Maker Lab source and user-local entry points. SPDX-License-Identifier: MIT."""
import argparse
import json
from pathlib import Path
import sys
from .core import SetupError, UserWorkspace, Workspace, load_config
from .paths import Layout, PathError


def main(user_local=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--system-check', '--check', dest='check', action='store_true',
                         help='Read-only platform, dependency, and installation report')
    actions.add_argument('--install', action='store_true', help='Install only in the current user XDG directories')
    actions.add_argument('--uninstall', action='store_true', help='Remove only verified installer-owned files')
    actions.add_argument('--verify-install', action='store_true', help='Verify the user-local installation hashes')
    parser.add_argument('--dry-run', action='store_true', help='Preview install/uninstall without creating files')
    parser.add_argument('--launch-external', action='store_true', help='Allow external apps; they manage their own files')
    args = parser.parse_args()
    if args.dry_run and not (args.install or args.uninstall):
        parser.error('--dry-run requires --install or --uninstall')
    try:
        layout = Layout.from_environment()
        if args.uninstall or args.verify_install:
            from .installer import uninstall, verify
            result = (uninstall(layout, dry_run=args.dry_run) if args.uninstall
                      else {'verified': True, 'inventory': verify(layout)})
            print(json.dumps(result, indent=2))
            return 0
        config_path = args.config
        if config_path is None and user_local and layout.config_file.exists():
            config_path = layout.config_file
        config = load_config(config_path)
        repository = Path(__file__).resolve().parents[2]
        if args.check or args.install:
            from .system_check import inspect_system
            report = inspect_system(layout, config)
            if args.check:
                print(json.dumps(report, indent=2))
                return int(bool(report['missing_required']))
            if user_local:
                raise SetupError('Run installation from the reviewed source checkout, not the installed archive.')
            from .installer import install
            print(json.dumps(install(repository, layout, report, dry_run=args.dry_run), indent=2))
            return 0
        from .gui import Dashboard, Gtk
        if not Gtk.init_check()[0]:
            raise SetupError('No display available. Run from your own desktop session.')
        workspace = UserWorkspace(layout) if user_local else Workspace(repository)
        workspace.initialize()
        window = Dashboard(config, workspace, args.launch_external)
        window.show_all()
        Gtk.main()
        return 0
    except (OSError, SetupError, PathError, ImportError, ValueError) as error:
        print('Parent setup: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
