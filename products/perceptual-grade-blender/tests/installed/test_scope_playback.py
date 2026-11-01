"""Scope acquisition and publication pause during native timeline playback."""
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


class InstalledScopePlaybackTests(unittest.TestCase):
    def test_cold_and_retained_scopes_pause_then_resume_latest_stopped_frame(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_playback_display',
                                                     str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-scope-playback-') as directory, ExitStack() as services:
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
                '--threads', '1',
                '--enable-event-simulate', '--window-geometry', '0', '0', '1280', '960',
                '--python-exit-code', '1', '--python', str(resources / 'scope_playback_runner.py'),
                '--', str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            def stop_group():
                for action in (signal.SIGCONT, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, action)
                    except ProcessLookupError:
                        pass
            try:
                stdout, _ = process.communicate(timeout=390)
            except subprocess.TimeoutExpired:
                stop_group()
                stdout, _ = process.communicate(timeout=10)
                self.fail('Installed scope playback acceptance timed out\n' + stdout[-16000:])
            finally:
                stop_group()
            data = json.loads(report.read_text()) if report.exists() else {}
            details = stdout[-16000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertNotIn('Traceback (most recent call last)', stdout, details)
            self.assertTrue(data['cold_paused_while_playing'], details)
            self.assertGreaterEqual(data['cold_resumed_frame'],1,details)
            self.assertEqual([case['stage'] for case in data['cases']],
                             ['LINEAR', 'REMAP', 'CHROMATIC'], details)
            for case in data['cases']:
                self.assertGreaterEqual(len(case['playing_frames']),2,details)
                self.assertTrue(case['publication_paused'] and case['acquisition_paused'],details)
                self.assertTrue(case['native_acknowledged'],details)
                self.assertGreaterEqual(case['resumed_frame'],1,details)
            self.assertTrue(data['loaded_animation']['native_preserved'],details)
            self.assertTrue(data['loaded_animation']['controls_restored'],details)
            self.assertTrue(data['loaded_animation']['dependency_mute_restored'],details)
            self.assertEqual([item['frame'] for item in data['loaded_animation']['frames']],[120,1],details)
            self.assertTrue(data['cleanup_clean'], details)
            print('Installed scope playback:', json.dumps(data, sort_keys=True), flush=True)
