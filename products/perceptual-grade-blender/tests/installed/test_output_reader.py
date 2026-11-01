"""Blender host reader scheduling exercised against the installed extension."""
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


class NativeOutputReaderTests(unittest.TestCase):
    def test_every_bound_bank_is_read_between_publications(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_reader_display', str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-output-reader-') as directory, ExitStack() as services:
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
                '--window-geometry', '0', '0', '1280', '960', '--python-exit-code', '1',
                '--python', str(resources / 'output_reader_runner.py'), '--',
                str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                stdout, _ = process.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=10)
                self.fail('Native reader probe timed out\n' + stdout[-16000:])
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            data = json.loads(report.read_text()) if report.exists() else {}
            detail = stdout[-16000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, detail)
            self.assertTrue(data.get('passed'), detail)
            self.assertEqual(data['publications'], 11, detail)
            self.assertEqual(data['failed_transfers'], 1, detail)
            self.assertGreater(data['blocked_render_attempts'], 0, detail)
            self.assertTrue(data['render_reader_off_main'], detail)
            self.assertTrue(data['render_publication_acknowledged'], detail)
            render_barriers = [event for event in data['events']
                               if event['event'] == 'render_publication_rejected']
            self.assertTrue(render_barriers, detail)
            self.assertTrue(all(event['native_job'] == 'RENDER' and event['job_running']
                                and event['main_thread'] and event['reader_started']
                                and event['reason'] and event['rejection']
                                for event in render_barriers), detail)
            self.assertGreater(data['blocked_light_bake_attempts'], 0, detail)
            self.assertGreater(data['light_bake_without_public_job'], 0, detail)
            self.assertTrue(all(value >= 15 for value in data['reads_by_bank']), detail)
            print('Native output reader contract:', json.dumps(data, sort_keys=True), flush=True)
