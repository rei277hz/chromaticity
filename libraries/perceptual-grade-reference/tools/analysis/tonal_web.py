"""Reproducible guarded-saturation Rec.709 tonal-web geometry and deformation plots.

Run //libraries/perceptual-grade-reference:tonal_web for the reset and mixed-edit fixtures. The tool also accepts a
JSON Warp color settings through --settings; no production kernel is involved.
"""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from color_tools.perceptual_grade_reference.appearance import encode_cones
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, Color, ColorSettings
from color_tools.perceptual_grade_reference.responses import HK, hk_energy, State
from color_tools.perceptual_grade_core.model.saturation import project, bounded_project
from color_tools.perceptual_grade_core.model.hk_guard import guard
from color_tools.perceptual_grade_core.model.tonal_web import (
    HANDLE_NAMES, TonalWeb, WebSettings, rec709_contour,
)

TONE_NAMES = ('Shadows', 'Midtones', 'White', 'Highlights')
HANDLE_COLORS = ('#dc3545', '#b28a00', '#22884a', '#0596a1', '#4269d7', '#aa45a5')
SOURCE_COLOR = '#929cab'
TARGET_COLOR = '#194b80'
SIGNED_COLOR = '#d87620'
CONTOUR_SAMPLES_PER_EDGE = 96
RING_FRACTIONS = (.25, .5, .75)


def mixed_settings(geometry):
    """A fixed, moderate mixed edit with one intentional signed-region probe."""
    gains = np.array([
        [1.12, .95, 1.08, .91, 1.45, 1.05],
        [.91, 1.16, 1.05, .94, 1.13, .97],
        [1.04, .94, .88, 1.12, .93, 1.08],
        [.96, 1.08, 1.14, .90, 1.05, .92],
    ])
    # Cross H²=66C at Shadows-blue by 12%. Keep this fixture useful if
    # exact Rec.709 geometry is improved later; report the resulting controls.
    gains[0, 4] = max(gains[0, 4],
                      1.12 * geometry.anchors[0]**2 / (HK * geometry.radii[0, 4]))
    angles = np.array([
        [5., -4., 7., -5., -8., 4.],
        [8., 3., -6., -5., 6., -4.],
        [-5., 5., 8., -4., -6., 3.],
        [4., -6., -5., 7., 4., -5.],
    ])
    scales = np.array([
        [1.04, .97, 1.02, 1.05, 1., .96],
        [.96, 1.06, 1.03, .97, 1.04, 1.02],
        [1.03, 1., .96, 1.04, 1.02, .98],
        [1.02, .98, 1.05, 1.03, .97, 1.04],
    ])
    rows = lambda value: tuple(tuple(float(v) for v in row) for row in value)
    return ColorSettings(web=WebSettings(log_chroma=rows(np.log2(gains)),
        hue_degrees=rows(angles),log_scale=rows(np.log2(scales))),
        adaptance=((3.,-2.),(-4.,3.),(2.,4.),(-3.,-2.)),adaptance_half_saturation=.25)


def load_settings(path):
    values = json.loads(path.read_text())
    expected = {'web', 'adaptance', 'adaptance_half_saturation'}
    if not isinstance(values, dict) or set(values) - expected:
        raise ValueError('Warp settings accept only web, adaptance and adaptance_half_saturation')
    settings=ColorSettings(**values)
    # Model validation includes dimensions and finite control values.
    from color_tools.perceptual_grade_reference.model import Model, Settings
    Model(Settings(color=settings))
    return settings


def serializable(settings):
    return {key:asdict(settings)[key] for key in ('web','adaptance','adaptance_half_saturation')}


def xy(ab):
    ab=np.asarray(ab)
    return np.stack((-ab[...,1],ab[...,0]),axis=-1)


def closed(points):
    return np.concatenate((points, points[:1]), axis=0)


def path(q, energy, *, close=False, negative=None):
    """Project geometry, optionally separating carried-energy branches."""
    points=bounded_project(q,energy);energy=np.asarray(energy)
    if close:
        points=closed(points);energy=np.r_[energy,energy[:1]]
    out=[]
    for i,point in enumerate(points):
        if i and (energy[i]<0)!=(energy[i-1]<0):out.append([np.nan,np.nan])
        out.append(point if negative is None or (energy[i]<0)==negative else [np.nan,np.nan])
    return xy(np.asarray(out))


def draw_path(axis,q,energy,*,close=False,**style):
    axis.plot(*path(q,energy,close=close,negative=False).T,**style)
    if np.any(np.asarray(energy)<0):
        axis.plot(*path(q,energy,close=close,negative=True).T,
                  **dict(style,linestyle=(0,(3,2))))


def serialized_point(point):
    return [float(value) if np.isfinite(value) else None for value in point]


def at_height(ab, height):
    q = np.concatenate((np.full((*ab.shape[:-1], 1), height), ab), axis=-1)
    return q, hk_energy(q[..., 0], np.hypot(q[..., 1], q[..., 2]))


def apply(color, q, energy, height):
    state=color.warp_state(State(q,energy),np.full(q.shape[:-1],height))
    out,eout=state.q,state.energy
    if not np.isfinite(out).all() or not np.isfinite(eout).all():
        raise ArithmeticError('Nonfinite web geometry')
    return np.asarray(out), np.asarray(eout)


def guarded(q, energy, reference_energy):
    """Display only: repair with the original sample's carried source energy.

    The raw model and Stack handoffs remain unchanged; the cube guard is not
    part of the Warp geometry chart.
    """
    return guard(q, energy, reference_energy)


def measurements(q, energy):
    chroma = np.hypot(q[..., 1], q[..., 2])
    saturation=project(q,energy);finite=np.isfinite(saturation).all(axis=-1)
    bounded=bounded_project(q,energy)
    return {
        'finite_saturation_count': int(np.count_nonzero(finite)),
        'singular_saturation_count': int(np.count_nonzero(~finite)),
        'maximum_linear_saturation': float(np.max(np.linalg.norm(saturation[finite],axis=-1),initial=0.)),
        'maximum_bounded_saturation': float(np.max(np.linalg.norm(bounded,axis=-1),initial=0.)),
        'count': int(energy.size),
        'signed_count': int(np.count_nonzero(energy < 0)),
        'zero_energy_count': int(np.count_nonzero(energy == 0)),
        'minimum_energy': float(np.min(energy)),
        'maximum_energy': float(np.max(energy)),
        'minimum_jhk': float(np.min(q[..., 0])),
        'maximum_jhk': float(np.max(q[..., 0])),
        'minimum_chroma': float(np.min(chroma)),
        'maximum_chroma': float(np.max(chroma)),
    }


def panel(axis, model, tone_index, contour, *, reset):
    web=model.web
    height = float(web.geometry.anchors[tone_index])
    source = np.concatenate(([[height,0.,0.]],web.geometry.q[tone_index]))
    source_energy = np.r_[height*height,web.geometry.energy[tone_index]]
    targets, target_energy = apply(model, source, source_energy, height)
    transformed, contour_energy = apply(model, contour.q, contour.energy, height)
    rings, spokes = [], []
    for fraction in RING_FRACTIONS:
        q, energy = at_height(contour.q[:, 1:] * fraction, height)
        out, eout = apply(model, q, energy, height)
        rings.append((q, energy, out, eout))
    for point in source[1:]:
        q, energy = at_height(np.linspace(0., 1., 97)[:, None] * point[1:], height)
        out, eout = apply(model, q, energy, height)
        spokes.append((q, energy, out, eout))

    shown_source, shown_source_energy = guarded(source, source_energy, source_energy)
    shown_contour_source, shown_contour_source_energy = guarded(
        contour.q, contour.energy, contour.energy)
    shown_targets, shown_target_energy = guarded(targets, target_energy, source_energy)
    shown_contour, shown_contour_energy = guarded(transformed, contour_energy, contour.energy)
    source_saturation=bounded_project(shown_source,shown_source_energy)
    target_saturation=bounded_project(shown_targets,shown_target_energy)
    for q, energy, out, eout in rings:
        shown, shown_e = guarded(out, eout, energy)
        draw_path(axis,shown,shown_e,close=True, color=TARGET_COLOR, linewidth=.85,
                  alpha=.3, zorder=2)
    for color, (q, energy, out, eout) in zip(HANDLE_COLORS, spokes):
        shown_input, shown_input_e = guarded(q, energy, energy)
        shown, shown_e = guarded(out, eout, energy)
        draw_path(axis,shown_input,shown_input_e, color=SOURCE_COLOR, linewidth=.8,
                  linestyle=(0, (3, 3)), alpha=.7, zorder=1)
        draw_path(axis,shown,shown_e, color=color, linewidth=1.1, alpha=.75, zorder=2)
    axis.plot(*path(shown_contour_source,shown_contour_source_energy,close=True).T, color=SOURCE_COLOR, linewidth=1.8,
              linestyle=(0, (4, 3)), zorder=3)
    draw_path(axis,shown_contour,shown_contour_energy,close=True, color=TARGET_COLOR, linewidth=1.8,
              zorder=4)
    signed = contour_energy < 0
    # The raw E=0 threshold is handle-specific after guard. In the live pad its
    # contextual rim is shown only during an active crossing; this static plot
    # therefore has no permanent H-K rim or universal E=0 circle.
    axis.axhline(0, color='#d6dce4', linewidth=.8, zorder=0)
    axis.axvline(0, color='#d6dce4', linewidth=.8, zorder=0)
    handles = []
    for i,(name,color,q,out,eout) in enumerate(zip(('center',*HANDLE_NAMES),
            ('#344256',*HANDLE_COLORS),shown_source,shown_targets,shown_target_energy)):
        original=xy(source_saturation[i]);target=xy(target_saturation[i])
        if np.isfinite(original).all():
            axis.scatter(*original[:,None], facecolors='white', edgecolors=color,
                         s=47, linewidths=1.5, zorder=6)
        if np.isfinite(target).all():
            if not reset and np.isfinite(original).all():
                axis.annotate('', xy=target, xytext=original,
                              arrowprops=dict(arrowstyle='->', color=color, linewidth=1.1), zorder=6)
            axis.scatter(*target[:,None], facecolors='none' if eout<0 else color,
                         edgecolors=SIGNED_COLOR if eout<0 else 'white',
                         s=36, linewidths=1.5 if eout<0 else .75, zorder=7)
        offsets = dict(center=(7,7), red=(6,15), yellow=(-10,8), green=(-12,-3),
                       cyan=(-5,-15), blue=(10,-8), magenta=(10,10))
        offset=offsets[name]
        if np.isfinite(original).all():
            axis.annotate('Neutral' if name=='center' else name[0].upper(), xy=original,
                          xytext=offset,textcoords='offset points',fontsize=8.2,color=color,
                          ha='left' if offset[0]>0 else 'right',
                          va='bottom' if offset[1]>0 else 'top',zorder=8)
        handles.append(dict(name=name,source_q=source[i].tolist(),source_energy=float(source_energy[i]),
            displayed_source_q=q.tolist(), displayed_source_energy=float(shown_source_energy[i]),
            target_q=targets[i].tolist(),target_energy=float(target_energy[i]),
            guarded_target_q=shown_targets[i].tolist(),
            guarded_target_energy=float(shown_target_energy[i]),
            source_saturation=serialized_point(source_saturation[i]),
            target_saturation=serialized_point(target_saturation[i])))
    axis.set_xlim(-1.17,1.17)
    axis.set_ylim(-1.17,1.17)
    axis.set_aspect('equal', adjustable='box')
    axis.set_xlabel(r'$-b_g / \sqrt{C_g^2+|E_g|}$', fontsize=10)
    axis.set_ylabel(r'$+a_g / \sqrt{C_g^2+|E_g|}$', fontsize=10)
    axis.tick_params(labelsize=8)
    axis.grid(True, color='#e4e8ee', linewidth=.6, alpha=.7, zorder=0)
    for spine in axis.spines.values():
        spine.set_edgecolor('#c4ccd6')
    axis.set_title(f'{TONE_NAMES[tone_index]} · input $J_{{HK}}$ = {height:.3f}',
                   fontsize=12.5, pad=12, color='#1f2937')
    axis.text(.025, .975,
              f'Guarded contour H: {shown_contour[:, 0].min():.2f}–{shown_contour[:, 0].max():.2f}\n'
              f'Raw $J_A < 0$ before guard: {np.count_nonzero(signed)}/{len(signed)} points',
              transform=axis.transAxes, fontsize=8, va='top', color='#475569',
              bbox=dict(facecolor='white', edgecolor='none', alpha=.9))

    all_source = np.concatenate([contour.q, source, *(item[0] for item in rings),
                                 *(item[0] for item in spokes)])
    all_source_energy = np.concatenate([contour.energy, source_energy,
                                        *(item[1] for item in rings), *(item[1] for item in spokes)])
    all_target = np.concatenate([transformed, targets, *(item[2] for item in rings),
                                 *(item[2] for item in spokes)])
    all_target_energy = np.concatenate([contour_energy, target_energy,
                                        *(item[3] for item in rings), *(item[3] for item in spokes)])
    unscaled=Color(replace(model.settings,web=replace(model.settings.web,
        log_scale=tuple((0.,)*6 for _ in range(4)))),model.tone)
    unscaled_q,unscaled_e=apply(unscaled,all_source,all_source_energy,height)
    scaled_points=bounded_project(all_target,all_target_energy)
    unscaled_points=bounded_project(unscaled_q,unscaled_e)
    if not np.array_equal(np.isfinite(scaled_points),np.isfinite(unscaled_points)):
        raise AssertionError('Scale changed finite saturation membership')
    finite=np.isfinite(scaled_points)
    scale_error=float(np.max(abs(scaled_points[finite]-unscaled_points[finite]),initial=0.))
    if not np.allclose(scaled_points,unscaled_points,rtol=2e-12,atol=2e-12,equal_nan=True):
        raise AssertionError(f'Scale changed raw saturation geometry: {scale_error}')
    guarded_q, guarded_e = guarded(all_target, all_target_energy, all_source_energy)
    unscaled_guarded_q, unscaled_guarded_e = guarded(unscaled_q, unscaled_e, all_source_energy)
    guarded_scale_displacement = float(np.max(abs(
        bounded_project(guarded_q, guarded_e)
        -bounded_project(unscaled_guarded_q, unscaled_guarded_e)), initial=0.))
    scales=np.exp2(np.asarray(web.settings.log_scale)[tone_index])
    radii=web.geometry.radii[tone_index]*np.exp2(np.asarray(web.settings.log_chroma)[tone_index])
    angles=web.geometry.angles[tone_index]+np.deg2rad(np.asarray(web.settings.hue_degrees)[tone_index])
    pre_ab=radii[:,None]*np.stack((np.cos(angles),np.sin(angles)),axis=-1)
    pre_q,pre_e=at_height(pre_ab,height)
    adapted,_=model.adaptation.apply(pre_q,pre_e,height,web.geometry.radii[tone_index],
                                    web.geometry.energy[tone_index])
    expected_corners=scales[:,None]*adapted[:,1:]
    expected_center=np.asarray(model.settings.adaptance[tone_index])
    expected_ab=np.vstack((expected_center,expected_corners))
    handle_error = float(np.max(abs(expected_ab - targets[:, 1:])))
    if handle_error > 2e-10 * max(1., float(np.max(abs(targets[:,1:])))):
        raise AssertionError(f'{TONE_NAMES[tone_index]} handle target error: {handle_error}')
    if reset and (not np.array_equal(all_source, all_target)
                  or not np.array_equal(all_source_energy, all_target_energy)):
        raise AssertionError('Reset web must exactly preserve every plotted coordinate and energy')
    neutral_q, neutral_energy = at_height(np.zeros((1, 2)), height)
    neutral_out, neutral_eout = apply(model, neutral_q, neutral_energy, height)
    if not np.allclose(neutral_out[0,1:],expected_center,rtol=0,atol=2e-12):
        raise AssertionError('Center must show the actual Adaptance output')
    return dict(
        name=TONE_NAMES[tone_index], input_jhk=height, handles=handles,
        source_contour=measurements(contour.q, contour.energy),
        transformed_contour=measurements(transformed, contour_energy),
        guarded_contour=measurements(shown_contour, shown_contour_energy),
        raw_output_samples=measurements(all_target, all_target_energy),
        plotted_output_samples=measurements(guarded_q, guarded_e),
        maximum_source_contour_height_error=float(np.max(abs(contour.q[:, 0] - height))),
        maximum_handle_ab_error=handle_error,
        maximum_scale_saturation_error=scale_error,
        maximum_guarded_scale_displacement=guarded_scale_displacement,
        maximum_reset_coordinate_error=float(np.max(abs(all_target - all_source))) if reset else None,
        reset_energy_exact=bool(np.array_equal(all_source_energy, all_target_energy)) if reset else None,
        center_target_exact=True,
    )


def render(path, settings, tone, contours, fixture_name):
    color = Color(settings, tone)
    reset = not color.active
    figure, axes = plt.subplots(2, 2, figsize=(14.2, 13.9), dpi=155)
    figure.suptitle(f'Warp · center and six corners · {fixture_name}', fontsize=19,
                    y=.972, color='#172b42')
    figure.text(.5, .943, 'Rec.709 template at each tone · bounded post-guard Warp saturation · orientation (−b, +a)',
                ha='center', fontsize=10.5, color='#526176')
    panels = [panel(axis, color, i, contour, reset=reset)
              for i, (axis, contour) in enumerate(zip(axes.flat, contours))]
    legend = [
        Line2D([], [], color=SOURCE_COLOR, linewidth=1.8, linestyle='--', label='Source Rec.709 outer contour / spokes'),
        Line2D([], [], color=TARGET_COLOR, linewidth=1.8, label='Transformed contour / web'),
        Line2D([], [], marker='o', linestyle='none', markerfacecolor='white', markeredgecolor='#64748b', label='Fixed Rec.709 target'),
        Line2D([], [], marker='o', linestyle='none', color='#4269d7', label='Transformed handle'),
    ]
    figure.legend(handles=legend, loc='lower center', bbox_to_anchor=(.5, .067),
                  ncol=3, fontsize=9, frameon=False, columnspacing=1.9)
    figure.text(.5, .018,
        'Modified contours, rings, spokes, and handles are shown after H–K repair using each sample’s original energy.\n'
        'The chart is (a,b)/√(C²+|E|), oriented (−b,+a); raw grading and handoffs remain unchanged.\n'
        'Arrows show the hue/chroma → selective cone Adaptance → saturation-preserving scale edit. '
        'Labels stay at fixed Rec.709 targets.\n'
        'A static plot has no active-handle rim. The cube guard is not applied.',
        fontsize=8.8, color='#526176', ha='center', va='bottom', linespacing=1.55)
    figure.subplots_adjust(left=.065, right=.975, top=.90, bottom=.15, hspace=.27, wspace=.12)
    figure.savefig(path, facecolor='white', metadata={'Title': f'Warp: {fixture_name}'})
    plt.close(figure)
    return dict(fixture=fixture_name, settings=serializable(settings), panels=panels)


def summary(report):
    lines = [
        '# Warp: guarded compact saturation pad', '',
        'Reproduce: `buck2 build //libraries/perceptual-grade-reference:tonal_web`.', '',
        'The main PNG uses the selected fixture; `tonal-web-reset.png` verifies the exact identity web. '
        'Both show actual Rec.709 perimeter-ray intersections with each constant-J_HK input slice. '
        'Source RGB is nonnegative with unrestricted exposure (no upper channel bound). '
        'Contour points are solved in geometry preparation, outside per-pixel grading.', '',
        'Raw grading and Stack handoffs are unchanged. Modified output contours, rings, spokes and handles '
        'are shown after the H–K repair using each plotted sample’s original carried source energy; the cube '
        'guard is not applied. The chart projects (a,b)/sqrt(C²+|E|), E=J_A|J_A|, oriented as (−b,+a). '
        'The H–K guard moves a raw E=0 chromatic state inside the compact disk, so the raw threshold is not '
        'a universal circle after repair. In the live pad, its contextual rim is shown only for an active '
        'handle crossing that threshold.', '',
        '| Fixture | Tone | Input J_HK | Guarded contour J_HK | Raw negative-J_A points | Handle a/b error |',
        '| --- | --- | ---: | ---: | ---: | ---: |',
    ]
    for fixture in report['fixtures']:
        for item in fixture['panels']:
            values = item['guarded_contour']
            lines.append(f"| {fixture['fixture']} | {item['name']} | {item['input_jhk']:.6f} | "
                         f"{values['minimum_jhk']:.6f} – {values['maximum_jhk']:.6f} | "
                         f"{item['transformed_contour']['signed_count']} / {values['count']} | {item['maximum_handle_ab_error']:.3g} |")
    lines += ['', 'The report records raw model results and separately the guarded coordinates used by the pad. '
              'Reset checks require bit-exact coordinate and carried-energy equality before repair. The center '
              'is the actual Adaptance output; all seven raw targets are checked against their algebraic '
              'positions. Raw Scale saturation is checked before the guard; a separate measured displacement '
              'reports how nonlinear H–K repair changes the displayed saturation. Modified inner rings are '
              'dimmed; original inner rings are omitted. R/Y/G/C/B/M tags remain at fixed Rec.709 targets.', '',
              'Use custom settings with `buck2 run //libraries/perceptual-grade-reference:tonal_web_tool -- --settings /absolute/settings.json '
              '--output-dir /absolute/output`. The JSON has `web` (containing `log_chroma`, `hue_degrees`, and '
              '`log_scale`, each a 4×6 array), `adaptance` (4×2), and `adaptance_half_saturation`. Tone rows are Shadows, Midtones, White, Highlights; '
              'handle columns are red, yellow, green, cyan, blue, magenta. Missing fields use reset values, with direct half-influence saturation R defaulting to 0.25.', '',
              'The mixed fixture varies all three control fields by tone and includes a Shadows-blue '
              'outward edit explicitly crossing H²=66C. Source boundary geometry is sampled with '
              f'{CONTOUR_SAMPLES_PER_EDGE} points per RGB-perimeter edge. Interior rings are fixed-H '
              'radial fractions of that contour.', '']
    return '\n'.join(lines)


def generate(output_dir, settings_path=None, fixture='mixed'):
    tone = Tone(ToneSettings())
    reset = ColorSettings()
    geometry = TonalWeb(reset.web, tone, encoder=encode_cones).geometry
    mixed = mixed_settings(geometry)
    selected = load_settings(settings_path) if settings_path else (reset if fixture == 'reset' else mixed)
    selected_name = 'custom edits' if settings_path else ('reset' if fixture == 'reset' else 'mixed edits')
    contours = [rec709_contour(float(h), reference=tone.reference,
                              samples_per_edge=CONTOUR_SAMPLES_PER_EDGE, encoder=encode_cones) for h in geometry.anchors]
    output_dir.mkdir(parents=True, exist_ok=True)
    reset_report = render(output_dir / 'tonal-web-reset.png', reset, tone, contours, 'reset')
    selected_report = render(output_dir / 'tonal-web.png', selected, tone, contours, selected_name)
    report = dict(
        version=5,
        geometry=dict(source_gamut='Linear Rec.709', input_slices='constant signed J_HK',
                      pad_projection='bounded saturation after H–K guard: (a_g,b_g)/sqrt(C_g²+abs(E_g)), displayed (-b_g,+a_g)',
                      reference_nits=tone.reference, anchors=np.asarray(geometry.anchors).tolist(),
                      source_perimeter='RGB rays through R,Y,G,C,B,M; solve appearance height per ray; no upper RGB channel bound',
                      samples_per_edge=CONTOUR_SAMPLES_PER_EDGE,
                      ring_fractions=list(RING_FRACTIONS), hk_guard_applied=True,
                      cube_guard_applied=False, guard_reference_energy='original source sample'),
        fixtures=[reset_report, selected_report],
    )
    if selected_name == 'mixed edits' and selected_report['panels'][0]['handles'][5]['target_energy'] >= 0:
        raise AssertionError('Mixed fixture Shadows-blue must cross into signed negative J_A')
    (output_dir / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    (output_dir / 'summary.md').write_text(summary(report))
    (output_dir / 'mixed-settings.json').write_text(json.dumps(serializable(mixed), indent=2) + '\n')
    (output_dir / 'reset-settings.json').write_text(json.dumps(serializable(reset), indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--settings', type=Path, help='JSON Warp settings object; overrides --fixture')
    parser.add_argument('--fixture', choices=('mixed', 'reset'), default='mixed')
    args = parser.parse_args()
    generate(args.output_dir, args.settings, args.fixture)
