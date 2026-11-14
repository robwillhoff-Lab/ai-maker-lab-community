"""Atomic journal and GUI error regressions using synthetic data only. MIT."""
import ast
import errno
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ai_maker_lab.core import SetupError, Workspace


class JournalTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('AI_MAKER_TEST_TMPDIR', '/tmp')).resolve()
        if not base.is_relative_to(Path('/tmp').resolve()):
            raise RuntimeError('Tests require temporary storage.')
        self.temporary = tempfile.TemporaryDirectory(prefix='ai-maker-journal-', dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Workspace(self.temporary.name)
        self.workspace.initialize()
        self.path = self.workspace.path('Journal/Maker-Journal.md')
        self.original = 'Synthetic original notes\n'
        self.workspace.save_journal(self.original)
        self.before = self.path.stat()

    def assert_original_preserved(self):
        self.assertEqual(self.path.read_text(), self.original)
        after = self.path.stat()
        self.assertEqual((after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns),
                         (self.before.st_dev, self.before.st_ino, self.before.st_mode, self.before.st_mtime_ns))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_successful_utf8_save_and_cleanup(self):
        text = 'Synthetic new notes — Imagine → Test\n'
        self.workspace.save_journal(text, expected=self.original)
        self.assertEqual(self.path.read_bytes(), text.encode('utf-8'))
        self.assertEqual(self.workspace.read_journal(), text)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_initial_creation_is_atomic(self):
        self.path.unlink()
        self.workspace.save_journal('Synthetic initial journal')
        self.assertEqual(self.workspace.read_journal(), 'Synthetic initial journal')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_flush_and_fsync_precede_atomic_replacement(self):
        events = []
        replacement = 'Complete replacement text\n'
        real_sync, real_replace = os.fsync, os.replace
        def synced(fd):
            temporary = list(self.path.parent.glob('.maker-journal-*.tmp'))
            self.assertEqual(len(temporary), 1)
            self.assertEqual(temporary[0].read_bytes(), replacement.encode())
            self.assertEqual(self.path.read_text(), self.original)
            events.append('fsync')
            real_sync(fd)
        def replaced(source, destination):
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(Path(destination), self.path)
            self.assertEqual(events, ['fsync'])
            self.assertEqual(self.path.read_text(), self.original)
            events.append('replace')
            real_replace(source, destination)
        with patch('ai_maker_lab.core.os.fsync', side_effect=synced), patch('ai_maker_lab.core.os.replace', side_effect=replaced):
            self.workspace.save_journal(replacement, expected=self.original)
        self.assertEqual(events, ['fsync', 'replace'])
        self.assertEqual(self.path.read_text(), replacement)

    def failing_stream(self, failure):
        real_fdopen = os.fdopen
        class Stream:
            def __init__(inner, fd, *args, **kwargs):
                inner.stream = real_fdopen(fd, *args, **kwargs)
            def __enter__(inner):
                return inner
            def __exit__(inner, *args):
                return inner.stream.__exit__(*args)
            def write(inner, text):
                if failure == 'write':
                    inner.stream.write(text[:2])
                    raise OSError(errno.ENOSPC, 'synthetic write failure')
                return inner.stream.write(text)
            def flush(inner):
                if failure == 'flush':
                    raise OSError(errno.ENOSPC, 'synthetic flush failure')
                return inner.stream.flush()
            def fileno(inner):
                return inner.stream.fileno()
        return Stream

    def test_failed_partial_temporary_write_preserves_existing_journal(self):
        with patch('ai_maker_lab.core.os.fdopen', side_effect=self.failing_stream('write')):
            with self.assertRaisesRegex(SetupError, 'existing file was not replaced') as result:
                self.workspace.save_journal('replacement', expected=self.original)
        self.assertIsInstance(result.exception.__cause__, OSError)
        self.assert_original_preserved()

    def test_failed_flush_preserves_existing_journal(self):
        with patch('ai_maker_lab.core.os.fdopen', side_effect=self.failing_stream('flush')):
            with self.assertRaisesRegex(SetupError, 'Journal save failed'):
                self.workspace.save_journal('replacement', expected=self.original)
        self.assert_original_preserved()

    def test_failed_fsync_does_not_attempt_replacement(self):
        with patch('ai_maker_lab.core.os.fsync', side_effect=OSError('synthetic sync failure')), patch('ai_maker_lab.core.os.replace') as replace:
            with self.assertRaisesRegex(SetupError, 'Journal save failed'):
                self.workspace.save_journal('replacement', expected=self.original)
        replace.assert_not_called()
        self.assert_original_preserved()

    def test_failed_atomic_replace_preserves_existing_journal(self):
        with patch('ai_maker_lab.core.os.replace', side_effect=OSError('synthetic replacement failure')):
            with self.assertRaisesRegex(SetupError, 'existing file was not replaced'):
                self.workspace.save_journal('replacement', expected=self.original)
        self.assert_original_preserved()

    def test_temporary_creation_failure_preserves_existing_journal(self):
        with patch('ai_maker_lab.core.tempfile.mkstemp', side_effect=OSError('synthetic creation failure')):
            with self.assertRaisesRegex(SetupError, 'Journal save failed'):
                self.workspace.save_journal('replacement', expected=self.original)
        self.assert_original_preserved()

    def test_fdopen_failure_closes_descriptor_and_cleans_temporary(self):
        captured = []
        real_create = tempfile.mkstemp
        def create(*args, **kwargs):
            pair = real_create(*args, **kwargs)
            captured.append(pair)
            return pair
        with patch('ai_maker_lab.core.tempfile.mkstemp', side_effect=create), patch('ai_maker_lab.core.os.fdopen', side_effect=OSError('synthetic stream failure')):
            with self.assertRaises(SetupError):
                self.workspace.save_journal('replacement')
        with self.assertRaises(OSError):
            os.fstat(captured[0][0])
        self.assert_original_preserved()

    def test_utf8_encoding_failure_preserves_existing_journal(self):
        with self.assertRaisesRegex(SetupError, 'Journal save failed'):
            self.workspace.save_journal('synthetic invalid text ' + chr(0xD800))
        self.assert_original_preserved()

    def test_conflict_before_write_creates_no_temporary_file(self):
        with patch('ai_maker_lab.core.tempfile.mkstemp') as create:
            with self.assertRaisesRegex(SetupError, 'changed outside'):
                self.workspace.save_journal('replacement', expected='stale content')
        create.assert_not_called()
        self.assert_original_preserved()

    def test_conflict_while_saving_preserves_external_edit(self):
        real_sync = os.fsync
        def changed(fd):
            real_sync(fd)
            self.path.write_text('Synthetic external edit')
        with patch('ai_maker_lab.core.os.fsync', side_effect=changed):
            with self.assertRaisesRegex(SetupError, 'changed outside'):
                self.workspace.save_journal('replacement', expected=self.original)
        self.assertEqual(self.path.read_text(), 'Synthetic external edit')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_initial_creation_does_not_overwrite_a_concurrent_new_file(self):
        self.path.unlink()
        real_sync = os.fsync
        def appeared(fd):
            real_sync(fd)
            self.path.write_text('Synthetic new external journal')
        with patch('ai_maker_lab.core.os.fsync', side_effect=appeared):
            with self.assertRaisesRegex(SetupError, 'changed while saving'):
                self.workspace.save_journal('replacement')
        self.assertEqual(self.path.read_text(), 'Synthetic new external journal')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_cleanup_failure_is_reported_and_original_remains(self):
        real_unlink = Path.unlink
        def denied(path, *args, **kwargs):
            if path.name.startswith('.maker-journal-'):
                raise PermissionError('synthetic cleanup failure')
            return real_unlink(path, *args, **kwargs)
        with patch('ai_maker_lab.core.os.replace', side_effect=OSError('synthetic replacement failure')), patch.object(Path, 'unlink', denied):
            with self.assertRaisesRegex(SetupError, 'cleanup also failed'):
                self.workspace.save_journal('replacement')
        self.assertEqual(self.path.read_text(), self.original)
        temporary = list(self.path.parent.glob('.maker-journal-*.tmp'))
        self.assertEqual(len(temporary), 1)
        self.assertEqual(temporary[0].stat().st_mode & 0o777, 0o600)
        temporary[0].unlink()  # Only this temporary fixture, after the injected failure ends.
        self.assert_original_preserved()

    def test_nontext_is_rejected_without_writes(self):
        with self.assertRaisesRegex(SetupError, 'must be text'):
            self.workspace.save_journal(None)
        self.assert_original_preserved()


class JournalGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'src/ai_maker_lab/gui.py').read_text())
        dashboard = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        methods = [node for node in dashboard.body
                   if isinstance(node, ast.FunctionDef) and node.name in ('journal', 'save_journal_edit')]
        cls.namespace = {'SetupError': SetupError}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<journal-gui>', 'exec'), cls.namespace)

    def fake(self):
        return SimpleNamespace(workspace=MagicMock(), status=MagicMock())

    def test_gui_success_is_reported_after_storage_success(self):
        fake = self.fake()
        success = self.namespace['save_journal_edit'](fake, 'new', 'old')
        self.assertTrue(success)
        fake.workspace.save_journal.assert_called_once_with('new', expected='old')
        self.assertEqual(fake.status.set_text.call_args.args[0], 'Journal saved in your workspace.')

    def test_gui_failure_never_reports_success(self):
        for error in (SetupError('synthetic storage failure'), OSError('synthetic I/O failure')):
            fake = self.fake()
            fake.workspace.save_journal.side_effect = error
            self.assertFalse(self.namespace['save_journal_edit'](fake, 'new', 'old'))
            message = fake.status.set_text.call_args.args[0]
            self.assertIn('Journal not saved', message)
            self.assertIn('edits remain open', message)
            self.assertNotIn('Journal saved', message)

    def test_gui_keeps_failed_edits_open_and_does_not_advance_original(self):
        fake = self.fake()
        fake.workspace.read_journal.return_value = 'original'
        fake.workspace.save_journal.side_effect = [SetupError('synthetic save failure'), None]
        fake.save_journal_edit = lambda text, original: self.namespace['save_journal_edit'](fake, text, original)
        buffer = MagicMock()
        buffer.get_text.return_value = 'edited text'
        view = MagicMock()
        view.get_buffer.return_value = buffer
        dialog = MagicMock()
        dialog.run.side_effect = [1, 1, 0]
        gtk = SimpleNamespace(Dialog=MagicMock(return_value=dialog), TextView=MagicMock(return_value=view),
                              ScrolledWindow=MagicMock(), Label=MagicMock(),
                              ResponseType=SimpleNamespace(OK=1, CANCEL=0),
                              WrapMode=SimpleNamespace(WORD_CHAR=0))
        self.namespace['Gtk'] = gtk
        self.namespace['journal'](fake)
        self.assertEqual(dialog.run.call_count, 3)
        self.assertEqual([call.kwargs['expected'] for call in fake.workspace.save_journal.call_args_list],
                         ['original', 'original'])
        self.assertIn('not saved', fake.status.set_text.call_args_list[0].args[0])
        self.assertEqual(fake.status.set_text.call_args_list[1].args[0], 'Journal saved in your workspace.')
        buffer.set_text.assert_called_once_with('original')  # Failed edits were never reset.
        dialog.destroy.assert_called_once()
