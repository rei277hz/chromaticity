"""Verify launch grouping, streaming evidence retention and report completeness."""
from importlib.machinery import SourceFileLoader
from importlib.resources import files
from importlib.util import module_from_spec, spec_from_loader
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile


class UndoCollectionTests(unittest.TestCase):
    def setUp(self):
        self.resources = files('tests.diagnostics')
        script = str(self.resources / 'pg_undo_trace_collect.py')
        loader = SourceFileLoader('_pg_undo_collection_test', script)
        self.collector = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(self.collector)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.recording = self.root / 'perceptual-grade-undo-trace-test'
        self.recording.mkdir()
        self.native = self.root / 'native'
        self.native.mkdir()
        self.metadata = dict(started_epoch=time.time(), blender_tempdir='', blend_filepath='', pid=1234,
                             native_session_dir=str(self.native))
        self.recorder(self.recording, self.metadata)

    def recorder(self, directory, metadata):
        directory.mkdir(parents=True, exist_ok=True)
        for name in ('events.jsonl', 'fatal-python.txt', 'periodic-python.txt', 'console.log'):
            (directory / name).write_text('')
        (directory / 'metadata.json').write_text(json.dumps(metadata))

    def collect(self, directory=None):
        (self.recording / 'metadata.json').write_text(json.dumps(self.metadata))
        with patch.object(Path, 'home', return_value=self.root):
            archive = self.collector.collect_session(directory or self.recording)
        with zipfile.ZipFile(archive) as bundle:
            root = bundle.namelist()[0].split('/')[0]
            collection = json.loads(bundle.read(root + '/collection.json'))
            self.assertIsNone(bundle.testzip())
        self.assertEqual(json.loads((archive.parent / root / 'collection.json').read_text()), collection)
        return archive, collection

    def modern(self, mandatory=()):
        manifest = dict(schema=1, launch_id='launch-1234', blender_pid=1234,
                        mandatory_artifacts=list(mandatory))
        (self.native / 'session.json').write_text(json.dumps(manifest))
        self.metadata.update(launch_id=manifest['launch_id'], native_session_dir=str(self.native))
        return manifest

    def test_preserves_launcher_nested_logs_hashes_and_explains_skipped_files(self):
        (self.native / 'launcher.txt').write_text('blender_pid=1234\nexit_status=134\n')
        (self.native / 'launcher-console.log').write_text('native diagnostic\n')
        nested = self.native / 'process-1234'
        nested.mkdir()
        (nested / 'stack-logs.data').write_bytes(b'allocation history')
        outside = self.root / 'unrelated.data'
        outside.write_bytes(b'not from this launch')
        (self.native / 'alias').symlink_to(outside)
        (self.native / 'directory-alias').symlink_to(self.root, target_is_directory=True)
        with (self.native / 'oversized.data').open('wb') as output:
            output.truncate(256 * 1024**2 + 1)
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.native / 'fifo')
        archive, collection = self.collect()
        rows = {Path(row['source']).name: row for row in collection['native_allocation']}
        self.assertEqual(rows['alias']['status'], 'skipped-symlink')
        self.assertEqual(rows['directory-alias']['status'], 'skipped-symlink')
        self.assertEqual(rows['oversized.data']['status'], 'size-limit')
        if hasattr(os, 'mkfifo'):
            self.assertEqual(rows['fifo']['status'], 'skipped-nonregular-file')
        self.assertTrue(rows['stack-logs.data']['complete_snapshot'])
        self.assertEqual(rows['stack-logs.data']['sha256'], hashlib.sha256(b'allocation history').hexdigest())
        self.assertTrue(collection['native_allocation_requested'])
        self.assertEqual(collection['artifact_completeness'], 'complete')
        self.assertEqual(collection['causal_coverage'], 'incomplete')
        with zipfile.ZipFile(archive) as bundle:
            prefix = self.recording.name + '/native-allocation/'
            self.assertEqual(bundle.read(prefix + 'process-1234/stack-logs.data'), b'allocation history')
            self.assertFalse(any(name.endswith('oversized.data') or name.endswith('/alias')
                                 for name in bundle.namelist()))

    def test_reports_missing_directory_and_does_not_guess_another_launch(self):
        self.metadata['native_session_dir'] = str(self.root / 'absent')
        _, collection = self.collect()
        self.assertEqual(collection['native_allocation'][0]['status'], 'missing-or-symlink-directory')
        self.assertEqual(collection['artifact_completeness'], 'incomplete')
        self.metadata.pop('native_session_dir')
        _, collection = self.collect()
        self.assertFalse(collection['native_allocation_requested'])
        self.assertEqual(collection['native_allocation'], [])

    def test_helper_entry_limit_cannot_crowd_out_main_pid(self):
        for index in range(2001):
            (self.native / ('helper-log-' + str(index))).touch()
        (self.native / 'launcher.txt').write_text('launcher marker')
        main = self.native / 'stack-logs.1234.main.index'
        main.write_text('main history')
        diagnostics = {'launch.json', 'wait-stop-failure.json', 'wait-stop-timeout.json',
                       'before-dispose.json', 'capture-errors.log'}
        for name in diagnostics:
            (self.native / name).write_text('original process failure evidence')
        _, collection = self.collect()
        rows = collection['native_allocation']
        required = diagnostics | {'launcher.txt', main.name}
        self.assertEqual({Path(row['source']).name for row in rows[:len(required)]}, required)
        self.assertTrue(all(row['mandatory'] and row['complete_snapshot']
                            for row in rows[:len(required)]))
        self.assertEqual(sum(row['status'] == 'included' for row in rows), 2000 + len(required))
        self.assertEqual(sum(row['status'] == 'entry-count-limit' for row in rows), 1)
        self.assertEqual(collection['optional_entries_skipped'], 1)
        self.assertEqual(collection['artifact_completeness'], 'complete')
        self.assertEqual(collection['optional_completeness'], 'incomplete')

    def test_mandatory_main_allocation_above_old_per_file_limit_is_streamed(self):
        main = self.native / 'stack-logs.1234.Blender.index'
        size = 256 * 1024**2 + 1
        with main.open('wb') as output:
            output.truncate(size)
        archive, collection = self.collect()
        row = next(row for row in collection['native_allocation'] if Path(row['source']) == main)
        self.assertEqual(row['captured_bytes'], size)
        self.assertTrue(row['mandatory'])
        self.assertEqual(row['status'], 'included')
        with zipfile.ZipFile(archive) as bundle:
            info = bundle.getinfo(self.recording.name + '/' + row['copy'])
            self.assertEqual(info.file_size, size)
            self.assertGreaterEqual(info.extract_version, 45)
        self.assertEqual(main.stat().st_size, size)

    def test_growing_mandatory_file_is_bounded_and_flagged_incomplete(self):
        self.modern(['growing.data'])
        growing = self.native / 'growing.data'
        growing.write_bytes(b'initial')
        inode = growing.stat().st_ino
        original = os.fstat
        calls = 0

        def append_after_stat(descriptor):
            nonlocal calls
            result = original(descriptor)
            if result.st_ino == inode:
                calls += 1
                if calls == 2:  # First fstat rejects nonregular files; second sets snapshot length.
                    with growing.open('ab') as output:
                        output.write(b' appended during collection')
            return result

        with patch.object(os, 'fstat', side_effect=append_after_stat):
            archive, collection = self.collect()
        row = next(row for row in collection['artifacts'] if Path(row['source']) == growing)
        self.assertEqual(row['captured_bytes'], len(b'initial'))
        self.assertTrue(row['changed_during_copy'])
        self.assertFalse(row['complete_snapshot'])
        self.assertEqual(collection['artifact_completeness'], 'incomplete')
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.read(self.native.name + '/' + row['copy']), b'initial')

    def test_launch_includes_restarted_recorders_and_excludes_other_launch(self):
        self.modern(['native-undo.log'])
        (self.native / 'native-undo.log').write_text('keep identical data-block')
        first = self.native / 'python' / 'first'
        second = self.native / 'python' / 'second'
        unrelated = self.native / 'python' / 'unrelated'
        for path in (first, second):
            self.recorder(path, self.metadata)
        self.recorder(unrelated, dict(self.metadata, launch_id='another-launch'))
        archive, collection = self.collect(self.native)
        self.assertIn(str(first), collection['recordings'])
        self.assertIn(str(second), collection['recordings'])
        self.assertNotIn(str(unrelated), collection['recordings'])
        with zipfile.ZipFile(archive) as bundle:
            self.assertTrue(any('/python/first/events.jsonl' in name for name in bundle.namelist()))
            self.assertFalse(any('/unrelated/' in name for name in bundle.namelist()))


    def test_missing_and_symlinked_mandatory_paths_are_explicit_gaps(self):
        self.modern(['absent.txt', 'alias/data'])
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'data').write_text('must not collect')
        (self.native / 'alias').symlink_to(outside, target_is_directory=True)
        archive, collection = self.collect(self.native)
        gaps = {Path(row['source']).relative_to(self.native).as_posix(): row['status']
                for row in collection['mandatory_gaps']}
        self.assertEqual(gaps['absent.txt'], 'missing-artifact')
        self.assertEqual(gaps['alias/data'], 'skipped-symlink')
        with zipfile.ZipFile(archive) as bundle:
            self.assertFalse(any(name.endswith('/alias/data') for name in bundle.namelist()))

    def test_causal_coverage_does_not_imply_artifact_completeness(self):
        manifest = self.modern(['absent.txt'])
        manifest['causal_evidence'] = {key: True for key in self.collector.CAUSAL_KEYS}
        (self.native / 'session.json').write_text(json.dumps(manifest))
        _, collection = self.collect(self.native)
        self.assertEqual(collection['causal_coverage'], 'complete')
        self.assertEqual(collection['artifact_completeness'], 'incomplete')
        with patch.object(Path, 'home', return_value=self.root):
            self.assertEqual(self.collector.main([str(self.native)]), 3)

    def test_storage_failure_does_not_publish_and_preserves_source(self):
        (self.recording / 'metadata.json').write_text(json.dumps(self.metadata))
        with patch.object(zipfile.ZipFile, 'open', side_effect=OSError(errno.ENOSPC, 'No space')):
            with self.assertRaises(OSError):
                self.collector.collect_session(self.recording)
        self.assertFalse(list(self.root.glob('*.zip')))
        self.assertFalse(list(self.root.glob('*.partial')))
        self.assertTrue((self.recording / 'metadata.json').is_file())

    def test_crc_failure_does_not_publish_archive(self):
        with patch.object(zipfile.ZipFile, 'testzip', return_value='corrupt-member'):
            with self.assertRaisesRegex(RuntimeError, 'CRC verification'):
                self.collect()
        self.assertFalse(list(self.root.glob('*.zip')))

    def test_recorder_collect_delegates_to_companion(self):
        script = str(self.resources / 'pg_undo_trace.py')
        loader = SourceFileLoader('_pg_undo_recorder_collection_test', script)
        recorder = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(recorder)
        self.modern(['native-undo.log'])
        (self.native / 'native-undo.log').write_text('undo decisions')
        (self.recording / 'metadata.json').write_text(json.dumps(self.metadata))
        with patch.object(Path, 'home', return_value=self.root), \
                patch.dict(os.environ, PG_UNDO_TRACE_TOOLS_DIR=str(self.resources)):
            archive = recorder.collect_report(self.recording)
        with zipfile.ZipFile(archive) as bundle:
            collection = json.loads(bundle.read(self.native.name + '/collection.json'))
        self.assertEqual(collection['schema'], 2)
        self.assertEqual(collection['artifact_completeness'], 'complete')

    def test_shell_wrapper_quotes_paths_and_runs_without_blender(self):
        script_dir = self.root / 'tools $(do-not-execute) with spaces'
        script_dir.mkdir()
        for name in ('pg_undo_trace_pack.command', 'pg_undo_trace_collect.py'):
            (script_dir / name).write_bytes((self.resources / name).read_bytes())
        self.metadata.pop('native_session_dir')
        (self.recording / 'metadata.json').write_text(json.dumps(self.metadata))
        result = subprocess.run(['bash', str(script_dir / 'pg_undo_trace_pack.command'), str(self.recording)],
                                env=dict(os.environ, PG_UNDO_TRACE_PYTHON=sys.executable),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('diagnostic ZIP:', result.stdout)


if __name__ == '__main__':
    unittest.main()
