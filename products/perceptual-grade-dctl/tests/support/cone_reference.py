"""Float64 equations at the Resolve cone-response wire and XYZ export boundaries."""
import numpy as np

from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_reference.appearance import Appearance, CAT16, response_constants
from color_tools.perceptual_grade_reference.export import OutputCompressionSettings, compress_saturation
from color_tools.perceptual_grade_reference.model import WHITES, xyz_from_xy
from color_tools.perceptual_grade_reference.responses import GAMMA, INVERSE, OPPONENT, State, eccentricity, signed_hk

WHITE = xyz_from_xy(WHITES["D65"])
FL, AW = response_constants(203.)


def from_xyz(xyz):
    cones = (np.asarray(xyz, dtype=np.float64) @ CAT16.T) / (CAT16 @ WHITE)
    power = (FL * abs(cones)) ** .42
    return np.sign(cones) * 400. * power / (27.13 + power)


def to_xyz(response):
    response = np.asarray(response, dtype=np.float64)
    if np.any(abs(response) >= 400.):
        raise ValueError("XYZ conversion requires an open cone-response interval")
    cones = np.sign(response) * (27.13 * abs(response) / (400. - abs(response))) ** (1. / .42) / FL
    return (cones * (CAT16 @ WHITE)) @ np.linalg.inv(CAT16).T


def appearance(response):
    response = np.asarray(response, dtype=np.float64)
    achromatic = response @ np.array([2., 1., .05]) / AW
    ja = 100. * np.sign(achromatic) * abs(achromatic) ** GAMMA
    ab = response @ OPPONENT.T
    ab[np.all(response == response[..., :1], axis=-1)] = 0.
    ab *= (1204. * eccentricity(np.arctan2(ab[..., 1], ab[..., 0])) / AW)[..., None]
    h = signed_hk(ja, np.linalg.norm(ab, axis=-1))
    return Appearance(np.concatenate([h[..., None], ab], axis=-1), ja)


def response(ja, a, b):
    ja, a, b = np.broadcast_arrays(ja, a, b)
    achromatic = AW * np.sign(ja) * (abs(ja) / 100.) ** (1. / GAMMA)
    factor = AW / (1204. * eccentricity(np.arctan2(b, a)))
    return np.stack([achromatic, factor * a, factor * b], axis=-1) @ INVERSE.T


def enter(wire):
    wire = np.asarray(wire, dtype=np.float64)
    if np.any(abs(wire) >= 400.):
        raise ValueError("Grading requires an open cone-response interval")
    chart = np.where(abs(wire) <= 200., wire, np.sign(wire) * 40000. / (400. - abs(wire)))
    return appearance(chart)


def pack(ja, a, b):
    chart = response(ja, a, b)
    magnitude = abs(chart)
    tail = 400. - 40000. / np.maximum(magnitude, 200.)
    return np.sign(chart) * np.where(magnitude <= 200., magnitude, tail)


def output(wire, compression=OutputCompressionSettings()):
    physical = appearance(wire)
    energy = physical.ja * abs(physical.ja)
    q, repaired = guard(physical.q, energy, energy)
    graded = compress_saturation(State(q, repaired), compression)
    changed = np.any(graded.q != physical.q, axis=-1) | (graded.energy != energy)
    result = np.asarray(wire, dtype=np.float64).copy()
    result[changed] = response(graded.ja[changed], graded.q[changed, 1], graded.q[changed, 2])
    return to_xyz(result)
