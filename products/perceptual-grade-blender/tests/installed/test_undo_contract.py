"""The ownership model's external undo boundary, tested in pinned Blender."""
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.installed.linux_runtime import with_pinned_linux_libraries


class NativeUndoContractTests(unittest.TestCase):
    def probe(self, mode):
        resources = files('tests.installed')
        root = resources / 'blender'
        executable = root / 'blender'
        if not executable.is_file():
            executable = root / 'Blender.app/Contents/MacOS/Blender'
        with tempfile.TemporaryDirectory() as directory:
            environment = {key: value for key, value in os.environ.items()
                           if key not in {'PYTHONPATH', 'PYTHONHOME', 'BLENDER_SYSTEM_SCRIPTS',
                                          'BLENDER_SYSTEM_PYTHON'}}
            environment.update(BLENDER_USER_CONFIG=directory, BLENDER_USER_SCRIPTS=directory,
                               BLENDER_USER_EXTENSIONS=directory)
            with_pinned_linux_libraries(resources, environment)
            completed = subprocess.run([str(executable), '--background', '--factory-startup',
                '--threads', '1', '--python', str(resources / 'undo_contract_runner.py'), '--', mode],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        reports = [line.removeprefix('PG_UNDO_CONTRACT ') for line in completed.stdout.splitlines()
                   if line.startswith('PG_UNDO_CONTRACT ')]
        self.assertEqual(len(reports), 1, completed.stdout)
        return json.loads(reports[0])

    def test_handler_exceptions_do_not_veto_native_replacement(self):
        report = self.probe('failure')
        self.assertEqual(report['version'], [5, 2, 2])
        self.assertEqual(report['result'], ['FINISHED'])
        self.assertEqual(report['events'], [
            ['before', 2], ['pre_failed', 2], ['pre_next', 2],
            ['post_failed', 1], ['post_next', 1], ['after', 1]])
        self.assertFalse(report['last_exception'])

    def test_native_post_callbacks_are_synchronously_reentrant(self):
        report = self.probe('reentrant')
        self.assertEqual(report['result'], ['FINISHED'])
        self.assertEqual(report['events'], [
            ['before', 2], ['pre', 2], ['post_enter', 1], ['pre', 1],
            ['post_enter', 0], ['post_leave', 0], ['nested_result', ['FINISHED']],
            ['post_leave', 0], ['after', 0]])

    def test_native_pre_callbacks_can_complete_nested_undo_before_outer_replacement(self):
        report = self.probe('reentrant_pre')
        self.assertEqual(report['result'], ['FINISHED'])
        self.assertEqual(report['events'], [
            ['before', 2], ['pre_enter', 2], ['pre_enter', 2], ['pre_leave', 2],
            ['post', 1], ['nested_result', ['FINISHED']], ['pre_leave', 1],
            ['post', 0], ['after', 0]])
