"""Kill only our disposable Blender child after evidence of an unfinished copy."""
from contextlib import ExitStack
from importlib.resources import files
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import tempfile
import time
import unittest
import zipfile

from tests.installed.linux_runtime import with_pinned_linux_libraries


class NativeCopyCrashTests(unittest.TestCase):
    def test_partial_native_copies_and_explicit_restart_production(self):
        resources = files('tests.installed')
        blender = Path(str(resources / 'blender' / 'blender')).resolve()
        runner = Path(str(resources / 'native_copy_runner.py')).resolve()
        persistence_runner = Path(str(resources / 'crash_runner.py')).resolve()
        library = Path(str(resources / 'native_copy_kill.so')).resolve()
        with tempfile.TemporaryDirectory(prefix='pg-native-copy-crash-') as directory, ExitStack() as services:
            root = Path(directory)
            repository = root / 'repository'
            package = repository / 'perceptual_grade'
            package.mkdir(parents=True)
            (root / 'tmp').mkdir()
            with zipfile.ZipFile(str(resources / 'extension.zip')) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items()
                   if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS',
                                  'BLENDER_SYSTEM_SCRIPTS', 'BLENDER_SYSTEM_PYTHON', 'LD_PRELOAD'}}
            env.update(BLENDER_USER_CONFIG=str(root / 'config'),
                       BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                       TMPDIR=str(root / 'tmp'), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            with_pinned_linux_libraries(resources, env)
            display_spec = importlib.util.spec_from_file_location(
                'pg_native_copy_display', str(resources / 'gui_display.py'))
            display = importlib.util.module_from_spec(display_spec)
            display_spec.loader.exec_module(display)
            services.enter_context(display.virtual_display(resources, root, env))
            project = root / 'lastgood.blend'
            serial = 0

            def command(script, *args):
                return [str(blender), '--background', '--factory-startup', '--disable-autoexec',
                        '--python-exit-code', '1', '--python', str(script), '--', *map(str, args)]

            def launch(mode, path=project):
                nonlocal serial
                serial += 1
                report = root / f'{serial}-{mode}.json'
                result = subprocess.run(command(persistence_runner, repository, mode, path, report),
                    cwd=root, env=env, capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
                self.assertTrue(report.exists(), result.stdout + '\n' + result.stderr)
                return json.loads(report.read_text())

            def alive(helper):
                try:
                    status = Path(f"/proc/{helper['pid']}/stat").read_text().split()
                    return status[21] == helper['start'] and status[2] != 'Z'
                except FileNotFoundError:
                    return False

            def interrupt(kind, cut, mode, path):
                nonlocal serial
                serial += 1
                report = root / f'{serial}-{kind}-{cut}-{mode}.json'
                log = root / f'{serial}-blender.log'
                read_fd, write_fd = os.pipe()
                process = None
                helpers = []
                try:
                    with log.open('wb') as output:
                        process = subprocess.Popen(command(runner, repository, path, report,
                            kind, cut, mode, write_fd, library), cwd=root,
                            env=dict(env, LD_PRELOAD=str(library)), pass_fds=(write_fd,),
                            stdout=output, stderr=subprocess.STDOUT)
                        os.close(write_fd)
                        write_fd = -1
                        evidence = bytearray()
                        deadline = time.monotonic() + 240
                        with selectors.DefaultSelector() as ready:
                            ready.register(read_fd, selectors.EVENT_READ)
                            while len(evidence) < 72 and time.monotonic() < deadline:
                                if ready.select(timeout=.1):
                                    chunk = os.read(read_fd, 72 - len(evidence))
                                    if not chunk:
                                        break
                                    evidence.extend(chunk)
                                if process.poll() is not None:
                                    break
                        self.assertEqual(len(evidence), 72,
                            'Native interception absent/incomplete:\n' + log.read_text())
                        magic, pid, total, prefix, before, new_prefix, old_suffix, changed, unfinished = \
                            struct.unpack('=9Q', evidence)
                        self.assertEqual(magic, 0x5047434F50594B31)
                        self.assertEqual(pid, process.pid, 'Evidence must name our Popen child')
                        self.assertEqual((before, new_prefix, old_suffix, changed, unfinished),
                                         (1, 1, 1, 1, 1))
                        data = json.loads(report.read_text())
                        helpers = data['helpers']
                        self.assertEqual((data['pid'], data['total'], data['prefix']),
                                         (pid, total, prefix))
                        self.assertEqual(data['phase'], 'WRITING')
                        deadline = time.monotonic() + 10
                        while process.poll() is None:
                            status = Path(f'/proc/{process.pid}/stat').read_text().split()[2]
                            if status in ('T', 't'):
                                break
                            self.assertLess(time.monotonic(), deadline, 'Child did not stop inside memcpy')
                            time.sleep(.001)
                        self.assertIsNone(process.poll(), log.read_text())
                        # Popen identifies the still-live child we just launched;
                        # no name search, PID guess, or unrelated process signal.
                        process.kill()
                        self.assertEqual(process.wait(timeout=20), -signal.SIGKILL)
                    deadline = time.monotonic() + 30
                    while any(alive(helper) for helper in helpers) and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertFalse([helper for helper in helpers if alive(helper)],
                                     'Owned numerical helpers must retire after parent EOF')
                    print('PG_NATIVE_COPY_EVIDENCE', json.dumps(dict(kind=kind, cut=cut, mode=mode,
                          total=total, prefix=prefix, before_matches=bool(before),
                          new_prefix=bool(new_prefix), old_suffix=bool(old_suffix),
                          changed_prefix=bool(changed), unfinished_suffix=bool(unfinished),
                          killed_own_child=True), sort_keys=True), flush=True)
                finally:
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait(timeout=20)
                    if not helpers and report.exists():
                        helpers = json.loads(report.read_text()).get('helpers', [])
                    # These identities came only from this child's installed
                    # runtime report; compare /proc start times before cleanup.
                    for helper in helpers:
                        if alive(helper):
                            os.kill(helper['pid'], signal.SIGKILL)
                    os.close(read_fd)
                    if write_fd >= 0:
                        os.close(write_fd)

            launch('seed_payloads')
            original_digest = hashlib.sha256(project.read_bytes()).hexdigest()
            for kind in ('shader', 'compositor'):
                for cut in ('first', 'middle', 'last'):
                    with self.subTest(kind=kind, cut=cut):
                        interrupt(kind, cut, 'overwrite', project)
                        self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), original_digest)
                        restored = launch('verify_payloads_valid')
                        self.assertTrue(restored['adopted'])
                        self.assertEqual(restored['transfers'], 0)
            fixture = launch('fixture_writing')
            partial = Path(fixture['fixture'])
            partial_digest = hashlib.sha256(partial.read_bytes()).hexdigest()
            for iteration in range(3):
                for kind in ('shader', 'compositor'):
                    with self.subTest(recovery=iteration + 1, kind=kind):
                        interrupt(kind, 'resume', 'resume', partial)
                        self.assertEqual(hashlib.sha256(partial.read_bytes()).hexdigest(), partial_digest)
                        self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), original_digest)
            repaired = launch('verify_payloads_render', partial)
            self.assertTrue(repaired['adopted'])
            self.assertTrue(repaired['preserved_before_edit'])
            self.assertTrue(repaired['rebuilt_after_edit'])
            self.assertEqual(set(repaired['rendered']), {'shader', 'compositor'})
            self.assertEqual(hashlib.sha256(partial.read_bytes()).hexdigest(), partial_digest)
            self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), original_digest)
            print('Installed native-copy crash acceptance: 6 interrupted publication copies; '
                  '3 explicit restart interruptions per adapter; unchanged last-good file; '
                  'native adoption and final shader/compositor render validation', flush=True)
