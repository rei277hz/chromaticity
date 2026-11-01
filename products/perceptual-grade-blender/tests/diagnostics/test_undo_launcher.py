"""Exercise the LLDB launcher contract without Apple tools or native hooks.

Only the copied test launcher redirects its two absolute Apple-tool checks to
fixtures. Production retains fixed system-tool paths; it has no executable-path
environment override for tests.
"""
from importlib.resources import files
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


class UndoLauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.script(self.bin / 'uname', '#!/bin/bash\nprintf "Darwin\\n"\n')
        self.launcher = (self.root / 'diagnostics & tools \'single\' "double" $cash' /
                         'pg_undo_trace_macos.command')
        self.launcher.parent.mkdir()
        resource = files('tests.diagnostics') / 'pg_undo_trace_macos.command'
        source = resource.read_text()
        for name in ('malloc_history', 'leaks'):
            fixture = self.bin / name
            self.script(fixture, '#!/bin/bash\nexit 0\n')
            source = source.replace('/usr/bin/' + name, shlex.quote(str(fixture)))
        self.launcher.write_text(source)
        for name in ('pg_undo_trace.py', 'pg_undo_trace_lldb.py', 'pg_undo_trace_native.py',
                     'pg_undo_trace_collect.py', 'pg_undo_trace_canary.py',
                     'pg_undo_trace_alloc_canary.c'):
            (self.launcher.parent / name).write_text('# bundle fixture\n')
        self.home = self.root / 'user space'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        MallocStackLogging='inherited-compact',
                        MallocStackLoggingNoCompact='inherited-noncompact',
                        MallocStackLoggingDirectory='inherited-directory')
        self.app = self.root / 'Blender special $name.app'
        self.executable = self.app / 'Contents' / 'MacOS' / 'Blender'
        self.executable.parent.mkdir(parents=True)
        self.script(self.executable, '#!/bin/bash\nprintf "must run through LLDB" >&2\nexit 97\n')
        self.lldb = self.bin / 'lldb'
        self.script(self.lldb, '#!' + sys.executable + '\n' + '''
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ['PG_UNDO_TRACE_SESSION_DIR'])
session_path = root / 'session.json'
session = json.loads(session_path.read_text())
(root / 'initial-session.json').write_text(json.dumps(session))
(root / 'debugger-input.json').write_text(json.dumps(dict(
    arguments=sys.argv[1:], debugger_pid=os.getpid(),
    tools=os.environ['PG_UNDO_TRACE_TOOLS_DIR'],
    allocator_environment={key: value for key, value in os.environ.items()
                           if key.startswith('MallocStackLogging')})))
if os.environ.get('FAKE_LLDB_REFUSAL'):
    print('Debugger launch denied/failed: fixture authorization refusal', file=sys.stderr)
    sys.exit(42)
# The mock debugger alone obtains a target PID and publishes it. The shell must
# neither assume its child is Blender nor overwrite the debugger's observation.
target = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'],
                        capture_output=True, text=True, check=True)
pid = int(target.stdout)
(root / 'observed-target-pid.txt').write_text(str(pid))
session.update(blender_pid=pid, status='exited')
session_path.write_text(json.dumps(session))
sys.exit(int(os.environ.get('FAKE_LLDB_EXIT', '0')))
''')
        self.script(self.bin / 'xcrun', '#!/bin/bash\n' +
                    'if [[ "${1:-}" != --find ]]; then exit 2; fi\n' +
                    'case "${2:-}" in\n' +
                    'lldb) printf "%s\\n" ' + shlex.quote(str(self.lldb)) + ';;\n' +
                    'python3) printf "%s\\n" ' + shlex.quote(sys.executable) + ';;\n' +
                    '*) exit 2;;\nesac\n')

    def script(self, path, contents):
        path.write_text(contents)
        path.chmod(0o700)

    def run_launcher(self, *args):
        return subprocess.run(['bash', str(self.launcher), *map(str, args)], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def native_dir(self):
        directories = list((self.home / 'Desktop').glob('perceptual-grade-native-trace-*'))
        self.assertEqual(len(directories), 1)
        return directories[0]

    def test_app_launch_preserves_paths_and_isolates_debugger_environment(self):
        project = self.root / 'project $(not-a-command) & spaces.blend'
        project.touch()
        result = self.run_launcher(self.app, project)
        self.assertEqual(result.returncode, 0, result.stderr)
        native = self.native_dir()
        config = json.loads((native / 'config.json').read_text())
        self.assertEqual(config['blender'], str(self.executable))
        self.assertEqual(config['project_args'], [str(project)])
        self.assertEqual(config['tools'], str(self.launcher.parent))
        self.assertEqual(config['lldb'], str(self.lldb))
        debugger = json.loads((native / 'debugger-input.json').read_text())
        self.assertEqual(debugger['arguments'],
                         ['--no-lldbinit', '--source', str(native / 'commands.lldb')])
        self.assertEqual(debugger['tools'], str(self.launcher.parent))
        self.assertEqual(debugger['allocator_environment'], {})
        module = str(self.launcher.parent / 'pg_undo_trace_lldb.py')
        quoted = '"' + module.replace('\\', '\\\\').replace('"', '\\"') + '"'
        self.assertEqual((native / 'commands.lldb').read_text(),
                         'command script import ' + quoted + '\npg-undo-run\n')
        self.assertIn('To pack again:', result.stdout)
        self.assertIn('Original evidence:', result.stdout)
        self.assertEqual(native.stat().st_mode & 0o777, 0o700)
        self.assertEqual((native / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_debugger_supplies_target_pid_instead_of_shell_pid(self):
        result = self.run_launcher(self.executable)
        self.assertEqual(result.returncode, 0, result.stderr)
        native = self.native_dir()
        before = json.loads((native / 'initial-session.json').read_text())
        after = json.loads((native / 'session.json').read_text())
        debugger = json.loads((native / 'debugger-input.json').read_text())
        self.assertIsNone(before['blender_pid'])
        self.assertEqual(after['blender_pid'], int((native / 'observed-target-pid.txt').read_text()))
        self.assertNotEqual(after['blender_pid'], before['launcher_pid'])
        self.assertNotEqual(after['blender_pid'], debugger['debugger_pid'])
        self.assertEqual(before['launch_id'], after['launch_id'])
        self.assertEqual(json.loads((native / 'config.json').read_text())['project_args'], [])

    def test_direct_executable_preserves_debugger_exit_status(self):
        self.env['FAKE_LLDB_EXIT'] = '134'
        result = self.run_launcher(self.executable)
        self.assertEqual(result.returncode, 134)
        self.assertIn('LLDB exited with status 134', result.stdout)
        self.assertTrue((self.native_dir() / 'session.json').is_file())

    def test_invalid_project_does_not_start_or_create_capture(self):
        result = self.run_launcher(self.app, self.root / 'missing.blend')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Project was not found', result.stderr)
        self.assertFalse((self.home / 'Desktop').exists())

    def test_incomplete_bundle_does_not_start_or_create_capture(self):
        (self.launcher.parent / 'pg_undo_trace_lldb.py').unlink()
        result = self.run_launcher(self.app)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Incomplete bundle; missing', result.stderr)
        self.assertIn('pg_undo_trace_lldb.py', result.stderr)
        self.assertFalse((self.home / 'Desktop').exists())

    def test_missing_debugger_does_not_launch_blender(self):
        self.script(self.bin / 'xcrun', '#!/bin/bash\nexit 1\n')
        result = self.run_launcher(self.app)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Apple LLDB unavailable', result.stderr)
        self.assertFalse((self.home / 'Desktop').exists())

    def test_debugger_refusal_preserves_evidence_without_direct_launch(self):
        self.env['FAKE_LLDB_REFUSAL'] = '1'
        result = self.run_launcher(self.app)
        self.assertEqual(result.returncode, 42)
        self.assertIn('Debugger launch denied/failed', result.stderr)
        self.assertNotIn('must run through LLDB', result.stderr)
        native = self.native_dir()
        session = json.loads((native / 'session.json').read_text())
        self.assertIsNone(session['blender_pid'])
        self.assertFalse((native / 'observed-target-pid.txt').exists())
        self.assertIn('To pack again:', result.stdout)

    def test_help_does_not_require_tools_or_create_capture(self):
        self.script(self.bin / 'uname', '#!/bin/bash\nprintf "Linux\\n"\n')
        result = self.run_launcher('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Automatically captures the first native fault', result.stdout)
        self.assertFalse((self.home / 'Desktop').exists())


if __name__ == '__main__':
    unittest.main()
