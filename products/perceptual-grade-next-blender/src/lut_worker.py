"""Back-to-back Stack GPU calculations in a private Blender helper process."""

import asyncio
import os
import time

import numpy as np

from .kernel import lut
from .lut_codec import freeze_prepared, thaw_settings
from .lut_gpu import StackGPUBackend
from .runtime.grade_preparation import GradePreparer


class StackWorker:
    """One process-owned backend, reused across serial helper operations."""

    def __init__(self):
        self.backend = StackGPUBackend()
        self.preparer = GradePreparer()

    def dispatch(self, operation, inputs, context):
        if context.role != "gpu":
            raise RuntimeError("Grade Stack baking requires the GPU helper")
        if operation == "gpu_probe":
            return self.probe(context)
        if operation == "stack_lut":
            return self.bake(inputs, context)
        raise ValueError("Unknown Stack helper operation: " + operation)

    def probe(self, context):
        """Exercise dispatch and readback before admitting required-GPU jobs."""
        context.checkpoint()
        job = self.backend.create_prepared((), "ACEScg", False)
        try:
            prepared = None
            while prepared is None:
                context.checkpoint()
                receipt = job.advance()
                if receipt is not None:
                    _quality, prepared = receipt
            cube = prepared.cube
            for index in ((0, 0, 0), (32, 17, 8), (64, 64, 64)):
                expected = lut.axis()[list(index)]
                if not np.allclose(cube.values[index], expected, rtol=2e-6, atol=1e-4):
                    raise ArithmeticError("Grade Stack GPU probe did not preserve identity")
            context.checkpoint()
            return {"conformance": True, "backend": "GPU", "worker_pid": os.getpid(),
                    "device": self.backend._gpu.platform.renderer_get()}
        finally:
            job.close()

    def bake(self, inputs, context):
        started = time.perf_counter()
        context.checkpoint()
        settings = thaw_settings(inputs["settings"])
        space = inputs["working_space"]
        progressive = bool(inputs["progressive"])
        preparation_rows = {}

        def timing(signature, component, began, finished):
            row = preparation_rows.setdefault(signature, {
                "signature": signature, "components": {},
            })
            row["components"][component] = finished - began

        self.preparer.on_timing = timing

        async def prepare_all():
            results = await asyncio.gather(
                *(self.preparer.prepare(item) for item in settings),
                return_exceptions=True,
            )
            # A preparation may fail while its siblings still own workers.
            # Wait for every physical writer before propagating any failure.
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            return tuple(results)

        preparation_started = time.perf_counter()
        try:
            prepared_grades = asyncio.run(prepare_all())
        finally:
            self.preparer.on_timing = None
        preparation_wall = time.perf_counter() - preparation_started
        context.checkpoint()
        reused = self.backend._shader is not None
        job = self.backend.create_prepared(
            prepared_grades, space, progressive, settings=settings,
        )
        setup_seconds = time.perf_counter() - started
        phase = "preview" if progressive else "full"
        phases = {}

        def phase_metrics():
            return phases.setdefault(phase, {
                "dispatch_batches": 0,
                "dispatch_submission_seconds": 0.0,
                "readback_seconds": 0.0,
                "inter_step_wait_seconds": 0.0,
                "texture_allocation_seconds": 0.0,
            })

        try:
            previous_finished = None
            while True:
                context.checkpoint()
                metrics = phase_metrics()
                step_started = time.perf_counter()
                if previous_finished is not None:
                    metrics["inter_step_wait_seconds"] += step_started - previous_finished
                readback = job._readback_pending
                receipt = job.advance()
                previous_finished = time.perf_counter()
                if readback:
                    metrics["readback_seconds"] = job.readback_seconds[phase]
                else:
                    metrics["dispatch_batches"] += 1
                    metrics["dispatch_submission_seconds"] += previous_finished - step_started
                metrics["texture_allocation_seconds"] = job.texture_allocation_seconds[phase]
                if receipt is None:
                    continue
                quality, prepared = receipt
                calculated_at = time.perf_counter()
                diagnostics = {
                    "worker_pid": os.getpid(),
                    "worker_started_at": started,
                    "worker_calculated_at": calculated_at,
                    "worker_setup_seconds": setup_seconds,
                    "worker_program_reused": reused,
                    "backend": "GPU",
                    "grade_preparation": list(preparation_rows.values()),
                    "grade_preparation_wall_seconds": preparation_wall,
                    "phases": {name: dict(values) for name, values in phases.items()},
                }
                payload = freeze_prepared(prepared, diagnostics)
                diagnostics["worker_receipt_prepared_at"] = time.perf_counter()
                context.checkpoint()
                if quality == "full":
                    return payload
                if quality != "preview" or not progressive:
                    raise RuntimeError("Stack helper emitted unexpected quality")
                context.preview(payload)
                # Cancellation requested after this receipt is observed at the
                # next dispatch boundary; physical retirement precedes reuse.
                phase = "full"
                previous_finished = None
        finally:
            job.close()

    def close(self):
        try:
            self.backend.close()
        finally:
            self.preparer.close()


def create():
    return StackWorker()
