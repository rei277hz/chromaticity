"""Reference Warp controls for repair before the common positive Scale.

The shared local solver works in the signed request before repair. Its display
residual uses the repaired chart, which is independent of the final Scale.
"""
import numpy as np
from ..perceptual_grade_core.model.selective_adaptance import (
    GuardedWarpDisplay as _Display, _GuardedCorner,
)
from ..perceptual_grade_core.model.tonal_web import _energy_at_fixed_h
from ..perceptual_grade_core.model.hk_guard import guard
from ..perceptual_grade_core.model.saturation import bounded_project


class GuardedWarpDisplay(_Display):
    """Display the already repaired Stage 3 result without a second guard."""
    def guarded_warp_state(self, state, tonal_h=None, source_chroma=None, source_energy=None):
        return self.warp_state(state, tonal_h, source_chroma, source_energy)

    def guarded_warp_targets(self, tonal_row):
        return self.warp_targets(tonal_row)

    def guarded_corner_evaluator(self, tonal_row, handle):
        """Return (pre-repair unscaled request, final bounded pad point)."""
        return RepairedCorner(self.adaptation, self.web, tonal_row, handle, self.hk_guard)

    def guard_rim_radius(self, tonal_row, handle):
        """Radius at this corner's pre-repair E=0, independent of Scale."""
        evaluator = self.guarded_corner_evaluator(tonal_row, handle)
        settings = evaluator.boundary()
        angle = (self.web.geometry.angles[tonal_row, handle]
                 + np.deg2rad(settings.hue_degrees[tonal_row][handle]))
        _, point = evaluator(settings.log_chroma[tonal_row][handle], angle)
        return float(np.hypot(*point))


class RepairedCorner(_GuardedCorner):
    """Use the shared local solve with the reference's corrected evaluation."""
    def __init__(self, adaptation, web, row, handle, hk_guard=True):
        super().__init__(adaptation, web, row, handle)
        self.hk_guard = hk_guard

    def _request(self, c, angle, energy=None):
        if not np.isfinite([c, angle]).all() or c <= 0:
            raise ValueError('Guarded corner requires positive finite chroma')
        if energy is None:
            energy = _energy_at_fixed_h(np.asarray(self.source_e), np.asarray(self.source_c), np.asarray(c))
        q = np.array([self.h, c*np.cos(angle), c*np.sin(angle)])
        q, e = self.adaptation.apply(q, np.asarray(energy), self.h, self.source_c, self.source_e)
        if not np.isfinite(q).all() or not np.isfinite(e):
            raise ValueError('Guarded corner exceeds the finite appearance domain')
        return self.adaptation.response_math.State(q, np.asarray(e))

    def _output(self, request):
        q, e = (guard(request.q, request.energy, self.source_e) if self.hk_guard
                else (request.q.copy(), request.energy.copy()))
        q = np.array(q, copy=True)
        q[1:] *= self.scale
        e = np.asarray(e*self.scale*self.scale)
        if self.scale != 1:
            q[0] = self.adaptation.response_math.signed_hk(np.sign(e)*np.sqrt(abs(e)), np.hypot(*q[1:]))
        if not np.isfinite(q).all() or not np.isfinite(e):
            raise ValueError('Guarded corner exceeds the finite appearance domain')
        return self.adaptation.response_math.State(q, e)

    def _state(self, c, angle, energy=None):
        request = self._request(c, angle, energy)
        output = self._output(request)
        return request, bounded_project(output.q, output.energy)

    def absolute_target(self, target):
        """Solve the corrected final a/b destination while retaining Scale."""
        target = np.asarray(target, float)
        magnitude = max(1., float(np.hypot(*target)))
        def residual(z):
            request, _ = self._evaluate(z)
            return (self._output(request).q[1:]-target)/magnitude
        return self._settings(self._solve(residual))

    def boundary(self, angle=None):
        """Locate zero signed energy after Adaptance, before H-K repair."""
        if angle is None:
            _, point = self()
            angle = float(np.arctan2(point[1], point[0]))
        if not np.isfinite(angle):
            raise ValueError('Guarded hue must be finite')
        if not self.adaptation.active:
            return self._settings(np.array([0., self._lift(angle, self.angle)]))
        def residual(z):
            request, point = self._evaluate(z)
            response = (np.sign(request.energy)*abs(request.energy/(self.h*self.h))
                        **(1/(2*self.adaptation.response_math.GAMMA)))
            direction = np.arctan2(point[1], point[0])
            return np.array([response, self._lift(direction, angle)-angle])
        return self._settings(self._solve(residual, seed=[0., self._lift(angle, self.angle)]))
