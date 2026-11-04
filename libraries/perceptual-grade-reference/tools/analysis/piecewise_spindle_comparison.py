"""Compare historical piecewise C2 and nonpiecewise pole experiments.

This diagnostic evaluates scalar radial maps. It does not adopt the candidate
in the grading model or measure changes to the full color pipeline.
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

from color_tools.perceptual_grade_reference.piecewise_spindle import (
    JOIN,
    SHOULDER_RATE,
    compress_radius,
    release_derivatives,
    release_radius,
)
from color_tools.perceptual_grade_reference.pole_spindle import (
    RADIAL_BOUNDARY_SLOPE,
    RADIAL_POLE,
    _POLE_SQUARED,
    _RADIAL_A,
    _RADIAL_B,
    _compress_radius,
    _release_radius,
)


INNER_LIFTS = (0.05, 0.10, 0.25)
POLES = (1.001, 1.01, 1.025, 1.05)
DEFAULT_LIFT = 0.10
DEFAULT_POLE = 1.01
CUBE_FRACTIONS = (0.50, 0.90, 0.99)
LIFT_COLORS = ("#1a7f8b", "#cf671a", "#7556a4")
FRACTION_COLORS = ("#2577a1", "#bc6426", "#85579c")


def baseline_derivative(x, k):
    """Analytic derivative of the historical rational-profile release."""
    z = np.asarray(x) ** 2
    p, a, b = _POLE_SQUARED, _RADIAL_A, _RADIAL_B
    profile = -b - (a - b) / ((p + 1) * (1 + z)) + p * (a + b * p) / (
        (p + 1) * (p - z)
    )
    derivative = (a - b) / ((p + 1) * (1 + z) ** 2) + p * (a + b * p) / (
        (p + 1) * (p - z) ** 2
    )
    gain = (np.asarray(k) - 1) * (np.asarray(k) + 1)
    root = np.sqrt(1 + gain * profile)
    return root + gain * z * derivative / root


def measure(source):
    """Sample both directions, joins, endpoint conditions, and pole behavior."""
    ratios = np.asarray([case["k"] for case in source["cases"]])
    checked_ratios = np.unique(np.r_[
        1.0, np.nextafter(1.0, np.inf), 1.0 + 1e-12, 1.0 + 1e-8,
        1.001, ratios,
    ])
    physical_x = np.unique(np.r_[
        0.0, np.geomspace(1e-300, 1e-2, 121), np.linspace(0, 1, 5001),
        np.nextafter(JOIN, 0), JOIN, np.nextafter(JOIN, 1),
        np.nextafter(1.0, 0),
    ])
    pole_distances = np.geomspace(1e-8, 1.0, 301)
    cube_fractions = np.unique(np.r_[0.0, np.geomspace(1e-300, 1e-2, 121),
                                     np.linspace(0, 1, 5001)])
    settings = []
    for lift in INNER_LIFTS:
        for pole in POLES:
            exterior_x = np.unique(pole - (pole - 1) * pole_distances)
            all_x = np.r_[physical_x, exterior_x[exterior_x > 1]]
            x, k = all_x[:, None], checked_ratios[None, :]
            y = release_radius(x, k, inner_lift=lift, pole=pole)
            restored = compress_radius(y, k, inner_lift=lift, pole=pole)
            absolute = np.abs(restored - x)
            cube_y = cube_fractions[:, None] * k
            cube_x = compress_radius(cube_y, k, inner_lift=lift, pole=pole)
            cube_restored = release_radius(cube_x, k, inner_lift=lift, pole=pole)
            cube_error = np.abs(cube_restored / k - cube_fractions[:, None])
            d1, d2 = release_derivatives(x, k, inner_lift=lift, pole=pole)
            joins = []
            for join in (JOIN, 1.0):
                sides = np.array([np.nextafter(join, 0), join,
                                  np.nextafter(join, np.inf)])[:, None]
                values = release_radius(sides, k, inner_lift=lift, pole=pole)
                first, second = release_derivatives(sides, k, inner_lift=lift, pole=pole)
                joins.append({
                    "x": join,
                    "max_adjacent_float_value_difference": float(np.ptp(values, axis=0).max()),
                    "max_adjacent_float_slope_difference": float(np.ptp(first, axis=0).max()),
                    "max_adjacent_float_curvature_difference": float(np.ptp(second, axis=0).max()),
                })
            boundary = release_radius(1.0, checked_ratios, inner_lift=lift, pole=pole)
            neutral_d1, neutral_d2 = release_derivatives(
                0.0, checked_ratios, inner_lift=lift, pole=pole,
            )
            settings.append({
                "inner_lift": lift,
                "pole": pole,
                "roundtrip_samples": int(y.size),
                "cube_roundtrip_samples": int(cube_y.size),
                "roundtrip_max_absolute": float(absolute.max()),
                "physical_roundtrip_max_absolute": float(absolute[:len(physical_x)].max()),
                "cube_roundtrip_max_error_as_capacity_fraction": float(cube_error.max()),
                "finite_values_and_derivatives": bool(
                    np.isfinite(y).all() and np.isfinite(restored).all()
                    and np.isfinite(d1).all() and np.isfinite(d2).all()
                    and np.isfinite(cube_restored).all()
                ),
                "minimum_sampled_slope": float(np.min(d1)),
                "minimum_sampled_curvature": float(np.min(d2)),
                "boundary_value_max_absolute_error": float(np.max(np.abs(boundary - checked_ratios))),
                "neutral_slope_max_absolute_error": float(np.max(np.abs(neutral_d1 - 1))),
                "neutral_curvature_max_absolute": float(np.max(np.abs(neutral_d2))),
                "joins": joins,
                "max_k_pole_approach": [
                    {"remaining_fraction": float(fraction),
                     "release_over_cube_capacity": float(release_radius(
                         pole - (pole - 1) * fraction, ratios.max(),
                         inner_lift=lift, pole=pole,
                     ) / ratios.max())}
                    for fraction in (1.0, 1e-2, 1e-4, 1e-6, 1e-8)
                ],
            })
    physical_values = [release_radius(physical_x[:, None], checked_ratios,
                       inner_lift=DEFAULT_LIFT, pole=pole) for pole in POLES]
    cases = []
    for quantile, k in zip(source["capacity_quantiles"], ratios):
        variants = []
        for lift in INNER_LIFTS:
            slope, curvature = release_derivatives(1.0, k, inner_lift=lift, pole=DEFAULT_POLE)
            variants.append({
                "inner_lift": lift,
                "boundary_slope": float(slope),
                "boundary_curvature": float(curvature),
                "relative_lift_at_join": float(release_radius(JOIN, k,
                    inner_lift=lift, pole=DEFAULT_POLE) / JOIN - 1),
                "compressed_cube_fractions": {
                    str(fraction): float(compress_radius(fraction * k, k,
                        inner_lift=lift, pole=DEFAULT_POLE))
                    for fraction in CUBE_FRACTIONS
                },
            })
        cases.append({
            "quantile": quantile, "k": float(k), "variants": variants,
            "baseline_compressed_cube_fractions": {
                str(fraction): float(_compress_radius(fraction * k, k))
                for fraction in CUBE_FRACTIONS
            },
        })
    return {
        "scope": "Historical scalar comparison of two archived experiments; active reference and production use cubic",
        "join": JOIN, "shoulder_rate": SHOULDER_RATE,
        "inner_lifts": list(INNER_LIFTS), "poles": list(POLES),
        "default_inner_lift": DEFAULT_LIFT, "default_pole": DEFAULT_POLE,
        "baseline": {"pole": RADIAL_POLE, "boundary_profile_slope": RADIAL_BOUNDARY_SLOPE,
                     "source": "libraries/perceptual-grade-reference/src/pole_spindle.py", "status": "historical pole experiment"},
        "source_capacity_samples": source["capacity_samples"],
        "capacity_quantiles": source["capacity_quantiles"],
        "tested_capacity_ratios": checked_ratios.tolist(),
        "physical_radius_samples": int(len(physical_x)),
        "total_roundtrip_samples": sum(row["roundtrip_samples"] + row["cube_roundtrip_samples"] for row in settings),
        "roundtrip_max_absolute": max(row["roundtrip_max_absolute"] for row in settings),
        "physical_roundtrip_max_absolute": max(row["physical_roundtrip_max_absolute"] for row in settings),
        "cube_roundtrip_max_error_as_capacity_fraction": max(
            row["cube_roundtrip_max_error_as_capacity_fraction"] for row in settings
        ),
        "physical_pole_parameter_max_difference": float(np.ptp(np.stack(physical_values), axis=0).max()),
        "settings": settings, "cases": cases,
        "limitation": "Finite float64 samples are numerical evidence, not uniform proofs. Adjacent-float join differences include ordinary variation across the sample interval.",
    }


def draw(output_dir, report):
    """Six views separate interior shape, exterior poles, and radial headroom."""
    ratios = np.array([case["k"] for case in report["cases"]])
    largest = float(ratios.max())
    colors = plt.get_cmap("viridis")(np.linspace(0.05, 0.86, len(ratios)))
    x = np.unique(np.r_[np.linspace(0, 1, 1601), JOIN])
    plt.rcParams.update({
        "font.size": 10, "axes.titlesize": 12, "axes.labelsize": 10,
        "legend.fontsize": 8.5, "axes.spines.top": False,
        "axes.spines.right": False,
    })
    figure, axes = plt.subplots(2, 3, figsize=(17.0, 10.6))
    release_axis, slope_axis, inner_axis, pole_axis, compress_axis, headroom_axis = axes.flat
    figure.suptitle("Historical shoulder comparison · piecewise C² release candidate", fontsize=19, y=0.978)
    figure.text(0.5, 0.943,
        rf"Join $s={JOIN:g}$ · shoulder rate $a={SHOULDER_RATE:g}$ · default pre-shoulder lift $\varepsilon=10\%$ · $k=U/B$",
        ha="center", fontsize=11, color="#444444")
    figure.legend(handles=[
        Line2D([], [], color="#333333", lw=2, label="Candidate (evaluation only)"),
        Line2D([], [], color="#333333", lw=1.5, ls="--", alpha=.7,
               label=f"Historical pole: p={RADIAL_POLE:g}, d={RADIAL_BOUNDARY_SLOPE:g}"),
    ], loc="upper center", bbox_to_anchor=(.5, .934), ncol=2, frameon=False)

    for case, k, color in zip(report["cases"], ratios, colors):
        label = f"Q{100 * case['quantile']:g}: k={k:.4g}"
        release_axis.plot(x, release_radius(x, k), color=color, lw=1.9, label=label)
        release_axis.plot(x, _release_radius(x, k), color=color, lw=1.1, ls="--", alpha=.6)
        slope_axis.plot(x, release_derivatives(x, k)[0], color=color, lw=1.9)
        slope_axis.plot(x, baseline_derivative(x, k), color=color, lw=1.1, ls="--", alpha=.6)
    release_axis.plot(x, x, color="#aaaaaa", lw=1, ls=":")
    release_axis.set(title="A   Release across sampled capacity ratios",
        xlabel=r"Spindle radius $x=C_{spindle}/B$",
        ylabel=r"Cube radius $R_k(x)=C_{cube}/B$", xlim=(0, 1.015), ylim=(0, largest * 1.04))
    release_axis.legend(loc="upper left", framealpha=.95, ncol=2, columnspacing=.8)
    slope_axis.set(title="B   Slope rises through the shoulder", yscale="log",
        xlabel=r"Spindle radius $x=C_{spindle}/B$",
        ylabel=r"Release slope $R'_k(x)$ · logarithmic scale", xlim=(0, 1.015))
    slope_axis.text(.03, .96, "Same capacity colors as A", transform=slope_axis.transAxes,
                    va="top", fontsize=9, color="#444444")
    for axis in (release_axis, slope_axis):
        axis.axvline(JOIN, color="#aaaaaa", lw=1, ls=":")
        axis.axvspan(.78, .82, color="#dfbb73", alpha=.17, zorder=0)

    inner_x = np.linspace(0, JOIN, 501)
    for lift, color in zip(INNER_LIFTS, LIFT_COLORS):
        values = release_radius(inner_x, largest, inner_lift=lift)
        relative = np.divide(values, inner_x, out=np.ones_like(values), where=inner_x > 0) - 1
        inner_axis.plot(inner_x, relative, color=color, lw=2.2,
                        label=rf"$\varepsilon={100 * lift:g}\%$")
    inner_axis.set(title=f"C   Pre-shoulder change · k={largest:.3g}",
        xlabel=r"Spindle radius $x=C_{spindle}/B$",
        ylabel=r"Release above identity $R_k(x)/x-1$",
        xlim=(0, JOIN * 1.025), ylim=(0, .27))
    inner_axis.yaxis.set_major_formatter(PercentFormatter(1))
    inner_axis.axvline(JOIN, color="#777777", lw=1, ls=":")
    inner_axis.legend(loc="upper left", framealpha=.95)
    inner_axis.text(.97, .06, rf"Join: $x={JOIN:g}$" + "\n" + r"Every curve: $R'_k(0)=1$",
        transform=inner_axis.transAxes, ha="right", fontsize=10, color="#444444",
        bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 3})

    remaining = np.geomspace(1, 1e-7, 1001)
    pole_colors = ("#466d94", "#d16c33", "#67954a", "#91609f")
    for pole, color in zip(POLES, pole_colors):
        exterior_x = pole - (pole - 1) * remaining
        pole_axis.plot(remaining, release_radius(exterior_x, largest, pole=pole) / largest,
                       color=color, lw=2, label=f"p={pole:g}")
    baseline_x = RADIAL_POLE - (RADIAL_POLE - 1) * remaining
    pole_axis.plot(remaining, _release_radius(baseline_x, largest) / largest,
                   color="#333333", ls="--", lw=1.5, alpha=.7)
    pole_axis.set(title="D   Pole continuation beyond the boundary", xscale="log", yscale="log",
        xlabel=r"Remaining fraction to pole $(p-x)/(p-1)$",
        ylabel=r"Released radius $R_k(x)/k$ · log scale", xlim=(1, 1e-7))
    pole_axis.legend(loc="upper left", framealpha=.95, ncol=2)
    pole_axis.text(.03, .06, "Boundary at left → pole at right\nPhysical range is identical for all four poles",
                   transform=pole_axis.transAxes, fontsize=9, color="#444444",
                   bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 3})

    cube_fraction = np.linspace(0, 1, 1201)
    for lift, color in zip(INNER_LIFTS, LIFT_COLORS):
        compress_axis.plot(cube_fraction, compress_radius(cube_fraction * largest, largest,
            inner_lift=lift), color=color, lw=2, label=rf"$\varepsilon={100 * lift:g}\%$")
    compress_axis.plot(cube_fraction, _compress_radius(cube_fraction * largest, largest),
                       color="#333333", ls="--", lw=1.7, label="Historical pole")
    for fraction in CUBE_FRACTIONS:
        value = float(compress_radius(fraction * largest, largest))
        compress_axis.scatter([fraction], [value], color=LIFT_COLORS[1], s=24, zorder=5)
        compress_axis.axvline(fraction, color="#999999", lw=.8, alpha=.5, ls=":")
    compress_axis.set(title=f"E   Cube → spindle placement · k={largest:.3g}",
        xlabel=r"Cube radius as capacity fraction $C_{cube}/U$",
        ylabel=r"Compressed radius $C_{spindle}/B$", xlim=(0, 1.015), ylim=(0, 1.025))
    compress_axis.legend(loc="lower right", framealpha=.95)
    compress_axis.text(.05, .18, "Higher placement leaves less radial\nroom before the spindle boundary.",
                      transform=compress_axis.transAxes, fontsize=9, color="#444444")

    capacity_grid = np.linspace(ratios.min(), ratios.max(), 501)
    for fraction, color in zip(CUBE_FRACTIONS, FRACTION_COLORS):
        candidate = 1 - compress_radius(fraction * capacity_grid, capacity_grid)
        baseline = 1 - _compress_radius(fraction * capacity_grid, capacity_grid)
        headroom_axis.plot(capacity_grid, candidate, color=color, lw=2,
                           label=f"{100 * fraction:g}% of cube capacity")
        headroom_axis.plot(capacity_grid, baseline, color=color, lw=1.4, ls="--", alpha=.75)
        headroom_axis.scatter(ratios, 1 - compress_radius(fraction * ratios, ratios),
                              color=color, s=14, zorder=5)
    headroom_axis.set(title="F   Remaining radial grading headroom", yscale="log",
        xlabel=r"Capacity ratio $k=U/B$",
        ylabel=r"Unused spindle radius $1-C_{spindle}/B$",
        xlim=(max(1.0, ratios.min() - .3), ratios.max() + .3))
    headroom_axis.yaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    headroom_axis.legend(loc="upper right", framealpha=.95)
    headroom_axis.text(.03, .055, "Dots: sampled capacity quantiles\nDefault candidate: ε = 10%", fontsize=9,
                       transform=headroom_axis.transAxes, color="#444444",
                       bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 3})

    for axis in axes.flat:
        axis.grid(True, which="major", color="#d9dde0", lw=.8, alpha=.85)
        axis.set_axisbelow(True)
        axis.tick_params(labelsize=9)
    figure.text(.5, .031,
        r"$B$: spindle capacity · $U$: cube capacity at the same $J_A$ and hue · "
        f"{report['source_capacity_samples']:,} source capacity samples · "
        f"{report['total_roundtrip_samples']:,} inverse checks\n"
        f"Maximum sampled inverse error: {report['roundtrip_max_absolute']:.2g} in normalized radius. "
        "Exterior curves are analytic continuations. The k=1 limit is identity, without a pole.",
        ha="center", va="center", fontsize=9, color="#444444")
    figure.subplots_adjust(left=.065, right=.978, bottom=.105, top=.864, hspace=.38, wspace=.32)
    figure.savefig(output_dir / "piecewise-spindle-comparison.png", dpi=180, facecolor="white",
                   metadata={"Title": "Historical piecewise C2 spindle release comparison"})
    plt.close(figure)


def write_summary(output_dir, report):
    lines = [
        "# Historical piecewise C² spindle release comparison", "",
        report["scope"] + ".", "",
        f"Join s={JOIN:g}; rational shoulder rate a={SHOULDER_RATE:g}. "
        "The lift settings 5%, 10%, and 25% cap the relative pre-shoulder release change; "
        "the actual change at the join is ε(1−1/k). "
        "Pole settings: " + ", ".join(f"{p:g}B" for p in POLES) + ".", "",
        "Physical release and compression are independent of the exterior pole location. "
        "The figure defaults to ε=10% and p=1.01B; this is a comparison setting, not an adoption decision.", "",
        "| k=U/B | Lift ε | Boundary slope | Compressed 0.5U / B | Compressed 0.9U / B | Compressed 0.99U / B |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        for variant in case["variants"]:
            values = variant["compressed_cube_fractions"]
            lines.append(f"| {case['k']:.6g} | {100 * variant['inner_lift']:g}% | "
                f"{variant['boundary_slope']:.7g} | {values['0.5']:.8f} | "
                f"{values['0.9']:.8f} | {values['0.99']:.8f} |")
    largest = max(report["cases"], key=lambda case: case["k"])
    selected = next(variant for variant in largest["variants"] if variant["inner_lift"] == DEFAULT_LIFT)
    previous = largest["baseline_compressed_cube_fractions"]["0.9"]
    proposed = selected["compressed_cube_fractions"]["0.9"]
    lines += ["", f"At the largest sampled k={largest['k']:.8g}, 0.9U maps to "
        f"{proposed:.8f}B with the default candidate, versus {previous:.8f}B for the historical pole map. "
        f"The remaining radial headroom is {100 * (1 - proposed):.3f}% versus "
        f"{100 * (1 - previous):.3f}% of B.", "",
        f"Checked {report['total_roundtrip_samples']:,} round trips across "
        f"{len(report['tested_capacity_ratios'])} capacity ratios (including the identity and near-identity limit), "
        "three inner-lift settings, and four poles.", "",
        f"Maximum sampled absolute inverse error: {report['roundtrip_max_absolute']:.8g}; "
        f"physical range: {report['physical_roundtrip_max_absolute']:.8g}. "
        f"Reverse (cube→spindle→cube) error as fraction of capacity U: "
        f"{report['cube_roundtrip_max_error_as_capacity_fraction']:.8g}. "
        f"Maximum physical release difference across pole settings: "
        f"{report['physical_pole_parameter_max_difference']:.8g}.", "",
        report["limitation"], "",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines))


def generate(output_dir, input_report):
    source = json.loads(input_report.read_text())
    report = measure(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    draw(output_dir, report)
    write_summary(output_dir, report)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    generate(arguments.output_dir, arguments.report)
