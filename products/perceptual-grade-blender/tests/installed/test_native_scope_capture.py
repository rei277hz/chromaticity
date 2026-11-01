"""Native graph sampling through the installed ZIP and isolated helper lane."""
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

from tests.installed.linux_runtime import with_pinned_linux_libraries


class NativeScopeCaptureTests(unittest.TestCase):
    def test_compositor_and_shader_color_inputs_use_native_evaluation(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        with tempfile.TemporaryDirectory(prefix='pg-native-scopes-') as directory, ExitStack() as services:
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
            with_pinned_linux_libraries(resources, environment)
            display_spec = importlib.util.spec_from_file_location(
                'pg_native_scope_display', str(resources / 'gui_display.py'))
            display = importlib.util.module_from_spec(display_spec)
            display_spec.loader.exec_module(display)
            services.enter_context(display.virtual_display(resources, root, environment))
            report = root / 'report.json'
            process = subprocess.Popen([str(blender), '--background', '--factory-startup',
                '--disable-autoexec', '--python-exit-code', '1', '--python',
                str(resources / 'native_scope_capture_runner.py'), '--',
                str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=10)
                self.fail('Native scope capture timed out\n' + stdout[-20000:])
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.exists() else {}
            detail = stdout[-20000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, detail)
            self.assertTrue(data.get('passed'), detail)
            self.assertTrue(data.get('automatic_transform'),detail)
            self.assertEqual(set(data['compositor']),
                             {'transform', 'mix', 'blur', 'nested', 'native_domain',
                              'byte_srgb_alpha', 'render_layers', 'external_render_layers',
                              'reference_grid','first_native_pair','native_adjustments','pending_upstream_private_capture'})
            self.assertEqual({(item['engine'], item['owner']) for item in data['shader']},
                {(engine, owner) for engine in ('BLENDER_EEVEE', 'CYCLES')
                 for owner in ('material', 'world')})
            self.assertEqual({(item['engine'], item['projection']) for item in data['viewport']},
                {(engine, projection) for engine in ('BLENDER_EEVEE', 'CYCLES')
                 for projection in ('orthographic', 'asymmetric_orthographic', 'perspective')})
            self.assertTrue(data['source_graphs_unchanged'], detail)
            self.assertTrue(data['no_file_output_writes'], detail)
            self.assertTrue(data['helper_is_native'] and data['helper_exited'], detail)
            self.assertTrue(data['snapshot_leases_released'], detail)
            self.assertIn('no visible samples', data['invisible_material_error'], detail)
            print('Installed native scope capture:', json.dumps(data, sort_keys=True), flush=True)


if __name__ == '__main__':
    unittest.main()
