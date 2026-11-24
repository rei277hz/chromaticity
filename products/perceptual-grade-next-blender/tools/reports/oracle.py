"""Current reference stage composition, with no input repair or export guards.

This module belongs exclusively to evaluation. Its equations and adapters come
from the reference package, never from the node implementation under test.
"""
from dataclasses import asdict
import numpy as np
from color_tools.perceptual_grade_reference import model, grading, appearance
from color_tools.perceptual_grade_reference.responses import INVERSE, GAMMA, eccentricity
from color_tools.perceptual_grade_reference.unified_chroma import UnifiedChroma, UnifiedChromaSettings


def parameters(linear, tone):
    """Return linear settings and the post-Tone viewing context for Warp."""
    return (model.LinearSettings(**asdict(linear)),
            grading.ToneSettings(reference_nits=tone.reference_nits, peak_nits=tone.peak_nits))


def reference_chroma(tone):
    """Use reference 3A equations at Blender's continuous Fit setting."""
    settings = asdict(tone)
    settings.pop('reference_nits')
    settings['fit'] = round(tone.fit)
    reference = UnifiedChroma(UnifiedChromaSettings(**settings))
    if settings['fit'] != tone.fit:
        curve = reference.tone
        curve.width = grading.fit_width(tone.fit)
        norms = np.array([grading.kernel(1., left, right, float(curve.width))
                          for left, right in zip(curve.knots[:-1], curve.knots[1:])])
        curve._slope_upper_bound = curve.slope + np.sum(curve.residual/norms)
    return reference


def adapters(space):
    white = model.xyz_from_xy(model.WHITES['D65'])
    matrix = model.rgb_matrix(space)
    if space == 'ACEScg':
        matrix = model.adaptation(model.xyz_from_xy(model.WHITES['ACES']), white, 'Bradford') @ matrix
    return white, matrix, np.linalg.inv(matrix)


def evaluate(rgb, linear, tone, space):
    lp, _ = parameters(linear, tone)
    white, before, after = adapters(space)
    correction = model.linear_matrix(lp, white)
    rgb = np.asarray(rgb, dtype=np.float64)
    # Preserve the exact scene-neutral contribution, as Model._forward does.
    xyz = rgb[...,1,None]*white + (rgb-rgb[...,1,None]) @ before.T
    xyz = xyz @ correction.T
    first = xyz @ after.T
    encoded = appearance.encode(xyz, white, 203.)
    mapped = reference_chroma(tone).apply(encoded)
    fl, aw = appearance.response_constants(203.)
    hue = np.arctan2(mapped.q[...,2], mapped.q[...,1])
    ab = mapped.q[...,1:]*(aw/(1204*eccentricity(hue)))[...,None]
    ac = aw*np.sign(mapped.ja)*(abs(mapped.ja)/100)**(1/GAMMA)
    responses = np.concatenate((ac[...,None], ab), axis=-1) @ INVERSE.T
    margin = 400-np.max(abs(responses), axis=-1)
    valid = np.isfinite(responses).all(axis=-1) & (margin > 0)
    output = np.zeros_like(rgb)
    if np.any(valid):
        decoded = appearance.decode(mapped.q[valid], mapped.ja[valid]*abs(mapped.ja[valid]), white, 203.)
        output[valid] = decoded @ after.T
    valid &= np.isfinite(output).all(axis=-1)
    output[~valid] = 0
    return dict(rgb=output, linear=first, encoded=encoded, tone=mapped,
                responses=responses, valid=valid, margin=margin,
                well_conditioned=valid & (np.max(abs(responses),axis=-1)<=300))


def metrics(actual, expected, mask=None):
    actual, expected = np.asarray(actual), np.asarray(expected)
    if mask is None:
        mask = np.ones(expected.shape[:-1],dtype=bool)
    error = np.max(abs(actual-expected),axis=-1)
    magnitude = np.max(abs(expected),axis=-1)
    normalized = error/(1+magnitude)
    selected = normalized[mask]
    near_black = mask & (magnitude <= .001)
    index = int(np.argmax(np.where(mask,normalized,-1))) if np.any(mask) else None
    return {'samples':int(np.sum(mask)), 'max_normalized':float(np.max(selected,initial=0)),
            'p99_normalized':float(np.percentile(selected,99)) if len(selected) else 0.,
            'max_absolute':float(np.max(error[mask],initial=0)),
            'near_black_max_absolute':float(np.max(error[near_black],initial=0)),
            'worst_index':index,
            'worst_actual':actual[index].tolist() if index is not None else None,
            'worst_expected':expected[index].tolist() if index is not None else None}


def evaluate_full(rgb, linear, tone, color, space):
    """Independent raw entry -> all stages -> guarded export; no input repair.

    Deliberately compose the reference's stage APIs rather than Model.forward,
    whose entry adapter includes the excluded LUT input projection.

    The reference Color stage owns the H-K-before-Scale policy. This oracle
    delegates that complete Stage 3 transition to its guarded implementation,
    then applies only the independent RGB cube containment at export.
    """
    from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard
    lp, _ = parameters(linear, tone)
    cp = grading.ColorSettings(**asdict(color))
    reference = model.Model(model.Settings(
        linear=lp, color=cp, tone_chroma=reference_chroma(tone).settings,
    ), space)
    before = evaluate(rgb, linear, tone, space)
    toned = before['tone']
    graded = reference.color.apply_state(toned)
    reference_energy = toned.ja*abs(toned.ja)
    boundary = exact_boundary(reference)
    bq, be, native = cube_guard(boundary, graded.q, graded.energy)
    to_scene = reference.xyz_to_rgb @ reference.cones_to_xyz @ np.linalg.inv(boundary.matrix)
    # Preserve the neutral contribution, as the native adapter does.
    output = native[..., 1, None]+(native-native[..., 1, None]) @ to_scene.T
    responses = boundary.responses(bq, be)
    margin = 400-np.max(abs(responses), axis=-1)
    valid = np.isfinite(output).all(axis=-1) & (margin > 0)
    return dict(rgb=output, linear=before['linear'], encoded=before['encoded'], tone=toned,
                color=graded, reference_energy=reference_energy,
                hk_q=graded.q, hk_energy=graded.energy,
                boundary_q=bq, boundary_energy=be, native_rgb=native, to_scene=to_scene,
                responses=responses, valid=valid, margin=margin,
                well_conditioned=valid.copy(), guarded=True)


def exact_boundary(reference):
    """The reference decoder/search with no optional fitted-capacity seed.

    The fit is expressly only an acceleration seed in cube_guard. Starting its
    independent 56-step bracketed search without it avoids importing production
    fitted assets and their unrelated workflow build closure into this oracle.
    """
    from color_tools.perceptual_grade_reference.cube import Context, white_response

    class UnseededContext(Context):
        def capacity(self, ja, hue):
            return np.zeros(np.broadcast_shapes(np.shape(ja), np.shape(hue)))

    rw = white_response(reference.fl)
    white = 100*(3.05*rw/reference.aw)**GAMMA
    return UnseededContext(white, reference.fl, reference.aw, reference.native_matrix, {})


def state_metrics(actual_q, actual_energy, reference_q, reference_energy,
                  input_q, input_energy):
    """Conditioned local-state errors, plus unconditioned energy diagnostics."""
    actual_q, reference_q, input_q = map(np.asarray, (actual_q, reference_q, input_q))
    actual_energy, reference_energy, input_energy = map(np.asarray,
        (actual_energy, reference_energy, input_energy))
    ci = np.hypot(input_q[..., 1], input_q[..., 2])
    co = np.hypot(reference_q[..., 1], reference_q[..., 2])
    se = 1+abs(input_energy)+abs(reference_energy)+66*(ci+co)
    sh = 1+np.sqrt(abs(input_energy)+66*ci)+np.sqrt(abs(reference_energy)+66*co)
    sc = 1+ci+co
    de = abs(actual_energy-reference_energy)
    significant = abs(reference_energy) > 1e-5*se
    return dict(h=float(np.max(abs(actual_q[..., 0]-reference_q[..., 0])/sh, initial=0)),
                ab=float(np.max(np.hypot(*(actual_q[..., 1:]-reference_q[..., 1:]).T)/sc, initial=0)),
                energy=float(np.max(de/se, initial=0)),
                energy_absolute=float(np.max(de, initial=0)),
                energy_relative=float(np.max(de/(1+abs(reference_energy)), initial=0)),
                significant_sign_mismatches=int(np.sum(significant &
                    (np.sign(actual_energy) != np.sign(reference_energy)))))
