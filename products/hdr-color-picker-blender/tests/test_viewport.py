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
                output, _ = process.communicate(timeout=960)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.is_file() else {}
            details = output + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            counts = {'sRGB': 9}
            if tuple(data['blender']) >= (5, 3, 0):
                counts.update({'Display P3': 6, 'Rec.1886': 6, 'Rec.2020': 6,
                               'Rec.2100-PQ': 14, 'Rec.2100-HLG': 9})
            for working in ('ACEScg', 'Linear Rec.709'):
                for emulation in ('OFF', 'AUTO'):
                    cases = [case for case in data['cases']
                             if case['working_space'] == working and case['emulation'] == emulation]
                    coverage = {device: len({case['view'] for case in cases if case['device'] == device})
                                for device in {case['device'] for case in cases}}
                    self.assertEqual(coverage, counts, details)
            print(f'Compared {len(data["cases"])} overlay and native Image Editor cases', flush=True)
