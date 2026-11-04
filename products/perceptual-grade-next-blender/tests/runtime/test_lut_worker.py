"""Value receipts and back-to-back worker orchestration, independent of Blender."""

from concurrent.futures import CancelledError
from unittest.mock import patch
import unittest

import numpy as np

from color_tools.kernel import lut
from color_tools.kernel.settings import LinearSettings
from color_tools.lut_codec import (
    freeze_prepared, freeze_settings, thaw_prepared, thaw_settings,
)
from color_tools.lut_gpu import PreparedStack
from color_tools.lut_worker import StackWorker


def prepared(size, settings=()):
    values = np.zeros((size, size, size, 3), dtype=np.float32)
    edges = np.zeros((3, size, size, size, 3), dtype=np.float32)
    cube = lut.LinearCube(values, edges, "signature", "ACEScg", np.eye(3),
                          np.eye(3), size)
    return PreparedStack(settings, "ACEScg", cube)


class Context:
    role = "gpu"

    def __init__(self):
        self.previews = []
        self.cancelled = False
        self.checks = 0

    def checkpoint(self):
        self.checks += 1
        if self.cancelled:
            raise CancelledError()

    def preview(self, value):
        self.previews.append(value)


class Job:
    def __init__(self, settings, progressive):
        self.receipts = (
            [None, ("preview", prepared(lut.PREVIEW_SIZE, settings))]
            if progressive else []
        ) + [None, ("full", prepared(lut.SIZE, settings))]
        self.closed = False
        self._readback_pending = False
        self.texture_allocation_seconds = {"preview": 0.0, "full": 0.0}
        self.readback_seconds = {"preview": 0.0, "full": 0.0}

    def advance(self):
        value = self.receipts.pop(0)
        self._readback_pending = bool(self.receipts and self.receipts[0] is not None)
        return value

    def close(self):
        self.closed = True


class Backend:
    _shader = None

    def create_job(self, settings, _space, progressive):
        self.job = Job(settings, progressive)
        return self.job

    def close(self):
        pass


class LUTWorkerTests(unittest.TestCase):
    def worker(self):
        backend = Backend()
        with patch("color_tools.lut_worker.StackGPUBackend", return_value=backend):
            return StackWorker(), backend

    def inputs(self, progressive):
        return {"settings": freeze_settings((LinearSettings(exposure=.4),)),
                "working_space": "ACEScg", "progressive": progressive}

    def test_settings_and_complete_cube_receipts_roundtrip(self):
        settings = (LinearSettings(exposure=.5, balance=(.1, .2),
                                   matrix=((1., 0., 0.), (0., 2., 0.), (0., 0., 3.))),)
        self.assertEqual(thaw_settings(freeze_settings(settings)), settings)
        original = prepared(lut.PREVIEW_SIZE, settings)
        result = thaw_prepared(freeze_prepared(original, {"worker_pid": 12}))
        self.assertEqual(result.settings, settings)
        self.assertEqual(result.diagnostics["worker_pid"], 12)
        self.assertFalse(result.cube.values.flags.writeable)
        self.assertFalse(result.cube.edge_values.flags.writeable)
        np.testing.assert_array_equal(result.cube.values, original.cube.values)

    def test_incomplete_or_nonfinite_receipt_is_rejected(self):
        payload = freeze_prepared(prepared(lut.PREVIEW_SIZE))
        payload["values"] = payload["values"][:-1]
        with self.assertRaisesRegex(ValueError, "values"):
            thaw_prepared(payload)
        payload = freeze_prepared(prepared(lut.PREVIEW_SIZE))
        payload["to_lut"][0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "input basis"):
            thaw_prepared(payload)

    def test_progressive_operation_publishes_preview_then_finishes_in_one_call(self):
        worker, backend = self.worker()
        context = Context()
        result = worker.dispatch("stack_lut", self.inputs(True), context)
        self.assertEqual([item["size"] for item in context.previews], [33])
        self.assertEqual(result["size"], 65)
        self.assertTrue(backend.job.closed)
        self.assertGreater(context.checks, 4)
        self.assertEqual(set(result["diagnostics"]["phases"]), {"preview", "full"})

    def test_direct_operation_has_only_full_receipt(self):
        worker, backend = self.worker()
        context = Context()
        result = worker.dispatch("stack_lut", self.inputs(False), context)
        self.assertEqual(context.previews, [])
        self.assertEqual(result["size"], 65)
        self.assertTrue(backend.job.closed)

    def test_superseded_preview_retires_at_next_checkpoint(self):
        worker, backend = self.worker()
        context = Context()

        def cancel_after_preview(value):
            context.previews.append(value)
            context.cancelled = True

        context.preview = cancel_after_preview
        with self.assertRaises(CancelledError):
            worker.dispatch("stack_lut", self.inputs(True), context)
        self.assertEqual(len(context.previews), 1)
        self.assertTrue(backend.job.closed)
        self.assertEqual(len(backend.job.receipts), 2)

    def test_non_gpu_role_is_rejected_before_backend_use(self):
        worker, _backend = self.worker()
        context = Context()
        context.role = "bulk"
        with self.assertRaisesRegex(RuntimeError, "GPU helper"):
            worker.dispatch("stack_lut", self.inputs(False), context)


if __name__ == "__main__":
    unittest.main()
