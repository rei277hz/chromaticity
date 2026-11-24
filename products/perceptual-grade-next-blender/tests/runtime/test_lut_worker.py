"""Value receipts and back-to-back worker orchestration, independent of Blender."""

from concurrent.futures import CancelledError
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from color_tools.kernel import lut
from color_tools.kernel.settings import ColorSettings, LinearSettings, Settings, ToneSettings, WebSettings
from color_tools.lut_codec import (
    freeze_prepared, freeze_settings, thaw_prepared, thaw_settings,
)
from color_tools.lut_gpu import PreparedStack, _inverse_transforms
from color_tools.lut_worker import StackWorker


def prepared(size, settings=(), directions=()):
    values = np.zeros((size, size, size, 3), dtype=np.float32)
    edges = np.zeros((3, size, size, size, 3), dtype=np.float32)
    cube = lut.LinearCube(values, edges, "signature", "ACEScg", np.eye(3),
                          np.eye(3), size)
    diagnostics = None
    if "INVERSE" in directions:
        diagnostics = {
            "inverse_approximate_vertices": size,
            "inverse_max_residual": 2.5,
        }
    return PreparedStack(settings, "ACEScg", cube, diagnostics, directions)


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
    def __init__(self, settings, progressive, directions):
        self.receipts = (
            [None, ("preview", prepared(lut.PREVIEW_SIZE, settings, directions))]
            if progressive else []
        ) + [None, ("full", prepared(lut.SIZE, settings, directions))]
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

    def create_prepared(self, _prepared, _space, progressive, *, settings=(), directions=None):
        self.job = Job(settings, progressive, directions)
        return self.job

    def close(self):
        pass


class LUTWorkerTests(unittest.TestCase):
    def test_inverse_rejects_linear_that_becomes_singular_in_float32(self):
        matrix = np.array(((1., 1., 0.), (1., 1. + 1e-9, 0.), (0., 0., 1.)))
        self.assertEqual(np.linalg.matrix_rank(matrix), 3)
        with self.assertRaisesRegex(ValueError, "Grade 1 has a singular Linear"):
            _inverse_transforms((SimpleNamespace(linear_to_cones=matrix),), ("INVERSE",), np.eye(3))

    def worker(self):
        backend = Backend()
        with patch("color_tools.lut_worker.StackGPUBackend", return_value=backend):
            return StackWorker(), backend

    def inputs(self, progressive):
        return {"settings": freeze_settings((Settings(linear=LinearSettings(exposure=.4)),)),
                "working_space": "ACEScg", "progressive": progressive}

    def test_settings_and_complete_cube_receipts_roundtrip(self):
        settings = (Settings(
            linear=LinearSettings(exposure=.5, balance=(.1, .2),
                                  matrix=((1., 0., 0.), (0., 2., 0.), (0., 0., 3.))),
            tone=ToneSettings(fit=.5, black_compression_nits=.4, muted_gain=-.5,
                              vivid_gain=.7, saturation_crossover=.6, shadow_chroma=.3,
                              highlight_chroma=-.25, tone_crossover=60.), space="ACEScg",
            color=ColorSettings(
                adaptance=((1., -.5),)*4,
                web=WebSettings(hue_degrees=((2.,)*6,)*4,
                                log_chroma=((.1,)*6,)*4,
                                log_scale=((.2,)*6,)*4)),
        ),)
        self.assertEqual(thaw_settings(freeze_settings(settings)), settings)
        original = prepared(lut.PREVIEW_SIZE, settings)
        result = thaw_prepared(freeze_prepared(original, {"worker_pid": 12}))
        self.assertEqual(result.settings, settings)
        self.assertEqual(result.directions, ("FORWARD",))
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

    def test_missing_direction_defaults_to_forward_and_invalid_direction_is_rejected(self):
        payload = freeze_prepared(prepared(lut.PREVIEW_SIZE, (Settings(),)))
        del payload["directions"]
        self.assertEqual(thaw_prepared(payload).directions, ("FORWARD",))
        for directions in ((), ("UNKNOWN",), ("FORWARD", "INVERSE")):
            with self.subTest(directions=directions):
                payload["directions"] = directions
                with self.assertRaisesRegex(ValueError, "Stack directions"):
                    thaw_prepared(payload)

    def test_inverse_receipt_requires_consistent_residual_diagnostics(self):
        size = lut.PREVIEW_SIZE
        payload = freeze_prepared(prepared(size, (Settings(),), ("INVERSE",)))
        self.assertEqual(thaw_prepared(payload).diagnostics, payload["diagnostics"])
        for count, residual in ((0, 2.5), (1, 1.0), (size**3 + 1, 2.5), (1, np.inf)):
            with self.subTest(count=count, residual=residual):
                payload["diagnostics"] = {
                    "inverse_approximate_vertices": count,
                    "inverse_max_residual": residual,
                }
                with self.assertRaisesRegex(ValueError, "inverse diagnostics"):
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

    def test_preview_and_full_receipts_preserve_inverse_direction(self):
        worker, _backend = self.worker()
        context = Context()
        inputs = self.inputs(True)
        inputs["directions"] = ("INVERSE",)
        result = worker.dispatch("stack_lut", inputs, context)
        for payload, size in ((context.previews[0], lut.PREVIEW_SIZE), (result, lut.SIZE)):
            receipt = thaw_prepared(payload)
            self.assertEqual(receipt.directions, ("INVERSE",))
            self.assertEqual(receipt.diagnostics["inverse_approximate_vertices"], size)
            self.assertEqual(receipt.diagnostics["inverse_max_residual"], 2.5)

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
