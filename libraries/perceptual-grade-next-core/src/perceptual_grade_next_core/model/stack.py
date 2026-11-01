"""Ordered reference-directed Stack evaluation and inverse residual reporting."""

from dataclasses import dataclass
from itertools import product

import numpy as np

from .._shared import linear as color_linear, modcam16
from .hk_guard import GradedState

from ..settings import Direction, StackSettings
from .grade import GradeModel
from .linear import rgb_xyz_matrices


TOLERANCE = 2e-10
MAXIMUM = 1024.0
ITERATIONS = 128


@dataclass(frozen=True)
class InverseResult:
    value: np.ndarray
    residual: np.ndarray
    status: np.ndarray


def _repair_ap1(rgb):
    """Reference Stack AP1 entry repair; this is separate from Grade entry."""
    rgb = np.asarray(rgb, dtype=np.float64)
    if rgb.shape[-1:] != (3,) or not np.isfinite(rgb).all():
        raise ValueError("Stack input must contain finite RGB triples")
    weights = np.asarray(color_linear.rgb_to_xyz("ACEScg")[1], dtype=np.float64)
    result = rgb.copy()
    active = (rgb.min(axis=-1) < 0.0) | (rgb.max(axis=-1) > MAXIMUM)
    if not np.any(active):
        return result
    rows = rgb[active]
    amplitude = np.max(np.abs(rows), axis=-1)
    unit = rows / amplitude[:, None]
    y = np.maximum(0.0, unit @ weights)
    k = np.maximum(0.0, -unit.min(axis=-1))
    factor = np.divide(y, y + k, out=np.zeros_like(y), where=y + k > 0.0)
    repaired = np.where((k > 0.0)[:, None], (unit + k[:, None]) * factor[:, None], unit)
    maximum = np.max(repaired, axis=-1)
    scale = np.minimum(amplitude, np.nextafter(MAXIMUM / np.maximum(maximum, 1e-300), -np.inf))
    result[active] = repaired * np.maximum(0.0, scale)[:, None]
    return result


def _attributes(state):
    ja = state.ja
    return np.concatenate((state.q[..., :1], ja[..., None], state.q[..., 1:]), axis=-1)


def _seeds(prior):
    scale = max(1.0, float(np.max(np.abs(prior))))
    stencil = prior + scale * np.asarray(tuple(product((-1.0, 0.0, 1.0), repeat=3)))
    weights = np.asarray(color_linear.rgb_to_xyz("ACEScg")[1], dtype=np.float64)
    rows = np.vstack((prior, np.zeros(3), np.full(3, prior @ weights),
                      np.asarray((0.25, 0.5, 2.0, 4.0))[:, None] * prior,
                      stencil))
    return np.unique(np.clip(rows, 0.0, MAXIMUM), axis=0)


def _solve(forward, target, prior, *, appearance=False):
    """Multi-start finite-difference LM, with explicit root/approximate status."""
    target = np.asarray(target, dtype=np.float64)
    prior = np.asarray(prior, dtype=np.float64)
    scale = 1.0 + np.abs(target) if appearance else 1.0 + np.max(np.abs(target))
    z = np.arcsinh(_seeds(prior) / 0.01)
    limit = np.arcsinh(MAXIMUM / 0.01)

    def residual(points):
        values = 0.01 * np.sinh(points)
        return (np.asarray(forward(values), dtype=np.float64) - target) / scale

    r = residual(z)
    score = np.sum(r * r, axis=-1)
    damping = np.full(len(z), 1e-3)
    active = np.ones(len(z), dtype=bool)
    eye = np.eye(3)
    for _ in range(ITERATIONS):
        ids = np.flatnonzero(active & (np.max(np.abs(r), axis=-1) > TOLERANCE / 10.0))
        if not len(ids):
            break
        points = z[ids]
        h = np.cbrt(np.finfo(np.float64).eps) * (1.0 + np.abs(points))
        columns = []
        for axis in range(3):
            lower = points.copy()
            upper = points.copy()
            lower[:, axis] = np.maximum(0.0, points[:, axis] - h[:, axis])
            upper[:, axis] = np.minimum(limit, points[:, axis] + h[:, axis])
            columns.append((residual(upper) - residual(lower))
                           / (upper[:, axis] - lower[:, axis])[:, None])
        jac = np.stack(columns, axis=-1)
        steps = np.empty_like(points)
        for row in range(len(ids)):
            augmented = np.vstack((jac[row], np.sqrt(damping[ids[row]]) * eye))
            steps[row] = np.linalg.lstsq(
                augmented, np.r_[r[ids[row]], np.zeros(3)], rcond=None
            )[0]
        proposed = np.clip(points - steps, 0.0, limit)
        proposed_r = residual(proposed)
        proposed_score = np.sum(proposed_r * proposed_r, axis=-1)
        accept = np.isfinite(proposed_score) & (proposed_score < score[ids])
        picked = ids[accept]
        z[picked], r[picked], score[picked] = proposed[accept], proposed_r[accept], proposed_score[accept]
        damping[ids] = np.clip(damping[ids] * np.where(accept, 1.0 / 3.0, 10.0), 1e-12, 1e12)
        active[ids] &= (damping[ids] < 1e12) & (np.max(np.abs(steps), axis=-1) > 2e-13)

    values = 0.01 * np.sinh(z)
    errors = np.max(np.abs(r), axis=-1)
    finite = np.isfinite(errors) & np.isfinite(values).all(axis=-1)
    if not finite.any():
        return np.full(3, np.nan), np.inf, "invalid"
    ids = np.flatnonzero(finite)
    roots = errors[ids] <= TOLERANCE
    if roots.any():
        ids = ids[roots]
    _, xyz_to_canonical = rgb_xyz_matrices("Linear Rec.709")
    ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
    to_canonical = xyz_to_canonical @ ap1_to_xyz
    canonical = values[ids] @ to_canonical.T
    canonical_prior = prior @ to_canonical.T
    distance = np.sum((np.arcsinh(canonical) - np.arcsinh(canonical_prior))**2, axis=-1)
    order = sorted(range(len(ids)), key=lambda i: (
        *((errors[ids[i]],) if not roots.any() else ()),
        distance[i],
        *canonical[i],
    ))
    selected = int(ids[order[0]])
    return values[selected], float(errors[selected]), "root" if errors[selected] <= TOLERANCE else "approximate"


class StackModel:
    """Evaluate ordered FORWARD/INVERSE entries in the AP1 Stack domain."""

    def __init__(self, settings=StackSettings()):
        if not isinstance(settings, StackSettings):
            settings = StackSettings(tuple(settings))
        self.settings = settings
        self.models = tuple(GradeModel(entry.settings) for entry in settings.entries)
        self.directions = tuple(entry.direction for entry in settings.entries)
        self.inverse_matrices = []
        for model, direction in zip(self.models, self.directions):
            if direction is Direction.INVERSE:
                if np.linalg.matrix_rank(model.stage1_ap1_matrix) < 3:
                    raise ValueError("Inverse Stage 1 matrix is singular")
                self.inverse_matrices.append(np.linalg.inv(model.stage1_ap1_matrix))
            else:
                self.inverse_matrices.append(None)

    def apply_ap1(self, values, *, repair=True, endpoint_matrices=True):
        """Evaluate the ordered Stack in ACEScg coordinates.

        LUT generation omits the first/last endpoint matrices because the
        installed LUT transport applies them around the sampled core. The
        transport repairs its input after the input endpoint matrix.
        """
        result = np.asarray(values, dtype=np.float64)
        if result.shape[-1:] != (3,) or not np.isfinite(result).all():
            raise ValueError("Stack input must contain finite RGB triples")
        if not self.models:
            return _repair_ap1(result) if repair else result.copy()
        pending = None
        cancelled = False
        for index, (model, direction) in enumerate(zip(self.models, self.directions)):
            if direction is Direction.FORWARD:
                stage_input = result
                external_input = endpoint_matrices or index != 0
                if external_input:
                    ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
                    xyz = stage_input @ ap1_to_xyz.T
                    xyz = xyz @ model.stage1.T
                    stage_input = xyz @ np.linalg.inv(ap1_to_xyz).T
                    stage_input = _repair_ap1(stage_input)
                elif index != 0:
                    stage_input = _repair_ap1(stage_input)
                next_inverse = index + 1 < len(self.models) and self.directions[index + 1] is Direction.INVERSE
                matching_pair = (next_inverse
                                 and model.settings.tone == self.models[index + 1].settings.tone
                                 and model.settings.color == self.models[index + 1].settings.color)
                pending = stage_input if matching_pair else model.grade_ap1(stage_input)
                cancelled = bool(matching_pair)
                if not next_inverse:
                    result = model.release_ap1(pending, guard=True)[2]
                    pending, cancelled = None, False
            else:
                if pending is not None and cancelled:
                    result = pending
                else:
                    target = _repair_ap1(result) if repair or index != 0 else result
                    inverse_result = self.inverse(model, target, raw_state=pending)
                    result = inverse_result.value
                external_output = endpoint_matrices or index != len(self.models) - 1
                if external_output:
                    result = result @ self.inverse_matrices[index].T
                pending, cancelled = None, False
        return result

    def apply_lut_core_ap1(self, values):
        """Evaluate the nonlinear Stack core for a 65³ LUT producer."""
        return self.apply_ap1(values, repair=False, endpoint_matrices=False)

    def apply_ap1_core(self, values):
        """Compatibility name for the endpoint-matrix-free LUT evaluator."""
        return self.apply_lut_core_ap1(values)

    @property
    def lut_endpoint_matrices(self):
        """Return ``(input, output)`` AP1 matrices handled outside the LUT."""
        identity = np.eye(3)
        input_matrix = (self.models[0].stage1_ap1_matrix.copy()
                        if self.models and self.directions[0] is Direction.FORWARD
                        else identity.copy())
        output_matrix = (self.inverse_matrices[-1].copy()
                         if self.models and self.directions[-1] is Direction.INVERSE
                         else identity.copy())
        return input_matrix, output_matrix

    def apply_rgb(self, values, space="Linear Rec.709"):
        if space not in ("Linear Rec.709", "Linear Rec.2020", "ACEScg"):
            raise ValueError("Unsupported Stack working RGB space")
        rgb_to_xyz, xyz_to_rgb = rgb_xyz_matrices(space)
        ap1_to_xyz, xyz_to_ap1 = rgb_xyz_matrices("ACEScg")
        values = np.asarray(values, dtype=np.float64)
        if values.shape[-1:] != (3,) or not np.isfinite(values).all():
            raise ValueError("Stack input must contain finite RGB triples")
        d65_xyz = values @ rgb_to_xyz.T
        ap1 = d65_xyz @ xyz_to_ap1.T
        result = self.apply_ap1(ap1)
        out_xyz = result @ ap1_to_xyz.T
        return out_xyz @ xyz_to_rgb.T

    def apply(self, values, space="Linear Rec.709"):
        return self.apply_rgb(values, space)

    def inverse(self, model, target_ap1, raw_state=None):
        """Invert one nonlinear grade and report its measured forward residual."""
        target = _repair_ap1(target_ap1)
        if raw_state is not None:
            raw_q = np.asarray(raw_state.q, dtype=np.float64).reshape(target.shape)
            raw_energy = np.asarray(raw_state.energy, dtype=np.float64).reshape(target.shape[:-1])
            if hasattr(raw_state, "reference_energy"):
                raw_state = GradedState(
                    raw_q,
                    raw_energy,
                    np.asarray(raw_state.reference_energy, dtype=np.float64).reshape(target.shape[:-1]),
                )
            else:
                raw_state = modcam16.State(raw_q, raw_energy)
            target = np.asarray(model.release_ap1(raw_state, guard=True)[2], dtype=np.float64)
        if target.ndim == 1:
            if raw_state is None:
                _, xyz_to_canonical = rgb_xyz_matrices("Linear Rec.709")
                ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
                to_canonical = xyz_to_canonical @ ap1_to_xyz
                wanted = target @ to_canonical.T

                def forward(candidate):
                    state = model.grade_ap1(_repair_ap1(candidate))
                    return model.release_ap1(state, guard=True)[2] @ to_canonical.T
            else:
                wanted = _attributes(raw_state).reshape(4)

                def forward(candidate):
                    return _attributes(model.grade_ap1(_repair_ap1(candidate)))

            if not model.tone.active and not model.color.active:
                reproduced = np.asarray(forward(target), dtype=np.float64)
                divisor = 1.0 + np.abs(wanted) if raw_state is not None else 1.0 + np.max(np.abs(wanted))
                error = np.max(np.abs(reproduced - wanted) / divisor)
                return InverseResult(target, np.asarray(error),
                                     np.asarray("root" if error <= TOLERANCE else "approximate"))
            value, residual, status = _solve(
                forward, wanted, target, appearance=raw_state is not None
            )
            return InverseResult(value, np.asarray(residual), np.asarray(status))

        values, residuals, statuses = [], [], []
        for row_index, row in enumerate(target.reshape(-1, 3)):
            if raw_state is None:
                row_state = None
            elif hasattr(raw_state, "reference_energy"):
                row_state = GradedState(
                    raw_state.q.reshape(-1, 3)[row_index:row_index + 1],
                    raw_state.energy.reshape(-1)[row_index:row_index + 1],
                    raw_state.reference_energy.reshape(-1)[row_index:row_index + 1],
                )
            else:
                row_state = modcam16.State(
                    raw_state.q.reshape(-1, 3)[row_index:row_index + 1],
                    raw_state.energy.reshape(-1)[row_index:row_index + 1],
                )
            if row_state is not None:
                row_grade = self.inverse(model, row, raw_state=row_state)
            else:
                row_grade = self.inverse(model, row)
            values.append(row_grade.value)
            residuals.append(row_grade.residual)
            statuses.append(row_grade.status)
        shape = target.shape
        return InverseResult(np.asarray(values).reshape(shape),
                             np.asarray(residuals).reshape(shape[:-1]),
                             np.asarray(statuses).reshape(shape[:-1]))
