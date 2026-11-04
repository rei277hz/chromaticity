"""Raw appearance coordinates, fitted AP1 capacity, and stable RGB decoding.

The active context contains cube face/crease data only. The historical spindle
context remains separate and is not part of entry, grading, or export.
"""
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from types import MappingProxyType
import numpy as np

from ..perceptual_grade_core.model.boundary_resource import FORMAT, BUDGET, load_data
from .responses import GAMMA, INVERSE, eccentricity
from ..color_core.scaled import Scalar as S, norm, dot

MAXIMUM = 1024.


def white_response(fl):
    p = np.power(np.float64(fl)*MAXIMUM, .42)
    return float(400*p/(27.13+p))


def native(values, matrix):
    delta = values-values[..., 1, None]
    return values[..., 1, None]+delta[..., 0, None]*matrix[:, 0]+delta[..., 2, None]*matrix[:, 2]


def opponent_responses(ab):
    """Two terms in a fixed order, independent of BLAS batch heuristics."""
    return ab[..., 0, None]*INVERSE[:, 1]+ab[..., 1, None]*INVERSE[:, 2]


@dataclass(frozen=True)
class Context:
    white: float
    fl: float
    aw: float
    matrix: np.ndarray
    cache: dict

    @cached_property
    def lookup(self):
        from ..perceptual_grade_core.model.boundary_table import Table
        return Table(self.cache)

    def unit(self, t, hue):
        return self.lookup.capacity(t, hue)

    def capacity(self, ja, hue):
        ja, hue = np.broadcast_arrays(np.asarray(ja, dtype=float), np.asarray(hue, dtype=float))
        if not np.isfinite(ja).all() or not np.isfinite(hue).all():
            raise ValueError('Capacity requires finite lightness and hue')
        out = np.zeros_like(ja)
        active = (ja > 0) & (ja < self.white)
        t = (ja[active]/self.white)**(1/GAMMA)
        out[active] = white_response(self.fl)*t*(1-t)*self.unit(t, hue[active])
        return out

    def capacity_scaled(self, ja, hue):
        ja = S(ja)
        if ja <= 0 or ja >= self.white:
            return S()
        t = (ja/self.white)**(1/GAMMA)
        return white_response(self.fl)*t*(1-t)*float(self.unit(float(t), hue))

    def responses(self, q, energy):
        q, energy = np.asarray(q), np.asarray(energy)
        if not np.isfinite(energy).all():
            raise ValueError('Decode requires finite energy')
        hue = np.arctan2(q[..., 2], q[..., 1])
        ab = q[..., 1:]*(self.aw/(1204*eccentricity(hue)))[..., None]
        # Raw grading carries signed Hunt--Pointer energy through the stack.
        # Decode preserves its sign while using its magnitude for the neutral
        # response law; export containment still rejects non-positive energy.
        r = white_response(self.fl)*np.sign(energy)*(np.sqrt(abs(energy))/self.white)**(1/GAMMA)
        return r[..., None]+opponent_responses(ab)

    def cones(self, q, energy):
        r, rw = self.responses(q, energy), white_response(self.fl)
        if not np.isfinite(r).all() or np.any(abs(r) >= 400):
            raise ValueError('Response pole reached before decode')
        return np.sign(r)*MAXIMUM*(abs(r)*(400-rw)/(rw*(400-abs(r))))**(50/21)

    def decode(self, q, energy):
        q = np.asarray(q)
        e = np.broadcast_to(energy, q.shape[:-1])
        out = native(self.cones(q, e), self.matrix)
        t = (np.sqrt(abs(e))/self.white)**(1/GAMMA)
        active = (e > 0) & (t > .5)
        if np.any(active):
            rows = q[active]
            hue, rw = np.arctan2(rows[:, 2], rows[:, 1]), white_response(self.fl)
            ab = rows[:, 1:]*(self.aw/(1204*eccentricity(hue)))[:, None]
            deficit = (1-t[active, None])-opponent_responses(ab)/rw
            positive = np.all(deficit <= 1, axis=-1)
            d = deficit[positive]
            cones = -MAXIMUM*np.expm1((50/21)*(np.log1p(-d)-np.log1p(rw/(400-rw)*d)))
            values = out[active]
            values[positive] = MAXIMUM-native(cones, self.matrix)
            out[active] = values
        return out

    def decode_scaled(self, q, energy):
        energy = S(energy)
        c = norm(q[1:])
        hue = np.arctan2(float(q[2]/c), float(q[1]/c)) if c else 0.
        rw = white_response(self.fl)
        magnitude = abs(energy)
        t = (magnitude**.5/self.white)**(1/GAMMA)
        r = rw*((1 if energy >= 0 else -1)*t)
        ab = [v*float(self.aw/(1204*eccentricity(hue))) for v in q[1:]]
        raw = [r+dot(row, ab) for row in INVERSE[:, 1:]]
        if any(abs(v) >= 400 for v in raw):
            raise ValueError('Response pole reached before decode')
        if energy > 0 and t > .5 and all(v >= 0 for v in raw):
            d = np.array([float((1-t)-dot(row, ab)/rw) for row in INVERSE[:, 1:]])
            deficits = -MAXIMUM*np.expm1((50/21)*(np.log1p(-d)-np.log1p(rw/(400-rw)*d)))
            return [S(MAXIMUM)-S(deficits[1])-dot(row, [S(v)-deficits[1] for v in deficits])
                    for row in self.matrix]
        cones = [(1 if v >= 0 else -1)*MAXIMUM*(abs(v)*(400-rw)/(rw*(400-abs(v))))**(50/21)
                 for v in raw]
        return [cones[1]+dot(row, [v-cones[1] for v in cones]) for row in self.matrix]

    @classmethod
    def load(cls, path, fl, aw, matrix):
        with np.load(path, allow_pickle=False) as archive:
            if int(archive['format']) != FORMAT:
                raise ValueError(f'Cube cache format {int(archive["format"])}; expected {FORMAT}')
            if Path(path).stat().st_size > BUDGET:
                raise ValueError('Aggregate cube cache exceeds 64 KiB')
            data = load_data(archive)
        slack = 64*np.finfo(float).eps
        expected = np.array([float(data['fl']), float(data['aw'])])
        actual = np.array([fl, aw], dtype=float)
        for name, value, target in zip(('fl', 'aw'), actual, expected):
            if not np.isfinite(value) or abs(value-target) > slack*(1+abs(target)):
                raise ValueError(f'D65 cube {name} metadata mismatch')
        candidate, matrices = np.asarray(matrix, dtype=float), data['matrices']
        if candidate.shape != (3, 3) or not np.isfinite(candidate).all():
            raise ValueError('D65 cube matrix metadata requires a finite 3 by 3 adapter')
        errors = np.max(abs(matrices-candidate)/(1+abs(matrices)), axis=(1, 2))
        selected = int(np.argmin(errors))
        if errors[selected] > slack:
            raise ValueError('D65 cube matrix metadata mismatch')
        return cls(float(data['white']), float(expected[0]), float(expected[1]),
                   matrices[selected], MappingProxyType(data))


@lru_cache(maxsize=2)
def _context(fl, aw, matrix):
    return Context.load(Path(__file__).with_name('d65_cube.npz'), fl, aw, np.asarray(matrix).reshape(3, 3))


def context(fl, aw, matrix):
    return _context(float(fl), float(aw), tuple(np.asarray(matrix).ravel()))


@lru_cache(maxsize=1)
def default_context():
    path = Path(__file__).with_name('d65_cube.npz')
    with np.load(path, allow_pickle=False) as data:
        return Context.load(path, float(data['fl']), float(data['aw']), data['matrices'][0])
