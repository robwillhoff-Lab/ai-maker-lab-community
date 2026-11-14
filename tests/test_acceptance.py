"""Fail-closed acceptance-harness boundary tests. SPDX-License-Identifier: MIT."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer_acceptance', ROOT / 'scripts/accept_installer.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class AcceptanceBoundaryTests(unittest.TestCase):
    def test_missing_sandbox_stops_without_fallback(self):
        with patch.object(acceptance.shutil, 'which', return_value=None):
            with self.assertRaises(acceptance.IsolationError):
                acceptance.sandbox_command(ROOT, '/tmp/synthetic-acceptance')

    def test_sandbox_uses_readonly_source_and_host_and_hidden_homes(self):
        command = acceptance.sandbox_command(ROOT, '/tmp/synthetic-acceptance', executable='/fake/bwrap')
        self.assertEqual(command[0], '/fake/bwrap')
        text = ' '.join(command)
        self.assertIn('--ro-bind / /', text)
        self.assertIn('--ro-bind ' + str(ROOT) + ' /mnt', text)
        self.assertIn('--tmpfs /home --remount-ro /home', text)
        self.assertIn('--clearenv', command)
        self.assertIn('--unshare-pid', command)
        self.assertNotIn('--launch-external', command)
        self.assertIn('/tmp/synthetic-acceptance/passwd', command)

    def test_non_temporary_destination_is_rejected_before_execution(self):
        with self.assertRaises(acceptance.IsolationError):
            acceptance.sandbox_command(ROOT, '/var/not-an-acceptance-root', executable='/fake/bwrap')

    def test_worker_refuses_unisolated_execution_before_mutations(self):
        with tempfile.TemporaryDirectory(prefix='ai-maker-boundary-') as directory:
            before = list(Path(directory).iterdir())
            with self.assertRaises(acceptance.IsolationError):
                acceptance.worker(directory)
            self.assertEqual(before, list(Path(directory).iterdir()))
