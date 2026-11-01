"""Fit the current compact saturation radius from deterministic RGB workloads."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from color_tools.color_core.linear import rgb_to_xyz
from color_tools.hdr_color_picker_core import (
    PICKER_J_PEAK,
    XYZ_TO_P3,
    _radius_from_saturation,
    _saturation_from_radius,
    _xyz_to_jsh,
)


REFERENCE_SCALE = 2.03
SEED = 20260912
TRAIN_COUNT = 5000
VALIDATION_COUNT = 5000
TEST_COUNT = 10000
FIT_STEPS = 16
EVALUATION_STEPS = 64
LOG_K_BOUNDS = (math.log(0.01), math.log(10000.0))
LOG1P_A_BOUNDS = (0.0, math.log1p(100.0))
GRID_K_POINTS = 33
GRID_A_POINTS = 17
LOCAL_GRID_POINTS = 5
LOCAL_REFINEMENTS = 12

GAMUTS = (
    ("rec709_sdr", 0.70, 1.0, np.asarray(rgb_to_xyz("Linear Rec.709"))),
    ("display_p3_hdr", 0.20, 10.0, np.linalg.inv(XYZ_TO_P3)),
    ("rec2020_hdr", 0.10, 10.0, np.asarray(rgb_to_xyz("Linear Rec.2020"))),
)


def _counts(count):
    rec709 = int(round(count * 0.70))
    p3 = int(round(count * 0.20))
    return rec709, p3, count - rec709 - p3


def _appearance(rgb, matrix):
    xyz = (rgb @ matrix.T) / REFERENCE_SCALE
    jhk, saturation, hue, _ = _xyz_to_jsh(xyz)
    valid = (np.isfinite(jhk) & (jhk >= 0.0) & (jhk <= PICKER_J_PEAK)
             & np.isfinite(saturation) & (saturation >= 0.0) & np.isfinite(hue))
    return np.column_stack((jhk, saturation, hue)), valid


def generate_pairs(count, seed):
    """Generate endpoint pairs inside the exact 70/20/10 D65 RGB workload."""
    rng = np.random.default_rng(seed)
    first, second = [], []
    diagnostics = {}

    for (name, _, rgb_max, matrix), wanted in zip(GAMUTS, _counts(count)):
        accepted_first, accepted_second = [], []
        accepted = proposals = 0
        while accepted < wanted:
            remaining = wanted - accepted
            batch = max(128, remaining * 2)
            rgb_a = rng.random((batch, 3)) * rgb_max
            rgb_b = rng.random((batch, 3)) * rgb_max
            appearance_a, valid_a = _appearance(rgb_a, matrix)
            appearance_b, valid_b = _appearance(rgb_b, matrix)
            keep = valid_a & valid_b
            take = min(remaining, int(keep.sum()))
            if take:
                accepted_first.append(appearance_a[keep][:take])
                accepted_second.append(appearance_b[keep][:take])
                accepted += take
            proposals += batch

        first.append(np.concatenate(accepted_first, axis=0))
        second.append(np.concatenate(accepted_second, axis=0))
        diagnostics[name] = {
            "accepted_pairs": wanted,
            "proposed_pairs": proposals,
            "rgb_max": rgb_max,
        }

    a = np.concatenate(first, axis=0)
    b = np.concatenate(second, axis=0)
    order = rng.permutation(count)
    return a[order], b[order], diagnostics


def achromatic_chroma(jhk, saturation):
    """Invert H^2 = J_A^2 + 66C, with C=(.007/.525)J_A*s."""
    u = (0.007 / 0.525) * saturation
    denominator = np.hypot(jhk, 33.0 * u) + 33.0 * u
    j_a = np.divide(jhk * jhk, denominator,
                    out=np.zeros_like(jhk), where=denominator > 0)
    return j_a, u * j_a


def ucs(jhk, saturation, hue):
    j_a, chroma = achromatic_chroma(jhk, saturation)
    vertical = 1.7 * j_a / (1.0 + 0.007 * j_a)
    radius = (2.4 / 0.098) * np.log1p(0.098 * chroma)
    return np.stack((vertical, radius * np.cos(hue), radius * np.sin(hue)), axis=-1)


def blend_mse(a, b, k, cubic, steps):
    radius_a = _radius_from_saturation(a[:, 1], k, cubic)
    radius_b = _radius_from_saturation(b[:, 1], k, cubic)
    ax, ay = radius_a * np.cos(a[:, 2]), radius_a * np.sin(a[:, 2])
    bx, by = radius_b * np.cos(b[:, 2]), radius_b * np.sin(b[:, 2])
    amount = np.linspace(0.0, 1.0, steps + 1)[None, :]
    jhk = (1.0 - amount) * a[:, None, 0] + amount * b[:, None, 0]
    x = (1.0 - amount) * ax[:, None] + amount * bx[:, None]
    y = (1.0 - amount) * ay[:, None] + amount * by[:, None]
    radius = np.hypot(x, y)
    saturation = _saturation_from_radius(radius, k, cubic)
    hue = np.arctan2(y, x)
    points = ucs(jhk, saturation, hue)
    distances = np.linalg.norm(np.diff(points, axis=1), axis=2)
    means = distances.mean(axis=1, keepdims=True)
    if np.any(means[:, 0] <= 1e-12) or not np.isfinite(distances).all():
        raise ValueError("The generated workload contains a degenerate blend")
    return np.mean((distances / means - 1.0) ** 2, axis=1)


def _loss(a, b, log_k, log1p_cubic):
    k = math.exp(log_k)
    cubic = math.expm1(log1p_cubic)
    return float(blend_mse(a, b, k, cubic, FIT_STEPS).mean())


def fit_curve(training):
    a, b = training
    log_k_grid = np.linspace(*LOG_K_BOUNDS, GRID_K_POINTS)
    log1p_cubic_grid = np.linspace(*LOG1P_A_BOUNDS, GRID_A_POINTS)
    best = None
    for log_k in log_k_grid:
        for log1p_cubic in log1p_cubic_grid:
            item = (float(log_k), float(log1p_cubic))
            loss = _loss(a, b, *item)
            if best is None or loss < best[0]:
                best = (loss, *item)

    coarse_spacing = (
        (LOG_K_BOUNDS[1] - LOG_K_BOUNDS[0]) / (GRID_K_POINTS - 1),
        (LOG1P_A_BOUNDS[1] - LOG1P_A_BOUNDS[0]) / (GRID_A_POINTS - 1),
    )
    spans = list(coarse_spacing)
    log_k, log1p_cubic = best[1:]
    for _ in range(LOCAL_REFINEMENTS):
        k_values = np.linspace(log_k - spans[0], log_k + spans[0], LOCAL_GRID_POINTS)
        a_values = np.linspace(log1p_cubic - spans[1], log1p_cubic + spans[1], LOCAL_GRID_POINTS)
        k_values = np.unique(np.clip(k_values, *LOG_K_BOUNDS))
        a_values = np.unique(np.clip(a_values, *LOG1P_A_BOUNDS))
        candidates = []
        for candidate_k in k_values:
            for candidate_a in a_values:
                loss = _loss(a, b, float(candidate_k), float(candidate_a))
                candidates.append((loss, float(candidate_k), float(candidate_a)))
        best = min(candidates)
        log_k, log1p_cubic = best[1:]
        spans = [span / (LOCAL_GRID_POINTS - 1) for span in spans]

    if (log_k <= LOG_K_BOUNDS[0] + 1e-8 or log_k >= LOG_K_BOUNDS[1] - 1e-8
            or log1p_cubic >= LOG1P_A_BOUNDS[1] - 1e-8):
        raise ValueError("The fitted parameters reached a configured search boundary")

    return math.exp(log_k), math.expm1(log1p_cubic), best[0], {
        "method": "deterministic_2d_grid_then_local_grid_refinement",
        "parameterization": "log(K), log(1 + A)",
        "log_K_bounds": list(LOG_K_BOUNDS),
        "log1p_A_bounds": list(LOG1P_A_BOUNDS),
        "global_grid_points": [GRID_K_POINTS, GRID_A_POINTS],
        "local_grid_points_per_axis": LOCAL_GRID_POINTS,
        "local_refinements": LOCAL_REFINEMENTS,
        "final_log_K_span": spans[0],
        "final_log1p_A_span": spans[1],
        "training_objective": best[0],
    }


def score(a, b, k, cubic):
    mse = blend_mse(a, b, k, cubic, EVALUATION_STEPS)
    return {
        "count": len(mse),
        "rms_cv_percent": float(100.0 * np.sqrt(mse.mean())),
        "median_cv_percent": float(100.0 * np.sqrt(np.median(mse))),
        "p95_cv_percent": float(100.0 * np.sqrt(np.quantile(mse, 0.95))),
    }


def fit_report():
    training_a, training_b, train_mix = generate_pairs(TRAIN_COUNT, SEED)
    validation_a, validation_b, validation_mix = generate_pairs(VALIDATION_COUNT, SEED + 1)
    test_a, test_b, test_mix = generate_pairs(TEST_COUNT, SEED + 2)
    k, cubic, loss, optimization = fit_curve((training_a, training_b))
    return {
        "schema": 2,
        "curve": {
            "family": "cubic_tangent_compactification",
            "encoding": "u = s/K; t = u + A*u^3; r = t/sqrt(1 + t^2)",
            "decoding": "t = r/sqrt(1 - r^2); solve A*u^3 + u = t; s = K*u",
            "K": k,
            "A": cubic,
            "finite_saturation_range": "0 <= r < 1",
            "unit_circle_edge": "infinite saturation; rejected by decoder",
        },
        "fit": {
            "objective": "mean over endpoint pairs of mean((step_distance / pair_mean_distance - 1)^2)",
            "coordinates": "linear interpolation in normalized J-prime/x-prime/y-prime",
            "metric": "Euclidean CAM16-UCS distance in (J-prime, M-prime*cos(h), M-prime*sin(h))",
            "optimization": optimization,
        },
        "workload": {
            "name": "d65_rgb_gamut_mix",
            "seed": SEED,
            "split_seeds": {
                "training": SEED,
                "validation": SEED + 1,
                "test": SEED + 2,
            },
            "rgb_sampling": "independent uniform linear RGB endpoint pairs within one assigned gamut cube",
            "xyz_scale_divisor": REFERENCE_SCALE,
            "gamut_weights_percent": {
                "rec709_sdr": 70,
                "display_p3_hdr": 20,
                "rec2020_hdr": 10,
            },
            "rgb_ranges": {
                "rec709_sdr": [0.0, 1.0],
                "display_p3_hdr": [0.0, 10.0],
                "rec2020_hdr": [0.0, 10.0],
            },
            "pair_counts_by_gamut": {
                name: dict(zip(("training", "validation", "test"),
                               (_counts(TRAIN_COUNT)[index],
                                _counts(VALIDATION_COUNT)[index],
                                _counts(TEST_COUNT)[index])))
                for index, (name, _, _, _) in enumerate(GAMUTS)
            },
            "accepted_endpoint_constraint": f"finite appearance with 0 <= J_HK <= {PICKER_J_PEAK}",
            "training_sampling": train_mix,
            "validation_sampling": validation_mix,
            "test_sampling": test_mix,
            "train_count": TRAIN_COUNT,
            "validation_count": VALIDATION_COUNT,
            "test_count": TEST_COUNT,
            "fit_steps": FIT_STEPS,
            "evaluation_steps": EVALUATION_STEPS,
        },
        "scores": {
            "training_rms_cv_percent": float(100.0 * math.sqrt(loss)),
            "validation": score(validation_a, validation_b, k, cubic),
            "test": score(test_a, test_b, k, cubic),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = fit_report()
    (args.output_dir / "radius_fit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
