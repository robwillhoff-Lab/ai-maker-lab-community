#!/usr/bin/env python3
"""Fail-closed, temporary filesystem-sandbox installer acceptance. SPDX-License-Identifier: MIT."""
import contextlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch


class IsolationError(RuntimeError):
    pass


def sandbox_command(repository, temporary, executable=None):
    bwrap = shutil.which('bwrap') if executable is None else executable
    if not bwrap:
        raise IsolationError('Bubblewrap is required; no unsandboxed fallback is permitted.')
    repository, temporary = Path(repository).resolve(), Path(temporary).resolve()
    if not temporary.is_relative_to(Path('/tmp').resolve()) or not (repository / 'src/ai_maker_lab').is_dir():
        raise IsolationError('Expected a source checkout and a temporary root outside account homes.')
    # /mnt already exists on supported acceptance hosts; no real mountpoint is created.
    if not Path('/mnt').is_dir():
        raise IsolationError('The sandbox requires an existing /mnt directory for read-only source.')
    home = temporary / 'learner1'
    return [bwrap, '--die-with-parent', '--new-session', '--unshare-pid', '--proc', '/proc',
            '--ro-bind', '/', '/', '--ro-bind', str(repository), '/mnt',
            '--bind', str(temporary), str(temporary),
            '--ro-bind', str(temporary / 'passwd'), '/etc/passwd',
            '--tmpfs', '/home', '--remount-ro', '/home',
            '--clearenv', '--setenv', 'HOME', str(home),
            '--setenv', 'XDG_DATA_HOME', str(home / 'data'),
            '--setenv', 'XDG_CONFIG_HOME', str(home / 'config'),
            '--setenv', 'XDG_STATE_HOME', str(home / 'state'),
            '--setenv', 'XDG_CACHE_HOME', str(home / 'cache'),
            '--setenv', 'TMPDIR', str(home / 'tmp'),
            '--setenv', 'AI_MAKER_TEST_TMPDIR', str(home / 'tmp'),
            '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
            '--chdir', str(home), sys.executable, '-I', '-B',
            '/mnt/scripts/accept_installer.py', '--worker', str(temporary)]


def worker(temporary):
    temporary = Path(temporary).resolve()
    home = temporary / 'learner1'
    # These checks precede any installation, source invocation, or fixture mutation.
    if not temporary.is_relative_to(Path('/tmp').resolve()):
        raise IsolationError('Acceptance root is not temporary.')
    if Path(pwd.getpwuid(os.getuid()).pw_dir) != home:
        raise IsolationError('Synthetic account mapping is unavailable.')
    for protected in ('/', '/mnt', '/home', '/opt'):
        if not os.statvfs(protected).f_flag & os.ST_RDONLY:
            raise IsolationError('Protected filesystem is not read-only: ' + protected)
    legacy = Path('/opt/maker-lab')
    if legacy.exists() and not os.statvfs(legacy).f_flag & os.ST_RDONLY:
        raise IsolationError('Live Maker Lab mount is not read-only.')
    if list(Path('/home').iterdir()):
        raise IsolationError('Real home directories are not hidden.')
    if os.statvfs(temporary).f_flag & os.ST_RDONLY:
        raise IsolationError('Temporary test area is not writable.')
    if '/home' in str(home):
        raise IsolationError('Synthetic installation must be outside home directories.')

    sys.path.insert(0, '/mnt/src')
    from ai_maker_lab import __main__ as cli
    from ai_maker_lab.core import UserWorkspace
    from ai_maker_lab.installer import digest, install, uninstall, verify
    from ai_maker_lab.paths import Layout, PathError
    layout = Layout.from_environment()
    for path in (*layout.owned_paths().values(), layout.manifest, layout.workspace, layout.config_file):
        if not path.is_relative_to(home):
            raise IsolationError('Acceptance destination escaped the synthetic home.')

    writes = []
    def audit(event, args):
        paths = []
        if event in ('os.chmod', 'os.chown', 'socket.__new__', 'socket.connect', 'os.system'):
            raise IsolationError('Disallowed acceptance operation: ' + event)
        if event == 'subprocess.Popen':
            executable, argv = args[:2]
            if str(executable) != sys.executable or argv[:3] not in (
                    [sys.executable, '-I', '-B'], [sys.executable, '-B', '-m']):
                raise IsolationError('Only Python smoke/regression processes are allowed.')
        if event == 'open':
            name, mode, flags = args
            if isinstance(name, (str, bytes, os.PathLike)) and isinstance(flags, int) and flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                paths = [name]
        elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
            paths = [args[0]]
        elif event in ('os.rename', 'os.link', 'os.symlink'):
            paths = args[:2]
        for path in paths:
            if not isinstance(path, (str, bytes, os.PathLike)):
                raise IsolationError('Unexpected filesystem argument.')
            resolved = Path(os.fsdecode(path)).resolve()
            if not resolved.is_relative_to(temporary):
                raise IsolationError('Write escaped acceptance temporary root.')
            writes.append(resolved)
    sys.addaudithook(audit)

    results = []
    def passed(label):
        results.append(label)

    def snapshot():
        return {str(path.relative_to(home)): digest(path.read_bytes())
                for path in home.rglob('*') if path.is_file()}

    def invoke(*arguments):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['ai-maker-lab', *arguments]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main()
        return code, out.getvalue(), err.getvalue()

    before = snapshot()
    code, output, error = invoke('--install', '--dry-run')
    assert code == 0, error
    report = json.loads(output)
    if report['missing_required']:
        raise IsolationError('Required dependencies missing in sandbox: ' + repr(report['missing_required']))
    assert report['ready'] and not report['collisions']
    assert snapshot() == before
    passed('initial dry-run: ready, no collisions, no writes')

    code, output, error = invoke('--install')
    assert code == 0, error
    assert set(verify(layout)['files']) == {'app.pyz', 'LICENSE', 'desktop'}
    passed('user-local installation: exactly four owned files including manifest')

    code, output, error = invoke('--verify-install')
    assert code == 0 and json.loads(output)['verified'], error
    passed('installed application verification: fixed inventory and hashes match')

    archive = layout.owned_paths()['app.pyz']
    before = snapshot()
    smoke = subprocess.run([sys.executable, '-I', '-B', str(archive), '--system-check'],
                           text=True, capture_output=True, check=True, timeout=30)
    smoke_report = json.loads(smoke.stdout)
    assert smoke_report['existing_installations']['user_local'] and smoke_report['gtk3']
    assert snapshot() == before and not layout.workspace.exists()
    passed('installed zipapp non-GUI system-check: successful, no workspace writes')

    before = snapshot()
    code, _, _ = invoke('--install')
    assert code != 0 and snapshot() == before
    passed('repeated install: refused without changing existing files')

    original_manifest = layout.manifest.read_bytes()
    layout.manifest.write_text('{invalid manifest')
    corrupted = snapshot()
    code, _, _ = invoke('--verify-install')
    assert code != 0
    code, _, _ = invoke('--uninstall')
    assert code != 0 and snapshot() == corrupted
    layout.manifest.write_bytes(original_manifest)
    passed('corrupted manifest: verification and uninstall refused; all files retained')

    original_license = layout.owned_paths()['LICENSE'].read_bytes()
    layout.owned_paths()['LICENSE'].write_bytes(b'synthetic modified installation file')
    corrupted = snapshot()
    code, _, _ = invoke('--uninstall')
    assert code != 0 and snapshot() == corrupted
    layout.owned_paths()['LICENSE'].write_bytes(original_license)
    verify(layout)
    passed('payload tampering: hash mismatch prevents all uninstall deletion')

    # A separate missing-dependency fixture avoids the existing-install collision.
    missing_home = temporary / 'missing-dependency'
    missing_home.mkdir()
    missing_layout = Layout.from_environment({}, home=missing_home)
    fake_report = {'missing_required': ['GTK 3 / PyGObject'], 'missing_optional': [],
                   'existing_installations': {}}
    assert not install('/mnt', missing_layout, fake_report)['ready']
    try:
        install('/mnt', missing_layout, fake_report, dry_run=False)
    except PathError:
        pass
    else:
        raise AssertionError('Missing required dependency did not block installation.')
    assert list(missing_home.iterdir()) == []
    passed('missing required dependency: dry-run not ready, apply refused without writes')

    workspace = UserWorkspace(layout)
    workspace.initialize()
    project = workspace.path('Projects/synthetic-project.txt')
    project.write_text('synthetic project only\n')
    workspace.save_journal('synthetic journal only\n')
    layout.config_file.parent.mkdir(parents=True)
    layout.config_file.write_text('{}\n')
    state = layout.state / 'ai-maker-lab/synthetic-state.txt'
    state.parent.mkdir(parents=True)
    state.write_text('preserve synthetic state\n')
    unrelated = layout.install_dir / 'unrelated.txt'
    unrelated.write_text('preserve unrelated file\n')
    outside = home / 'unrelated.txt'
    outside.write_text('preserve unrelated home file\n')
    owned = {*layout.owned_paths().values(), layout.manifest}
    preserved = {path: path.read_bytes() for path in home.rglob('*') if path.is_file() and path not in owned}
    before = snapshot()
    code, _, error = invoke('--uninstall', '--dry-run')
    assert code == 0 and snapshot() == before, error
    passed('uninstall dry-run: no file changes')

    # Exercise the installed archive's actual maintenance entry, not a mock.
    removed = subprocess.run([sys.executable, '-I', '-B', str(archive), '--uninstall'],
                             text=True, capture_output=True, check=True, timeout=30)
    assert json.loads(removed.stdout)['operation'] == 'uninstall'
    assert all(not path.exists() for path in owned)
    assert all(path.read_bytes() == content for path, content in preserved.items())
    assert layout.workspace.is_dir() and layout.install_dir.is_dir()  # unrelated file retained
    passed('uninstall: only four owned files removed; workspace, journal, config, state, unrelated files preserved')

    before = snapshot()
    code, _, _ = invoke('--verify-install')
    assert code != 0
    code, _, _ = invoke('--uninstall')
    assert code != 0 and snapshot() == before
    passed('post-uninstall: verification/removal fail safely, preserved bytes unchanged')
    assert 'ai_maker_lab.gui' not in sys.modules
    assert writes and all(path.is_relative_to(temporary) for path in writes)
    passed('isolation: read-only host/source/legacy mounts, hidden homes, temporary writes only')

    # Regression subprocess inherits the same mount isolation and synthetic identity.
    regressions = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', '/mnt/tests', '-v'],
                                 text=True, capture_output=True, timeout=60)
    if regressions.returncode:
        raise AssertionError(regressions.stdout + regressions.stderr)
    print(json.dumps({'status': 'PASS', 'lifecycle_checks': results,
                      'regression_summary': regressions.stderr.strip().splitlines()[-3:]}, indent=2))
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        return worker(sys.argv[2])
    if len(sys.argv) != 1:
        raise IsolationError('This harness accepts no destination overrides.')
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='ai-maker-acceptance-', dir='/tmp') as directory:
        temporary = Path(directory)
        home = temporary / 'learner1'
        (home / 'tmp').mkdir(parents=True)
        # Only this namespace sees this account file; the OS account DB is never edited.
        (temporary / 'passwd').write_text(
            'learner1:x:' + str(os.getuid()) + ':' + str(os.getgid()) + ':Synthetic learner:' + str(home) + ':/bin/false\n')
        command = sandbox_command(repository, temporary)
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise IsolationError('Sandbox acceptance failed; no unsandboxed fallback.\n' + result.stderr)
        print(result.stdout, end='')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (IsolationError, OSError, subprocess.TimeoutExpired, AssertionError) as error:
        print('Acceptance STOPPED: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
