"""Portable behavior tests; all generated data stays in temporary test directories."""
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
from ai_maker_lab.applications import Discovery
from ai_maker_lab.core import DEFAULTS, SetupError, Workspace, launch_plan, load_config, validate_config


class PortableTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('AI_MAKER_TEST_TMPDIR', '/tmp')).resolve()
        if not base.is_relative_to(Path('/tmp').resolve()):
            raise RuntimeError('Test storage must stay beneath /tmp.')
        self.temporary = tempfile.TemporaryDirectory(prefix='ai-maker-portable-', dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.ws = Workspace(self.repo)
        self.config = validate_config({})
        self.discovery = Discovery(self.repo, (), (), (), ())

    def available(self, command):
        path = self.repo / 'bin' / Path(command).name
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700), 'w') as stream:
                stream.write('synthetic executable fixture; never run')
        return str(path)

    def test_missing_directories_are_created_only_in_workspace(self):
        self.assertFalse(self.ws.root.exists())
        self.ws.initialize()
        self.assertTrue(self.ws.path('Code').is_dir())
        self.assertEqual(self.ws.root.stat().st_mode & 0o777, 0o700)
        self.assertTrue(self.ws.path('Projects').is_dir())
        self.assertIn('Maker Journal', self.ws.read_journal())
        for path in self.repo.rglob('*'):
            self.assertTrue(path.is_relative_to(self.repo / '.dev-data'))

    def test_initialize_preserves_existing_journal(self):
        self.ws.initialize()
        self.ws.save_journal('my notes')
        self.ws.initialize()
        self.assertEqual(self.ws.read_journal(), 'my notes')

    def test_current_user_only(self):
        self.assertEqual(self.ws.root.name, 'user-' + str(os.getuid()))
        with patch('ai_maker_lab.core.os.getuid', return_value=os.getuid() + 100):
            other = Workspace(self.repo)
        self.assertNotEqual(other.root, self.ws.root)

    def test_unsafe_paths(self):
        for value in ('../outside', '/tmp/outside', 'Code/../../outside', '', '.'):
            with self.subTest(value=value), self.assertRaises(SetupError):
                self.ws.path(value)

    def test_symlink_storage_rejected(self):
        (self.repo / '.dev-data').symlink_to(self.repo)
        with self.assertRaises(SetupError):
            self.ws.initialize()

    def test_symlink_journal_does_not_change_target(self):
        self.ws.initialize()
        sentinel = self.repo / 'sentinel'
        sentinel.write_text('unchanged')
        self.ws.path('Journal/Maker-Journal.md').unlink()
        (self.ws.root / 'Journal/Maker-Journal.md').symlink_to(sentinel)
        with self.assertRaises(SetupError):
            self.ws.save_journal('overwrite')
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_hardlink_journal_does_not_change_target(self):
        self.ws.initialize()
        sentinel = self.repo / 'sentinel'
        sentinel.write_text('unchanged')
        journal = self.ws.path('Journal/Maker-Journal.md')
        journal.unlink()
        os.link(sentinel, journal)
        with self.assertRaises(SetupError):
            self.ws.save_journal('overwrite')
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def test_parent_symlink_rejected(self):
        self.ws.initialize()
        self.ws.path('Projects').rmdir()
        (self.ws.root / 'Projects').symlink_to(self.repo)
        with self.assertRaises(SetupError):
            self.ws.path('Projects/anything')

    def test_journal_conflict_preserved(self):
        self.ws.initialize()
        original = self.ws.read_journal()
        self.ws.save_journal('new notes')
        with self.assertRaises(SetupError):
            self.ws.save_journal('old notes', expected=original)
        self.assertEqual(self.ws.read_journal(), 'new notes')

    def test_missing_optional_apps(self):
        self.ws.initialize()
        self.config['coach_url'] = 'https://chatgpt.com/g/example'
        wad = self.repo / 'synthetic.wad'
        wad.write_text('test fixture only; not game assets')
        self.config['freedoom_wad'] = str(wad)
        for activity in ('coach', 'code', 'bambu', 'minecraft', 'freedoom', 'projects'):
            with self.subTest(activity=activity), self.assertRaises(SetupError):
                launch_plan(activity, self.config, self.ws, which=lambda _: None, discovery=self.discovery)

    def test_missing_directories_report_setup(self):
        for activity in ('code', 'projects'):
            with self.assertRaises(SetupError):
                launch_plan(activity, self.config, self.ws, which=self.available, discovery=self.discovery)

    def test_no_coach_or_game_assets(self):
        for activity in ('coach', 'freedoom'):
            with self.assertRaises(SetupError):
                launch_plan(activity, self.config, self.ws, which=self.available, discovery=self.discovery)

    def test_invalid_configurations(self):
        cases = [[], {'unknown': True}, {'display_name': ''}, {'display_name': 'x\n'},
                 {'terminal': 'sh'}, {'bambu_command': 'bambu;echo'},
                 {'minecraft_command': '/some/path'}, {'doom_command': ['doomretro']},
                 {'freedoom_wad': '../game.wad'}, {'freedoom_wad': '/game.zip'},
                 {'coach_url': 'http://chatgpt.com/g/example'},
                 {'coach_url': 'https://chatgpt.com.evil.invalid/g/example'},
                 {'coach_url': 'https://' + 'user:pass' + '@' + 'chatgpt.com/g/example'},
                 {'coach_url': 'https://chatgpt.com:bad/g/example'},
                 {'coach_url': 'https://chatgpt.com/g/example?token=value'},
                 {'coach_url': 'https://chatgpt.com/g/example\n'}, {'coach_url': 123}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(SetupError):
                validate_config(case)

    def test_config_file_and_example(self):
        self.assertEqual(load_config(), DEFAULTS)
        self.assertEqual(load_config(ROOT / 'config/dashboard.example.json'), DEFAULTS)
        file = self.repo / 'example.json'
        file.write_text('{not json}')
        with self.assertRaises(SetupError):
            load_config(file)
        file.unlink()
        file.symlink_to(ROOT / 'config/dashboard.example.json')
        with self.assertRaises(SetupError):
            load_config(file)

    def test_plans_do_not_spawn_or_write(self):
        self.ws.initialize()
        for name in ('codex', 'foot', 'bambu-studio', 'prismlauncher', 'xdg-open'):
            self.available(name)
        before = {p: p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        with patch('subprocess.Popen', side_effect=AssertionError('unexpected spawn')):
            for activity in ('code', 'bambu', 'minecraft', 'projects'):
                argv, cwd = launch_plan(activity, self.config, self.ws, which=self.available, discovery=self.discovery)
                self.assertTrue(Path(argv[0]).is_relative_to(self.repo / 'bin'))
                self.assertEqual(cwd, self.ws.root)
        self.assertEqual(before, {p: p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})

    def test_launch_arguments_are_separate(self):
        self.ws.initialize()
        argv, _ = launch_plan('code', self.config, self.ws, which=self.available, discovery=self.discovery)
        self.assertEqual(argv[1:4], ['-e', self.available('codex'), '--cd'])
        self.assertEqual(argv[4], str(self.ws.path('Code')))
        wad = self.repo / 'synthetic game.wad'
        wad.write_text('synthetic fixture')
        self.config['freedoom_wad'] = str(wad)
        argv, _ = launch_plan('freedoom', self.config, self.ws, which=self.available, discovery=self.discovery)
        self.assertEqual(argv[1:3], ['-iwad', str(wad)])
        self.assertIn('-noautoload', argv)

    def test_unknown_activity_rejected(self):
        with self.assertRaises(SetupError):
            launch_plan('unexpected', self.config, self.ws, which=self.available, discovery=self.discovery)

    def test_no_machine_specific_home_paths_in_package(self):
        for path in (ROOT / 'src').rglob('*.py'):
            body = path.read_text()
            self.assertNotIn('/home/', body)
            if path.name != 'system_check.py':
                self.assertNotIn('/opt/', body)
            self.assertNotIn('MakerLab/Assets/settings.json', body)

    def test_headless_preview_gui_never_spawns(self):
        # Exercise the real handler without importing GTK or starting a display.
        import ast
        source = ast.parse((ROOT / 'src/ai_maker_lab/gui.py').read_text())
        dashboard = next(node for node in source.body if isinstance(node, ast.ClassDef))
        method = next(node for node in dashboard.body if isinstance(node, ast.FunctionDef) and node.name == 'perform')
        namespace = {'launch_plan': launch_plan, 'SetupError': SetupError, 'subprocess': subprocess}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<handler>', 'exec'), namespace)
        self.ws.initialize()
        class Status:
            def set_text(self, text):
                self.text = text
        class Fake:
            config = self.config
            workspace = self.ws
            launch_external = False
            status = Status()
        with patch('shutil.which', return_value=self.available('bambu-studio')), patch('subprocess.Popen', side_effect=AssertionError('spawn')):
            namespace['perform'](Fake(), 'bambu')
        self.assertIn('Preview', Fake.status.text)

    def test_workspace_operations_cannot_write_outside_development_tree(self):
        # Audit actual OS write attempts in a separate interpreter so the hook
        # cannot affect unrelated tests or their cleanup.
        script = r"""
import os
from pathlib import Path
import sys
from ai_maker_lab.core import Workspace
root = Path(sys.argv[1]).resolve()
seen = []
def audit(event, args):
    paths = []
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)) and (
            (isinstance(mode, str) and any(c in mode for c in 'wax+')) or
            (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))):
            paths = [path]
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
        paths = [args[0]]
    elif event == 'os.rename':
        paths = args[:2]
    for path in paths:
        resolved = Path(os.fsdecode(path)).resolve()
        if not resolved.is_relative_to(root):
            raise AssertionError('write escaped development workspace')
        seen.append(resolved)
sys.addaudithook(audit)
workspace = Workspace(root)
workspace.initialize()
workspace.save_journal('isolated notes', expected=workspace.read_journal())
assert seen and all(path.is_relative_to(workspace.root) or path == root / '.dev-data' for path in seen)
print('writes confined')
"""
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.repo)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('writes confined', result.stdout)

    def test_explicit_external_dispatch_uses_argv_without_shell(self):
        import ast
        source = ast.parse((ROOT / 'src/ai_maker_lab/gui.py').read_text())
        dashboard = next(node for node in source.body if isinstance(node, ast.ClassDef))
        method = next(node for node in dashboard.body if isinstance(node, ast.FunctionDef) and node.name == 'perform')
        namespace = {'launch_plan': launch_plan, 'SetupError': SetupError, 'subprocess': subprocess}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<handler>', 'exec'), namespace)
        self.ws.initialize()
        class Status:
            def set_text(self, text):
                self.text = text
        class Fake:
            config = self.config
            workspace = self.ws
            launch_external = True
            children = []
            status = Status()
        with patch('shutil.which', return_value=self.available('bambu-studio')), patch('subprocess.Popen') as popen:
            namespace['perform'](Fake(), 'bambu')
        self.assertEqual(popen.call_args.args[0], [self.available('bambu-studio')])
        self.assertFalse(popen.call_args.kwargs['shell'])
        self.assertEqual(popen.call_args.kwargs['cwd'], self.ws.root)

    def test_entrypoint_check_is_read_only(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        before = sorted(p.relative_to(self.repo) for p in self.repo.rglob('*'))
        result = subprocess.run([sys.executable, '-B', '-m', 'ai_maker_lab', '--check'],
                                cwd=self.repo, env=env, text=True, capture_output=True)
        self.assertIn('gtk3', json.loads(result.stdout))
        self.assertEqual(before, sorted(p.relative_to(self.repo) for p in self.repo.rglob('*')))


if __name__ == '__main__':
    unittest.main()
