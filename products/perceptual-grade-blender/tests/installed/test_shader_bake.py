"""Installed Shader Image Bake acceptance through the extension ZIP."""
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


class InstalledShaderBakeTests(unittest.TestCase):
    def test_still_image_bake_and_standalone_reader(self):
        resources = files('tests.installed')
        blender = next(path for path in (Path(str(resources / 'blender')).resolve() / 'blender',
            Path(str(resources / 'blender')).resolve() / 'Blender.app/Contents/MacOS/Blender')
            if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_shader_bake_display',
                                                     str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-installed-shader-bake-') as directory, ExitStack() as services:
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
            process = subprocess.Popen([str(blender), '--factory-startup',
                '--disable-autoexec', '--enable-event-simulate',
                '--window-geometry', '0', '0', '1280', '960', '--python-exit-code', '1', '--python',
                str(resources / 'shader_bake_runner.py'), '--', str(package.parent), str(report)],
                cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=360)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=10)
                self.fail('Installed Shader Bake acceptance timed out\n' + stdout[-20000:])
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.exists() else {}
            details = stdout[-20000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertEqual(data['route'], {'domain': 'IMAGE', 'width': 4, 'height': 2,
                                              'source': 'image'}, details)
            self.assertEqual(data['image']['kind'], 'SHADER_IMAGE', details)
            self.assertEqual(data['image']['size'], [4, 2], details)
            self.assertEqual(data['image']['channels'], 4, details)
            self.assertGreater(data['image']['packed_bytes'], 0, details)
            self.assertTrue(data['image']['finite'] and not data['image']['dirty'], details)
            self.assertEqual(data['reader']['kind'], 'image', details)
            self.assertEqual(data['reader']['steps'], 0, details)
            self.assertEqual(data['reader']['alpha_kind'], 'image', details)
            self.assertEqual(data['reader']['alpha_channel'], 'ALPHA', details)
            self.assertEqual(data['reader']['alpha_steps'], 0, details)
            self.assertTrue(data['original_links_preserved'], details)
            for key in ('material_add_operator', 'world_add_operator', 'native_shader_draws',
                        'compositor_image_selector', 'reader_vector', 'grade_vector',
                        'playback_stop_waits_for_native', 'native_wait_race_click', 'native_wait_tooltip',
                        'reopened_controls_drawn', 'reopened_selections', 'reopened_tooltips',
                        'vector_reopen', 'vector_edit_after_reopen', 'packed_reopen'):
                self.assertTrue(data.get(key), key + '\n' + details)
            self.assertEqual(data['selector_path'], 'native template_ID and pointer assignment', details)
            drawn = {item[1] for item in data['drawn_nodes']}
            self.assertIn('Installed Shader Bake Grade', drawn, details)
            self.assertIn('Installed Shader Bake Stack', drawn, details)
            self.assertTrue(all(data['route_ui'][key] for key in ('grade_labels', 'stack_labels')), details)
            print('Installed Shader Bake:', json.dumps(data, sort_keys=True), flush=True)


if __name__ == '__main__':
    unittest.main()
