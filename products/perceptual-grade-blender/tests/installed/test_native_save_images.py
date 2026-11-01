"""Native GUI Save must ignore clean internal LUTs and retain user warnings."""
from contextlib import ExitStack
from importlib.resources import files
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import zipfile


class NativeSaveImagesTests(unittest.TestCase):
    def test_internal_banks_do_not_prompt_and_user_image_still_does(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_save_display', str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-native-save-images-') as directory, ExitStack() as services:
            root = Path(directory)
            package = root / 'repository/perceptual_grade'
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / 'extension.zip')) as archive:
                archive.extractall(package)
            environment = {key: value for key, value in os.environ.items() if key not in {
                'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS', 'BLENDER_SYSTEM_SCRIPTS',
                'BLENDER_SYSTEM_PYTHON'}}
            environment.update(BLENDER_USER_CONFIG=str(root / 'config'),
                               BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            services.enter_context(display.virtual_display(resources, root, environment))
            report = root / 'report.json'
            process = subprocess.Popen([str(blender), '--factory-startup', '--disable-autoexec',
                '--enable-event-simulate', '--window-geometry', '0', '0', '1280', '960',
                '--python-exit-code', '1', '--python', str(resources / 'native_save_images_runner.py'),
                '--', str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=10)
                self.fail('Native image-save regression timed out\n' + stdout[-16000:])
            finally:
                # Only this test's disposable process group and its helpers.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.exists() else {}
            detail = stdout[-16000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, detail)
            self.assertTrue(data.get('passed'), detail)
            self.assertTrue(data['cleanup_clean'], detail)
            self.assertEqual([item['case'] for item in data['saves']],
                ['initialized', 'first_update', 'reused_banks', 'after_user_warning_cancel'], detail)
            self.assertTrue(all(item['result'] == ['FINISHED'] for item in data['saves']), detail)
            self.assertEqual(len(data['save_pre']), 4, detail)
            self.assertTrue(data['dirty_user_preserved'], detail)
            self.assertTrue(data['native_user_warning'], detail)
            self.assertTrue(data['cancelled_without_save'], detail)
            self.assertGreaterEqual(len(data['transfers']), 8, detail)
            print('Native Save image acceptance: initialization and repeated Shader/Compositor '
                  'LUT updates save without warning; unrelated user image survives publication '
                  'and opens native warning before save_pre; Escape cancels without saving', flush=True)
