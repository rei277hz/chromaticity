"""Real native pointer routing against the installed extension ZIP."""
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


class InstalledGizmoContextTests(unittest.TestCase):
    def test_hover_close_reopen_and_automatic_capture_on_all_pages(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_gizmo_display',
                                                     str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-gizmo-context-') as directory, ExitStack() as services:
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
                '--python-exit-code', '1', '--python', str(resources / 'gizmo_context_runner.py'),
                '--', str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            def stop_group():
                for action in (signal.SIGCONT, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, action)
                    except ProcessLookupError:
                        pass
            try:
                stdout, _ = process.communicate(timeout=450)
            except subprocess.TimeoutExpired:
                stop_group()
                stdout, _ = process.communicate(timeout=10)
                self.fail('Installed Gizmo context acceptance timed out\n' + stdout[-16000:])
            finally:
                stop_group()
            data = json.loads(report.read_text()) if report.exists() else {}
            details = stdout[-16000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertNotIn('Traceback (most recent call last)', stdout, details)
            self.assertEqual([case['stage'] for case in data['cases']],
                             ['LINEAR', 'REMAP', 'CHROMATIC'], details)
            for case in data['cases']:
                self.assertTrue(case['closed'] and case['reopened'] and case['tab_changed'], details)
                self.assertGreater(case['native_context_status_calls'], 0, details)
                self.assertGreater(case['hover_calls'], 0, details)
            self.assertTrue(data['initial_open_captured'],details)
            self.assertGreaterEqual(data['native_calls']['acquire'], 8, details)
            self.assertEqual([(case['editor'], case['stage']) for case in data['automatic_cases']],
                [(editor, stage) for editor in ('ShaderNodeTree', 'CompositorNodeTree')
                 for stage in ('LINEAR', 'REMAP', 'CHROMATIC')], details)
            for case in data['automatic_cases']:
                for flag in ('captured', 'hover_passive', 'parameters_unchanged'):
                    self.assertTrue(case[flag], details)
                self.assertFalse(case['autokey'], details)
            self.assertTrue(data['cleanup_clean'], details)
            print('Installed Gizmo context:', json.dumps(data, sort_keys=True), flush=True)
