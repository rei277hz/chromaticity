"""Compare Vectorscope histogram reducers on one captured RGBA array."""

from hashlib import sha256
from time import perf_counter_ns

import numpy as np


_PARITY_RTOL = 2e-5
_PARITY_ATOL = 2e-4
REDUCERS = ("cpu", "gpu", "shader-tree")


def _milliseconds(started, finished):
    return (finished - started) / 1e6


def _validated_histogram(histogram, expected_shape, name):
    values = np.asarray(histogram, dtype=np.float64)
    if values.shape != expected_shape or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError(f"{name} returned an invalid Vectorscope histogram")
    return values


def _compare(analysis, rgba, linear_matrix, space, reducers):
    """Return correctness and stage timings for each reducer on identical samples."""
    size = analysis.SIZE
    started = perf_counter_ns()
    chroma = analysis.chroma_samples(rgba, linear_matrix, space, size=size)
    mapped = perf_counter_ns()
    reference = analysis.accumulate(*chroma)
    accumulated = perf_counter_ns()
    analysis.normalize_histogram(reference)
    normalized_at = perf_counter_ns()
    rows = [{
        "name": "cpu",
        "mapping_ms": _milliseconds(started, mapped),
        "accumulation_ms": _milliseconds(mapped, accumulated),
        "normalization_ms": _milliseconds(accumulated, normalized_at),
        "total_ms": _milliseconds(started, normalized_at),
        "maximum_bin_error": 0.0,
        "mass_error": 0.0,
        "parity": True,
    }]
    expected_shape = (size, size)
    for name, reducer in reducers.items():
        reducer_start = perf_counter_ns()
        rec709_matrix = analysis.linear_to_rec709(space) @ np.asarray(linear_matrix, dtype=np.float64)
        histogram, timings = reducer(rgba, rec709_matrix, size=size,
                                     limit=analysis.CHROMA_LIMIT)
        reducer_finished = perf_counter_ns()
        values = _validated_histogram(histogram, expected_shape, name)
        parity = bool(np.allclose(values, reference, rtol=_PARITY_RTOL, atol=_PARITY_ATOL))
        normalize_started = perf_counter_ns()
        analysis.normalize_histogram(values)
        normalize_finished = perf_counter_ns()
        rows.append({
            "name": name,
            **timings,
            "normalization_ms": _milliseconds(normalize_started, normalize_finished),
            "total_ms": _milliseconds(reducer_start, reducer_finished)
                        + _milliseconds(normalize_started, normalize_finished),
            "maximum_bin_error": float(np.max(np.abs(values - reference))),
            "mass_error": abs(float(values.sum() - reference.sum())),
            "parity": parity,
        })
        if not parity:
            error = np.abs(values - reference)
            bin_index = np.unravel_index(np.argmax(error), expected_shape)
            raise AssertionError(f"{name} histogram differs from CPU at bin {bin_index}: "
                                 f"{values[bin_index]} vs {reference[bin_index]}, "
                                 f"total weight {values.sum()} vs {reference.sum()}")
    return rows


def _parity_pixels(analysis):
    limit = analysis.CHROMA_LIMIT
    edge = limit * (2 * 87 / analysis.SIZE - 1)
    chroma = np.asarray([
        (edge - 0.0005, 0.13), (edge + 0.0005, 0.13),
        (-0.22, edge - 0.0005), (-0.22, edge + 0.0005),
        (limit - 0.0005, -0.19), (limit + 0.0005, -0.19),
        (-limit + 0.0005, 0.19), (-limit - 0.0005, 0.19),
        (0.27, -0.28), (0.27, -0.28), (-0.27, 0.28), (0.11, 0.23),
        (0.19, 0.23), (0.16, -0.37), (0.33, 0.11), (-0.18, -0.48),
    ])
    cb, cr = chroma.T
    luminance = 0.23
    red = luminance + cr * 1.5748
    blue = luminance + cb * 1.8556
    green = (luminance - 0.2126 * red - 0.0722 * blue) / 0.7152
    code = np.stack((red, green, blue), axis=-1)
    magnitude = np.abs(code)
    rgb = np.sign(code) * np.where(magnitude < 0.081, magnitude / 4.5,
                                   ((magnitude + 0.099) / 1.099) ** (1 / 0.45))
    alpha = (1, 0.75, 0.25, 1, 1, 1, 1, 1, 0.5, 2, 0, -1, 0.375, 0.25, 0.5, 1)
    rgba = np.column_stack((rgb, alpha)).astype(np.float32).reshape(4, 4, 4)
    rgba[3, 1, 0] = np.nan
    rgba[3, 2, 3] = np.inf
    rgba[3, 3, :3] = 0.0
    return rgba


def compare_color_components(analysis, rgba, matrix, space):
    """Check the live CPU color sums against independent scalar histograms."""
    size, limit = analysis.SIZE, analysis.CHROMA_LIMIT
    pixels = np.asarray(rgba, dtype=np.float64).reshape(-1, 4)
    corrected = (pixels[:, :3] @ np.asarray(matrix, dtype=np.float64).T
                 @ analysis.linear_to_rec709(space).T)
    magnitude = np.abs(corrected)
    code = np.copysign(np.where(magnitude < 0.018, 4.5 * magnitude,
                               1.099 * magnitude ** 0.45 - 0.099), corrected)
    red, green, blue = code.T
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    cr, cb = (red - luma) / 1.5748, (blue - luma) / 1.8556
    alpha = pixels[:, 3]
    inside = (np.isfinite(code).all(axis=1) & np.isfinite(alpha) & (alpha > 0)
              & (np.abs(cr) <= limit) & (np.abs(cb) <= limit))
    weights = np.clip(alpha[inside], 0, 1)
    colors = np.clip(code[inside], 0, 1)
    edges = np.linspace(-limit, limit, size + 1)

    def histogram(sample_weights):
        return np.histogram2d(cr[inside], cb[inside], bins=(edges, edges),
                              weights=sample_weights)[0]

    expected_mass = histogram(weights)
    expected_energy = np.stack([histogram(weights * channel) for channel in colors.T], axis=-1)
    started = perf_counter_ns()
    mass, energy = analysis.color_histogram(rgba, matrix, space, size=size)
    binned = perf_counter_ns()
    splat_mass, splat_energy = analysis.splat_components(mass, energy)
    smoothed = perf_counter_ns()
    expected_mass_total = float(expected_mass.sum())
    expected_energy_total = expected_energy.sum(axis=(0, 1))
    splat_energy_total = splat_energy.sum(axis=(0, 1))
    np.testing.assert_allclose(mass, expected_mass, rtol=_PARITY_RTOL, atol=_PARITY_ATOL)
    np.testing.assert_allclose(energy, expected_energy, rtol=_PARITY_RTOL, atol=_PARITY_ATOL)
    np.testing.assert_allclose(splat_mass.sum(), expected_mass_total,
                               rtol=_PARITY_RTOL, atol=_PARITY_ATOL)
    np.testing.assert_allclose(splat_energy_total, expected_energy_total,
                               rtol=_PARITY_RTOL, atol=_PARITY_ATOL)
    return {
        "binning_ms": _milliseconds(started, binned),
        "splat_ms": _milliseconds(binned, smoothed),
        "maximum_mass_bin_error": float(np.max(np.abs(mass - expected_mass))),
        "maximum_rgb_energy_bin_error": float(np.max(np.abs(energy - expected_energy))),
        "splat_mass_error": abs(float(splat_mass.sum()) - expected_mass_total),
        "splat_rgb_energy_error": np.abs(splat_energy_total - expected_energy_total).tolist(),
        "parity": True,
    }


def compare_reducers(analysis, datasets, selection, shader_reducer):
    """Measure matched captures and run a signed color and alpha parity fixture."""
    from .vectorscope_gpu import gpu_histogram

    names = REDUCERS if selection == "all" else (selection,)
    available = {"gpu": gpu_histogram, "shader-tree": shader_reducer}
    reducers = {name: available[name] for name in names if name != "cpu"}
    comparisons = []
    checks = []
    for path, (rgba, matrix, space, capture_ms) in datasets.items():
        digest = sha256(np.ascontiguousarray(rgba).tobytes()).hexdigest()
        height, width = rgba.shape[:2]
        for row in _compare(analysis, rgba, matrix, space, reducers):
            if row["name"] in names:
                comparisons.append({
                    "path": path, "input_sha256": digest, "dimensions": [width, height],
                    "capture_ms": capture_ms, "capture_and_reduce_ms": capture_ms + row["total_ms"],
                    **row,
                })
        if path == "direct_image":
            pixels = _parity_pixels(analysis)
            # Use a non-identity exposure while preserving the designed boundary locations.
            pixels[..., :3] *= 0.5
            for row in _compare(analysis, pixels, 2.0 * np.eye(3), "Linear Rec.709", reducers):
                if row["name"] in names:
                    checks.append({"fixture": "signed_alpha_and_bin_boundaries", **row})
    return comparisons, checks
