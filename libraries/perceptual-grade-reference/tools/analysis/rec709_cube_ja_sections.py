"""Plot raw fixed-J_A cube sections and the J_A/C driver crossover."""

import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from color_tools.perceptual_grade_reference.cube import white_response
from color_tools.perceptual_grade_reference.grading import LOW_Y, CHROMA_CROSSOVER as RATIO
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.responses import GAMMA, INVERSE, eccentricity
from tools.build.boundary_oracle import capacity_unit, ray_valid

HUE_SAMPLES = 1440
CLOUD_GRID_SIZE = 19
GROUP_COLORS = ('#2563eb', '#a855f7', '#dc2626')


def section_levels(model):
    reference = model.tone.reference
    labels = ('Shadows', 'Midtones', 'White', 'Highlights', '4,000 nits', '10,000 nits')
    nits = np.array((LOW_Y*reference, .18*reference, reference, 1000., 4000., 10000.))
    return labels, nits, 100*np.asarray(model.tone.nits_to_j(nits))


def direction(hue, aw):
    return ((aw/(1204*eccentricity(hue)))[..., None]
            *(np.cos(hue)[..., None]*INVERSE[:, 1]+np.sin(hue)[..., None]*INVERSE[:, 2]))


class Sections:
    def __init__(self, model):
        self.model, self.context = model, model.boundary
        self.rw = white_response(self.context.fl)
        self.matrix = model.xyz_to_canonical @ model.cones_to_xyz

    def membership(self, ja, hue, c):
        t = np.full(np.shape(c), (ja/self.context.white)**(1/GAMMA))
        scale = self.rw*t*(1-t)
        return ray_valid(t, c/scale, direction(hue, self.context.aw), self.rw, self.matrix)

    def boundary(self, ja, hue):
        t = (ja/self.context.white)**(1/GAMMA)
        rec709 = self.rw*t*(1-t)*capacity_unit(t, hue, self.context.fl, self.context.aw, self.matrix)
        ap1 = self.context.capacity(ja, hue)
        epsilon = max(1e-11, 2e-9*float(np.max(rec709)))
        if not self.membership(ja, hue, np.maximum(0, rec709-epsilon)).all():
            raise ValueError('An inner Rec.709 boundary witness is invalid')
        if self.membership(ja, hue, rec709+epsilon).any():
            raise ValueError('An outer Rec.709 boundary witness is legal')
        return rec709, ap1

    def point_cloud(self, ja, boundary):
        extent = np.max(boundary)
        values = np.linspace(-extent, extent, CLOUD_GRID_SIZE)
        a, b = np.meshgrid(values, values)
        c = np.hypot(a.ravel(), b.ravel()); hue = np.arctan2(b.ravel(), a.ravel())
        inside = self.membership(ja, hue, c)
        c, hue = c[inside], hue[inside]
        # Stage 3 membership is intentionally independent of the fitted AP1
        # capacity and hue.  The physical AP1 boundary remains the plotting
        # domain, but it does not define the selector radius.
        radius = RATIO*abs(ja)
        denominator = c*c+radius*radius
        membership = np.divide(c*c, denominator, out=np.zeros_like(c), where=denominator > 0)
        groups = (membership < .4, (membership >= .4) & (membership <= .6), membership > .6)
        if not len(c):
            raise ValueError('Cartesian cloud missed the source section')
        return hue, c, groups


def generate(output_dir):
    model = Model(); sections = Sections(model)
    labels, nits, heights = section_levels(model)
    hue = np.linspace(0, 2*np.pi, HUE_SAMPLES, endpoint=False)
    closed = np.r_[hue, 2*np.pi]
    figure, axes = plt.subplots(2, 3, figsize=(15, 10.5), dpi=160, subplot_kw={'projection': 'polar'})
    figure.suptitle('Raw Rec.709 and AP1 cube sections · J_A/C crossover 35/75', fontsize=16, y=.98)
    for axis, label, luminance, ja in zip(axes.flat, labels, nits, heights):
        raw, ap1 = sections.boundary(ja, hue)
        axis.plot(closed, np.r_[raw, raw[0]], color='#d97706', linewidth=1.8,
                  linestyle=(0, (5, 3)), label='Rec.709 raw boundary')
        axis.plot(closed, np.r_[ap1, ap1[0]], color='#334155', linewidth=1.5, label='AP1 fitted boundary')
        radius = RATIO*abs(ja)
        axis.plot(closed, np.full_like(closed, radius), color='#16a34a', linewidth=1.7,
                  linestyle=':', label='Low/high crossover: (35/75)|J_A|')
        cloud_hue, cloud_c, groups = sections.point_cloud(ja, raw)
        for color, group in zip(GROUP_COLORS, groups):
            axis.scatter(cloud_hue[group], cloud_c[group], s=16, color=color,
                         linewidths=.3, edgecolors='white', alpha=.85)
        # Keep a crossover outside the fitted gamut visible instead of
        # clipping it to the AP1 capacity curve.
        frame = 1.03*max(np.max(raw), np.max(ap1), radius)
        axis.set_ylim(0, frame)
        axis.set_theta_zero_location('E'); axis.set_theta_direction(1)
        axis.set_thetagrids(np.arange(0, 360, 45)); axis.set_rlabel_position(135)
        axis.tick_params(axis='both', labelsize=8)
        axis.grid(True, color='#cbd5e1', linewidth=.75, alpha=.75)
        axis.set_title(f'{label} / {luminance:,.3g} nits\nJ_A={ja:.6f}', fontsize=11, pad=8)
    figure.legend(handles=(
        Line2D([], [], color='#d97706', linewidth=1.8, linestyle='--', label='Raw Rec.709 cube boundary'),
        Line2D([], [], color='#334155', linewidth=1.5, label='Fitted AP1 capacity U(J_A, hue)'),
        Line2D([], [], color='#16a34a', linewidth=1.7, linestyle=':', label='Reference crossover: (35/75)|J_A|'),
        *(Line2D([], [], color=color, marker='o', linestyle='none', markersize=5, label=name)
          for color, name in zip(GROUP_COLORS, ('Low samples', 'Transition samples', 'High samples')))),
        loc='lower center', bbox_to_anchor=(.5, .075), ncol=3, fontsize=9, frameon=False)
    figure.text(.5, .02,
        'Angular coordinate: modCAM hue (0°=+a, 90°=+b); radius: raw C. Each panel has its own C scale.\n'
        'All curves and samples share the stated J_A. The outer circle is a display limit; the hue-dependent AP1 boundary is drawn.\n'
        'Entry radial mapping is retired, so each raw point keeps its coordinates before grading. '
        'Membership m=C²/(C²+((35/75)|J_A|)²): low m<0.4; transition 0.4≤m≤0.6; high m>0.6.\n'
        f'Geometry: {HUE_SAMPLES:,} hue samples; point cloud uses an even {CLOUD_GRID_SIZE}×{CLOUD_GRID_SIZE} '
        'Cartesian grid with exact source-cube membership.', ha='center', va='bottom', fontsize=8.6, color='#334155')
    figure.subplots_adjust(left=.045, right=.955, bottom=.16, top=.86, wspace=.2, hspace=.31)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_dir/'rec709-cube-ja-sections.png', facecolor='white',
                   metadata={'Title': 'Raw Rec.709/AP1 fixed-J_A sections and 35/75 selectors'})
    plt.close(figure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    generate(parser.parse_args().output_dir)
