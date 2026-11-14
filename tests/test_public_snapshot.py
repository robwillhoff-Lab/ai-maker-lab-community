"""Public snapshot exclusion and integrity checks. SPDX-License-Identifier: MIT."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_snapshot_check', ROOT / 'scripts/check_public_snapshot.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PublicSnapshotTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('AI_MAKER_TEST_TMPDIR', '/tmp')).resolve()
        if not base.is_relative_to(Path('/tmp').resolve()):
            raise RuntimeError('Test files must be temporary.')
        self.temporary = tempfile.TemporaryDirectory(prefix='ai-maker-public-test-', dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.snapshot = Path(self.temporary.name)
        for name in checker.inventory(ROOT):
            destination = self.snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)

    def test_exact_candidate_passes(self):
        self.assertEqual(checker.check(self.snapshot, snapshot=True), [])

    def test_private_records_are_not_in_inventory(self):
        names = checker.inventory(ROOT)
        self.assertNotIn('docs/public-release-audit.md', names)
        self.assertNotIn('docs/privacy-audit.md', names)
        self.assertNotIn('docs/public-snapshot-plan.md', names)
        self.assertFalse(any('.git/' in name or 'private-backup' in name for name in names))

    def test_extra_configuration_is_rejected(self):
        (self.snapshot / '.env').write_text('synthetic local data\n')
        self.assertTrue(any('outside public inventory' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_private_report_in_inventory_is_rejected(self):
        with (self.snapshot / 'release/public-files.txt').open('a') as stream:
            stream.write('docs/public-release-audit.md\n')
        self.assertTrue(any('Forbidden path' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_git_metadata_path_in_inventory_is_rejected(self):
        with (self.snapshot / 'release/public-files.txt').open('a') as stream:
            stream.write('.git/config\n')
        self.assertTrue(any('Forbidden path' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_missing_license_notice_is_rejected(self):
        (self.snapshot / 'LICENSE').write_text('synthetic missing license\n')
        self.assertTrue(any('MIT license' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_release_version_mismatch_is_rejected(self):
        path = self.snapshot / 'pyproject.toml'
        path.write_text(path.read_text().replace('0.1.0a0', '0.3.0.dev0'))
        self.assertTrue(any('version mismatch' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_private_document_link_is_rejected(self):
        with (self.snapshot / 'README.md').open('a') as stream:
            stream.write('\n[Unselected document](docs/public-release-audit.md)\n')
        self.assertTrue(any('link outside public inventory' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_symlink_cannot_substitute_selected_file(self):
        path = self.snapshot / 'README.md'
        path.unlink()
        path.symlink_to(ROOT / 'README.md')
        self.assertTrue(any('symlink' in error for error in checker.check(self.snapshot, snapshot=True)))

    def test_generic_synthetic_account_is_not_private(self):
        accounts = [SimpleNamespace(pw_name='learner1', pw_uid=1000)]
        with mock.patch.object(checker.pwd, 'getpwall', return_value=accounts):
            self.assertEqual(checker.check(self.snapshot, snapshot=True), [])

    def test_other_local_identifier_is_detected(self):
        accounts = [SimpleNamespace(pw_name='synthetic_private_identity', pw_uid=1000)]
        with (self.snapshot / 'README.md').open('a') as stream:
            stream.write('\nsynthetic_private_identity\n')
        with mock.patch.object(checker.pwd, 'getpwall', return_value=accounts):
            self.assertTrue(any('local account identifier' in error
                                for error in checker.check(self.snapshot, snapshot=True)))
