"""Acceptance against pinned native Blender and only the installed ZIP."""
from contextlib import ExitStack
from importlib.resources import files
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tests.installed.linux_runtime import with_pinned_linux_libraries


class InstalledExtensionTests(unittest.TestCase):
    def test_native_cpu_gpu_helpers_parity_and_reload_cleanup(self):
        resources = files('tests.installed')
        binary='Blender.app/Contents/MacOS/Blender' if sys.platform=='darwin' else 'blender'
        blender = Path(str(resources / 'blender' / binary)).resolve()
        runner = Path(str(resources / 'runner.py')).resolve()
        with tempfile.TemporaryDirectory(prefix='pg-installed-') as directory, ExitStack() as services:
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
                'pg_standalone_display', str(resources / 'gui_display.py'))
            display = importlib.util.module_from_spec(display_spec)
            display_spec.loader.exec_module(display)
            services.enter_context(display.virtual_display(resources, root, env))
            report = root / 'report.json'
            result = subprocess.run([str(blender), '--background', '--factory-startup', '--disable-autoexec',
                                     '--python-exit-code', '1', '--python', str(runner), '--',
                                     str(repository), str(report)],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=900)
            details = result.stdout + '\n' + result.stderr
            self.assertEqual(result.returncode, 0, details)
            self.assertTrue(report.exists(), details)
            data = json.loads(report.read_text())
            self.assertIn(data['blender'], ([5, 2, 4], [5, 3, 0]))
            self.assertEqual(set(data['roles']), {'linear', 'bulk', 'gpu'})
            self.assertEqual(data['gpu_backend'], 'GPU')
            self.assertEqual(data['native_backend'],'METAL' if sys.platform=='darwin' else 'OPENGL')
            self.assertTrue(data['gpu_probe']['conformance'])
            self.assertLessEqual(data['gpu_probe']['numerical']['power_max_ulp'],3)
            self.assertEqual([trial['kind'] for trial in data['gpu_trials']],['cold','warm'])
            self.assertTrue(all(trial['backend']=='GPU' and trial['helper_pid']!=data['parent_pid']
                for trial in data['gpu_trials']))
            self.assertTrue(all(trial['preview_backend']=='GPU' and trial['preview_helper_pid']==trial['helper_pid']
                for trial in data['gpu_trials']))
            self.assertEqual(data['gpu_trials'][0]['helper_pid'],data['gpu_trials'][1]['helper_pid'])
            self.assertEqual(data['fallback']['backend'],'CPU')
            self.assertTrue(data['fallback']['prior_gpu_unchanged'])
            self.assertTrue(data['fallback']['diagnostic']['reason'])
            self.assertNotEqual(data['fallback']['diagnostic']['pid'],data['gpu_probe']['worker_pid'])
            self.assertTrue(data['all_helpers_native'] and data['all_helpers_exited'])
            self.assertTrue(data['reloaded_runtime_replaced'] and data['journal_clean'])
            self.assertTrue(data['source_isolation'])
            print('Installed Blender acceptance:', json.dumps(data, sort_keys=True), flush=True)
