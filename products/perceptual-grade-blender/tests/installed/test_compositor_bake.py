"""Installed analytic compositor bakes, shared Images and native modal undo."""
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


class InstalledCompositorBakeTests(unittest.TestCase):
    def test_packed_snapshots_and_native_publication(self):
        resources = files('tests.installed')
        binary_root = Path(str(resources / 'blender')).resolve()
        blender = next(path for path in (binary_root / 'blender',
            binary_root / 'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec = importlib.util.spec_from_file_location('pg_bake_display',
                                                     str(resources / 'gui_display.py'))
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-installed-bake-') as directory, ExitStack() as services:
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
                '--python-exit-code', '1', '--python', str(resources / 'compositor_bake_runner.py'),
                '--', str(package.parent), str(report)], cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            def stop_group():
                for action in (signal.SIGCONT, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, action)
                    except ProcessLookupError:
                        pass
            try:
                stdout, _ = process.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                stop_group()
                stdout, _ = process.communicate(timeout=10)
                self.fail('Installed compositor bake timed out\n' + stdout[-20000:])
            finally:
                stop_group()
            data = json.loads(report.read_text()) if report.exists() else {}
            details = stdout[-20000:] + '\n' + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get('passed'), details)
            self.assertEqual(set(data['snapshots']), {'Grade', 'Stack'}, details)
            self.assertEqual({item['case'] for item in data['rebakes']},
                             {'same_dimensions', 'changed_dimensions'}, details)
            for value in data['snapshots'].values():
                self.assertGreater(value['analytic_lut_difference'], 1e-6, details)
                self.assertLessEqual(value['maximum_error'], 3e-6, details)
            for value in data['rebakes']:
                self.assertTrue(value['same_image'] and value['undo_redo'] and value['no_recapture'], details)
                self.assertEqual(value['consumers'], 3, details)
            for key in ('source_graph_unchanged', 'settings_unchanged', 'packed_reopen',
                        'source_baked_color', 'shared_image_consumers', 'first_bake_undo_redo',
                        'rebake_packed_reopen', 'temporary_exrs_removed', 'bake_node_replay',
                        'external_image_untouched',
                        'reopened_controls_drawn', 'reopened_selections', 'reopened_tooltips',
                        'grade_selection_cancels_bake', 'grade_parameter_cancels_bake',
                        'editor_selection_keeps_bake',
                        'destination_selection', 'other_destination_untouched',
                        'parallel_bakes', 'parallel_publication_undo', 'shared_destination_queue',
                        'recovery_failure_retained', 'recovery_retry_no_recapture',
                        'dirty_image_preserved',
                        'native_modal_undo_redo', 'intervening_edit_preserved', 'redo_no_recapture',
                        'cancel_ready_without_image', 'snapshot_leases_released',
                        'playback_cancel_running_queued', 'playback_no_new_request', 'playback_cancel_ready',
                        'playback_stop_waits_for_native', 'native_wait_tooltip', 'native_wait_race_click',
                        'pending_load_cancelled', 'active_disable_retired',
                        'helper_is_native', 'helper_exited', 'cleanup_clean'):
                self.assertTrue(data.get(key), key + '\n' + details)
            print('Installed compositor bake:', json.dumps(data, sort_keys=True), flush=True)
