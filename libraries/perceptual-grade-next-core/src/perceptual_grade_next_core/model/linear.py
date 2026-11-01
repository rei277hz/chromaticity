"""Reference-aligned Stage 1 matrix construction without host dependencies."""

import math

import numpy as np

from ..settings import LinearSettings, SUPPORTED_WHITE
from .._shared import linear as color_linear


CAT16 = np.asarray(color_linear.CAT16, dtype=np.float64)
ICAT16 = np.asarray(color_linear.ICAT16, dtype=np.float64)
D65 = color_linear.D65


def _xyz_from_xy(xy):
    return np.asarray(color_linear.xyz(tuple(map(float, xy))), dtype=np.float64)


def source_white(point):
    """Clamp xy to the same CAT16-positive polygon used by the reference."""
    point = np.asarray(point, dtype=np.float64)
    if point.shape != (2,) or not np.isfinite(point).all():
        raise ValueError("Source white must be a finite xy pair")
    point = np.clip(point, 0.0, 0.9)
    normals = CAT16[:, :2] - CAT16[:, 2, None]
    offsets = CAT16[:, 2] - 0.002 * np.linalg.norm(normals, axis=-1)
    planes = np.vstack((np.column_stack((normals, offsets)), (0.0, 1.0, -0.002)))
    polygon = np.asarray(((0.0, 0.0), (0.9, 0.0), (0.9, 0.9), (0.0, 0.9)))
    for a, b, c in planes:
        vertices = []
        for p, q in zip(polygon, np.roll(polygon, -1, axis=0)):
            fp = a * p[0] + b * p[1] + c
            fq = a * q[0] + b * q[1] + c
            if fp >= 0.0:
                vertices.append(p)
            if (fp >= 0.0) != (fq >= 0.0):
                vertices.append(p + fp / (fp - fq) * (q - p))
        polygon = np.asarray(vertices)
    if np.all(planes[:, :2] @ point + planes[:, 2] >= 0.0):
        return tuple(map(float, point))
    starts, ends = polygon, np.roll(polygon, -1, axis=0)
    edges = ends - starts
    denominator = np.sum(edges * edges, axis=-1)
    t = np.clip(np.sum((point - starts) * edges, axis=-1) / denominator, 0.0, 1.0)
    candidates = starts + t[:, None] * edges
    selected = candidates[np.argmin(np.sum((candidates - point) ** 2, axis=-1))]
    return tuple(map(float, selected))


def xyz_matrix(settings: LinearSettings):
    """Return the correction matrix in the fixed D65 XYZ grading context."""
    if not isinstance(settings, LinearSettings):
        raise ValueError("settings must be LinearSettings")
    if settings.matrix is not None:
        matrix = np.asarray(settings.matrix, dtype=np.float64)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            raise ValueError("Authoritative XYZ matrix must be finite and 3 by 3")
        return matrix.copy()

    white = _xyz_from_xy(color_linear.WHITES[SUPPORTED_WHITE])
    source = _xyz_from_xy(source_white(settings.source_white_xy))
    ratios = (CAT16 @ white) / (CAT16 @ source)
    cat = np.eye(3) + ICAT16 @ np.diag(ratios - 1.0) @ CAT16
    directional = np.eye(3)
    if any(value != 0.0 for value in (*settings.balance, *settings.spread, *settings.heading)):
        white_xy = np.asarray(color_linear.xy(white), dtype=np.float64)
        anchors = white_xy + 0.3 * (np.asarray(((0.64, 0.33), (0.15, 0.06))) - white_xy)
        targets = []
        for xy, balance, spread, heading in zip(
            anchors, settings.balance, settings.spread, settings.heading
        ):
            angle = math.radians(heading % 360.0)
            rotation = np.asarray(((math.cos(angle), -math.sin(angle)),
                                  (math.sin(angle), math.cos(angle))))
            direction = rotation @ (xy - white_xy)
            point = white_xy + (1.0 + spread / 100.0) * direction
            point[1] = max(0.01, point[1])
            gain = 2.0**(-balance)
            x, y = point
            targets.append((x / y * gain, gain, (1.0 - x - y) / y * gain))
        basis = np.column_stack((white, *(_xyz_from_xy(anchor) for anchor in anchors)))
        target = np.column_stack((white, np.asarray(targets, dtype=np.float64).T))
        directional = np.eye(3) + (target - basis) @ np.linalg.inv(basis)
    return 2.0**settings.exposure * directional @ cat


def rgb_xyz_matrices(space):
    """Return RGB→D65 XYZ and D65 XYZ→RGB matrices for a supported space."""
    if space not in color_linear.SPACES:
        raise ValueError(f"Unsupported working RGB space: {space}")
    primaries, white = color_linear.SPACES[space]
    rgb_to_xyz = np.asarray(color_linear.rgb_to_xyz(space), dtype=np.float64)
    if tuple(white) != tuple(D65):
        rgb_to_xyz = np.asarray(color_linear.bradford(white, D65), dtype=np.float64) @ rgb_to_xyz
    return rgb_to_xyz, np.linalg.inv(rgb_to_xyz)


def rgb_matrix(settings: LinearSettings, space="Linear Rec.709"):
    """Return the complete Stage 1 correction in the selected RGB space."""
    rgb_to_xyz, xyz_to_rgb = rgb_xyz_matrices(space)
    return xyz_to_rgb @ xyz_matrix(settings) @ rgb_to_xyz
