#!/usr/bin/env python3
"""Emit official ACES 2.0 OCIO forward/inverse reference vectors.

This script deliberately uses PyOpenColorIO and the bundled config rather
than any Rust implementation. ``ocio_oracle.test.mjs`` compares its JSON
output with the browser WASM port.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
from picker_reference import PEAK, REFERENCE_J, P3, REC709, REC2020, code_xyz, neutral_jhk


CONFIG = Path(__file__).parent / "reference" / "cg-config-v4.0.0_aces-v2.0_ocio-v2.5.ocio"
_STAGED_COLORCHECKER_REFERENCE = (
    Path(__file__).resolve().parent.parent / "references" / "colorchecker"
    / "ColorChecker24_After_Nov2014.txt"
)
_LIBRARY_COLORCHECKER_REFERENCE = (
    Path(__file__).resolve().parents[3] / "libraries" / "modcam16-color-core"
    / "references" / "colorchecker" / "ColorChecker24_After_Nov2014.txt"
)
COLORCHECKER_REFERENCE = Path(os.environ.get(
    "COLORCHECKER_REFERENCE",
    str(_STAGED_COLORCHECKER_REFERENCE if _STAGED_COLORCHECKER_REFERENCE.is_file()
        else _LIBRARY_COLORCHECKER_REFERENCE),
))
PROFILES = {
    "0": "ACES 2.0 - HDR 1000 nits (Rec.2020)",
    "1": "ACES 2.0 - SDR 100 nits (Rec.709)",
    "2": "ACES 2.0 - HDR 1000 nits (P3 D65)",
    "4": "ACES 2.0 - SDR 100 nits (P3 D65)",
}
VECTORS = np.asarray(
    [
        [0.0, 0.0, 0.0],
        [0.1, 0.2, 0.3],
        [0.1, 0.1, 0.1],
        [0.2, 0.3, 0.4],
        [1.0, 0.0, 0.0],
        [0.08, 0.12, 0.18],
        [2.0, 0.5, 0.25],
    ],
    dtype=np.float32,
)

CAT02 = np.array(
    [
        [0.7328, 0.4296, -0.1624],
        [-0.7036, 1.6975, 0.0061],
        [0.0030, 0.0136, 0.9834],
    ]
)


def _white_xyz(x: float, y: float) -> np.ndarray:
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


D50_WHITE = _white_xyz(0.34567, 0.35850)
ACES_WHITE = _white_xyz(0.32168, 0.33767)
AP1_PRIMARIES = ((0.713, 0.293), (0.165, 0.830), (0.128, 0.044))


def _rgb_to_xyz_matrix(primaries, white: np.ndarray) -> np.ndarray:
    columns = np.array([_white_xyz(x, y) for x, y in primaries]).T
    return columns @ np.diag(np.linalg.solve(columns, white))


AP1_TO_XYZ = _rgb_to_xyz_matrix(AP1_PRIMARIES, ACES_WHITE)


def _lab_d50_to_xyz(lab: np.ndarray) -> np.ndarray:
    delta = 6.0 / 29.0
    f_y = (lab[..., 0] + 16.0) / 116.0
    f_x = f_y + lab[..., 1] / 500.0
    f_z = f_y - lab[..., 2] / 200.0

    def inverse(value: np.ndarray) -> np.ndarray:
        return np.where(
            value > delta,
            value**3,
            3.0 * delta**2 * (value - 4.0 / 29.0),
        )

    return np.stack(
        [D50_WHITE[0] * inverse(f_x), inverse(f_y), D50_WHITE[2] * inverse(f_z)],
        axis=-1,
    )


def _colorchecker_lab() -> tuple[list[str], np.ndarray]:
    rows: dict[str, list[float]] = {}
    in_data = False
    for source_line in COLORCHECKER_REFERENCE.read_text(encoding="utf-8").splitlines():
        line = source_line.strip()
        if line == "BEGIN_DATA":
            in_data = True
            continue
        if line == "END_DATA":
            break
        if not in_data or not line:
            continue
        name, *values = line.split()
        rows[name] = [float(value.replace(",", ".")) for value in values]
    if len(rows) != 24:
        raise RuntimeError(f"Expected 24 ColorChecker records, got {len(rows)}")
    active = [
        "A1", "B1", "C1", "D1", "E1", "F1",
        "A2", "B2", "C2", "D2", "E2", "F2",
        "A3", "B3", "C3", "D3", "E3", "F3",
    ]
    return active, np.asarray([rows[name] for name in active], dtype=np.float64)


def _colorchecker_scene_targets():
    names, lab = _colorchecker_lab()
    d50_to_aces_white = (
        np.linalg.inv(CAT02)
        @ np.diag((CAT02 @ ACES_WHITE) / (CAT02 @ D50_WHITE))
        @ CAT02
    )
    xyz_d50_to_ap1 = np.linalg.inv(AP1_TO_XYZ) @ d50_to_aces_white
    ap1 = _lab_d50_to_xyz(lab) @ xyz_d50_to_ap1.T
    return names, ap1


def _view_group(config: ocio.Config, view_name: str) -> ocio.GroupTransform:
    view = config.getViewTransform(view_name)
    if view is None:
        raise RuntimeError(f"Missing OCIO view transform: {view_name}")
    view_transform = view.getTransform(ocio.VIEWTRANSFORM_DIR_FROM_REFERENCE)
    if view_transform is None:
        raise RuntimeError(f"Missing scene-reference transform: {view_name}")
    colorspace = ocio.ColorSpaceTransform()
    colorspace.setSrc("ACEScg")
    colorspace.setDst("ACES2065-1")
    group = ocio.GroupTransform()
    group.appendTransform(colorspace)
    group.appendTransform(view_transform)
    return group


def _apply(processor: ocio.CPUProcessor, values: np.ndarray) -> list[list[float]]:
    result = np.ascontiguousarray(values, dtype=np.float32).copy()
    processor.applyRGB(result)
    return result.astype(np.float64).tolist()


def main() -> None:
    config = ocio.Config.CreateFromFile(str(CONFIG))
    records: dict[str, object] = {
        "config": str(CONFIG),
        "config_cache_id": str(config.getCacheID()),
        "vectors": VECTORS.astype(np.float64).tolist(),
        "profiles": {},
    }
    for profile_id, view_name in PROFILES.items():
        group = _view_group(config, view_name)
        forward = config.getProcessor(group).getDefaultCPUProcessor()
        inverse = config.getProcessor(
            group, ocio.TRANSFORM_DIR_INVERSE
        ).getDefaultCPUProcessor()
        profile_records = records["profiles"]
        assert isinstance(profile_records, dict)
        profile_records[profile_id] = {
            "view": view_name,
            "forward_xyz": _apply(forward, VECTORS),
            "inverse_acescg": _apply(inverse, VECTORS),
        }
    hdr_inverse = config.getProcessor(_view_group(config, PROFILES["0"]), ocio.TRANSFORM_DIR_INVERSE).getDefaultCPUProcessor()
    colorchecker_names, colorchecker_scene = _colorchecker_scene_targets()
    records["colorchecker"] = {
        "names": colorchecker_names,
        "scene": colorchecker_scene.tolist(),
        "views": {},
    }
    for profile_id, view_name in PROFILES.items():
        forward = config.getProcessor(_view_group(config, view_name)).getDefaultCPUProcessor()
        inverse_matrix = np.linalg.inv(
            {"0": REC2020, "1": REC709, "2": P3, "4": P3}[profile_id]
        )
        records["colorchecker"]["views"][profile_id] = (
            np.asarray(_apply(forward, colorchecker_scene)) @ inverse_matrix.T
        ).tolist()
    codes = [[0, .5, .5], [REFERENCE_J, .5, .5], [100 / PEAK, .5, .5],
             [1, .5, .5], [.38, .86, .62], [.3, .38, .65], [.6, .55, .53], [.1, .48, .52]]
    xyz = np.array([code_xyz(code) for code in codes])
    scene = _apply(hdr_inverse, xyz)
    backgrounds = [0, REFERENCE_J, neutral_jhk(203) / PEAK, 1]
    bg_xyz = np.array([code_xyz([v, .5, .5]) for v in backgrounds])
    bg_scene = _apply(hdr_inverse, bg_xyz)
    records["picker"] = {
        "peak_jhk": PEAK, "reference_j": REFERENCE_J,
        "reference_100_jhk": neutral_jhk(100), "codes": codes,
        "source_rec2020": (xyz @ np.linalg.inv(REC2020).T).tolist(),
        "scene": scene, "backgrounds": backgrounds, "views": {},
    }
    for profile_id, view_name in PROFILES.items():
        forward = config.getProcessor(_view_group(config, view_name)).getDefaultCPUProcessor()
        inverse_matrix = np.linalg.inv({"0": REC2020, "1": REC709, "2": P3, "4": P3}[profile_id])
        records["picker"]["views"][profile_id] = {
            "rgb": (np.asarray(_apply(forward, np.asarray(scene))) @ inverse_matrix.T).tolist(),
            "background_rgb": (np.asarray(_apply(forward, np.asarray(bg_scene))) @ inverse_matrix.T).tolist(),
        }
    json.dump(records, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
