"""Installer tests use temporary synthetic homes outside the real account home. MIT."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_maker_lab.core import UserWorkspace, validate_config
from ai_maker_lab.installer import install, payloads, uninstall, verify, zipapp_bytes
from ai_maker_lab.paths import Layout, PathError
from ai_maker_lab.system_check import inspect_system


class InstallerTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('AI_MAKER_TEST_TMPDIR', '/tmp')).resolve()
        if not base.is_relative_to(Path('/tmp').resolve()):
            raise RuntimeError('Test storage must stay beneath /tmp.')
        self.temp = tempfile.TemporaryDirectory(prefix='ai-maker-installer-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'learner1'
        self.home.mkdir()
        self.layout = Layout.from_environment({}, home=self.home)
        self.report = inspect_system(self.layout, which=lambda _: None, gtk_probe=lambda: True,
                                     env={}, legacy_path=self.root / 'absent-legacy')

    def apply(self, layout=None):
        return install(ROOT, layout or self.layout, self.report, dry_run=False)

    def run_installed(self, *arguments):
        # Test-only OS identity adapter; production has no alternate-home option.
        bootstrap = (
            'import pwd,runpy,sys; from types import SimpleNamespace; '
            'home,archive=sys.argv[1:3]; '
            'pwd.getpwuid=lambda uid: SimpleNamespace(pw_dir=home); '
            'sys.argv=[archive,*sys.argv[3:]]; runpy.run_path(archive,run_name="__main__")'
        )
        env = dict(os.environ, XDG_DATA_HOME=str(self.layout.data),
                   XDG_CONFIG_HOME=str(self.layout.config), XDG_STATE_HOME=str(self.layout.state))
        return subprocess.run([sys.executable, '-I', '-B', '-c', bootstrap, str(self.home),
                               str(self.layout.owned_paths()['app.pyz']), *arguments],
                              env=env, capture_output=True, text=True)

    def test_dry_run_does_not_create_files(self):
        before = list(self.home.rglob('*'))
        result = install(ROOT, self.layout, self.report)
        self.assertEqual(list(self.home.rglob('*')), before)
        self.assertEqual(set(result['files']), {'app.pyz', 'LICENSE', 'desktop'})
        self.assertTrue(result['missing_optional'])
        self.assertIn(str(self.layout.workspace), result['preserved'])

    def test_install_and_verify_exact_inventory(self):
        self.apply()
        self.assertEqual(set(verify(self.layout)['files']), {'app.pyz', 'LICENSE', 'desktop'})
        created = {p for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(created, set(self.layout.owned_paths().values()) | {self.layout.manifest})
        self.assertFalse(self.layout.workspace.exists())
        self.assertFalse(self.layout.config_file.exists())

    def test_archive_is_allowlisted_python_zipapp(self):
        with zipfile.ZipFile(io.BytesIO(zipapp_bytes(ROOT))) as archive:
            names = archive.namelist()
            self.assertIn('__main__.py', names)
            self.assertIn('LICENSE', names)
            self.assertEqual(len(names), 10)
            self.assertTrue(all(name == 'LICENSE' or name.endswith('.py') for name in names))
            self.assertIn('user_local=True', archive.read('__main__.py').decode())

    def test_verification_ignores_invalid_user_configuration(self):
        self.apply()
        self.layout.config_file.parent.mkdir(parents=True)
        self.layout.config_file.write_text('intentionally invalid configuration')
        result = self.run_installed('--verify-install')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['verified'])
        self.assertEqual(self.layout.config_file.read_text(), 'intentionally invalid configuration')

    def test_symlinked_source_directory_is_not_packaged(self):
        source = self.home / 'source'
        (source / 'src').mkdir(parents=True)
        (source / 'src/ai_maker_lab').symlink_to(ROOT / 'src/ai_maker_lab')
        with self.assertRaises(PathError):
            zipapp_bytes(source)

    def test_reproducible_archive(self):
        self.assertEqual(zipapp_bytes(ROOT), zipapp_bytes(ROOT))

    def test_installed_archive_system_check_without_gui(self):
        self.apply()
        result = self.run_installed('--system-check')
        self.assertIn('gtk3', json.loads(result.stdout))
        self.assertTrue(json.loads(result.stdout)['existing_installations']['user_local'])
        self.assertFalse(self.layout.workspace.exists())

    def test_existing_installation_is_not_overwritten(self):
        self.apply()
        before = {path: path.read_bytes() for path in self.layout.owned_paths().values()}
        with self.assertRaises(PathError):
            self.apply()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_foreign_desktop_entry_is_not_overwritten(self):
        path = self.layout.owned_paths()['desktop']
        path.parent.mkdir(parents=True)
        path.write_text('unrelated launcher')
        with self.assertRaises(PathError):
            self.apply()
        self.assertEqual(path.read_text(), 'unrelated launcher')
        self.assertFalse(self.layout.install_dir.exists())

    def test_empty_existing_install_dir_is_not_adopted(self):
        self.layout.install_dir.mkdir(parents=True)
        with self.assertRaises(PathError):
            self.apply()

    def test_missing_required_dependency_blocks_install(self):
        report = dict(self.report, missing_required=['GTK 3 / PyGObject'])
        self.assertEqual(install(ROOT, self.layout, report)['missing_required'], report['missing_required'])
        with self.assertRaises(PathError):
            install(ROOT, self.layout, report, dry_run=False)
        self.assertFalse(self.layout.install_dir.exists())

    def test_optional_dependencies_do_not_block_install(self):
        self.assertTrue(self.report['missing_optional'])
        self.apply()
        verify(self.layout)

    def test_uninstall_preserves_projects_journal_config_and_unrelated_files(self):
        self.apply()
        workspace = UserWorkspace(self.layout)
        workspace.initialize()
        workspace.save_journal('keep my journal')
        project = workspace.path('Projects/example.txt')
        project.write_text('keep project')
        self.layout.config_file.parent.mkdir(parents=True)
        self.layout.config_file.write_text('{}')
        unrelated = self.layout.install_dir / 'unrelated.txt'
        unrelated.write_text('keep unrelated')
        uninstall(self.layout, dry_run=False)
        self.assertEqual(workspace.read_journal(), 'keep my journal')
        self.assertEqual(project.read_text(), 'keep project')
        self.assertEqual(self.layout.config_file.read_text(), '{}')
        self.assertEqual(unrelated.read_text(), 'keep unrelated')
        self.assertFalse(self.layout.manifest.exists())
        self.assertTrue(all(not path.exists() for path in self.layout.owned_paths().values()))

    def test_uninstall_dry_run_does_not_remove_files(self):
        self.apply()
        result = uninstall(self.layout)
        self.assertEqual(len(result['files']), 4)
        verify(self.layout)

    def test_changed_file_stops_all_uninstall_deletions(self):
        self.apply()
        self.layout.owned_paths()['desktop'].write_text('modified by user')
        with self.assertRaises(PathError):
            uninstall(self.layout, dry_run=False)
        self.assertTrue(all(path.exists() for path in self.layout.owned_paths().values()))
        self.assertTrue(self.layout.manifest.exists())

    def test_uninstall_requires_manifest(self):
        self.apply()
        self.layout.manifest.unlink()
        with self.assertRaises(OSError):
            uninstall(self.layout, dry_run=False)
        self.assertTrue(all(path.exists() for path in self.layout.owned_paths().values()))

    def test_manifest_cannot_add_arbitrary_paths(self):
        self.apply()
        data = json.loads(self.layout.manifest.read_text())
        data['files']['../../unrelated'] = '0' * 64
        self.layout.manifest.write_text(json.dumps(data))
        with self.assertRaises(PathError):
            uninstall(self.layout, dry_run=False)
        self.assertTrue(all(path.exists() for path in self.layout.owned_paths().values()))

    def test_symlink_installation_paths_rejected(self):
        outside = self.root / 'sentinel'
        outside.mkdir()
        (self.home / '.local').symlink_to(outside)
        with self.assertRaises(PathError):
            self.apply()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_and_hardlink_installed_files_rejected(self):
        self.apply()
        file = self.layout.owned_paths()['LICENSE']
        sentinel = self.home / 'sentinel'
        sentinel.write_text(file.read_text())
        file.unlink()
        file.symlink_to(sentinel)
        with self.assertRaises(PathError):
            uninstall(self.layout, dry_run=False)
        file.unlink()
        os.link(sentinel, file)
        with self.assertRaises(PathError):
            uninstall(self.layout, dry_run=False)
        self.assertTrue(sentinel.exists())

    def test_xdg_escape_relative_paths_and_overlap_rejected(self):
        for value in ('relative', str(self.home / '../outside'), str(self.root / 'outside')):
            with self.subTest(value=value), self.assertRaises(PathError):
                Layout.from_environment({'XDG_DATA_HOME': value}, home=self.home)
        with self.assertRaises(PathError):
            Layout.from_environment({'XDG_CONFIG_HOME': str(self.layout.install_dir)}, home=self.home)

    def test_foreign_owner_is_rejected(self):
        original = Path.lstat
        def fake_lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.home:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info
        with patch.object(Path, 'lstat', fake_lstat), self.assertRaises(PathError):
            self.apply()

    def test_separate_synthetic_homes_have_separate_installations(self):
        other_home = self.root / 'learner2'
        other_home.mkdir()
        other = Layout.from_environment({}, home=other_home)
        self.apply()
        self.apply(other)
        UserWorkspace(self.layout).initialize()
        UserWorkspace(other).initialize()
        uninstall(self.layout, dry_run=False)
        verify(other)
        self.assertNotEqual(self.layout.workspace, other.workspace)
        self.assertTrue(other.workspace.is_dir())

    def test_os_account_home_not_home_environment_selects_user(self):
        from types import SimpleNamespace
        other_home = self.root / 'learner2'
        other_home.mkdir()
        for current, misleading in ((self.home, other_home), (other_home, self.home)):
            with patch('ai_maker_lab.paths.pwd.getpwuid', return_value=SimpleNamespace(pw_dir=str(current))):
                layout = Layout.from_environment({'HOME': str(misleading)})
            self.assertEqual(layout.home, current)
            self.assertTrue(layout.workspace.is_relative_to(current))

    def test_user_local_workspace_refuses_preserved_data_symlink(self):
        self.layout.workspace.parent.mkdir(parents=True)
        sentinel = self.home / 'sentinel'
        sentinel.mkdir()
        self.layout.workspace.symlink_to(sentinel)
        with self.assertRaises(PathError):
            UserWorkspace(self.layout).initialize()
        self.assertEqual(list(sentinel.iterdir()), [])

    def test_custom_xdg_directories_and_spaces(self):
        layout = Layout.from_environment({'XDG_DATA_HOME': str(self.home / 'data with spaces'),
                                          'XDG_CONFIG_HOME': str(self.home / 'configuration'),
                                          'XDG_STATE_HOME': str(self.home / 'state')}, home=self.home)
        self.apply(layout)
        verify(layout)
        desktop = layout.owned_paths()['desktop'].read_text()
        self.assertIn('"' + str(layout.owned_paths()['app.pyz']) + '"', desktop)
        self.assertIn('"-I" "-B"', desktop)
        uninstall(layout, dry_run=False)

    def test_root_apply_is_rejected(self):
        with patch('ai_maker_lab.installer.os.geteuid', return_value=0):
            with self.assertRaises(PathError):
                self.apply()
        self.assertFalse(self.layout.install_dir.exists())

    def test_failure_rolls_back_only_new_owned_files(self):
        from ai_maker_lab import installer
        write = installer.write_new
        def fail_desktop(path, content, layout):
            if path == layout.owned_paths()['desktop']:
                raise OSError('synthetic interrupted write')
            return write(path, content, layout)
        sentinel = self.home / 'sentinel'
        sentinel.write_text('preserve')
        with patch.object(installer, 'write_new', fail_desktop), self.assertRaises(OSError):
            self.apply()
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertTrue(all(not path.exists() for path in self.layout.owned_paths().values()))

    def test_system_report_and_bambu_alias_detection(self):
        legacy = self.root / 'legacy'
        legacy.mkdir()
        alias = self.home / 'BambuStudio'
        with os.fdopen(os.open(alias, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700), 'w') as stream:
            stream.write('synthetic executable; never run')
        report = inspect_system(self.layout, which=lambda name: str(alias) if name == 'BambuStudio' else None,
                                gtk_probe=lambda: False, env={'XDG_CURRENT_DESKTOP': 'Synthetic Desktop'},
                                legacy_path=legacy)
        self.assertEqual(report['desktop'], 'Synthetic Desktop')
        self.assertIn('GTK 3 / PyGObject', report['missing_required'])
        self.assertEqual(report['applications']['Bambu Studio'], str(alias))
        self.assertTrue(report['existing_installations']['legacy_shared'])
        self.assertIn('python', report)
        self.assertIn('operating_system', report)

    def test_installer_audit_rejects_writes_outside_synthetic_home(self):
        script = r"""
import os
from pathlib import Path
import sys
from ai_maker_lab.core import UserWorkspace
from ai_maker_lab.installer import install, uninstall
from ai_maker_lab.paths import Layout
home = Path(sys.argv[1])
repository = Path(sys.argv[2])
layout = Layout.from_environment({}, home=home)
seen = []
def audit(event, args):
    paths = []
    if event in ('os.chmod', 'os.chown', 'subprocess.Popen'):
        raise AssertionError('unexpected permission change or subprocess')
    if event == 'open':
        name, mode, flags = args
        if isinstance(name, (str, bytes, os.PathLike)) and isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            paths = [name]
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
        paths = [args[0]]
    for path in paths:
        resolved = Path(os.fsdecode(path)).resolve()
        assert resolved.is_relative_to(home), 'write escaped synthetic home'
        seen.append(resolved)
sys.addaudithook(audit)
report = {'missing_required': [], 'missing_optional': [], 'existing_installations': {}}
install(repository, layout, report, dry_run=False)
workspace = UserWorkspace(layout)
workspace.initialize()
workspace.save_journal('preserve this journal')
uninstall(layout, dry_run=False)
assert workspace.read_journal() == 'preserve this journal'
assert seen
print('install and uninstall confined')
"""
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.home), str(ROOT)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('install and uninstall confined', result.stdout)

    def test_partial_write_failure_removes_only_its_new_file(self):
        from ai_maker_lab.installer import write_new
        destination = self.home / 'partial'
        class BrokenWriter:
            def __init__(self, fd):
                self.fd = fd
            def __enter__(self):
                return self
            def write(self, content):
                os.write(self.fd, content[:2])
                raise OSError('synthetic disk failure')
            def __exit__(self, *args):
                os.close(self.fd)
        with patch('ai_maker_lab.installer.os.fdopen', side_effect=lambda fd, mode: BrokenWriter(fd)):
            with self.assertRaises(OSError):
                write_new(destination, b'payload', self.layout)
        self.assertFalse(destination.exists())

    def test_application_writes_and_installs_stay_within_synthetic_home(self):
        self.apply()
        workspace = UserWorkspace(self.layout)
        workspace.initialize()
        for path in self.root.rglob('*'):
            self.assertTrue(path.is_relative_to(self.home))
        self.assertTrue(workspace.root.is_relative_to(self.layout.data))


if __name__ == '__main__':
    unittest.main()
