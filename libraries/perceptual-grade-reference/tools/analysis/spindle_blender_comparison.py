"""Compare the historical pole experiment with Blender's production cubic.

The public physical maps supply every plotted release and compression value.
Derivatives describe the interior map, including its left derivative at B;
neither this diagnostic nor its checks evaluate a physical map beyond B.
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import numpy as np

from color_tools.perceptual_grade_core.model.spindle import map_radius as blender_map
from color_tools.perceptual_grade_reference.pole_spindle import (
    RADIAL_BOUNDARY_SLOPE,
    RADIAL_POLE,
    RADIAL_SHAPE,
    _POLE_GAP,
    _POLE_SQUARED,
    _RADIAL_A,
    _RADIAL_BLEND,
    _pole_profile,
    radius_map as reference_map,
)


CUBE_FRACTIONS = (0.50, 0.90, 0.95, 0.99, 0.999)
ROUNDTRIP_TOLERANCE = 1e-12
SLOPE_TOLERANCE = 2e-7


def reference_slope(x, k):
    """Analytic radial derivative, evaluated without near-boundary cancellation."""
    x, k = np.broadcast_arrays(np.asarray(x, dtype=float), k)
    z = x * x
    gap = 1 - z
    denominator = _POLE_GAP + gap
    n = z * gap * gap
    dn = gap * (1 - 3 * z)
    divisor = (RADIAL_SHAPE + z) * denominator
    dd = denominator - (RADIAL_SHAPE + z)
    base_derivative = 1 + (dn * divisor - n * dd) / (divisor * divisor)
    pole_derivative = _POLE_GAP * (1 + _POLE_GAP) / denominator**2
    df = (1 - _RADIAL_BLEND) * base_derivative + _RADIAL_BLEND * pole_derivative
    gain = (k - 1) * (k + 1)
    root = np.sqrt(1 + gain * _pole_profile(z))
    return root + gain * z * df / root


def blender_slope(x, k):
    return 1 + 3 * (np.asarray(k) - 1) * np.asarray(x) ** 2


def interior_crossover(k):
    """Nontrivial crossing of the two releases; neutral and x=1 are excluded.

    Squaring their positive releases and removing z(1-z), z=x^2,
    leaves a quadratic. Its positive root is evaluated in rationalized form.
    The identity case has no unique crossing.
    """
    if k == 1:
        return None
    a = k - 1
    b = 2 + a * (2 - _POLE_SQUARED)
    c = 2 * _POLE_SQUARED - (k + 1) * _RADIAL_A
    discriminant = b * b - 4 * a * c
    if discriminant <= 0 or c >= 0:
        return None
    z = -2 * c / (b + np.sqrt(discriminant))
    if not 0 < z < 1:
        return None
    x = float(np.sqrt(z))
    reference = float(reference_map(x, 1., k, release=True))
    blender = float(blender_map(x, 1., k, release=True))
    error = abs(reference - blender) / k
    if error > ROUNDTRIP_TOLERANCE:
        raise AssertionError(f"Crossover does not match actual maps: {error}")
    return {
        "spindle_fraction": x,
        "cube_fraction": reference / k,
        "remaining_radial_margin": 1 - x,
        "normalized_release_disagreement": error,
    }


def check_slopes(mapping, derivative, ratios):
    """Five-point centered differences inside; one-sided differences at endpoints."""
    k = ratios[None, :]
    points = np.array([.001, .01, .1, .25, .5, .75, .8, .9, .95,
                       .99, .999, .9999, .99999])[:, None]
    steps = np.minimum.reduce([
        np.full_like(points, 1e-4), .01 * (RADIAL_POLE - points),
        .2 * points, .2 * (1 - points),
    ])

    def release(x):
        return mapping(x, 1., k, release=True)

    centered = (release(points - 2 * steps) - 8 * release(points - steps)
                + 8 * release(points + steps) - release(points + 2 * steps)) / (12 * steps)
    expected = derivative(points, k)
    centered_error = np.max(abs(centered - expected) / np.maximum(1., abs(expected)))
    endpoint_errors = []
    for endpoint, direction in ((0., 1.), (1., -1.)):
        step = 1e-6
        samples = [release(endpoint + direction * i * step) for i in range(5)]
        forward = (-25 * samples[0] + 48 * samples[1] - 36 * samples[2]
                   + 16 * samples[3] - 3 * samples[4]) / (12 * step)
        estimate = direction * forward
        wanted = derivative(endpoint, k)
        endpoint_errors.append(float(np.max(abs(estimate - wanted) / np.maximum(1., abs(wanted)))))
    maximum = max(float(centered_error), *endpoint_errors)
    if maximum > SLOPE_TOLERANCE:
        raise AssertionError(f"Analytic slope disagrees with physical map: {maximum}")
    return {
        "centered_max_scaled_error": float(centered_error),
        "neutral_right_derivative_max_scaled_error": endpoint_errors[0],
        "boundary_left_derivative_max_scaled_error": endpoint_errors[1],
        "tolerance": SLOPE_TOLERANCE,
    }


def measure(source):
    ratios = np.asarray([case["k"] for case in source["cases"]], dtype=float)
    quantiles = np.asarray(source["capacity_quantiles"], dtype=float)
    if ratios.shape != quantiles.shape or ratios.size != 7:
        raise ValueError("Expected seven matching capacity quantiles and cases")
    if not np.isfinite(ratios).all() or np.any(ratios < 1):
        raise ValueError("Capacity ratios must be finite and at least one")
    checked_ratios = np.unique(np.r_[1., np.nextafter(1., np.inf), 1. + 1e-12,
                                    1. + 1e-8, 1.001, ratios])
    np.testing.assert_allclose(reference_slope(1., checked_ratios),
                               checked_ratios + RADIAL_BOUNDARY_SLOPE * (checked_ratios - 1 / checked_ratios),
                               rtol=8e-15, atol=8e-15)
    x = np.unique(np.r_[0., np.geomspace(1e-300, .01, 121), np.linspace(0, 1, 5001),
                        1 - np.geomspace(1e-14, .01, 401), np.nextafter(1., 0.)])[:, None]
    k = checked_ratios[None, :]
    validation = {}
    for name, mapping, derivative in (("reference", reference_map, reference_slope),
                                      ("blender", blender_map, blender_slope)):
        released = mapping(x, 1., k, release=True)
        restored = mapping(released, 1., k)
        entered = mapping(x * k, 1., k)
        restored_cube = mapping(entered, 1., k, release=True) / k
        if not all(np.isfinite(v).all() for v in (released, restored, entered, restored_cube)):
            raise AssertionError(f"{name}: nonfinite physical map")
        release_error = float(np.max(abs(restored - x)))
        entry_error = float(np.max(abs(restored_cube - x)))
        if max(release_error, entry_error) > ROUNDTRIP_TOLERANCE:
            raise AssertionError(f"{name}: normalized roundtrip exceeds tolerance")
        np.testing.assert_array_equal(mapping(0., 1., checked_ratios), 0.)
        np.testing.assert_array_equal(mapping(0., 1., checked_ratios, release=True), 0.)
        np.testing.assert_array_equal(mapping(checked_ratios, 1., checked_ratios), 1.)
        np.testing.assert_array_equal(mapping(1., 1., checked_ratios, release=True), checked_ratios)
        np.testing.assert_array_equal(mapping(x, 1., 1.), x)
        np.testing.assert_array_equal(mapping(x, 1., 1., release=True), x)
        release_step = float(np.min(np.diff(released / k, axis=0)))
        entry_step = float(np.min(np.diff(entered, axis=0)))
        if min(release_step, entry_step) < -64 * np.finfo(float).eps:
            raise AssertionError(f"{name}: physical map is not sampled monotone")
        if np.any(derivative(x, k) < 1):
            raise AssertionError(f"{name}: radial release derivative falls below one")
        validation[name] = {
            "samples_per_direction": int(released.size),
            "checked_ratios": checked_ratios.tolist(),
            "exact_endpoints": True,
            "exact_k1_identity": True,
            "release_then_entry_max_absolute_error_in_B": release_error,
            "entry_then_release_max_absolute_error_in_U": entry_error,
            "normalized_roundtrip_tolerance": ROUNDTRIP_TOLERANCE,
            "minimum_sampled_release_increment_in_U": release_step,
            "minimum_sampled_entry_increment_in_B": entry_step,
            "slopes": check_slopes(mapping, derivative, checked_ratios),
        }
    cases = []
    for quantile, ratio in zip(quantiles, ratios):
        positions = []
        for fraction in CUBE_FRACTIONS:
            ref = float(reference_map(fraction * ratio, 1., ratio))
            prod = float(blender_map(fraction * ratio, 1., ratio))
            positions.append({
                "cube_fraction": fraction,
                "reference_spindle_fraction": ref,
                "blender_spindle_fraction": prod,
                "reference_remaining_radial_margin": 1 - ref,
                "blender_remaining_radial_margin": 1 - prod,
            })
        cases.append({
            "capacity_quantile": float(quantile),
            "k": float(ratio),
            "reference_boundary_left_slope": float(reference_slope(1., ratio)),
            "blender_boundary_left_slope": float(blender_slope(1., ratio)),
            "reference_neutral_cubic_coefficient": float((ratio - 1) * (ratio + 1) * _RADIAL_A / (2 * _POLE_SQUARED)),
            "blender_neutral_cubic_coefficient": float(ratio - 1),
            "interior_crossover": interior_crossover(float(ratio)),
            "compressed_positions": positions,
        })
    return {
        "scope": "Scalar physical radial maps at fixed J_A and hue; historical nonpiecewise pole experiment versus actual Blender production cubic. The active reference now matches the cubic. No performance benchmark.",
        "definitions": {
            "B": "Spindle capacity at fixed J_A",
            "U": "Cube capacity at the same J_A and hue",
            "k": "U/B",
            "x": "C_spindle/B",
            "R": "C_cube/B",
            "cube_fraction": "C_cube/U",
            "remaining_radial_margin": "1-x, at fixed J_A; not full grading headroom",
            "boundary_slope": "Left derivative R'(1); physical wrappers clamp outside the boundary",
        },
        "reference": {"pole": RADIAL_POLE, "profile_boundary_derivative": RADIAL_BOUNDARY_SLOPE,
                      "shape": RADIAL_SHAPE, "status": "historical pole experiment", "source": "libraries/perceptual-grade-reference/src/pole_spindle.py:radius_map"},
        "blender": {"release": "R(x)=x+(k-1)x^3", "source": "libraries/perceptual-grade-core/src/perceptual_grade_core/model/spindle.py:map_radius"},
        "capacity_samples": int(source["capacity_samples"]),
        "capacity_quantiles": quantiles.tolist(),
        "cases": cases,
        "validation": validation,
        "limitations": [
            "The historical map's analytic pole is outside the physical map. Both wrappers and the existing hard guard stop at B; the pole provides no usable exterior grading range.",
            "Both maps preserve J_A and hue. J_HK and grading-driver values change with the compressed chroma; fixed-J_A radial margin is not full grade headroom.",
            "Sampled radial checks do not certify geometry, full RGB pipelines, float32 kernels, or GPU performance.",
        ],
    }


def plot_comparison(report, output_dir):
    cases = report["cases"]
    ratios = np.asarray([case["k"] for case in cases])
    colors = plt.get_cmap("viridis")(np.linspace(.06, .87, len(cases)))
    x = np.unique(np.r_[np.linspace(0, 1, 1201), 1 - np.geomspace(1e-9, .02, 601)])
    cube_fraction = np.unique(np.r_[np.linspace(0, 1, 1201), 1 - np.geomspace(1e-9, .02, 601)])
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 11.5))
    release_axis, slope_axis, entry_axis, margin_axis = axes.ravel()
    fig.suptitle("Spindle mapping: historical pole vs Blender production", fontsize=18, y=.985)
    for ratio, color in zip(ratios, colors):
        for mapping, derivative, style, width in ((reference_map, reference_slope, "-", 2.),
                                                  (blender_map, blender_slope, "--", 1.55)):
            release_axis.plot(x, mapping(x, 1., ratio, release=True), color=color,
                              linestyle=style, linewidth=width)
            slope_axis.plot(x, derivative(x, ratio), color=color,
                            linestyle=style, linewidth=width)
            entry_axis.plot(cube_fraction, mapping(cube_fraction * ratio, 1., ratio),
                            color=color, linestyle=style, linewidth=width)
        release_axis.scatter([1.], [ratio], s=16, color=[color], zorder=4)
    release_axis.set(xlim=(0, 1.01), ylim=(0, 1.055 * ratios.max()),
                     xlabel=r"Spindle radius $x=C_{spindle}/B$",
                     ylabel=r"Released cube radius $R_k(x)=C_{cube}/B$",
                     title="Release · same spindle radius")
    release_axis.text(.045, .94, r"Both: $R_k(0)=0$, $R_k(1)=k$" + "\n"
                      + r"Near neutral: $R_k'(0)=1$, $R_k''(0)=0$",
                      transform=release_axis.transAxes, va="top", fontsize=10)
    slope_axis.set(xlim=(0, 1.01), ylim=(.9, 1.35 * reference_slope(1., ratios.max())),
                   xlabel=r"Spindle radius $x=C_{spindle}/B$",
                   ylabel=r"Release slope $R_k'(x)$ · logarithmic scale",
                   title="Slope · boundary value is the left derivative")
    slope_axis.set_yscale("log")
    inset = slope_axis.inset_axes([.075, .49, .46, .43])
    near_boundary = 1 - np.r_[np.geomspace(1e-10, .02, 701)[::-1], 0.]
    largest = int(np.argmax(ratios))
    high_k, high_color = float(ratios[largest]), colors[largest]
    inset.plot(near_boundary, reference_slope(near_boundary, high_k), color=high_color, linewidth=1.7)
    inset.plot(near_boundary, blender_slope(near_boundary, high_k), color=high_color,
               linestyle="--", linewidth=1.5)
    inset.set(xlim=(.98, 1.), ylim=(0, 1.1 * reference_slope(1., high_k)),
              title=f"Near B · maximum k={high_k:.4g}")
    inset.set_xticks([.98, .99, 1.])
    inset.tick_params(labelsize=8)
    inset.title.set_fontsize(9)
    inset.grid(True, color="#dddddd", linewidth=.6)
    slope_axis.text(.98, .06,
                    rf"At B, max k: {reference_slope(1., high_k):.1f} vs {blender_slope(1., high_k):.1f}",
                    transform=slope_axis.transAxes, ha="right", fontsize=9,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 2.})
    entry_axis.set(xlim=(0, 1.01), ylim=(0, 1.02),
                   xlabel=r"Uncompressed cube fraction $f=C_{cube}/U$",
                   ylabel=r"Compressed spindle radius $x=C_{spindle}/B$",
                   title="Compression · same cube color")
    entry_axis.axhline(1., color="#555555", linewidth=.8, linestyle=":")
    fractions = np.unique(np.r_[np.linspace(.9, .999, 1001),
                                1 - np.geomspace(1e-4, .1, 1001)])
    ref_margin = 1 - reference_map(fractions * high_k, 1., high_k)
    prod_margin = 1 - blender_map(fractions * high_k, 1., high_k)
    margin_axis.plot(fractions, ref_margin, color=high_color, linewidth=2., label="Historical pole")
    margin_axis.plot(fractions, prod_margin, color=high_color, linewidth=1.8,
                     linestyle="--", label="Blender")
    margin_axis.set_yscale("log")
    margin_axis.set(xlim=(.9, 1.), ylim=(1e-6, .08),
                    xlabel=r"Uncompressed cube fraction $f=C_{cube}/U$",
                    ylabel=r"Remaining radial margin $1-x$ · logarithmic scale",
                    title=f"Room before B · maximum k={high_k:.5g}")
    margin_axis.xaxis.set_major_formatter(PercentFormatter(1., decimals=0))
    crossover = cases[largest]["interior_crossover"]
    if crossover is not None:
        crossing_f = crossover["cube_fraction"]
        crossing_margin = crossover["remaining_radial_margin"]
        margin_axis.axvline(crossing_f, color="#555555", linewidth=.9, linestyle=":")
        margin_axis.scatter([crossing_f], [crossing_margin], color="#333333", marker="D", s=28, zorder=4)
        margin_axis.annotate(f"Equal margin at {100 * crossing_f:.3f}% of U",
                             xy=(crossing_f, crossing_margin), xytext=(.912, .001),
                             arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
        margin_axis.text(.915, .12, "Historical pole leaves more room below the crossing;\n"
                         "Blender leaves more room above it.",
                         transform=margin_axis.get_xaxis_transform(), fontsize=9)
    margin_axis.text(.04, .045, r"Fixed-$J_A$ radial margin; samples stop at $f=0.9999$.",
                     transform=margin_axis.transAxes, fontsize=9, color="#444444")
    for axis in axes.ravel():
        axis.grid(True, which="major", color="#dddddd", linewidth=.75)
        axis.set_axisbelow(True)
        axis.tick_params(labelsize=9)
    model_handles = [
        Line2D([], [], color="#333333", linewidth=2., label=f"Historical pole · {RADIAL_POLE:g}B, d={RADIAL_BOUNDARY_SLOPE:g}"),
        Line2D([], [], color="#333333", linewidth=1.7, linestyle="--", label="Blender production · cubic"),
    ]
    fig.legend(handles=model_handles, loc="upper center", bbox_to_anchor=(.5, .958),
               ncol=2, frameon=False, fontsize=11)
    quantile_handles = [Line2D([], [], color=color, linewidth=2.,
                              label=f"Q{100 * case['capacity_quantile']:g}: k={case['k']:.4g}")
                        for case, color in zip(cases, colors)]
    fig.legend(handles=quantile_handles, loc="lower center", bbox_to_anchor=(.5, .078),
               ncol=7, frameon=False, fontsize=9, handlelength=1.7, columnspacing=1.4)
    fig.text(.5, .018,
             r"$B$: spindle capacity; $U$: cube capacity at the same $J_A$ and hue; $k=U/B$. "
             + f"Seven capacity quantiles from {report['capacity_samples']:,} samples.\n"
             + rf"All plots use the physical domain. The historical pole at ${RADIAL_POLE:g}B$ is outside it; both physical release wrappers stop at $B$." + "\n"
             + r"Both maps preserve $J_A$ and hue; compressed $C$ changes $J_{HK}$ and grading drivers. Radial margin is not full grading headroom.",
             ha="center", va="bottom", fontsize=9)
    fig.subplots_adjust(left=.075, right=.974, bottom=.16, top=.9, hspace=.3, wspace=.24)
    fig.savefig(output_dir / "spindle-blender-comparison.png", dpi=170, facecolor="white",
                metadata={"Title": "Historical pole map versus Blender production cubic"})
    plt.close(fig)


def summary(report):
    rows = [
        "# Historical pole experiment versus Blender spindle mapping", "",
        report["scope"], "",
        "`B` is the spindle capacity, `U` is cube capacity at the same J_A and hue, "
        "and `k=U/B`. Release uses x=C_spindle/B and R=C_cube/B.", "",
        "The historical pole experiment uses p=1.001, d=20 and its rational-profile release. "
        "Blender uses R=x+(k-1)x^3. Both have R'(0)=1, R''(0)=0 and R(1)=k; "
        "the boundary left slopes are 21k-20/k and 3k-2 respectively.", "",
        "Each paired cell below is **historical pole / Blender**. Fractions label the same "
        "uncompressed color C_cube/U; entries give C_spindle/B. The crossover "
        "excludes the shared neutral and boundary endpoints.", "",
        "| Quantile | k | 0.5U | 0.9U | 0.95U | 0.99U | 0.999U | Boundary slope | Crossover C/U |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        cells = [f"Q{100 * case['capacity_quantile']:g}", f"{case['k']:.8g}"]
        cells.extend(f"{pos['reference_spindle_fraction']:.7f} / {pos['blender_spindle_fraction']:.7f}"
                     for pos in case["compressed_positions"])
        cells.append(f"{case['reference_boundary_left_slope']:.6g} / {case['blender_boundary_left_slope']:.6g}")
        crossing = case["interior_crossover"]
        cells.append(f"{crossing['cube_fraction']:.8f}" if crossing is not None else "none")
        rows.append("| " + " | ".join(cells) + " |")
    rows.extend(["", "The historical pole map releases farther for the same spindle radius below the nontrivial "
                 "crossing, so its entry map leaves more radial room there. In the outermost region "
                 "the ordering reverses. Its very large boundary slope is concentrated close to B.", "",
                 "Matching the neutral derivative does not imply identical finite low-chroma behavior. "
                 "The historical pole map's neutral cubic coefficient is "
                 f"{_RADIAL_A / (2 * _POLE_SQUARED):.9f}(k²-1), versus Blender's (k-1).", "",
                 "Validation uses the actual public physical maps, including k=1 and values close to it. "
                 "All endpoints and the identity case are exact; sampled maps are nondecreasing. "
                 "Five-point differences verify analytic slopes, with one-sided estimates at neutral and B.", ""])
    for name, result in report["validation"].items():
        slopes = result["slopes"]
        rows.append(
            f"- {'Historical pole' if name == 'reference' else name.capitalize()}: {result['samples_per_direction']:,} samples per direction; "
            f"release/entry roundtrip error {result['release_then_entry_max_absolute_error_in_B']:.3g} B; "
            f"entry/release roundtrip error {result['entry_then_release_max_absolute_error_in_U']:.3g} U; "
            f"maximum scaled slope error {max(slopes['centered_max_scaled_error'], slopes['neutral_right_derivative_max_scaled_error'], slopes['boundary_left_derivative_max_scaled_error']):.3g}."
        )
    rows.extend(["", *report["limitations"], ""])
    return "\n".join(rows)


def generate(output_dir, source_report):
    report = measure(json.loads(source_report.read_text()))
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_comparison(report, output_dir)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output_dir / "summary.md").write_text(summary(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output_dir, args.report)
