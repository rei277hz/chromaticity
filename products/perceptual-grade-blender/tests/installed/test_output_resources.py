"""Native undo and fixed output relationships in the installed extension."""
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


class NativeOutputResourcesTests(unittest.TestCase):
    def test_publication_preserves_links_across_native_undo(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_output_display', str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-output-resources-') as directory, ExitStack() as services:
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
                '--python-exit-code', '1', '--python', str(resources / 'output_resources_runner.py'),
                '--', str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=10)
                self.fail('Native resource regression timed out\n' + stdout[-16000:])
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.exists() else {}
            detail = stdout[-16000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, detail)
            self.assertTrue(data.get('passed'), detail)
            self.assertEqual(len(data['cases']), 8, detail)
            self.assertEqual(len(data['covered']), 4, detail)
            self.assertGreaterEqual(data['native_undo'], 5, detail)
            self.assertGreaterEqual(data['native_redo'], 5, detail)
            self.assertGreaterEqual(data['numeric_checks'], 8, detail)
            self.assertGreaterEqual(data['preserved_checks'], 24, detail)
            self.assertEqual(data['snapshot_checks'], 6, detail)
            self.assertGreater(data['fixed_edge_checks'], 80, detail)
            print('Native output lifetime:', json.dumps(data, sort_keys=True), flush=True)
