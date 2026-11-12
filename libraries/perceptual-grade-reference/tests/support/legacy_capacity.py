"""Verification adapters for the retained production .4*capacity crossover.

This module is not part of a runtime component or extension bundle. Production
comparisons explicitly opt into the previous reference classifier; the public
analytic reference uses 35/75*abs(J_A). This fixture also retains raw signed
appearance handoffs, Scale before H-K repair, and export-time H-K repair.
Baking retains the unchanged shared float32 kernels.
"""
from dataclasses import replace
import numpy as np
from color_tools.color_core.scaled import Scalar as S, norm
from color_tools.perceptual_grade_reference import grading
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.responses import compress, coordinates
from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard, guard_scaled as cube_guard_scaled
from color_tools.perceptual_grade_reference.stack import Stack, FROM_NATIVE, matrix_native
from color_tools.perceptual_grade_core.model.hk_guard import GradedState, guard as hk_guard, guard_scaled as hk_guard_scaled
from color_tools.perceptual_grade_core.model.selective_adaptance import GuardedWarpDisplay, SelectiveAdaptance
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
    def __init__(self, settings, tone, boundary=None):
        super().__init__(settings, tone, boundary, hk_guard=False)

    # These adapters deliberately guard the final scaled raw request. The
    # current reference display methods instead receive an already repaired row.
    guarded_warp_state = GuardedWarpDisplay.guarded_warp_state
    guarded_warp_targets = GuardedWarpDisplay.guarded_warp_targets
    guarded_corner_evaluator = GuardedWarpDisplay.guarded_corner_evaluator
    guard_rim_radius = GuardedWarpDisplay.guard_rim_radius

    def _crossover_radius(self, q, ja):
        return CHROMA_CAPACITY_FRACTION*self.boundary.capacity(ja, np.arctan2(q[..., 2], q[..., 1]))

    def _scaled_crossover_radius(self, q, ja):
        c = norm(q[1:])
        angle = np.arctan2(float(q[2]/c), float(q[1]/c)) if c else 0.
        return CHROMA_CAPACITY_FRACTION*self.boundary.capacity_scaled(ja, angle)

    def target_settings(self, tonal_row, handle, target_ab):
        if not 0 <= tonal_row < 4 or not -1 <= handle < 6:
            raise ValueError('Warp target index is outside its four-by-seven grid')
        target = np.asarray(target_ab, float)
        if target.shape != (2,) or not np.isfinite(target).all():
            raise ValueError('Warp target must be a finite a/b pair')
        if handle == -1:
            adapted = np.array(self.settings.adaptance, float)
            adapted[tonal_row] = target
            SelectiveAdaptance(adapted, self.web.geometry.anchors, self.adaptation.aw,
                               self.settings.adaptance_half_saturation)
            return replace(self.settings, adaptance=tuple(map(tuple, adapted)))
        return replace(self.settings, web=self.adaptation.target(self.web, tonal_row, handle, target))

    def target_saturation_settings(self, tonal_row, handle, target):
        if not 0 <= tonal_row < 4 or not -1 <= handle < 6:
            raise ValueError('Warp target index is outside its four-by-seven grid')
        target = np.asarray(target, float)
        if target.shape != (2,) or not np.isfinite(target).all():
            raise ValueError('Warp saturation target must be a finite pair')
        if handle == -1:
            return self.target_settings(tonal_row, handle, self.web.geometry.anchors[tonal_row]*target)
        return replace(self.settings, web=self.adaptation.saturation_target(self.web, tonal_row, handle, target))


class LegacyCapacityModel(Model):
    def __init__(self, settings=Settings(), space='Linear Rec.709', *, hk_guard=True):
        super().__init__(settings, space, hk_guard=hk_guard)
        self.color = LegacyCapacityColor(settings.color, self.tone, lambda: self.boundary)

    def grade_state(self, state):
        """Retain signed requests and their post-tone export reference."""
        if state.q.dtype != object and self.vector_controls:
            tone = self.tone.apply(state)
            result = self.color.apply_state(tone)
            reference = tone.ja*np.abs(tone.ja) if self.tone.active else state.energy.copy()
            return GradedState(result.q, result.energy, reference)
        values, energies, references = [], [], []
        for q, j, e in zip(state.q.reshape(-1, 3), state.ja.reshape(-1), state.energy.reshape(-1)):
            base, j = self.tone.scaled_apply(list(map(S, q)), S(j))
            reference = j*abs(j) if self.tone.active else S(e)
            request, energy = self.color.scaled_apply_state(base, j, reference)
            values.append(request); energies.append(energy); references.append(reference)
        return GradedState(np.asarray(values, dtype=object).reshape(state.q.shape),
                           np.asarray(energies, dtype=object).reshape(state.energy.shape),
                           np.asarray(references, dtype=object).reshape(state.energy.shape))

    def release_state(self, state, guard=False, *, reference_energy=None):
        """Apply the historical H-K repair only when exporting grade context."""
        if reference_energy is None:
            reference_energy = getattr(state, 'reference_energy', None)
        if not self.hk_guard:
            reference_energy = None
        if state.q.dtype != object:
            q, e = state.q, state.energy
            if guard:
                if reference_energy is not None:
                    q, e = hk_guard(q, e, reference_energy)
                return cube_guard(self.boundary, q, e)[2]
            return self.boundary.decode(q, e)
        result = []
        references = (np.broadcast_to(reference_energy, state.energy.shape).reshape(-1)
                      if reference_energy is not None else [None]*state.energy.size)
        for q, e, reference in zip(state.q.reshape(-1, 3), state.energy.reshape(-1), references):
            q = list(q)
            if guard and reference is not None:
                q, e = hk_guard_scaled(q, e, reference)
            rgb = (cube_guard_scaled(self.boundary, q, e)[2] if guard
                   else self.boundary.decode_scaled(q, e))
            result.append([float(v) for v in rgb])
        return np.asarray(result).reshape(state.q.shape)

    def core(self, cones, export=True):
        boundary = self.boundary
        source = [compress(v, boundary.fl) for v in cones]
        q, ja = coordinates(source, boundary.aw)
        if cones[0] == cones[1] == cones[2]:
            q = [ja, S(), S()]
        stage2_q, stage2_ja = self.tone.scaled_apply(q, ja)
        request, energy = self.color.scaled_apply_state(stage2_q, stage2_ja)
        if export:
            if self.hk_guard:
                request, energy = hk_guard_scaled(request, energy, stage2_ja*abs(stage2_ja))
            return cube_guard_scaled(boundary, request, energy)[2]
        return boundary.decode_scaled(request, energy)

    def _core_arrays(self, cones, export=True):
        source = self.encode_cones(cones)
        stage2 = self.tone.apply(source)
        if np.any((stage2.ja != 0) & (np.abs(stage2.ja) < 2.**-200)):
            return None
        result = self.color.apply_state(stage2)
        request, energy = result.q, result.energy
        if np.any((request[..., 0] > 0) & (request[..., 0] < 2.**-200)):
            return None
        if export:
            if self.hk_guard:
                request, energy = hk_guard(request, energy, stage2.ja*np.abs(stage2.ja))
            return cube_guard(self.boundary, request, energy)[2]
        return self.boundary.decode(request, energy)


class LegacyCapacityStack(Stack):
    def __init__(self, settings, directions=None, *, hk_guard=True):
        self.models = tuple(LegacyCapacityModel(setting, hk_guard=hk_guard) for setting in settings)
        self.directions = tuple(directions) if directions is not None else ('FORWARD',)*len(self.models)
        if len(self.models) != len(self.directions) or any(d not in ('FORWARD', 'INVERSE') for d in self.directions):
            raise ValueError('Invalid Stack directions')
        self.inverses = []
        for model, direction in zip(self.models, self.directions):
            if direction == 'INVERSE' and np.linalg.matrix_rank(np.asarray(model.linear, dtype=float)) < 3:
                raise ValueError('Inverse Stage 1 matrix is singular')
            try:
                inverse = np.linalg.inv(matrix_native(model)) if direction == 'INVERSE' else None
            except np.linalg.LinAlgError as error:
                raise ValueError('Inverse Stage 1 matrix is singular') from error
            self.inverses.append(inverse)


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
