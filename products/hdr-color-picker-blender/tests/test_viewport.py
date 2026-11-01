"""Installed picker display path through a real native Blender window."""
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


class ViewportTests(unittest.TestCase):
    def test_real_region_and_final_window_match_active_view(self):
        resources = files(__package__)
        fixture = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (fixture / 'blender', fixture / 'Blender.app/Contents/MacOS/Blender')
                       if path.is_file())
        spec = importlib.util.spec_from_file_location('hdr_viewport_display_fixture',
                                                     str(resources / 'gui_display.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='hdr-viewport-') as directory, ExitStack() as services:
            root = Path(directory)
            package = root / 'repository/hdr_color_picker'
            with zipfile.ZipFile(str(resources / 'hdr_color_picker.zip')) as archive:
                archive.extractall(package)
            env = {key: value for key, value in os.environ.items() if key not in (
                'PYTHONPATH', 'PYTHONHOME', 'BLENDER_USER_SCRIPTS', 'BLENDER_SYSTEM_SCRIPTS',
                'BLENDER_SYSTEM_PYTHON')}
            env.update(BLENDER_USER_CONFIG=str(root / 'config'),
                       BLENDER_USER_EXTENSIONS=str(root / 'extensions'),
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
            services.enter_context(module.virtual_display(resources, root, env))
            report = root / 'report.json'
            command = [str(blender), '--factory-startup', '--disable-autoexec',
                       '--window-geometry', '0', '0', '1280', '960', '--python-exit-code', '1',
                       '--python', str(resources / 'viewport_runner.py'), '--', str(package.parent), str(report)]
            process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                output, _ = process.communicate(timeout=180)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.is_file() else {}
            details = output + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertEqual(len(data['cases']), 12, details)
            print('Native viewport display acceptance:', json.dumps(data, sort_keys=True), flush=True)
