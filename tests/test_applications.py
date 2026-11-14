"""Synthetic optional launcher validation tests. SPDX-License-Identifier: MIT."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_maker_lab.applications import (Discovery, LauncherError, command, desktop_target,
                                      executable, resolve_application, SPECS, trusted_owner)
from ai_maker_lab.core import SetupError, Workspace, launch_plan, validate_config
from ai_maker_lab.system_check import inspect_system


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('AI_MAKER_TEST_TMPDIR', '/tmp')).resolve()
        if not base.is_relative_to(Path('/tmp').resolve()):
            raise RuntimeError('Tests require temporary storage.')
        self.temp = tempfile.TemporaryDirectory(prefix='ai-maker-apps-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.context = Discovery(self.home, (self.home / 'desktop',), (self.home / 'Applications',),
                                 (('user', self.home / 'flatpak-user'), ('system', self.home / 'flatpak-system')),
                                 (self.home / 'system-bin',))
        self.config = validate_config({})
        self.ws = Workspace(self.home)
        self.ws.initialize()

    def mock_app(self, relative, mode=0o700):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), 'w') as stream:
            stream.write('synthetic application fixture; never execute\n')
        return path

    def resolve(self, which=lambda _: None, config=None):
        return resolve_application('bambu', self.config if config is None else config,
                                   which=which, discovery=self.context)

    def metadata(self, scope='user', app_id='com.bambulab.BambuStudio', name=None):
        root = dict(self.context.flatpak_roots)[scope]
        path = root / 'app' / app_id / 'current/active/metadata'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Application]\nname=' + (name or app_id) + '\n')
        return path

    def desktop(self, target, extra='', exec_value=None):
        path = self.home / 'desktop/bambu.desktop'
        path.parent.mkdir(exist_ok=True)
        value = exec_value if exec_value is not None else '"' + str(target) + '" %U'
        path.write_text('[Desktop Entry]\nType=Application\nName=Bambu Studio\nExec=' + value + '\n' + extra)
        return path

    def test_missing_application_has_parent_setup_message(self):
        result = self.resolve()
        self.assertFalse(result.argv)
        self.assertIn('Ask a parent', result.message)
        with self.assertRaisesRegex(SetupError, 'Ask a parent'):
            launch_plan('bambu', self.config, self.ws, which=lambda _: None, discovery=self.context)

    def test_alias_used_by_dashboard_and_system_report(self):
        app = self.mock_app('bin/BambuStudio')
        which = lambda name: str(app) if name == 'BambuStudio' else None
        planned, _ = launch_plan('bambu', self.config, self.ws, which=which, discovery=self.context)
        report = inspect_system(discovery=self.context, config=self.config, which=which,
                                gtk_probe=lambda: True)
        self.assertEqual(planned, [str(app)])
        self.assertEqual(report['application_details']['Bambu Studio']['argv'], planned)
        self.assertEqual(report['applications']['Bambu Studio'], str(app))

    def test_standard_location_detected_without_path_entry(self):
        app = self.mock_app('system-bin/BambuStudio')
        result = self.resolve()
        self.assertEqual(result.argv, [str(app)])
        self.assertEqual(result.method, 'standard-location')

    def test_explicit_path_with_spaces(self):
        app = self.mock_app('private tools/Approved AppImage.AppImage')
        config = validate_config({'application_launchers': {'bambu': {'kind': 'executable', 'path': str(app)}}})
        result = self.resolve(config=config)
        self.assertEqual(result.argv, [str(app)])
        self.assertEqual(result.method, 'configured-path')

    def test_home_relative_override(self):
        app = self.mock_app('Applications/BambuStudio.AppImage')
        config = validate_config({'application_launchers': {'bambu': {'kind': 'executable', 'path': '~/Applications/BambuStudio.AppImage'}}})
        self.assertEqual(self.resolve(config=config).argv, [str(app)])

    def test_broken_explicit_override_never_falls_back(self):
        app = self.mock_app('system-bin/BambuStudio')
        config = validate_config({'application_launchers': {'bambu': {'kind': 'executable', 'path': str(self.home / 'missing')}}})
        result = self.resolve(config=config)
        self.assertFalse(result.argv)
        self.assertEqual(result.method, 'configured-invalid')
        self.assertTrue(app.exists())

    def test_custom_legacy_command_never_falls_back(self):
        self.mock_app('system-bin/BambuStudio')
        result = self.resolve(config=validate_config({'bambu_command': 'parent-selected-command'}))
        self.assertFalse(result.argv)
        self.assertIn('parent-selected-command', result.message)

    def test_appimage_detected_in_current_home(self):
        app = self.mock_app('Applications/BambuStudio_Example.AppImage')
        self.assertEqual(self.resolve().argv, [str(app)])

    def test_multiple_appimages_require_selection(self):
        self.mock_app('Applications/BambuStudio_One.AppImage')
        self.mock_app('Applications/BambuStudio_Two.AppImage')
        result = self.resolve()
        self.assertFalse(result.argv)
        self.assertEqual(result.method, 'ambiguous')

    def test_nonexecutable_appimage_reported_without_chmod(self):
        app = self.mock_app('Applications/BambuStudio.AppImage', mode=0o600)
        before = app.stat().st_mode
        result = self.resolve()
        self.assertFalse(result.argv)
        self.assertIn('not executable', result.message)
        with self.assertRaisesRegex(LauncherError, 'not executable'):
            executable(app)
        self.assertEqual(app.stat().st_mode, before)

    def test_directory_and_dangling_link_are_not_executables(self):
        with self.assertRaisesRegex(LauncherError, 'not a regular'):
            executable(self.home)
        link = self.home / 'broken'
        link.symlink_to(self.home / 'missing')
        with self.assertRaises(LauncherError):
            executable(link)

    def test_native_symlink_validates_target(self):
        app = self.mock_app('tools/actual')
        link = self.home / 'tools/BambuStudio'
        link.symlink_to(app)
        self.assertEqual(executable(link), str(link))

    def test_unsafe_owner_or_mode_rejected(self):
        app = self.mock_app('BambuStudio')
        original = Path.stat
        for field, replacement in ((0, app.stat().st_mode | 0o022), (4, os.getuid() + 100)):
            def fake_stat(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == app:
                    values = list(info)
                    values[field] = replacement
                    return os.stat_result(values)
                return info
            with self.subTest(field=field), patch.object(Path, 'stat', fake_stat), self.assertRaises(LauncherError):
                executable(app)

    def test_unmapped_owner_requires_readonly_namespace_without_inner_root(self):
        from types import SimpleNamespace
        app = self.mock_app('BambuStudio')
        def metadata(path, *args, **kwargs):
            if str(path) == '/proc/sys/kernel/overflowuid':
                return '65534'
            if str(path) == '/proc/self/uid_map':
                return '1000 0 1'
            raise AssertionError('Unexpected metadata read')
        with patch.object(Path, 'read_text', metadata):
            with patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                self.assertTrue(trusted_owner(app, 65534))
                self.assertFalse(trusted_owner(app, 1200))
            with patch('os.statvfs', return_value=SimpleNamespace(f_flag=0)):
                self.assertFalse(trusted_owner(app, 65534))

    def test_overflow_owner_not_trusted_when_inner_root_is_mapped(self):
        from types import SimpleNamespace
        app = self.mock_app('BambuStudio')
        def metadata(path, *args, **kwargs):
            return '65534' if str(path).endswith('overflowuid') else '0 0 4294967295'
        with patch.object(Path, 'read_text', metadata), patch('os.statvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            self.assertFalse(trusted_owner(app, 65534))

    def test_relative_which_result_rejected(self):
        with self.assertRaises(LauncherError):
            command('BambuStudio', which=lambda _: 'relative-file')

    def test_desktop_quoted_appimage_and_file_code(self):
        app = self.mock_app('tools/Bambu Studio.AppImage')
        desktop = self.desktop(app)
        result = self.resolve()
        self.assertEqual(result.argv, [str(app)])
        self.assertEqual(result.evidence, str(desktop))

    def test_desktop_and_appimage_same_target_are_deduplicated(self):
        app = self.mock_app('Applications/BambuStudio.AppImage')
        self.desktop(app)
        self.assertEqual(self.resolve().argv, [str(app)])

    def test_desktop_wrappers_and_unsupported_codes_rejected(self):
        app = self.mock_app('tools/BambuStudio')
        for value in ('sh -c "BambuStudio"', str(app) + ' --unreviewed-flag', str(app) + ' %x', str(app) + ' | other'):
            desktop = self.desktop(app, exec_value=value)
            with self.subTest(value=value), self.assertRaises(LauncherError):
                desktop_target(desktop, SPECS['bambu'], lambda _: None)

    def test_hidden_terminal_and_dbus_desktop_entries_rejected(self):
        app = self.mock_app('tools/BambuStudio')
        for key in ('Hidden', 'Terminal', 'DBusActivatable'):
            desktop = self.desktop(app, extra=key + '=true\n')
            with self.subTest(key=key), self.assertRaises(LauncherError):
                desktop_target(desktop, SPECS['bambu'], lambda _: None)

    def test_desktop_tryexec_is_checked(self):
        app = self.mock_app('tools/BambuStudio')
        desktop = self.desktop(app, extra='TryExec=missing-command\n')
        with self.assertRaises(LauncherError):
            desktop_target(desktop, SPECS['bambu'], lambda _: None)

    def test_malformed_desktop_does_not_crash_discovery(self):
        path = self.home / 'desktop/bambu.desktop'
        path.parent.mkdir()
        path.write_text('[Desktop Entry]\nName=Bambu Studio\nName=duplicate\n')
        result = self.resolve()
        self.assertFalse(result.argv)

    def test_user_flatpak_uses_scope_and_installed_metadata(self):
        runtime = self.mock_app('bin/flatpak')
        self.metadata()
        result = self.resolve(which=lambda name: str(runtime) if name == 'flatpak' else None)
        self.assertEqual(result.argv, [str(runtime), 'run', '--user', 'com.bambulab.BambuStudio'])
        self.assertEqual(result.method, 'flatpak')

    def test_system_flatpak_detected(self):
        runtime = self.mock_app('bin/flatpak')
        self.metadata('system')
        result = self.resolve(which=lambda name: str(runtime) if name == 'flatpak' else None)
        self.assertEqual(result.argv[1:3], ['run', '--system'])

    def test_explicit_flatpak_scope_overrides_user_default(self):
        runtime = self.mock_app('bin/flatpak')
        self.metadata('system')
        self.metadata('user')
        config = validate_config({'application_launchers': {'bambu': {'kind': 'flatpak',
                                  'app_id': 'com.bambulab.BambuStudio', 'scope': 'system'}}})
        result = self.resolve(which=lambda name: str(runtime) if name == 'flatpak' else None, config=config)
        self.assertEqual(result.argv[2], '--system')

    def test_flatpak_runtime_without_app_is_not_available(self):
        runtime = self.mock_app('bin/flatpak')
        self.assertFalse(self.resolve(which=lambda name: str(runtime) if name == 'flatpak' else None).argv)

    def test_flatpak_metadata_without_runtime_is_not_available(self):
        self.metadata()
        self.assertFalse(self.resolve().argv)

    def test_flatpak_identity_mismatch_rejected(self):
        runtime = self.mock_app('bin/flatpak')
        self.metadata(name='org.example.OtherApp')
        self.assertFalse(self.resolve(which=lambda name: str(runtime) if name == 'flatpak' else None).argv)

    def test_invalid_configuration_fields_and_shell_strings(self):
        invalid = [[], {'unknown': {}}, {'bambu': None},
                   {'bambu': {'kind': 'executable', 'path': 'relative'}},
                   {'bambu': {'kind': 'executable', 'path': '~/../outside'}},
                   {'bambu': {'kind': 'executable', 'path': '~/App; command'}},
                   {'bambu': {'kind': 'executable', 'path': '$HOME/AppImage'}},
                   {'bambu': {'kind': 'executable', 'path': '~/App\nImage'}},
                   {'bambu': {'kind': 'executable', 'path': '~/App', 'args': ['--unsafe']}},
                   {'bambu': {'kind': 'flatpak', 'app_id': '--command=shell', 'scope': 'user'}},
                   {'bambu': {'kind': 'flatpak', 'app_id': 'org.example.App', 'scope': 'custom'}},
                   {'freedoom': {'kind': 'flatpak', 'app_id': 'org.example.App', 'scope': 'user'}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(SetupError):
                validate_config({'application_launchers': value})

    def test_appimage_example_is_valid_and_not_machine_specific(self):
        from ai_maker_lab.core import load_config
        example = load_config(ROOT / 'config/dashboard.appimage.example.json')
        self.assertEqual(example['application_launchers']['bambu']['path'], '~/Applications/BambuStudio.AppImage')

    def test_no_process_probe_or_write_during_discovery(self):
        self.mock_app('Applications/BambuStudio.AppImage')
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with patch('subprocess.run', side_effect=AssertionError('probe')), patch('subprocess.Popen', side_effect=AssertionError('launch')), patch('os.chmod', side_effect=AssertionError('chmod')):
            self.assertTrue(self.resolve().argv)
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_six_dashboard_pathways_remain_visible(self):
        tree = ast.parse((ROOT / 'src/ai_maker_lab/gui.py').read_text())
        assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'actions' for t in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value), [('Maker Coach', 'coach'), ('Code Lab', 'code'),
                         ('3D Workshop', 'bambu'), ('Gaming Lab', 'gaming'),
                         ('My Projects', 'projects'), ('Maker Journal', 'journal')])
