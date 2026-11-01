"""Verification adapters for the retained production .4*capacity crossover.

This module is not part of a runtime component or extension bundle. Production
comparisons explicitly opt into the previous reference classifier; the public
analytic reference uses 35/75*abs(J_A). The grading equations and independent
inverse remain the reference implementation, while baking retains the unchanged
shared float32 kernels.
"""
import numpy as np
from color_tools.color_core.scaled import norm
from color_tools.perceptual_grade_reference import grading
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.stack import Stack, FROM_NATIVE, matrix_native
from color_tools.perceptual_grade_core.model.bake import Kernel
from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_core.model.stack_kernel import StackKernel
from color_tools.perceptual_grade_core.model.tone_table import ToneTable


CHROMA_CAPACITY_FRACTION = .4


def legacy_drivers(q, ja, capacity=None):
    """Previous independent driver oracle, including optional explicit U."""
    q = np.asarray(q, dtype=np.float64)
    if capacity is None:
        from color_tools.perceptual_grade_reference.cube import default_context
        capacity = default_context().capacity(ja, np.arctan2(q[..., 2], q[..., 1]))
    return grading._drivers_at_radius(q, CHROMA_CAPACITY_FRACTION*np.asarray(capacity, dtype=np.float64))


class LegacyCapacityColor(grading.Color):
    def _crossover_radius(self, q, ja):
        return CHROMA_CAPACITY_FRACTION*self.boundary.capacity(ja, np.arctan2(q[..., 2], q[..., 1]))

    def _scaled_crossover_radius(self, q, ja):
        c = norm(q[1:])
        angle = np.arctan2(float(q[2]/c), float(q[1]/c)) if c else 0.
        return CHROMA_CAPACITY_FRACTION*self.boundary.capacity_scaled(ja, angle)


def _retain_capacity_color(model):
    model.color = LegacyCapacityColor(model.settings.color, model.tone, lambda: model.boundary)
    return model


class LegacyCapacityModel(Model):
    def __init__(self, settings=Settings(), space='Linear Rec.709', *, hk_guard=True):
        super().__init__(settings, space, hk_guard=hk_guard)
        _retain_capacity_color(self)


class LegacyCapacityStack(Stack):
    def __init__(self, settings, directions=None, *, hk_guard=True):
        super().__init__(settings, directions, hk_guard=hk_guard)
        # Stack construction only prepares the linear inverses. Its models have
        # not evaluated any grade, so replacing their Color cannot stale a cache.
        for model in self.models:
            _retain_capacity_color(model)


class LegacyCapacityBakeStack(StackKernel, LegacyCapacityStack):
    """Explicit old-kernel assembly for verification and offline product tools."""
    def __init__(self, settings, directions=None, table=None, *, hk_guard=True, program_factory=None):
        self.program_factory = program_factory
        LegacyCapacityStack.__init__(self, settings, directions, hk_guard=hk_guard)
        self.hk_guard = bool(hk_guard)
        model = self.models[0] if self.models else LegacyCapacityModel(hk_guard=hk_guard)
        data = model.boundary.cache
        self.table = PolynomialTable(data) if table is None else table
        kernels = tuple(Kernel(data, m.tone, m.color, self.table, hk_guard=self.hk_guard) for m in self.models)
        StackKernel.__init__(self, kernels, [matrix_native(m) for m in self.models], self.inverses,
            self.directions, FROM_NATIVE, model.acescg_y,
            [(m.settings.tone, m.settings.color, self.hk_guard) for m in self.models], tone_factory=ToneTable)

    def prepare_gpu(self):
        if self.program is None:
            if self.program_factory is None:
                raise RuntimeError('GPU baking requires an explicit host program factory')
            if not self.solvers:
                raise ValueError('An empty Stack has no compute program')
            self.program = self.program_factory(self.solvers[0])
        return self.program

    def bake_native(self, values, backend='CPU', checkpoint=None, program=None):
        if backend == 'GPU' and self.solvers and program is None:
            program = self.prepare_gpu()
        return super().bake_native(values, backend, checkpoint, program)
