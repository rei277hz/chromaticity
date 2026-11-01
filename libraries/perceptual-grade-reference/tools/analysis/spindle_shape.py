"""Plot raw cube capacity and J_A/C driver regions on the 65³ lattice."""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from color_tools.perceptual_grade_core.model import lut as production_lut
from color_tools.perceptual_grade_reference.cube import MAXIMUM, white_response
from color_tools.perceptual_grade_reference.grading import CHROMA_CROSSOVER as RATIO
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.responses import GAMMA
from tools.build.boundary_oracle import capacity_unit

REFERENCE_NITS = (500., 1000., 2000., 4000., 10000.)
HISTOGRAM_MAX_NITS = 10000.
GROUP_COLORS = ('#2563eb', '#a855f7', '#dc2626')
GROUP_NAMES = ('Low', 'Transition', 'High')


def cube_capacity_envelopes(context, ja, hues):
    minimum, maximum = np.full_like(ja, np.inf), np.zeros_like(ja)
    for start in range(0, len(hues), 48):
        capacity = context.capacity(ja[:, None], hues[None, start:start+48])
        minimum = np.minimum(minimum, capacity.min(axis=1))
        maximum = np.maximum(maximum, capacity.max(axis=1))
    return minimum, maximum


def source_cube_matrix(model):
    matrix = model.xyz_to_rgb @ model.cones_to_xyz
    expected = np.linalg.inv(model.to_acescg) @ model.boundary.matrix
    if not np.allclose(matrix, expected, rtol=2e-12, atol=2e-12):
        raise ValueError(f'{model.space} cube adapter differs from the input adapter')
    return matrix


def raw_cube_envelopes(model, ja, hues):
    """Independent source-cube rays in raw coordinates, without radial mapping."""
    context = model.boundary
    t = (ja/context.white)**(1/GAMMA)
    active = (ja > 0) & (ja < context.white)
    matrix = source_cube_matrix(model)
    minimum, maximum = np.full_like(ja, np.inf), np.zeros_like(ja)
    for start in range(0, len(hues), 48):
        angles = hues[start:start+48]
        capacity = np.zeros((len(ja), len(angles)))
        capacity[active] = (white_response(context.fl)*t[active, None]*(1-t[active, None])
                            *capacity_unit(t[active, None], angles[None, :],
                                           context.fl, context.aw, matrix))
        minimum = np.minimum(minimum, capacity.min(axis=1))
        maximum = np.maximum(maximum, capacity.max(axis=1))
    return minimum, maximum


def production_samples(model, models):
    if production_lut.SIZE != 65 or production_lut.KAPPA != .01 or production_lut.SPACE != 'ACEScg':
        raise ValueError('Unexpected production LUT lattice contract')
    lattice = np.asarray(production_lut.lattice(), dtype=float)
    state = model.enter_native(lattice)
    c = np.hypot(state.q[:, 1], state.q[:, 2])
    relative = np.divide(c, np.abs(state.ja), out=np.zeros_like(c), where=state.ja != 0)
    radius = RATIO*np.abs(state.ja)
    denominator = c*c+radius*radius
    membership = np.divide(c*c, denominator, out=np.zeros_like(c), where=denominator > 0)
    neutral = c == 0
    groups = (membership < .4, (membership >= .4) & (membership <= .6), membership > .6)
    masks, uncapped = {}, {}
    for name, source in models.items():
        rgb = lattice @ np.linalg.inv(source.to_acescg).T
        masks[name] = np.all(rgb >= 0, axis=-1)
        uncapped[name] = int(np.count_nonzero(masks[name] & np.any(rgb > MAXIMUM, axis=-1)))
    if lattice.shape != (65**3, 3) or np.count_nonzero(neutral) != 65:
        raise ValueError('Unexpected production lattice or neutral count')
    if np.count_nonzero(masks['Rec.709']) != 22164 or np.count_nonzero(masks['Rec.2020']) != 93118:
        raise ValueError('Unexpected nonnegative source-gamut populations')
    return c, relative, groups, neutral, masks, uncapped, (lattice @ model.acescg_y)*model.tone.reference


def histogram_scale(heights):
    peak = int(max(np.max(values) for values in heights))
    raw_step = max(1., peak/6)
    power = 10.**np.floor(np.log10(raw_step))
    step = next(multiple*power for multiple in (1., 2., 5., 10.) if multiple*power >= raw_step)
    maximum = step*np.ceil(peak/step)
    return maximum, np.arange(0, maximum+step/2, step)


def add_lattice_histogram(axis, name, samples, edges, full_height, subset_height, maximum, ticks):
    c, relative, groups, neutral, masks, uncapped, nits = samples
    subset = masks[name]
    histogram = axis.twinx()
    histogram.set_zorder(0); axis.set_zorder(1); axis.patch.set_alpha(0)
    histogram.stairs(full_height, edges, fill=True, color='#3b82f6', alpha=.5, linewidth=.8)
    histogram.stairs(subset_height, edges, fill=True, color='#f97316', alpha=.5, linewidth=.8)
    histogram.set_ylim(0, maximum); histogram.set_yticks(ticks)
    histogram.set_ylabel('Vertices per raw C bin (absolute count)', color='#64748b', fontsize=8)
    histogram.tick_params(axis='y', colors='#64748b', labelsize=8)
    for color, label, group in zip(GROUP_COLORS, GROUP_NAMES, groups):
        selected = subset & group & ~neutral
        axis.scatter(c[selected], relative[selected], s=3, color=color, alpha=.35,
                     linewidths=0, rasterized=True, label=f'{label} ({np.count_nonzero(selected):,})')
    selected = subset & neutral
    axis.scatter(c[selected], relative[selected], s=6, color='#334155', alpha=.7,
                 label=f'Neutral ({np.count_nonzero(selected):,})')
    lower, upper = RATIO*np.sqrt(2/3), RATIO*np.sqrt(3/2)
    axis.axhspan(lower, upper, color='#a855f7', alpha=.08)
    axis.axhline(RATIO, color='#334155', linestyle=(0, (5, 4)), linewidth=1.3,
                 label='Low/high crossover: C/|J_A| = 35/75')
    axis.axhline(lower, color='#a855f7', linestyle=':', linewidth=1)
    axis.axhline(upper, color='#a855f7', linestyle=':', linewidth=1)
    axis.set_xlim(edges[0], edges[-1]); axis.set_ylim(0, 1.04*max(1., float(np.max(relative))))
    axis.set_title(f'{name} subset: raw J_A/C membership')
    axis.set_xlabel('Raw C'); axis.set_ylabel('Chroma ratio C / |J_A|')
    axis.grid(True, color='#cbd5e1', linewidth=.7, alpha=.55)
    handles, labels = axis.get_legend_handles_labels()
    handles.extend([Patch(facecolor='#3b82f6', alpha=.5), Patch(facecolor='#f97316', alpha=.5)])
    labels.extend([f'Full AP1 histogram ({int(full_height.sum()):,})',
                   f'{name} histogram ({int(subset_height.sum()):,})'])
    axis.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5, -.13),
                ncol=2, fontsize=7.6, frameon=False)
    axis.text(.035, .975, f'65³ production shaper · {np.count_nonzero(subset):,} vertices\n'
              f'{uncapped[name]:,} have a {name} channel >1024\n'
              'Histograms: input Y ≤10,000 nits; 80 raw-C bins',
              transform=axis.transAxes, va='top', fontsize=7.8,
              bbox=dict(facecolor='white', alpha=.86, edgecolor='none'))


def generate(output_dir):
    models = {name: Model(space=f'Linear {name}') for name in ('Rec.709', 'Rec.2020')}
    model = models['Rec.709']; context = model.boundary; white = context.white
    ja = white*np.unique(np.r_[np.linspace(0, 1, 1801), np.geomspace(1e-12, .01, 128)])
    hues = np.linspace(0, 2*np.pi, 1440, endpoint=False)
    ap1 = cube_capacity_envelopes(context, ja, hues)
    envelopes = {name: raw_cube_envelopes(source, ja, hues) for name, source in models.items()}
    samples = production_samples(model, models)
    c, _, _, _, masks, _, nits = samples
    x_limit = 50*np.ceil(max(1., float(np.max(c)))/50)
    edges = np.linspace(0, x_limit, 81)
    cutoff = nits <= HISTOGRAM_MAX_NITS
    full_height = np.histogram(c[cutoff], bins=edges)[0]
    subset_heights = {name: np.histogram(c[cutoff & mask], bins=edges)[0] for name, mask in masks.items()}
    hist_maximum, hist_ticks = histogram_scale([full_height, *subset_heights.values()])
    figure, axes = plt.subplots(1, 3, figsize=(22, 9), dpi=160)
    figure.suptitle('Raw cube capacity and reference low/high driver regions · k=35/75, visibility=4',
                    fontsize=16, y=.97)
    axis = axes[0]
    for (minimum, maximum), color, label in [(ap1, '#1464a0', 'AP1 fitted'),
            (envelopes['Rec.709'], '#a855f7', 'Rec.709 exact'),
            (envelopes['Rec.2020'], '#008b8b', 'Rec.2020 exact')]:
        axis.plot(ja/white, minimum, color=color, linewidth=1.5, linestyle='--', label=f'{label} C_max: min over hue')
        axis.plot(ja/white, maximum, color=color, linewidth=1.8, label=f'{label} C_max: max over hue')
    crossover = RATIO*np.abs(ja)
    axis.plot(ja/white, crossover, color='#c34b37', linewidth=1.5, linestyle=':',
              label='Reference crossover: (35/75)|J_A|')
    for nits_value, position in zip(REFERENCE_NITS, 100*model.tone.nits_to_j(REFERENCE_NITS)/white):
        axis.axvline(position, color='#64748b', linewidth=.9, linestyle=(0, (4, 4)), alpha=.75)
        axis.annotate(f'{nits_value:,.0f} nits', (position, 1.), xycoords=('data', 'axes fraction'),
                      xytext=(2, -3), textcoords='offset points', rotation=90, va='top', fontsize=8)
    axis.set_xlim(0, 1); axis.set_ylim(0, 1.05*max(np.max(ap1[1]), np.max(crossover)))
    axis.set_title('Raw C_max and crossover vs normalized J_A')
    axis.set_xlabel('J_A / W'); axis.set_ylabel('Raw C')
    axis.grid(True, color='#cbd5e1', linewidth=.7, alpha=.55)
    axis.legend(loc='upper center', bbox_to_anchor=(.5, -.13), ncol=1, fontsize=8, frameon=False)
    for axis, name in zip(axes[1:], models):
        add_lattice_histogram(axis, name, samples, edges, full_height,
                             subset_heights[name], hist_maximum, hist_ticks)
    figure.text(.5, .025,
        f'All coordinates are raw modCAM16; entry and exit radial mappings are retired. W={white:.6f} '
        f'(neutral {MAXIMUM*model.tone.reference:,.0f} nits).\n'
        'Left: source cubes [0,1024]³; the crossover uses only |J_A| and can lie outside the gamut. Dashed verticals show neutral input luminance.\n'
        'Right: nonnegative Rec.709 / Rec.2020 subsets with no source-channel upper bound; sample clouds retain all luminances.\n'
        'Membership m=C²/(C²+((35/75)|J_A|)²): low m<0.4; transition 0.4≤m≤0.6; high m>0.6. Neutrals are separate.\n'
        'Both histograms exclude input Y>10,000 nits; overlays use alpha=0.5 and the same absolute-count axis with evenly spaced ticks.',
        ha='center', va='bottom', fontsize=9, color='#334155')
    figure.subplots_adjust(left=.05, right=.96, bottom=.32, top=.87, wspace=.3)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_dir/'spindle-boundary-shape.png', facecolor='white',
                    metadata={'Title': 'Raw cube capacity and J_A/C 35/75 driver regions'})
    plt.close(figure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    generate(parser.parse_args().output_dir)
