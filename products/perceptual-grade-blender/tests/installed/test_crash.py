"""Kill real installed Blender parents and restart against the same journal."""
from contextlib import ExitStack
from importlib.resources import files
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
import zipfile

from tests.installed.linux_runtime import with_pinned_linux_libraries


class InstalledCrashTests(unittest.TestCase):
    def test_saved_partial_buffers_and_native_autosave_preserve_native_output(self):
        resources = files('tests.installed')
        blender = Path(str(resources / 'blender' / 'blender')).resolve()
        runner = Path(str(resources / 'crash_runner.py')).resolve()
        with tempfile.TemporaryDirectory(prefix='pg-installed-payload-recovery-') as directory, ExitStack() as services:
            root = Path(directory)
            repository = root / 'repository'
            package = repository / 'perceptual_grade'
            package.mkdir(parents=True)
            (root / 'tmp').mkdir()
            with zipfile.ZipFile(str(resources / 'extension.zip')) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items()
                   if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS',
                                  'BLENDER_SYSTEM_SCRIPTS', 'BLENDER_SYSTEM_PYTHON'}}
            env.update(BLENDER_USER_CONFIG=str(root / 'config'),
                       BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                       TMPDIR=str(root / 'tmp'), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            with_pinned_linux_libraries(resources, env)
            display_spec = importlib.util.spec_from_file_location(
                'pg_crash_display', str(resources / 'gui_display.py'))
            display = importlib.util.module_from_spec(display_spec)
            display_spec.loader.exec_module(display)
            services.enter_context(display.virtual_display(resources, root, env))
            project = root / 'lastgood.blend'
            serial = 0

            def launch(mode, path=project):
                nonlocal serial
                serial += 1
                report = root / f'{serial}-{mode}.json'
                result = subprocess.run([str(blender), '--background', '--factory-startup',
                    '--disable-autoexec', '--python-exit-code', '1', '--python', str(runner),
                    '--', str(repository), mode, str(path), str(report)],
                    cwd=root, env=env, capture_output=True, text=True, timeout=240)
                details = result.stdout + '\n' + result.stderr
                self.assertEqual(result.returncode, 0, details)
                self.assertTrue(report.exists(), details)
                return json.loads(report.read_text())

            launch('seed_payloads')
            original_digest = hashlib.sha256(project.read_bytes()).hexdigest()
            valid = launch('verify_payloads_valid')
            self.assertTrue(valid['adopted'])
            self.assertEqual(valid['transfers'], 0)
            for kind in ('writing', 'edited', 'autosave'):
                with self.subTest(kind=kind):
                    fixture = launch('fixture_' + kind)
                    self.assertEqual(len(fixture['damaged']), 2)
                    self.assertEqual({value['tree'] for value in fixture['damaged']},
                                     {'ShaderNodeTree', 'CompositorNodeTree'})
                    if kind == 'autosave':
                        self.assertTrue(fixture['native_autosave'])
                        self.assertEqual(fixture['save_pre_calls'], 0)
                    path = Path(fixture['fixture'])
                    fixture_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    restored = launch('verify_payloads_autosave' if kind == 'autosave'
                                      else 'verify_payloads_damaged', path)
                    self.assertEqual(restored['native_autosave_recovery'], kind == 'autosave')
                    self.assertTrue(restored['adopted'])
                    self.assertTrue(restored['preserved_before_edit'])
                    self.assertFalse(restored['rebuilt_after_edit'])
                    self.assertEqual(restored['transfers'], 0)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), fixture_digest)
                    self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), original_digest)
            print('Installed persisted-payload acceptance: native adoption without rewrite; '
                  'mixed pixels with WRITING or unchanged producer metadata preserved; actual native '
                  'wm.save_auto_save recovery; no numerical provenance claimed', flush=True)

    def test_parent_work_publication_repair_and_shutdown_crashes(self):
        resources = files('tests.installed')
        blender = Path(str(resources / 'blender' / 'blender')).resolve()
        runner = Path(str(resources / 'crash_runner.py')).resolve()
        known_helpers = []
        def alive(helper):
            try:
                status = Path(f"/proc/{helper['pid']}/stat").read_text().split()
                return status[21] == helper['start'] and status[2] != 'Z'
            except FileNotFoundError:
                return False
        def wait_helpers(helpers):
            deadline = time.monotonic() + 30
            while any(alive(helper) for helper in helpers) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse([helper for helper in helpers if alive(helper)], 'Helpers must exit on parent EOF')
        try:
            with tempfile.TemporaryDirectory(prefix='pg-installed-crash-') as directory, ExitStack() as services:
                root = Path(directory)
                repository = root / 'repository'
                package = repository / 'perceptual_grade'
                package.mkdir(parents=True)
                with zipfile.ZipFile(str(resources / 'extension.zip')) as archive:
                    archive.extractall(package)
                env = {key: value for key, value in os.environ.items()
                       if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS',
                                      'BLENDER_SYSTEM_SCRIPTS', 'BLENDER_SYSTEM_PYTHON'}}
                env.update(BLENDER_USER_CONFIG=str(root / 'config'),
                           BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                           OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
                with_pinned_linux_libraries(resources, env)
                display_spec = importlib.util.spec_from_file_location(
                    'pg_crash_work_display', str(resources / 'gui_display.py'))
                display = importlib.util.module_from_spec(display_spec)
                display_spec.loader.exec_module(display)
                services.enter_context(display.virtual_display(resources, root, env))
                project = root / 'recover.blend'
                serial = 0
                def launch(mode, prior=None, expected=0):
                    nonlocal serial
                    serial += 1
                    report = root / f'{serial}-{mode}.json'
                    result = subprocess.run([str(blender), '--background', '--factory-startup',
                                             '--disable-autoexec', '--python-exit-code', '1',
                                             '--python', str(runner), '--', str(repository), mode,
                                             str(project), str(report), str(prior or '')],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=180)
                    details = result.stdout + '\n' + result.stderr
                    self.assertEqual(result.returncode, expected, details)
                    self.assertTrue(report.exists(), details)
                    data = json.loads(report.read_text())
                    known_helpers.extend(data.get('helpers', ()))
                    return report, data
                launch('seed')
                for role in ('bulk', 'gpu'):
                    report, data = launch('work_' + role, expected=-signal.SIGKILL)
                    self.assertFalse(json.loads((Path(data['directory']) / 'journal.json').read_text())['clean'])
                    self.assertGreater(data['progress'], 0)
                    self.assertLess(data['progress'], 1)
                    _, probe = launch('probe_lease', prior=report)
                    self.assertTrue(probe['lease_preserved'])
                    os.kill(data['helper_stopped'], signal.SIGCONT)
                    wait_helpers(data['helpers'])
                    launch('recover_valid', prior=report)
                publication, data = launch('publication', expected=75)
                self.assertTrue(data['pending_saved'])
                wait_helpers(data['helpers'])
                repair, data = launch('repair', prior=publication, expected=76)
                self.assertTrue(data['pending_saved'])
                wait_helpers(data['helpers'])
                _, data = launch('recover_pending', prior=repair)
                self.assertTrue(data['pending_before'] and data['preserved_before_edit'] and data['rebuilt_after_edit'])
                launch('recover_valid')
                shutdown, data = launch('shutdown', expected=77)
                self.assertTrue(data['retired'])
                wait_helpers(data['helpers'])
                self.assertFalse(json.loads((Path(data['directory']) / 'journal.json').read_text())['clean'])
                launch('recover_valid', prior=shutdown)
                print('Installed crash acceptance: CPU/GPU parent SIGKILL, leased orphan, '
                      'EOF exit, publication/repair pending snapshot, shutdown commit interruption', flush=True)
        finally:
            # A failed assertion must not leave the deliberately stopped child.
            for helper in known_helpers:
                if alive(helper):
                    os.kill(helper['pid'], signal.SIGKILL)
