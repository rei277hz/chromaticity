"""Durable crash markers and actual cross-process ownership leases."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from color_tools.blender_runtime.execution.journal import Lease, Session, recover


FIXTURE = Path(__file__).with_name('helper_fixture.py')


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def child(self, mode, root):
        ready = self.root / ('ready-' + str(time.monotonic_ns()))
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join(path for path in sys.path if path)
        process = subprocess.Popen([sys.executable, str(FIXTURE), mode, str(root), str(ready)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, process)
        end = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < end:
            time.sleep(.005)
        self.assertTrue(ready.exists(), 'Lease fixture failed to start')
        return process, Path(ready.read_text())

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        process.stderr.close()

    def test_concurrent_live_sessions_are_never_reclaimed(self):
        first, second = Session(self.root), Session(self.root)
        self.addCleanup(first.lease.close)
        self.addCleanup(second.lease.close)
        self.assertEqual(recover(self.root), ())
        first.close(False)
        self.assertEqual(recover(self.root), ((first.path.name, False),))
        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())
        second.close(True)
        self.assertEqual(recover(self.root), ((second.path.name, True),))

    def test_orphan_helper_lease_blocks_reclamation_until_actual_exit(self):
        session = Session(self.root)
        process, path = self.child('lease', session.path)
        session.close(False)
        self.assertEqual(recover(self.root), ())
        self.assertTrue(path.exists())
        self.stop(process)
        self.assertEqual(recover(self.root), ((path.name, False),))
        self.assertFalse(path.exists())

    def test_actual_owner_kill_leaves_unclean_marker_and_next_session_repairs(self):
        process, path = self.child('owner', self.root)
        self.assertFalse(json.loads((path / 'journal.json').read_text())['clean'])
        self.assertEqual(recover(self.root), ())
        self.stop(process)
        replacement = Session(self.root)
        self.addCleanup(replacement.close, True)
        self.assertEqual(replacement.recovered, ((path.name, False),))
        self.assertFalse(path.exists())
        self.assertFalse(json.loads((replacement.path / 'journal.json').read_text())['clean'])

    def test_interrupted_recovery_defers_only_owned_session_and_allows_new_runtime(self):
        session = Session(self.root)
        healthy = Session(self.root)
        (session.path / 'array-partial.npy').write_bytes(b'incomplete')
        session.close(False)
        healthy.close(True)
        original = Path.unlink
        def fail_payload(path, *args, **kwargs):
            if path.name == 'array-partial.npy':
                raise OSError('Injected interruption during reclamation')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_payload):
            with self.assertLogs('color_tools.blender_runtime.execution.journal', level='WARNING'):
                self.assertEqual(recover(self.root), ((healthy.path.name, True),))
            self.assertFalse(json.loads((session.path / 'journal.json').read_text())['clean'])
            with self.assertLogs('color_tools.blender_runtime.execution.journal', level='WARNING'):
                replacement = Session(self.root)
            self.addCleanup(replacement.close, True)
            self.assertEqual(replacement.recovered, ())
            self.assertTrue(replacement.path.exists())
        lease = Lease(session.path / 'lease', exclusive=True)
        lease.close()
        self.assertEqual(recover(self.root), ((session.path.name, False),))
        self.assertEqual(recover(self.root), ())

    def test_failed_clean_commit_preserves_unclean_record_and_releases_lease(self):
        session = Session(self.root)
        with patch('color_tools.blender_runtime.execution.journal.os.fsync', side_effect=OSError('Disk failure')):
            with self.assertRaisesRegex(OSError, 'Disk failure'):
                session.close(True)
        self.assertFalse(json.loads((session.path / 'journal.json').read_text())['clean'])
        self.assertEqual(recover(self.root), ((session.path.name, False),))

    def test_unowned_symlink_is_never_followed(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'precious').write_text('retained')
        try:
            (self.root / 'session-symlink').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        self.assertEqual(recover(self.root), ())
        self.assertEqual((outside / 'precious').read_text(), 'retained')
