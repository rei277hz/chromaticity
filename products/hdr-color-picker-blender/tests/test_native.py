"""Pinned Blender installed-package tests, with a private software GPU display."""
from contextlib import ExitStack
from importlib.resources import files
import json
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import zipfile

def virtual_display(resources, root, env):
    # Load the shared fixture as a resource so unittest does not collect its
    # Perceptual Grade test class as part of this extension's suite.
    spec = importlib.util.spec_from_file_location('hdr_picker_display_fixture', str(resources/'gui_display.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.virtual_display(resources, root, env)


class NativeTests(unittest.TestCase):
    def test_installed_picker_and_independent_extensions(self):
        data = self._run('native_runner.py', background=True)
        self.assertGreaterEqual(data['tests'], 6)

    def test_native_gizmo_cancel_confirm_and_undo(self):
        data = self._run('gui_runner.py', background=False)
        self.assertEqual(data['events'], ['cancel_left_brush_unchanged', 'release_committed_hdr',
                         'undo_restored_scene', 'redo_restored_scene', 'hide_released_preview', 'complete'])

    def _run(self, runner, *, background):
        resources = files(__package__)
        fixture = Path(str(resources/'blender')).resolve()
        blender = next(path for path in (fixture/'blender', fixture/'Blender.app/Contents/MacOS/Blender') if path.is_file())
        with tempfile.TemporaryDirectory(prefix='hdr-picker-') as directory, ExitStack() as stack:
            root = Path(directory)
            repository = root/'repository'
            for name in ('hdr_color_picker', 'perceptual_grade'):
                with zipfile.ZipFile(str(resources/(name+'.zip'))) as archive:
                    archive.extractall(repository/name)
            env = {k:v for k,v in os.environ.items() if k not in (
                'PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','BLENDER_SYSTEM_PYTHON')}
            env.update(BLENDER_USER_CONFIG=str(root/'config'), BLENDER_USER_EXTENSIONS=str(root/'extensions'),
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
            stack.enter_context(virtual_display(resources, root, env))
            report = root/'report.json'
            command = [str(blender), '--factory-startup', '--disable-autoexec']
            command += (['--background'] if background else
                        ['--enable-event-simulate', '--window-geometry', '0', '0', '1280', '960'])
            command += ['--python-exit-code', '1', '--python', str(resources/runner), '--', str(repository)]
            if background:
                command.append(str(resources))
            command.append(str(report))
            process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                output, _ = process.communicate(timeout=300)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.assertEqual(process.returncode, 0, output)
            self.assertTrue(report.is_file(), output)
            data = json.loads(report.read_text())
            self.assertTrue(data['passed'], output)
            return data
