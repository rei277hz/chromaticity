"""Plot the historical spindle-to-cube pole experiment and its continuation."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from color_tools.perceptual_grade_reference.pole_spindle import (
    RADIAL_BOUNDARY_SLOPE,
    RADIAL_POLE,
    _release_radius,
)


def previous_release(x, k):
    """Previous p=1.01, F'(1)=6 curve for the visual comparison only."""
    z = x * x
    pole_squared = 10201 / 10000
    blend = 5 * (pole_squared - 1)
    denominator = pole_squared - z
    f = ((1 - blend) * (z + z * (1 - z)**2 / ((1 + z) * denominator))
         + blend * (pole_squared - 1) * z / denominator)
    return x * np.sqrt(1 + (k * k - 1) * f)


def generate(output_dir, report):
    data = json.loads(report.read_text())
    ratios = np.array([case["k"] for case in data["cases"]])
    shoulders = np.array([case["curvature_minimum_x"] for case in data["cases"]])
    shoulder_min, shoulder_max = shoulders.min(), shoulders.max()
    shoulder_label = f"{shoulder_min:.4f}–{shoulder_max:.4f}B"
    quantiles = data["capacity_quantiles"]
    colors = plt.get_cmap("viridis")(np.linspace(0.08, 0.88, len(ratios)))
    physical_x = np.linspace(0.0, 1.0, 1201)
    pole_gap = RADIAL_POLE - 1.0
    continuation_x = np.unique(np.r_[
        1.0, RADIAL_POLE - np.geomspace(pole_gap * 1e-6, pole_gap, 1400)
    ])
    boundary_slope = (rf"$R_k'(1)={1 + RADIAL_BOUNDARY_SLOPE:g}k"
                      rf"-{RADIAL_BOUNDARY_SLOPE:g}/k$")

    figure, (physical_axis, pole_axis) = plt.subplots(
        1, 2, figsize=(13.5, 7.0), gridspec_kw={"width_ratios": [1.35, 1.0]}
    )
    figure.suptitle("Spindle → cube: historical pole experiment", fontsize=17, y=0.97)
    for quantile, ratio, color in zip(quantiles, ratios, colors):
        label = f"Q{100 * quantile:g}: k={ratio:.4g}"
        physical_axis.plot(physical_x, _release_radius(physical_x, ratio),
                           color=color, linewidth=2.0, label=label)
        physical_axis.plot(physical_x, previous_release(physical_x, ratio),
                           color=color, linewidth=1.1, alpha=0.45, linestyle=":")
        physical_axis.scatter([1.0], [ratio], color=[color], s=26, zorder=4)
        pole_axis.plot(continuation_x, _release_radius(continuation_x, ratio),
                       color=color, linewidth=1.8, linestyle=(0, (5, 3)))
        pole_axis.scatter([1.0], [ratio], color=[color], s=26, zorder=4)

    physical_axis.axvspan(shoulder_min, shoulder_max, color="#d9ad50", alpha=0.25)
    physical_axis.axvline(shoulders.mean(), color="#a36e09", linewidth=1.1,
                         linestyle=(0, (2, 3)))
    physical_axis.axvline(1.0, color="#333333", linewidth=1.15, linestyle="--")
    physical_axis.text(shoulder_min - 0.015, 0.98,
                       f"Curvature shoulder: {shoulder_label}\n(no piecewise join)",
                       transform=physical_axis.get_xaxis_transform(),
                       ha="right", va="top", fontsize=9, color="#79540e")
    physical_axis.text(0.99, 0.04, "spindle boundary B", rotation=90,
                       transform=physical_axis.get_xaxis_transform(),
                       ha="right", va="bottom", fontsize=9, color="#333333")
    physical_axis.set(xlim=(0.0, 1.04), ylim=(0.0, 1.06 * max(ratios)),
                      xlabel=r"Spindle radius $x=C_{spindle}/B$",
                      ylabel=r"Released cube radius $R_k(x)=C_{cube}/B$",
                      title="Physical range · linear axes")
    physical_axis.set_xticks(np.arange(0.0, 1.01, 0.2))
    physical_axis.legend(loc="upper left", framealpha=0.96, fontsize=8.5)
    physical_axis.text(0.04, 0.49, r"All curves: $R_k'(0)=1$" + "\n"
                       + r"Boundary: $R_k(1)=k$" + "\n"
                       + "Historical slope: " + boundary_slope,
                       transform=physical_axis.transAxes,
                       fontsize=10, va="top")

    pole_axis.axvspan(1.0, RADIAL_POLE, color="#d8e5ed", alpha=0.30, zorder=0)
    pole_axis.axvline(1.0, color="#333333", linewidth=1.15, linestyle="--",
                      label="physical boundary $x=1$")
    pole_axis.axvline(RADIAL_POLE, color="#a52b2b", linewidth=1.2, linestyle=":",
                      label=rf"pole $p={RADIAL_POLE:g}$")
    pole_axis.set_yscale("log")
    continuation_max = _release_radius(continuation_x[-1], max(ratios))
    pole_axis.set(xlim=(1.0 - 0.1 * pole_gap, RADIAL_POLE + 0.1 * pole_gap),
                  ylim=(0.9, 1.2 * continuation_max),
                  xlabel=r"Spindle radius $x=C_{spindle}/B$",
                  ylabel=r"Analytic release $R_k(x)=C_{cube}/B$",
                  title="Analytic continuation · logarithmic y-axis")
    pole_axis.set_xticks(np.linspace(1.0, RADIAL_POLE, 6))
    pole_axis.ticklabel_format(axis="x", style="plain", useOffset=False)
    pole_axis.legend(loc="upper left", framealpha=0.96, fontsize=9)
    for axis in (physical_axis, pole_axis):
        axis.grid(True, which="major", color="#d8d8d8", linewidth=0.8, alpha=0.8)
        axis.set_axisbelow(True)

    figure.text(
        0.5, 0.015,
        r"$B$: spindle capacity; $U$: cube capacity at the same $J_A$ and hue. "
        r"Colors: quantiles of $k=U/B$ across " + f"{data['capacity_samples']:,} samples.\n"
        rf"Solid: historical $p={RADIAL_POLE:g}$, $d={RADIAL_BOUNDARY_SLOPE:g}$. "
        r"Faint dotted: previous $p=1.01$, $d=6$. "
        r"Dashed: analytic continuation; physical release clamps at $B$." + "\n"
        rf"Pole: $x\to{RADIAL_POLE:g}^-$ for $k>1$. "
        f"Shoulder band: outer curvature minima across the {len(ratios)} plotted quantiles. "
        r"The special case $k=1$ is the identity and has no pole.",
        ha="center", va="bottom", fontsize=9,
    )
    figure.subplots_adjust(left=0.07, right=0.98, bottom=0.19, top=0.88, wspace=0.28)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_dir / "spindle-release-curve.png", dpi=170, facecolor="white",
                   metadata={"Title": "Historical spindle-to-cube pole experiment"})
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output_dir, args.report)
