"""Array ownership and bounded incremental control transport."""
import gc
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from color_tools.blender_runtime.execution.payloads import CHUNK, PayloadStore
from color_tools.blender_runtime.execution.transport import Channel, frame


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = PayloadStore(self.root)
        self.addCleanup(self.store.close)

    def test_primitive_and_strided_array_roundtrip_and_view_lifetime(self):
        values = np.arange(42, dtype='f4').reshape(6, 7)[:, ::2]
        payload = {'values': values, 'tuple': (np.int64(7), float('inf'), float('nan')), 'empty': None}
        files = []
        encoded = self.store.encode(payload, files)
        actual = self.store.decode(encoded)
        np.testing.assert_array_equal(actual['values'], values)
        self.assertIsInstance(actual['tuple'], tuple)
        self.assertEqual(actual['tuple'][:2], (7, float('inf')))
        self.assertTrue(np.isnan(actual['tuple'][2]))
        self.assertFalse(actual['values'].flags.writeable)
        view = actual['values'][1:]
        del actual
        gc.collect();self.store.collect()
        self.assertTrue((self.root / files[0]).exists())
        del view
        gc.collect();self.store.collect()
        self.assertFalse((self.root / files[0]).exists())

    def test_copied_input_can_release_file_without_invalidating_values(self):
        values = np.arange(24, dtype='i4')
        files = []
        actual = self.store.decode(self.store.encode(values, files), copy=True)
        self.store.release_files(files)
        np.testing.assert_array_equal(actual, values)
        self.assertFalse(actual.flags.writeable)
        self.assertFalse(self.store.mapped)
        self.assertFalse(list(self.root.glob('array-*')))

    def test_close_keeps_existing_consumer_views_readable(self):
        values = np.arange(24, dtype='f4').reshape(6, 4)
        files = []
        actual = self.store.decode(self.store.encode(values, files))
        view = actual[1:, ::2]
        self.store.close()
        np.testing.assert_array_equal(actual, values)
        np.testing.assert_array_equal(view, values[1:, ::2])
        if os.name != 'nt':
            self.assertFalse(self.store.owned)
            self.assertFalse((self.root / files[0]).exists())
        del actual, view
        gc.collect()
        self.store.close()
        self.assertFalse(self.store.owned)

    def test_array_staging_yields_in_bounded_chunks_and_can_abort(self):
        values = np.arange(CHUNK * 3 // 4, dtype='f4')
        files = []
        generator = self.store.encode_iter(values, files)
        next(generator)
        self.assertEqual(len(files), 1)
        partial = np.load(self.root / files[0], mmap_mode='r')
        np.testing.assert_array_equal(partial[:CHUNK // 4], values[:CHUNK // 4])
        self.assertEqual(partial[-1], 0)
        partial._mmap.close()
        generator.close()
        self.store.release_files(files)
        self.assertFalse(self.store.owned)
        self.assertFalse(list(self.root.iterdir()))

    def test_descriptor_mismatch_and_unsafe_paths_are_rejected(self):
        files = []
        encoded = self.store.encode(np.arange(5, dtype='f4'), files)
        for change in ({'shape': [6]}, {'dtype': '<i4'}, {'bytes': 1}, {'shape': [-5]},
                       {'shape': [True]}, {'dtype': 'O'}, {'$array': '../array-escape.npy'}):
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)):
                self.store.decode(encoded | change)
        link = self.root / 'array-link.npy'
        try:
            link.symlink_to(self.root / files[0])
        except (OSError, NotImplementedError):
            return
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.store.decode(encoded | {'$array': link.name})

    def test_budget_and_arbitrary_objects_reject_before_creating_payload(self):
        self.store.maximum = 8
        for value, error in ((np.zeros(9, dtype='u1'), MemoryError),
                             (np.array([object()], dtype=object), ValueError),
                             (object(), TypeError)):
            with self.subTest(value=type(value)), self.assertRaises(error):
                self.store.encode(value, [])
        self.assertFalse(list(self.root.iterdir()))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.sender, receiver = socket.socketpair()
        self.channel = Channel(receiver)
        self.addCleanup(self.sender.close)
        self.addCleanup(self.channel.close)

    def test_partial_frames_and_multiple_receipts_preserve_message_boundaries(self):
        first, second = frame({'kind': 'hello'}), frame({'kind': 'complete', 'attempt': 42})
        self.sender.sendall(first[:2])
        self.assertEqual(self.channel.pump(), [])
        self.sender.sendall(first[2:7])
        self.assertEqual(self.channel.pump(), [])
        self.sender.sendall(first[7:] + second)
        self.assertEqual(self.channel.pump(), [{'kind': 'hello'}, {'kind': 'complete', 'attempt': 42}])
        self.assertFalse(self.channel.incoming)

    def test_oversized_frame_is_rejected_before_receiving_body(self):
        with patch('color_tools.blender_runtime.execution.transport.MAX_FRAME', 64):
            self.sender.sendall(struct.pack('!I', 65))
            with self.assertRaisesRegex(ValueError, 'Oversized'):
                self.channel.pump()

    def test_outgoing_queue_is_bounded_and_serialization_error_keeps_existing_frame(self):
        with patch('color_tools.blender_runtime.execution.transport.MAX_FRAME', 64):
            self.channel.send({'value': 'x' * 40})
            self.channel.send({'value': 'y' * 40})
            existing = bytes(self.channel.outgoing)
            with self.assertRaises(BufferError):
                self.channel.send({'value': 'z' * 40})
            self.assertEqual(bytes(self.channel.outgoing), existing)
            with self.assertRaises(ValueError):
                self.channel.send({'value': float('nan')})
            self.assertEqual(bytes(self.channel.outgoing), existing)
