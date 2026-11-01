"""Real native window/operator/undo acceptance, run by Buck2."""
from contextlib import contextmanager, ExitStack
from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import selectors
import subprocess
import sys
import tempfile
import unittest
import zipfile


@contextmanager
def virtual_display(resources, root, env):
    """Use a private pinned X server on Linux; native WindowServer on macOS."""
    if sys.platform != 'linux':
        yield
        return
    fixture = Path(str(resources / 'xvfb')).resolve()
    library_dir = fixture / 'usr/lib/x86_64-linux-gnu'
    library_paths = [str(library_dir)]
    if env.get('LD_LIBRARY_PATH'):
        library_paths.append(env['LD_LIBRARY_PATH'])
    library_path = os.pathsep.join(library_paths)
    driver_path = str(fixture / 'usr/lib/x86_64-linux-gnu/dri')
    runtime = root / 'xdg-runtime'
    runtime.mkdir(mode=0o700)
    child_env = dict(env, LD_LIBRARY_PATH=library_path,
                     LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe',
                     LIBGL_DRIVERS_PATH=driver_path)
    read_fd, write_fd = os.pipe()
    with (root / 'xvfb.log').open('w') as log:
        process = None
        try:
            process = subprocess.Popen([
                str(fixture / 'usr/bin/Xvfb'), '-displayfd', str(write_fd),
                '-screen', '0', '1280x960x24', '-nolisten', 'tcp', '-ac', '+iglx',
                '-xkbdir', str(fixture / 'usr/share/X11/xkb'),
            ], cwd=fixture, env=child_env, pass_fds=(write_fd,),
                stdout=log, stderr=subprocess.STDOUT)
            os.close(write_fd)
            write_fd = None
            with selectors.DefaultSelector() as ready:
                ready.register(read_fd, selectors.EVENT_READ)
                if not ready.select(timeout=30):
                    raise RuntimeError('Xvfb did not publish a display number')
                display = os.read(read_fd, 64).decode('ascii').strip()
            if not display.isdigit():
                raise RuntimeError('Xvfb startup failed: ' + (root / 'xvfb.log').read_text())
            env.update(DISPLAY=':' + display, XDG_RUNTIME_DIR=str(runtime),
                       LD_LIBRARY_PATH=library_path,
                       LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe',
                       LIBGL_DRIVERS_PATH=driver_path)
            env.pop('WAYLAND_DISPLAY', None)
            yield
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


class NativeGUIUndoTests(unittest.TestCase):
    cycles = 50

    def test_blue_warp_native_operator_undo_redo(self):
        resources = files('tests.installed')
        root_binary = Path(str(resources / 'blender')).resolve()
        candidates = (root_binary / 'Blender.app/Contents/MacOS/Blender', root_binary / 'blender')
        blender = next((path for path in candidates if path.is_file()), None)
        self.assertIsNotNone(blender, 'Pinned native Blender artifact missing')
        runner = Path(str(resources / 'gui_undo_runner.py')).resolve()
        with tempfile.TemporaryDirectory(prefix='pg-gui-undo-') as directory, ExitStack() as services:
            root = Path(directory)
            package = root / 'repository/perceptual_grade'
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / 'extension.zip')) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items()
                   if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS',
                                  'BLENDER_SYSTEM_SCRIPTS', 'BLENDER_SYSTEM_PYTHON'}}
            env.update(BLENDER_USER_CONFIG=str(root / 'config'),
                       BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            services.enter_context(virtual_display(resources, root, env))
            report = root / 'report.json'
            command = [str(blender), '--factory-startup', '--disable-autoexec',
                       '--enable-event-simulate', '--window-geometry', '0', '0', '1280', '960',
                       '--python-exit-code', '1', '--python', str(runner), '--',
                       str(package.parent), str(report), str(self.cycles)]
            process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, start_new_session=True)
            def stop_group():
                # Helpers share the native parent's isolated process group.
                for action in (signal.SIGCONT, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, action)
                    except ProcessLookupError:
                        pass
            try:
                output, _ = process.communicate(timeout=1800)
            except subprocess.TimeoutExpired:
                stop_group()
                output, _ = process.communicate(timeout=10)
                self.fail('Native GUI acceptance timed out\n' + output[-16000:])
            finally:
                # Helpers inherit this isolated process group. Also reap a
                # deliberately paused helper if the foreground crashed.
                stop_group()
            data = json.loads(report.read_text()) if report.exists() else {}
            details = output[-16000:] + '\n' + json.dumps(data, indent=2)
            stacks = report.with_suffix('.stacks.txt')
            if stacks.exists():
                details += '\nStartup stacks:\n' + stacks.read_text()[-32000:]
            if (root / 'xvfb.log').exists():
                details += '\nXvfb:\n' + (root / 'xvfb.log').read_text()[-8000:]
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertEqual(data['events'][-1]['event'], 'complete', details)
            self.assertEqual(len(data['cases']), self.cycles, details)
            pending_cycles = (self.cycles + 1) // 2
            reset_cases = min(5, self.cycles)
            self.assertEqual(sum(case['pending'] for case in data['cases']), pending_cycles)
            self.assertTrue(all(case['runtime_reconciled'] for case in data['cases']))
            self.assertTrue(all(case['fixed_native_links'] for case in data['cases']))
            self.assertTrue(data['cleanup_clean'], details)
            self.assertTrue(data['retired_helper_pids'], details)
            completions=[event for event in data['events'] if event['event']=='runtime_recovery_complete']
            native_posts=[event for event in data['events'] if event['event'] in {'native_undo_post','native_redo_post'}]
            self.assertEqual(len(completions),len(native_posts),details)
            self.assertTrue(all(done['seconds']>=post['seconds'] for post,done in zip(native_posts,completions)),details)
            self.assertTrue(all(case['pending_analytic_captures'] > 0
                                and case['pending_scope_preparing_waits'] == 0
                                for case in data['cases'] if case['pending']), details)
            self.assertEqual(sum(case['reset_chain'] for case in data['cases']), reset_cases, details)
            self.assertEqual(sum(case['gc_deferred'] for case in data['cases']), pending_cycles)
            for name, count in (('native_undo_pre', 2 * (self.cycles + reset_cases)),
                                ('native_undo_post', 2 * (self.cycles + reset_cases)),
                                ('native_redo_pre', self.cycles + reset_cases),
                                ('native_redo_post', self.cycles + reset_cases),
                                ('reset_stage', reset_cases), ('reset_chain_complete', reset_cases),
                                ('gc_after_native_undo', pending_cycles), ('pending_attempt', pending_cycles)):
                self.assertEqual(sum(event['event'] == name for event in data['events']), count, details)
            print('Native GUI undo acceptance:', json.dumps(data, sort_keys=True), flush=True)
