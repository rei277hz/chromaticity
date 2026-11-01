"""Retain historical crossover studies and check the current J_A/C drivers."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import numpy as np

from color_tools.perceptual_grade_core.model import lut as production_lut
from color_tools.perceptual_grade_reference.grading import CHROMA_CROSSOVER, drivers as reference_drivers
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.spindle import context as historical_context


CROSSOVERS = ((1.0 / 3.0, "1/3", "1-3"), (0.4, "0.4", "0p4"))
VISIBILITIES = ((0.25, "0p25"), (1.0, "1"), (4.0, "4"), (16.0, "16"))
CROSSOVER_COMPARISON = ((0.3, "0.3", "0p3"), (1.0 / 3.0, "1/3", "1-3"))
RAW_CAPACITY_CROSSOVERS = ((0.3, "0p3"), (0.4, "0p4"), (0.5, "0p5"))
GAMUTS = ("Rec.709", "Rec.2020")
EXPECTED_COUNTS = {"Rec.709": 22164, "Rec.2020": 93118}
CONTOURS = (0.1, 0.5, 0.9)
JA_LINEAR_THRESHOLD = 1.0
C_LINEAR_THRESHOLD = 0.25
JA_TICKS = (0.0, 1.0, 10.0, 100.0, 1000.0)
C_TICKS = (0.0, 0.25, 1.0, 4.0, 16.0, 64.0, 256.0)
COLOR_NORMALIZATION = Normalize(vmin=0.0, vmax=1.0)
LEGACY_CROSSOVER = .3
LEGACY_CAPACITY_FRACTION = .4


@dataclass(frozen=True)
class Samples:
    ja: np.ndarray
    chroma: np.ndarray
    masks: dict
    counts: dict
    union: np.ndarray
    x_limit: float
    y_limit: float


def require(condition, message):
    if not condition:
        raise ValueError(message)


def driver_weights(ja, chroma, crossover, visibility):
    """Evaluate L=V(1-m), H=Vm, with both drivers zero at neutral/black."""
    ja, chroma = np.broadcast_arrays(np.asarray(ja, dtype=float),
                                     np.asarray(chroma, dtype=float))
    radius = crossover * np.abs(ja)
    scale = np.maximum(chroma, radius)
    a = np.divide(chroma, scale, out=np.zeros_like(chroma), where=scale > 0.0)
    b = np.divide(radius, scale, out=np.zeros_like(chroma), where=scale > 0.0)
    denominator = a * a + b * b
    high_membership = np.divide(a * a, denominator, out=np.zeros_like(chroma),
                                where=denominator > 0.0)
    low_membership = np.divide(b * b, denominator, out=np.zeros_like(chroma),
                               where=denominator > 0.0)
    visible = (chroma / np.hypot(chroma, np.sqrt(visibility))) ** 2
    return visible * low_membership, visible * high_membership, visible


def production_samples():
    """Compress the actual shaper lattice once, retaining every nonnegative RGB."""
    require(production_lut.SIZE == 65 and production_lut.KAPPA == 0.01
            and production_lut.SPACE == "ACEScg", "Unexpected production LUT contract")
    lattice = np.asarray(production_lut.lattice(), dtype=float)
    require(lattice.shape == (65 ** 3, 3) and np.all(lattice >= 0.0),
            "Expected a nonnegative production 65-cube")
    models = {gamut: Model(space=f"Linear {gamut}") for gamut in GAMUTS}
    model = models["Rec.709"]
    require(np.allclose(production_lut.FROM_LUT, np.linalg.inv(model.to_acescg),
                        rtol=2e-12, atol=2e-12), "Production Rec.709 adapter differs")
    masks, counts = {}, {}
    input_nits = (lattice @ model.acescg_y) * model.tone.reference
    for gamut, source in models.items():
        rgb = lattice @ np.linalg.inv(source.to_acescg).T
        masks[gamut] = np.all(rgb >= 0.0, axis=-1)
        count = int(np.count_nonzero(masks[gamut]))
        require(count == EXPECTED_COUNTS[gamut], f"Unexpected {gamut} sample count: {count}")
        counts[gamut] = dict(
            samples=count,
            channel_above_1024=int(np.count_nonzero(np.any(rgb[masks[gamut]] > 1024.0, axis=-1))),
            input_luminance_above_10000_nits=int(np.count_nonzero(
                masks[gamut] & (input_nits > 10000.0))),
        )
    require(np.all(~masks["Rec.709"] | masks["Rec.2020"]),
            "Rec.709 sample subset is not contained in Rec.2020")
    # Preserve this retired experiment explicitly; Model entry is now raw.
    source = model.enter_native(lattice)
    context = historical_context(model.fl, model.aw, model.native_matrix)
    compressed, energy = context.compress(source.q, source.energy)
    from color_tools.perceptual_grade_reference.responses import State
    state = State(compressed, energy)
    model._historical_boundary = context
    ja = np.asarray(state.ja, dtype=float)
    chroma = np.hypot(state.q[:, 1], state.q[:, 2])
    require(np.isfinite(ja).all() and np.isfinite(chroma).all()
            and np.all(ja >= 0.0) and np.all(chroma >= 0.0),
            "Compressed appearance coordinates are invalid")
    require(np.all(chroma <= context.body(ja) * (1.0 + 2e-12) + 2e-12),
            "Compressed lattice exceeds the AP1 spindle")
    neutral = np.all(lattice == lattice[:, :1], axis=-1)
    require(np.count_nonzero(neutral) == 65 and np.all(chroma[neutral] == 0.0),
            "Neutral production vertices changed chroma")
    union = masks["Rec.709"] | masks["Rec.2020"]
    samples = Samples(ja, chroma, masks, counts, union,
                      100.0 * np.ceil(float(np.max(ja)) / 100.0),
                      50.0 * np.ceil(float(np.max(chroma)) / 50.0))
    # The plotted compressed experiments keep their historical ratios. Check
    # the current reference equation separately on this same coordinate set.
    low, high, _ = driver_weights(ja, chroma, CHROMA_CROSSOVER, 4.0)
    actual = reference_drivers(state.q, ja)[:, :2]
    reference_error = float(np.max(np.abs(np.column_stack((low, high)) - actual)))
    require(np.allclose(np.column_stack((low, high)), actual, rtol=2e-14, atol=2e-14),
            'Current reference drivers differ from the J_A/C equation')
    return model, samples, dict(reference_crossover=CHROMA_CROSSOVER, reference_visibility=4.0,
                               reference_driver_coordinates='Historical compressed samples; equation check only',
                               reference_driver_max_absolute_error=reference_error,
                               reference_driver_samples=int(len(lattice)),
                               neutral_vertices=int(np.count_nonzero(neutral)),
                               rec709_subset_of_rec2020=True)


def response_grid(model, samples):
    """Dense analytic response guides, clipped to the AP1 spindle only."""
    ja = np.unique(np.r_[np.linspace(0.0, 1.0, 25),
                        np.geomspace(1.0, model.boundary.white, 480)])
    chroma = np.unique(np.r_[np.linspace(0.0, 0.25, 25),
                            np.geomspace(0.25, samples.y_limit, 420)])
    x, y = np.meshgrid(ja, chroma)
    outside = y > model._historical_boundary.body(ja)[None, :]
    return x, y, outside


def response_group(samples, crossover, visibility):
    low, high, visible = driver_weights(samples.ja, samples.chroma, crossover, visibility)
    complement_error = float(np.max(np.abs(low + high - visible)))
    require(complement_error <= 4e-16, "Low/high responses do not sum to visibility")
    require(np.isfinite(low).all() and np.isfinite(high).all()
            and np.all(low >= 0.0) and np.all(high >= 0.0)
            and np.all(low <= 1.0) and np.all(high <= 1.0), "Invalid driver responses")
    neutral = samples.chroma == 0.0
    require(np.all(low[neutral] == 0.0) and np.all(high[neutral] == 0.0),
            "A neutral sample has nonzero chroma-driver response")
    check_ja = np.array((1e-12, 0.1, 1.0, 100.0, 1000.0))
    equal_low, equal_high, equal_visible = driver_weights(
        check_ja, crossover * check_ja, crossover, visibility)
    require(np.array_equal(equal_low, equal_high)
            and np.allclose(equal_low, 0.5 * equal_visible, rtol=2e-15, atol=0.0),
            "Driver equality does not lie on the selected crossover")
    normalizers = [float(np.max(values[samples.union])) for values in (low, high)]
    require(all(value > 0.0 for value in normalizers), "Driver normalization is zero")
    relative = [values / maximum for values, maximum in zip((low, high), normalizers)]
    for values in relative:
        require(np.isfinite(values[samples.union]).all()
                and np.all((values[samples.union] >= 0.0) & (values[samples.union] <= 1.0)),
                "Relative response is outside the displayed 0..1 range")
    statistics = {}
    for gamut in GAMUTS:
        mask = samples.masks[gamut]
        statistics[gamut] = dict(samples=samples.counts[gamut]["samples"],
                                 low_max=float(np.max(low[mask])),
                                 high_max=float(np.max(high[mask])),
                                 relative_low_max=float(np.max(relative[0][mask])),
                                 relative_high_max=float(np.max(relative[1][mask])))
    return relative, normalizers, dict(
        crossover=crossover, visibility=visibility,
        normalizers=dict(low=normalizers[0], high=normalizers[1]),
        gamuts=statistics, complement_max_absolute_error=complement_error,
        crossover_equality=True, neutral_zero=True, finite_relative_range_0_1=True,
    )


def draw_group(figure, axes, model, samples, grid, crossover, crossover_label,
               visibility, relative, normalizers, compact=False):
    """Draw one 2x2 group; normalize each driver across both gamut populations."""
    x, y, outside = grid
    grid_drivers = driver_weights(x, y, crossover, visibility)[:2]
    label_size = 6.5 if compact else 8.5
    for row, gamut in enumerate(GAMUTS):
        mask = samples.masks[gamut]
        for column, name in enumerate(("Low", "High")):
            axis = axes[row, column]
            axis.set_xscale("symlog", linthresh=JA_LINEAR_THRESHOLD, linscale=1.0, base=10)
            axis.set_yscale("symlog", linthresh=C_LINEAR_THRESHOLD, linscale=1.0, base=10)
            axis.scatter(samples.ja[mask], samples.chroma[mask], c=relative[column][mask],
                         cmap="viridis", norm=COLOR_NORMALIZATION,
                         s=1.4 if compact else 3.0, alpha=1.0, linewidths=0.0,
                         edgecolors="none", rasterized=True, zorder=2)
            values = np.ma.array(grid_drivers[column] / normalizers[column], mask=outside)
            contours = axis.contour(x, y, values, levels=CONTOURS, colors="#374151",
                                    linewidths=0.45 if compact else 0.65, zorder=3)
            axis.clabel(contours, inline=True, fontsize=5.5 if compact else 7.0,
                        fmt={0.1: "10%", 0.5: "50%", 0.9: "90%"})
            axis.set_xlim(0.0, samples.x_limit)
            axis.set_ylim(0.0, samples.y_limit)
            axis.set_xticks(JA_TICKS, labels=[f"{value:g}" for value in JA_TICKS])
            axis.set_yticks(C_TICKS, labels=[f"{value:g}" for value in C_TICKS])
            axis.minorticks_off()
            axis.tick_params(labelsize=label_size)
            axis.set_title(f"{gamut} · {name} driver", fontsize=8 if compact else 12)
            if row == 1:
                axis.set_xlabel("Compressed $J_A$", fontsize=label_size)
            if column == 0:
                axis.set_ylabel("Compressed $C$", fontsize=label_size)
            axis.text(
                0.035, 0.975,
                f"k={crossover_label}, v={visibility:g} · N={np.count_nonzero(mask):,}\n"
                f"shared {name.lower()} maximum={normalizers[column]:.6f}",
                transform=axis.transAxes, va="top", ha="left",
                fontsize=5.8 if compact else 8,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.92, pad=2),
                zorder=5,
            )
            axis.set_facecolor("#f8fafc")
            axis.grid(True, color="#d1d5db", linewidth=0.5, alpha=0.55, zorder=0)


def add_colorbar(figure, axes, compact=False):
    colorbar = figure.colorbar(ScalarMappable(norm=COLOR_NORMALIZATION, cmap="viridis"),
                              ax=list(axes.flat), fraction=0.032, pad=0.025,
                              ticks=(0.0, 0.1, 0.5, 0.9, 1.0), shrink=0.95)
    colorbar.set_label("Response / driver maximum across both gamuts",
                       fontsize=7 if compact else 10)
    colorbar.ax.tick_params(labelsize=6.5 if compact else 9)


@dataclass(frozen=True)
class RawSamples:
    ja: np.ndarray
    chroma: np.ndarray
    hue: np.ndarray
    capacity: np.ndarray
    input_nits: np.ndarray
    masks: dict
    counts: dict
    union: np.ndarray
    neutral: np.ndarray
    x_limit: float
    y_limit: float


def radius_driver_weights(chroma, radius, visibility=4.0):
    """Stable per-point crossover weights, including zero-radius neutral tips."""
    chroma, radius = np.broadcast_arrays(np.asarray(chroma, dtype=float),
                                        np.asarray(radius, dtype=float))
    require(np.isfinite(chroma).all() and np.isfinite(radius).all()
            and np.all(chroma >= 0.0) and np.all(radius >= 0.0),
            "Invalid chroma or crossover radius")
    scale = np.maximum(chroma, radius)
    a = np.divide(chroma, scale, out=np.zeros_like(chroma), where=scale > 0.0)
    b = np.divide(radius, scale, out=np.zeros_like(chroma), where=scale > 0.0)
    denominator = a * a + b * b
    membership = np.divide(a * a, denominator, out=np.zeros_like(chroma),
                           where=denominator > 0.0)
    low_membership = np.divide(b * b, denominator, out=np.zeros_like(chroma),
                               where=denominator > 0.0)
    visible = (chroma / np.hypot(chroma, np.sqrt(visibility))) ** 2
    low, high = visible * low_membership, visible * membership
    require(np.max(np.abs(low + high - visible)) <= 4e-16,
            "Capacity drivers do not sum to visibility")
    require(np.all((low >= 0.0) & (low <= 1.0))
            and np.all((high >= 0.0) & (high <= 1.0))
            and np.isfinite(low).all() and np.isfinite(high).all(),
            "Capacity driver response is outside 0..1")
    return low, high, visible, membership


def raw_production_samples():
    """Reuse subset contracts, then encode without historical compression."""
    from color_tools.perceptual_grade_reference.export import input_repair

    model, compressed, validations = production_samples()
    lattice = np.asarray(production_lut.lattice(), dtype=float)
    native = input_repair(lattice, model.acescg_y)
    require(np.array_equal(native, lattice), "Production AP1 lattice required input repair")
    inverse = np.linalg.inv(model.boundary.matrix)
    cones = native[:, 1, None] + np.einsum('ij,...j->...i', inverse,
                                          native - native[:, 1, None])
    source = model.encode_cones(cones)
    ja = np.asarray(source.ja, dtype=float)
    chroma = np.hypot(source.q[:, 1], source.q[:, 2])
    hue = np.arctan2(source.q[:, 2], source.q[:, 1])
    input_nits = (lattice @ model.acescg_y) * model.tone.reference
    require(np.isfinite(source.q).all() and np.isfinite(ja).all()
            and np.isfinite(input_nits).all() and np.all(input_nits >= 0.0)
            and np.all(ja >= 0.0) and np.all(ja <= model.boundary.white),
            "Invalid raw production appearance coordinates")
    require(np.allclose(ja, compressed.ja, rtol=2e-12, atol=2e-12),
            "Historical compression changed achromatic lightness")
    require(np.all(chroma + 2e-12 >= compressed.chroma),
            "Historical compression increased raw chroma")
    neutral = np.all(lattice == lattice[:, :1], axis=-1)
    require(np.count_nonzero(neutral) == 65 and np.array_equal(chroma == 0.0, neutral),
            "Raw encoding did not preserve exactly the 65 neutral vertices")
    interior = (ja > 0.0) & (ja < model.boundary.white)
    require(np.all(neutral | interior), "A chromatic sample lies at a neutral tip")
    capacity = np.zeros_like(chroma)
    capacity[interior] = model.boundary.capacity(ja[interior], hue[interior])
    require(np.isfinite(capacity).all() and np.all(capacity[interior] > 0.0),
            "Invalid fitted AP1 cube capacity")
    samples = RawSamples(ja, chroma, hue, capacity, input_nits, compressed.masks,
                         compressed.counts, compressed.union, neutral,
                         compressed.x_limit,
                         50.0 * np.ceil(float(np.max(chroma)) / 50.0))
    baseline = radius_driver_weights(compressed.chroma,
                                    LEGACY_CROSSOVER * np.abs(compressed.ja))
    check_low, check_high, check_visible = driver_weights(
        compressed.ja, compressed.chroma, LEGACY_CROSSOVER, 4.0)
    require(all(np.array_equal(actual, expected) for actual, expected in
                zip(baseline[:3], (check_low, check_high, check_visible))),
            "Historical compressed baseline differs from existing diagnostic")
    active_error = float(np.max(np.abs(
        reference_drivers(source.q, ja)[:, :2]-np.column_stack(
            radius_driver_weights(chroma, CHROMA_CROSSOVER*np.abs(ja))[:2]))))
    require(np.isfinite(active_error) and active_error <= 2e-14,
            'Active reference drivers differ from the raw J_A/C equation')
    validations.update(
        raw_neutral_vertices=int(np.count_nonzero(neutral)),
        raw_ja_matches_compressed=True,
        raw_encoding="Neutral-centered AP1-to-cones transform, then Model.encode_cones; no compression",
        raw_chroma_not_smaller_than_compressed=True,
        interior_capacity_positive=True,
        capacity_neutral_hue_convention="atan2(0,0)=0; neutral tips have zero capacity",
        baseline_matches_existing_diagnostic_exactly=True,
        active_reference_crossover=CHROMA_CROSSOVER,
        active_reference_max_absolute_error=active_error,
    )
    return model, samples, compressed, baseline, validations


def distribution(values):
    """Finite empirical quantiles; no density or image-frequency inference."""
    values = np.asarray(values, dtype=float)
    require(len(values) > 0 and np.isfinite(values).all(), "Invalid distribution population")
    levels = (0, 1, 10, 25, 50, 75, 90, 99, 100)
    return dict(samples=int(len(values)),
                quantiles={f"p{level}": float(value) for level, value in
                           zip(levels, np.percentile(values, levels))})


def normalised_responses(values, union):
    maxima = [float(np.max(value[union])) for value in values[:2]]
    require(all(np.isfinite(maximum) and maximum > 0.0 for maximum in maxima),
            "Invalid driver normalization")
    relative = [value / maximum for value, maximum in zip(values[:2], maxima)]
    require(all(np.all((value[union] >= 0.0) & (value[union] <= 1.0))
                for value in relative), "Relative driver response is outside 0..1")
    return relative, maxima


def response_differences(actual, baseline, mask):
    delta = actual[mask] - baseline[mask]
    return dict(mean_signed=float(np.mean(delta)),
                mean_absolute=float(np.mean(np.abs(delta))),
                root_mean_square=float(np.sqrt(np.mean(delta * delta))),
                maximum_absolute=float(np.max(np.abs(delta))))


def raw_population_statistics(samples, mask, values, relative, crossover_radius,
                              baseline=None, baseline_relative=None):
    low, high, visible, membership = values
    count = int(np.count_nonzero(mask))
    require(count > 0, "Empty calibration population")
    chromatic = mask & ~samples.neutral
    groups = dict(
        neutral=int(np.count_nonzero(mask & samples.neutral)),
        low=int(np.count_nonzero(chromatic & (membership < 0.4))),
        transition=int(np.count_nonzero(chromatic & (membership >= 0.4)
                                        & (membership <= 0.6))),
        high=int(np.count_nonzero(chromatic & (membership > 0.6))),
    )
    require(sum(groups.values()) == count, "Membership groups do not partition population")
    require(np.all(crossover_radius[chromatic] > 0.0),
            "Chromatic sample has zero crossover radius")
    cube_relative = samples.chroma[chromatic] / samples.capacity[chromatic]
    crossover_relative = samples.chroma[chromatic] / crossover_radius[chromatic]
    result = dict(
        samples=count, groups=groups,
        group_fractions={name: value / count for name, value in groups.items()},
        chromatic_group_fractions={name: groups[name] / int(np.count_nonzero(chromatic))
                                   for name in ('low', 'transition', 'high')},
        high_membership=distribution(membership[chromatic]),
        raw_cube_relative_radius=distribution(cube_relative),
        raw_chroma_over_crossover_radius=distribution(crossover_relative),
        drivers={}, visibility=distribution(visible[mask]),
    )
    for name, value, response in zip(('low', 'high'), (low, high), relative):
        result['drivers'][name] = dict(
            maximum=float(np.max(value[mask])),
            relative_maximum=float(np.max(response[mask])),
            response=distribution(value[mask]), relative_response=distribution(response[mask]),
            response_above={f"{int(100 * threshold)}%":
                            int(np.count_nonzero(value[mask] > threshold))
                            for threshold in CONTOURS},
            relative_response_above={f"{int(100 * threshold)}%":
                                     int(np.count_nonzero(response[mask] > threshold))
                                     for threshold in CONTOURS},
        )
    if baseline is not None:
        result['difference_from_compressed_baseline'] = {
            name: response_differences(actual, old, mask)
            for name, actual, old in zip(('low', 'high', 'visibility', 'high_membership'),
                                        values, baseline)}
        result['difference_from_compressed_baseline'].update({
            f'relative_{name}': response_differences(actual, old, mask)
            for name, actual, old in zip(('low', 'high'), relative, baseline_relative)})
    return result


def population_masks(samples):
    return {gamut: {'all_luminances': mask,
                    'at_or_below_10000_nits': mask & (samples.input_nits <= 10000.0)}
            for gamut, mask in samples.masks.items()}


def capacity_excess_statistics(samples, mask):
    excess = np.maximum(samples.chroma - samples.capacity, 0.0)
    tolerance = np.maximum(1e-8, 1e-6 * samples.capacity)
    chromatic = mask & ~samples.neutral
    return dict(samples=int(np.count_nonzero(mask)),
                positive_excess_samples=int(np.count_nonzero(mask & (excess > 0.0))),
                excess_above_tolerance_samples=int(np.count_nonzero(mask & (excess > tolerance))),
                maximum_absolute_excess=float(np.max(excess[mask])),
                maximum_relative_excess=float(np.max(excess[chromatic]
                                                      / samples.capacity[chromatic])),
                cube_relative_radius=distribution(samples.chroma[chromatic]
                                                   / samples.capacity[chromatic]))


def oracle_capacity_spotcheck(model, samples):
    """Independent offline cube oracle; fit errors are measurements, not repairs."""
    from tools.build.boundary_oracle import capacity_unit
    from color_tools.perceptual_grade_reference.responses import GAMMA
    from color_tools.perceptual_grade_reference.spindle import white_response

    context = model.boundary
    rw = white_response(context.fl)
    tip_heights = np.geomspace(1e-9, 0.02, 9)
    heights = np.unique(np.r_[0.0, tip_heights, np.linspace(0.02, 0.98, 25),
                              1.0 - tip_heights, 1.0])
    angles = np.deg2rad(np.r_[np.arange(0.0, 360.0, 5.0), 1e-7, 360.0 - 1e-7])
    t, hue = np.meshgrid(heights, angles, indexing='ij')
    t, hue = t.ravel(), hue.ravel()
    grid_samples = len(t)
    selector = context.lookup.selector
    edges = np.arange(len(selector.edges))
    crease_t = np.mean(selector.vertices[selector.edges], axis=-1)
    crease_hue = selector.curve(crease_t, edges, 0)
    t = np.r_[t, np.repeat(crease_t, 3)]
    hue = np.r_[hue, (crease_hue[:, None] + np.array((-1e-6, 0.0, 1e-6))).ravel()]
    fitted_unit = context.unit(t, hue)
    oracle_unit = capacity_unit(t, hue, context.fl, context.aw, context.matrix)
    factor = rw * t * (1.0 - t)
    fitted_capacity = factor * fitted_unit
    oracle_capacity = factor * oracle_unit
    require(np.isfinite(oracle_unit).all() and np.all(oracle_unit > 0.0)
            and np.isfinite(fitted_unit).all() and np.all(fitted_unit > 0.0),
            'Invalid capacity oracle sweep')

    def comparison(fitted, exact):
        delta = fitted - exact
        ratio = delta[exact > 0.0] / exact[exact > 0.0]
        return dict(samples=int(len(delta)),
                    mean_absolute_error=float(np.mean(np.abs(delta))),
                    maximum_absolute_error=float(np.max(np.abs(delta))),
                    maximum_relative_error=float(np.max(np.abs(ratio))),
                    signed_error=distribution(delta), signed_relative_error=distribution(ratio))

    sweep = dict(
        samples=int(len(t)), grid_samples=int(grid_samples), crease_samples=int(3 * len(edges)),
        response_heights=heights.tolist(), hue_degrees=np.rad2deg(angles).tolist(),
        crease_probes='Each cached edge at its response-height midpoint and hue offsets -1e-6,0,+1e-6 radians',
        unit=comparison(fitted_unit, oracle_unit),
        physical_capacity=comparison(fitted_capacity, oracle_capacity),
    )
    worst = np.unique(np.r_[np.argmax(np.abs(fitted_unit / oracle_unit - 1.0)),
                            np.argmax(np.abs(fitted_capacity - oracle_capacity)),
                            np.argmax(fitted_capacity - oracle_capacity),
                            np.argmin(fitted_capacity - oracle_capacity)])
    sweep['worst_witnesses'] = [dict(
        response_height=float(t[index]), ja=float(context.white * t[index] ** GAMMA),
        hue_degrees=float(np.rad2deg(hue[index])), fitted_unit=float(fitted_unit[index]),
        oracle_unit=float(oracle_unit[index]), fitted_capacity=float(fitted_capacity[index]),
        oracle_capacity=float(oracle_capacity[index])) for index in worst]

    chromatic_ids = np.flatnonzero(~samples.neutral)
    response_height = (samples.ja / context.white) ** (1.0 / GAMMA)
    excess = np.maximum(samples.chroma - samples.capacity, 0.0)
    radius_ratio = samples.chroma[chromatic_ids] / samples.capacity[chromatic_ids]
    tip_order = np.argsort(response_height[chromatic_ids], kind='stable')
    selections = dict(
        largest_fitted_capacity_excess=chromatic_ids[
            np.argsort(-excess[chromatic_ids], kind='stable')[:24]],
        largest_raw_cube_relative_radius=chromatic_ids[
            np.argsort(-radius_ratio, kind='stable')[:24]],
        nearest_black_tip=chromatic_ids[tip_order[:16]],
        nearest_white_tip=chromatic_ids[tip_order[-16:]],
    )
    ids = np.unique(np.concatenate(list(selections.values())))
    physical_oracle = rw * response_height[ids] * (1.0 - response_height[ids]) * capacity_unit(
        response_height[ids], samples.hue[ids], context.fl, context.aw, context.matrix)
    require(np.isfinite(physical_oracle).all() and np.all(physical_oracle > 0.0),
            'Invalid actual-lattice capacity oracle')
    lattice = np.asarray(production_lut.lattice(), dtype=float)
    witnesses = [dict(
        lattice_index=int(index), ap1_rgb=lattice[index].tolist(),
        selected_by=[name for name, selection in selections.items() if index in selection],
        response_height=float(response_height[index]), ja=float(samples.ja[index]),
        hue_degrees=float(np.rad2deg(samples.hue[index]) % 360.0),
        raw_chroma=float(samples.chroma[index]), input_nits=float(samples.input_nits[index]),
        fitted_capacity=float(samples.capacity[index]), oracle_capacity=float(exact),
        raw_minus_fitted=float(samples.chroma[index] - samples.capacity[index]),
        raw_minus_oracle=float(samples.chroma[index] - exact),
        in_rec709=bool(samples.masks['Rec.709'][index]),
        in_rec2020=bool(samples.masks['Rec.2020'][index]))
        for index, exact in zip(ids, physical_oracle)]
    return dict(
        method='Independent capacity_unit float64 cube-face ray oracle, offline bisection only',
        policy='Fit errors and raw boundary excess are reported without clipping or containment assertions',
        sweep=sweep,
        actual_lattice=dict(samples=int(len(ids)),
                           selection='Stable index-ranked excess, relative-radius and near-tip witnesses',
                           capacity=comparison(samples.capacity[ids], physical_oracle),
                           witnesses=witnesses),
    )


def draw_raw_capacity_group(figure, axes, samples, rho, relative, maxima, compact=False):
    """Actual raw points carry hue-dependent responses; no universal contours."""
    size = 7 if compact else 8.5
    for row, gamut in enumerate(GAMUTS):
        mask = samples.masks[gamut]
        for column, name in enumerate(('Low', 'High')):
            axis = axes[row, column]
            axis.set_xscale('symlog', linthresh=JA_LINEAR_THRESHOLD, linscale=1.0, base=10)
            axis.set_yscale('symlog', linthresh=C_LINEAR_THRESHOLD, linscale=1.0, base=10)
            axis.scatter(samples.ja[mask], samples.chroma[mask], c=relative[column][mask],
                         cmap='viridis', norm=COLOR_NORMALIZATION,
                         s=1.4 if compact else 3.0, alpha=1.0, linewidths=0.0,
                         edgecolors='none', rasterized=True, zorder=2)
            axis.set_xticks(JA_TICKS, labels=[f'{value:g}' for value in JA_TICKS])
            ticks = (*C_TICKS, 1000.0)
            axis.set_yticks(ticks, labels=[f'{value:g}' for value in ticks])
            axis.set_xlim(0.0, samples.x_limit)
            axis.set_ylim(0.0, samples.y_limit)
            axis.minorticks_off()
            axis.tick_params(labelsize=size)
            axis.set_title(f'{gamut} · {name} driver', fontsize=10 if compact else 12)
            if row == 1:
                axis.set_xlabel('Raw $J_A$', fontsize=size)
            if column == 0:
                axis.set_ylabel('Raw $C$', fontsize=size)
            design_label = 'Baseline · k=0.3, v=4' if rho is None else f'ρ={rho:g}, v=4'
            axis.text(0.035, 0.975,
                      f'{design_label} · N={np.count_nonzero(mask):,}\n'
                      f'shared {name.lower()} maximum={maxima[column]:.6f}',
                      transform=axis.transAxes, va='top', ha='left',
                      fontsize=6.5 if compact else 8,
                      bbox=dict(facecolor='white', edgecolor='none', alpha=0.92, pad=2),
                      zorder=5)
            axis.set_facecolor('#f8fafc')
            axis.grid(True, color='#d1d5db', linewidth=0.5, alpha=0.55, zorder=0)


def calibration_summary(report):
    lines = [
        '# Historical raw-capacity crossover calibration', '',
        'The retained production law uses ρ=0.4; ρ=0.3/0.5 are historical comparison candidates. '
        'The analytic reference now uses r=(35/75)|J_A| and does not use capacity for membership.', '',
        'Candidates use raw modCAM16 C, r=ρU(J_A,h), V=C²/(C²+4), '
        'm=C²/(C²+r²), low=V(1−m), high=Vm. U is the current fitted AP1 cube capacity.', '',
        'The historical baseline uses retired cube→spindle compression and r=0.3J_A. '
        'Unchanged visibility 4 evaluates different C in the two designs.', '',
        'Every nonnegative-gamut lattice vertex is retained, without an RGB upper bound. '
        'Rows labelled ≤10000 use input luminance; all normalizers remain those of the full gamut union.', '',
        'Neutral vertices are separate. Chromatic low: m<0.4; transition: 0.4≤m≤0.6; high: m>0.6. '
        'Counts describe this LUT lattice, not expected image pixel frequencies.', '',
        '| Design | Gamut | Input nits | N | Neutral | Low | Transition | High | Low max | High max |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    designs = [('historical compressed baseline', report['baseline'])]
    designs.extend((f"ρ={case['rho']:g}", case) for case in report['cases'])
    for name, design in designs:
        for gamut, strata in design['gamuts'].items():
            for stratum, stats in strata.items():
                groups = stats['groups']
                label = 'all' if stratum == 'all_luminances' else '≤10000'
                lines.append(f"| {name} | {gamut} | {label} | {stats['samples']:,} | "
                             f"{groups['neutral']:,} | {groups['low']:,} | {groups['transition']:,} | "
                             f"{groups['high']:,} | {stats['drivers']['low']['maximum']:.6f} | "
                             f"{stats['drivers']['high']['maximum']:.6f} |")
    lines.extend(['', 'Independent driver normalizers over both full gamut subsets:', '',
                  '| Design | Low | High |', '| --- | ---: | ---: |'])
    for name, design in designs:
        lines.append(f"| {name} | {design['normalizers']['low']:.9f} | "
                     f"{design['normalizers']['high']:.9f} |")
    lines.extend(['', 'Candidate difference from historical compressed baseline (all luminances):', '',
                  '| ρ | Gamut | Low mean abs | High mean abs | Membership mean abs | Visibility mean abs |',
                  '| ---: | --- | ---: | ---: | ---: | ---: |'])
    for case in report['cases']:
        for gamut in GAMUTS:
            difference = case['gamuts'][gamut]['all_luminances']['difference_from_compressed_baseline']
            lines.append(f"| {case['rho']:g} | {gamut} | {difference['low']['mean_absolute']:.6f} | "
                         f"{difference['high']['mean_absolute']:.6f} | "
                         f"{difference['high_membership']['mean_absolute']:.6f} | "
                         f"{difference['visibility']['mean_absolute']:.6f} |")
    lines.extend(['', 'The capacity lookup is uncertified for strict containment. '
                  'Positive excess is measured, never clipped or treated as a calibration failure.', '',
                  '| Gamut | Input nits | Positive excess N | Excess above tolerance N | Max excess C | Max relative excess |',
                  '| --- | --- | ---: | ---: | ---: | ---: |'])
    for gamut, strata in report['fitted_capacity_excess']['gamuts'].items():
        for stratum, stats in strata.items():
            label = 'all' if stratum == 'all_luminances' else '≤10000'
            lines.append(f"| {gamut} | {label} | {stats['positive_excess_samples']:,} | "
                         f"{stats['excess_above_tolerance_samples']:,} | "
                         f"{stats['maximum_absolute_excess']:.9f} | "
                         f"{stats['maximum_relative_excess']:.9f} |")
    lines.extend(['', 'Excess tolerance is max(1e−8, 1e−6 U). The JSON report also records quantiles, '
                  'absolute and relative response counts strictly above 10/50/90%, full/≤10000 statistics, '
                  'and signed/absolute/RMS/maximum baseline differences.', '',
                  'Each plot uses opaque raw J_A/C sample points with per-point hue and capacity. '
                  'Different hues can overlap in this projection; no universal response contours are drawn.', '',
                  'JSON quantiles exclude neutrals for membership and relative-radius distributions. '
                  'Driver response and visibility distributions include neutrals.'])
    oracle = report['oracle_capacity_spotcheck']
    lines.extend(['', f"Independent float64 cube oracle: {oracle['sweep']['samples']:,} deterministic "
                  f"height/hue probes and {oracle['actual_lattice']['samples']} actual-lattice "
                  'boundary-excess/near-tip witnesses.', '',
                  f"Sweep maximum physical C error: {oracle['sweep']['physical_capacity']['maximum_absolute_error']:.9f}; "
                  f"maximum relative error: {oracle['sweep']['unit']['maximum_relative_error']:.9f}. "
                  'These are sampled measurements, not a containment certificate.'])
    return '\n'.join(lines) + '\n'


def generate_raw_capacity(output_dir):
    model, samples, compressed, baseline, validations = raw_production_samples()
    masks = population_masks(samples)
    baseline_relative, baseline_maxima = normalised_responses(baseline, samples.union)
    baseline_radius = LEGACY_CROSSOVER * np.abs(compressed.ja)
    baseline_report = dict(
        description='Historical compressed modCAM16 C; r=0.3 J_A; visibility 4',
        crossover=LEGACY_CROSSOVER, visibility=4.0,
        normalizers=dict(zip(('low', 'high'), baseline_maxima)),
        gamuts={gamut: {name: raw_population_statistics(
            samples, mask, baseline, baseline_relative, baseline_radius)
            for name, mask in strata.items()} for gamut, strata in masks.items()},
    )
    # The shared population helper reports raw C/r; label the baseline's
    # compressed C/r separately rather than silently changing that definition.
    for gamut, strata in masks.items():
        for name, mask in strata.items():
            chromatic = mask & ~samples.neutral
            baseline_report['gamuts'][gamut][name]['compressed_chroma_over_crossover_radius'] = distribution(
                compressed.chroma[chromatic] / baseline_radius[chromatic])
    cases = []
    plot_cases = [('Historical compressed baseline', None, baseline_relative, baseline_maxima)]
    previous_membership = None
    for rho, slug in RAW_CAPACITY_CROSSOVERS:
        radius = rho * samples.capacity
        values = radius_driver_weights(samples.chroma, radius)
        if previous_membership is not None:
            require(np.all(values[3] <= previous_membership + 2e-16),
                    'Increasing rho increased high membership')
        previous_membership = values[3]
        relative, maxima = normalised_responses(values, samples.union)
        require(np.all(values[0][samples.neutral] == 0.0)
                and np.all(values[1][samples.neutral] == 0.0),
                'A neutral vertex has a nonzero candidate chroma driver')
        check = radius_driver_weights(radius, radius)
        require(np.array_equal(check[0], check[1])
                and np.allclose(check[0], 0.5 * check[2], rtol=2e-15, atol=0.0),
                'Candidate equality does not lie at rho U')
        filename = f'driver-raw-capacity-rho{slug}-v4.png'
        case = dict(
            rho=rho, visibility=4.0, png=filename,
            normalizers=dict(zip(('low', 'high'), maxima)),
            complement_max_absolute_error=float(np.max(np.abs(values[0] + values[1] - values[2]))),
            crossover_equality=True, neutral_zero=True,
            gamuts={gamut: {name: raw_population_statistics(
                samples, mask, values, relative, radius, baseline, baseline_relative)
                for name, mask in strata.items()} for gamut, strata in masks.items()},
        )
        cases.append(case)
        plot_cases.append((f'ρ={rho:g}, v=4', rho, relative, maxima))
        figure, axes = plt.subplots(2, 2, figsize=(12, 10), dpi=160)
        figure.subplots_adjust(left=0.075, right=0.91, bottom=0.15, top=0.87,
                               hspace=0.26, wspace=0.20)
        figure.suptitle(f'Raw-capacity crossover · ρ={rho:g} · visibility v=4', fontsize=15, y=0.975)
        figure.text(0.5, 0.925,
                    r'$r=\rho U(J_A,h)$, $V=C^2/(C^2+4)$, $m=C^2/(C^2+r^2)$, $L=V(1-m)$, $H=Vm$',
                    ha='center', fontsize=12)
        draw_raw_capacity_group(figure, axes, samples, rho, relative, maxima)
        add_colorbar(figure, axes)
        figure.text(0.5, 0.025,
                    'Raw modCAM16 coordinates from the production log1p 65³ AP1 lattice; '
                    'nonnegative Rec.709 / Rec.2020 subsets.\n'
                    'All luminances retained; no RGB upper bound. Colors use per-point hue and fitted AP1 cube capacity.\n'
                    'Each driver is divided by its own maximum over both full gamut subsets for this ρ; '
                    'colors compare relative response.\n'
                    'Hue-dependent responses can overlap in this J_A/C projection. '
                    'JSON separately reports ≤10,000-nit strata and historical compressed baseline differences.\n'
                    'Historical capacity study: retained production uses ρ=0.4; the analytic reference uses (35/75)|J_A|.',
                    ha='center', va='bottom', fontsize=8.3, color='#334155')
        figure.savefig(output_dir / filename, dpi=160, facecolor='white',
                       metadata={'Title': f'Raw-capacity relative response rho={rho:g}, v=4'})
        plt.close(figure)
    overview = plt.figure(figsize=(24, 20), dpi=160)
    outer = overview.add_gridspec(2, 2, left=0.045, right=0.965, bottom=0.115,
                                 top=0.90, wspace=0.24, hspace=0.29)
    for index, (label, rho, relative, maxima) in enumerate(plot_cases):
        row, column = divmod(index, 2)
        subgrid = outer[row, column].subgridspec(2, 2, hspace=0.30, wspace=0.27)
        axes = np.array([[overview.add_subplot(subgrid[r, c]) for c in range(2)] for r in range(2)])
        draw_raw_capacity_group(overview, axes, samples, rho, relative, maxima, compact=True)
        add_colorbar(overview, axes, compact=True)
        position = outer[row, column].get_position(overview)
        overview.text((position.x0 + position.x1) / 2, position.y1 + 0.018,
                      label, ha='center', fontsize=17)
    overview.suptitle('Historical capacity comparison · retained production ρ=0.4', fontsize=23, y=0.985)
    overview.text(0.5, 0.95, r'Candidates: $r=\rho U(J_A,h)$ · raw modCAM16 C and J_A · fitted AP1 capacity U',
                  ha='center', fontsize=16)
    overview.text(0.5, 0.028,
                  'Within each group: Rec.709 / Rec.2020 rows, low / high columns. '
                  'All nonnegative-gamut lattice vertices retained; no luminance cutoff or RGB upper bound.\n'
                  'Baseline selectors read compressed C and r=0.3 J_A; candidate selectors read raw C and r=ρU. '
                  'Every group uses the same raw J_A/C positions.\n'
                  'Each driver uses its own full-union maximum per design. '
                  'Per-point hue and capacity determine candidate response; overlapping hues share positions.\n'
                  'JSON and summary compare the historical compressed baseline and ≤10,000-nit strata, '
                  'using the same full-population normalizers.',
                  ha='center', va='bottom', fontsize=11, color='#334155')
    overview_name = 'driver-raw-capacity-overview.png'
    overview.savefig(output_dir / overview_name, dpi=160, facecolor='white',
                     metadata={'Title': 'Raw-capacity crossover calibration overview'})
    plt.close(overview)
    report = dict(
        comparison='raw-capacity', scope='Historical capacity study; retained production uses rho0.4; analytic reference uses 35/75 abs(J_A)',
        retained_production_capacity_fraction=LEGACY_CAPACITY_FRACTION,
        analytic_reference_crossover=CHROMA_CROSSOVER,
        lattice=dict(size=65, vertices=65 ** 3, space='ACEScg', shaper='log1p',
                     kappa=production_lut.KAPPA, maximum=production_lut.MAXIMUM),
        samples=dict(gamuts=samples.counts, union=int(np.count_nonzero(samples.union)),
                     criterion='Every source RGB channel >=0; no RGB upper bound; figures retain all luminances',
                     stratum='At or below 10000 input nits, with the same full-union normalizers'),
        coordinates=dict(x='Raw J_A', y='Raw C', hue='Per-point atan2(b,a), retained for capacity lookup',
                         capacity='Current fitted AP1 cube C_max at raw J_A and hue',
                         x_limit=samples.x_limit, y_limit=samples.y_limit,
                         scale='symlog', ja_linthresh=JA_LINEAR_THRESHOLD, c_linthresh=C_LINEAR_THRESHOLD),
        equations=dict(radius='rho U(J_A,h)', visibility='C^2/(C^2+4)',
                       high_membership='C^2/(C^2+radius^2)',
                       low='visibility (1-high_membership)', high='visibility high_membership'),
        membership_groups=dict(neutral='Raw C == 0, counted separately',
                               low='Chromatic m < 0.4', transition='Chromatic 0.4 <= m <= 0.6',
                               high='Chromatic m > 0.6'),
        normalization='Independent low/high maxima over full union of both gamut subsets per design; '
                      'the same normalizers apply to <=10000-nit strata',
        response_thresholds='Counts strictly above 10/50/90%, recorded for absolute and normalized drivers',
        distribution_population='Membership and relative-radius distributions exclude neutrals; '
                                'driver and visibility distributions include neutrals',
        projection='Opaque per-sample colors; different hues may overlap at raw J_A/C; no universal contours',
        fitted_capacity_excess=dict(
            policy='Measured without clipping; the current fitted resource is not certified for strict containment',
            tolerance='max(1e-8, 1e-6 U)',
            all_lattice=capacity_excess_statistics(samples, np.ones(len(samples.ja), dtype=bool)),
            gamuts={gamut: {name: capacity_excess_statistics(samples, mask)
                           for name, mask in strata.items()} for gamut, strata in masks.items()}),
        oracle_capacity_spotcheck=oracle_capacity_spotcheck(model, samples),
        validations={**validations, 'increasing_rho_never_increases_high_membership': True},
        baseline=baseline_report, cases=cases,
        overview=overview_name, summary='summary.md',
    )
    (output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (output_dir / 'summary.md').write_text(calibration_summary(report))


def generate(output_dir, comparison="visibility"):
    output_dir.mkdir(parents=True, exist_ok=True)
    if comparison == 'raw-capacity':
        generate_raw_capacity(output_dir)
        return
    model, samples, validations = production_samples()
    grid = response_grid(model, samples)
    crossover_comparison = comparison == "crossover"
    crossovers = CROSSOVER_COMPARISON if crossover_comparison else CROSSOVERS
    visibilities = ((4.0, "4"),) if crossover_comparison else VISIBILITIES
    cases = []
    for crossover, label, crossover_slug in crossovers:
        for visibility, visibility_slug in visibilities:
            relative, normalizers, report = response_group(samples, crossover, visibility)
            filename = f"driver-sensitivity-k{crossover_slug}-v{visibility_slug}.png"
            cases.append((crossover, label, visibility, relative, normalizers, report, filename))
            figure, axes = plt.subplots(2, 2, figsize=(12, 10), dpi=160)
            figure.subplots_adjust(left=0.075, right=0.91, bottom=0.155, top=0.87,
                                   hspace=0.26, wspace=0.20)
            figure.suptitle(f"Historical low/high response · crossover k={label} · visibility v={visibility:g}",
                           fontsize=15, y=0.975)
            figure.text(0.5, 0.925,
                        r"$V=C^2/(C^2+v)$, $m=C^2/[C^2+(kJ_A)^2]$, $L=V(1-m)$, $H=Vm$",
                        ha="center", fontsize=12)
            draw_group(figure, axes, model, samples, grid, crossover, label,
                       visibility, relative, normalizers)
            add_colorbar(figure, axes)
            figure.text(
                0.5, 0.025,
                "Historical compressed study: production log1p 65³ AP1 lattice after cubic cube-to-spindle compression; "
                "nonnegative Rec.709 / Rec.2020 subsets.\n"
                "All luminances retained; no RGB upper bound. Opaque points represent actual lattice vertices.\n"
                "Each driver uses its own maximum across the union of both gamuts for this (k, v); "
                "color compares relative response, not low/high amplitude.\n"
                "Thin 10/50/90% curves are analytic response guides within the AP1 spindle, not gamut coverage.\n"
                "Shared symlog axes: linear below J_A=1 and C=0.25; tick labels show raw appearance values.",
                ha="center", va="bottom", fontsize=8.3, color="#334155")
            figure.savefig(output_dir / filename, dpi=160, facecolor="white",
                           metadata={"Title": f"Driver relative response k={label}, v={visibility:g}"})
            plt.close(figure)
            report["png"] = filename

    if crossover_comparison:
        overview = plt.figure(figsize=(24, 11), dpi=160)
        outer = overview.add_gridspec(1, 2, left=0.045, right=0.965, bottom=0.17,
                                     top=0.855, wspace=0.24)
        overview_title = "Historical crossover comparison · fixed visibility v=4"
        layout_description = (
            "Left group: crossover k=0.3. Right group: crossover k=1/3. Visibility v=4 in both. "
            "Within each group: Rec.709 / Rec.2020 rows, low / high columns.\n")
    else:
        overview = plt.figure(figsize=(32, 17), dpi=160)
        outer = overview.add_gridspec(2, 4, left=0.035, right=0.97, bottom=0.10,
                                     top=0.925, wspace=0.30, hspace=0.26)
        overview_title = "Historical visibility sweep on the production 65³ lattice"
        layout_description = (
            "Group rows: crossover k=1/3 and 0.4; group columns: visibility v=0.25, 1, 4, 16. "
            "Within every group: Rec.709 / Rec.2020 rows, low / high columns.\n")
    for index, case in enumerate(cases):
        crossover, label, visibility, relative, normalizers, _, _ = case
        row, column = (0, index) if crossover_comparison else divmod(index, len(visibilities))
        subgrid = outer[row, column].subgridspec(2, 2, hspace=0.30, wspace=0.27)
        axes = np.array([[overview.add_subplot(subgrid[r, c]) for c in range(2)]
                         for r in range(2)])
        draw_group(overview, axes, model, samples, grid, crossover, label,
                   visibility, relative, normalizers, compact=not crossover_comparison)
        add_colorbar(overview, axes, compact=not crossover_comparison)
        position = outer[row, column].get_position(overview)
        overview.text((position.x0 + position.x1) / 2.0,
                      position.y1 + (0.04 if crossover_comparison else 0.014),
                      f"k={label}, v={visibility:g}", ha="center", va="bottom",
                      fontsize=17 if crossover_comparison else 13)
    overview.suptitle(overview_title, fontsize=23, y=0.985)
    overview.text(
        0.5, 0.028,
        layout_description +
        "Opaque colors show driver response divided by that driver's maximum across both gamuts "
        "for its (k, v). All groups use the same 0–1 color scale and raw symlog coordinates.\n"
        "All nonnegative-gamut lattice vertices are retained, without luminance cutoff or RGB upper bound. "
        "Thin 10/50/90% contours are analytic response guides within the AP1 spindle, not gamut coverage.",
        ha="center", va="bottom", fontsize=10.5 if crossover_comparison else 12, color="#334155")
    overview.savefig(output_dir / "driver-sensitivity-overview.png", dpi=160, facecolor="white",
                     metadata={"Title": "Low/high driver crossover comparison overview"
                               if crossover_comparison else "Low/high driver visibility sweep overview"})
    plt.close(overview)

    report = dict(
        comparison=comparison,
        scope="Historical compressed visibility/crossover experiments; current analytic reference uses 35/75 abs(J_A) on raw coordinates",
        lattice=dict(size=65, vertices=65 ** 3, space="ACEScg", shaper="log1p",
                     kappa=production_lut.KAPPA, maximum=production_lut.MAXIMUM),
        samples=dict(gamuts=samples.counts, union=int(np.count_nonzero(samples.union)),
                     criterion="Every source RGB channel >= 0; no upper bound or luminance cutoff"),
        coordinates=dict(x="Post-compression J_A", y="Post-compression C",
                         x_limit=samples.x_limit, y_limit=samples.y_limit,
                         scale="symlog", ja_linthresh=JA_LINEAR_THRESHOLD,
                         c_linthresh=C_LINEAR_THRESHOLD, ja_ticks=JA_TICKS, c_ticks=C_TICKS),
        normalization="Independent low/high maxima over union of gamut samples, separately for each (k, v)",
        contour_levels=CONTOURS,
        contour_domain="AP1 spindle; analytic response guides do not indicate gamut sample coverage",
        validations=validations,
        cases=[case[5] for case in cases],
        overview="driver-sensitivity-overview.png",
    )
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--comparison", choices=("visibility", "crossover", "raw-capacity"), default="visibility",
                        help="Visibility sweep, compressed crossover comparison, or raw capacity rho=0.3/0.4/0.5 at v=4")
    arguments = parser.parse_args()
    generate(arguments.output_dir, comparison=arguments.comparison)
