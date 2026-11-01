"""Deterministic f64 inverse search, independent of production inverse machinery.

Canonical means nearest-linear among roots found by this fixed search profile.
No claim is made that multistart enumerates all roots or proves reachability.
Every RGB residual evaluates the forward H-K repair using that candidate's
post-tone reference; no separate guard inverse is called during the search.
"""
from dataclasses import dataclass
from itertools import product
import numpy as np
from ..color_core.scaled import Scalar as S, dot, total
from .responses import compress, uncompress, Response, GAMMA

BOUND = float(2**20)
TOLERANCE = 2e-10
ITERATIONS = 128


@dataclass(frozen=True)
class InverseResult:
    value: np.ndarray
    residual: np.ndarray
    status: np.ndarray


def seeds(prior, target):
    if np.asarray(prior).dtype == object:
        scale = max(S(1.), *(abs(S(v)) for v in [*prior, *target]))
        rows = [prior, target, [0.]*3]
        rows += [[S(v)*factor for v in prior] for factor in (.25, .5, 2., 4.)]
        rows += [[S(v)+scale*c for v, c in zip(prior, offsets)] for offsets in product((-1., 0., 1.), repeat=3)]
        return np.unique([[float(min(S(BOUND), max(S(-BOUND), S(v)))) for v in row] for row in rows], axis=0)
    scale = max(1., np.max(np.abs(prior)), np.max(np.abs(target)))
    stencil = prior+scale*np.array(list(product((-1., 0., 1.), repeat=3)))
    rows = np.vstack((prior, target, np.zeros(3), np.array([.25, .5, 2., 4.])[:, None]*prior, stencil))
    return np.unique(np.clip(rows, -BOUND, BOUND), axis=0)


def to_xyz(model, rgb):
    rgb = np.asarray(rgb)
    return rgb[..., 1, None]*model.white+(rgb-rgb[..., 1, None]) @ model.canonical_to_xyz.T


def from_xyz(model, xyz):
    xyz = np.asarray(xyz)
    return xyz[..., 1, None]+(xyz-xyz[..., 1, None]*model.white) @ model.xyz_to_canonical.T


def neutral_seed(model, target):
    """Analytic neutral-tone preimage, used only as a forward-validated seed.

    Every target gets this seed; there is no near-neutral classification.
    It handles the square-root chroma cusp on the negative neutral axis.
    """
    response = compress(target[1], model.fl).value
    ja = 100*np.sign(float(response))*float(abs(3.05*response/model.aw)**GAMMA)
    magnitude = float(model.tone.inverse(abs(ja)))
    r = S(np.sign(ja))*model.aw*(S(magnitude)/100)**(1/GAMMA)/3.05
    if abs(r) >= 400:
        return []
    value = uncompress(Response(r, 400-abs(r)), model.fl)
    gain = S(model.linear[0, 0])
    if gain and all(S(v) == (gain if i == j else S())
                    for i, row in enumerate(model.linear) for j, v in enumerate(row)):
        return [[value/gain]*3]
    return [linear_prior(model, np.array([float(value)*w for w in model.white]))]


def candidates(model, target, prior, forward=None):
    """Batched independent Levenberg-Marquardt steps in asinh canonical RGB."""
    scale = 1+np.max(np.abs(target))
    starts = seeds(prior, target)
    extra = neutral_seed(model,target)
    if extra:
        starts = np.unique(np.vstack((starts, [[float(min(S(BOUND), max(S(-BOUND), S(v))))
                                                for v in row] for row in extra])), axis=0)
    z = np.arcsinh(starts)
    limit = np.arcsinh(BOUND)
    forward = model.forward_xyz if forward is None else forward
    def residual(points):
        x = to_xyz(model, np.sinh(points))
        return (from_xyz(model, forward(x))-target)/scale
    r = residual(z)
    score = np.sum(r*r, axis=-1)
    damping = np.full(len(z), 1e-3)
    active = np.ones(len(z), dtype=bool)
    eye = np.eye(3)
    for _ in range(ITERATIONS):
        ids = np.flatnonzero(active & (np.max(np.abs(r), axis=-1) > TOLERANCE/10))
        if not len(ids):
            break
        points = z[ids]
        h = np.cbrt(np.finfo(np.float64).eps)*(1+np.abs(points))
        jac = np.stack([(residual(points+h[:, i, None]*eye[i])-residual(points-h[:, i, None]*eye[i]))/(2*h[:, i, None])
                        for i in range(3)], axis=-1)
        step = np.empty_like(points)
        for row in range(len(ids)):
            augmented = np.vstack((jac[row], np.sqrt(damping[ids[row]])*eye))
            step[row] = np.linalg.lstsq(augmented, np.r_[r[ids[row]], np.zeros(3)], rcond=None)[0]
        proposed = np.clip(points-step, -limit, limit)
        proposed_r = residual(proposed)
        proposed_score = np.sum(proposed_r*proposed_r, axis=-1)
        accept = np.isfinite(proposed_score) & (proposed_score < score[ids])
        picked = ids[accept]
        z[picked], r[picked], score[picked] = proposed[accept], proposed_r[accept], proposed_score[accept]
        damping[ids] = np.clip(damping[ids]*np.where(accept, 1/3, 10), 1e-12, 1e12)
        active[ids] &= (damping[ids] < 1e12) & (np.max(np.abs(step), axis=-1) > 2e-13)
    return np.sinh(z), np.max(np.abs(r), axis=-1)


def choose(values, errors, prior):
    """Validated roots rank by prior distance; approximations rank by residual first."""
    values, errors = np.asarray(values), np.asarray(errors)
    valid = np.isfinite(errors) & np.isfinite(values).all(axis=-1)
    if not np.any(valid):
        raise ArithmeticError('No finite inverse candidate')
    values, errors = values[valid], errors[valid]
    if np.asarray(prior).dtype == object:
        def asinh(value):
            value = S(value)
            if abs(value) < 2.**27:
                return S(np.arcsinh(float(value)))
            return (1 if value > 0 else -1)*((S(value.e)+np.log2(abs(value.m))+1)*np.log(2))
        reference = [asinh(v) for v in prior]
        # The common prior-squared term cancels from every ranking. Removing it
        # avoids erasing the candidate differences for an enormous linear prior.
        distance = [total(S(a)*a-2*S(a)*b for a, b in zip(np.arcsinh(row), reference)) for row in values]
    else:
        distance = np.sum((np.arcsinh(values)-np.arcsinh(prior))**2, axis=-1)
    roots = errors <= TOLERANCE
    ids = np.flatnonzero(roots) if np.any(roots) else np.arange(len(values))
    # Lexicographic RGB is the final tie-break, independent of seed/batch order.
    keys = [(distance[i], *values[i]) if np.any(roots) else (errors[i], distance[i], *values[i]) for i in ids]
    selected = ids[min(range(len(ids)), key=lambda i: keys[i])]
    return values[selected], errors[selected], 'root' if roots[selected] else 'approximate'


def linear_prior(model, target):
    magnitude = np.max(np.abs(model.linear), initial=0)
    if model.linear.dtype != object and (magnitude == 0 or 2.**-200 < magnitude < 2.**200):
        return from_xyz(model, np.linalg.lstsq(model.linear, target, rcond=None)[0])
    matrix = [[S(v) for v in row] for row in model.linear]
    largest = max(abs(v) for row in matrix for v in row)
    if not largest:
        return np.zeros(3)
    normalized = np.array([[float(v/largest) for v in row] for row in matrix])
    target_scale = max(1., np.max(np.abs(target)))
    solution = np.linalg.lstsq(normalized, target/target_scale, rcond=None)[0]
    xyz = [S(v)*target_scale/largest for v in solution]
    return np.array([dot(row, xyz) for row in model.xyz_to_canonical], dtype=object)


def solve(model, xyz, forward=None):
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.shape[-1:] != (3,):
        raise ValueError('Inverse input must have a final dimension of three')
    shape = xyz.shape
    rows = xyz.reshape(-1, 3)
    out = np.full_like(rows, np.nan)
    errors = np.full(len(rows), np.inf)
    statuses = np.full(len(rows), 'invalid', dtype='<U11')
    forward = model.forward_xyz if forward is None else forward
    for index, y in enumerate(rows):
        if not np.isfinite(y).all():
            continue
        target = from_xyz(model, y)
        prior = linear_prior(model, y)
        # Exact linear/reset paths still obey the full-forward acceptance test.
        if not (model.tone.active or model.color.active):
            values = np.array([[float(min(S(BOUND), max(S(-BOUND), S(v)))) for v in prior]])
            reproduced = from_xyz(model, forward(to_xyz(model, values)))
            residual = np.max(np.abs(reproduced-target), axis=-1)/(1+np.max(np.abs(target)))
            if residual[0] > TOLERANCE:
                values, residual = candidates(model, target, prior, forward)
        else:
            values, residual = candidates(model, target, prior, forward)
        value, error, status = choose(values, residual, prior)
        out[index], errors[index], statuses[index] = to_xyz(model, value), error, status
    return InverseResult(out.reshape(shape), errors.reshape(shape[:-1]), statuses.reshape(shape[:-1]))
