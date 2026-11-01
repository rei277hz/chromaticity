"""Case-scoped development gates for prepared Color fields and native stages.

This module describes acceptance policies used by development audits and
tests. Raw scalar/local precision thresholds retain the exact alternating
extreme Web exception. Layout admission for Web toes, Color coefficients and
compact Adaptance uses the authorized HDR worsening budget, while retaining
raw precision results as diagnostics.
"""

import numpy as np

from color_tools.perceptual_grade_nodes.color_prepare import COLOR_TABLE_ERROR_LIMIT, _audit_field


ALTERNATING_WEB_LIMIT = 1e-4
DEFAULT_WEB_LOCAL_LIMIT = 1e-5
WEB_TOE_HDR_WORSENING_LIMIT = 0.05
FIELD_HDR_WORSENING_LIMIT = 0.05
HDR_ADMITTED_FIELDS = frozenset(('Web toes', 'Color coefficients', 'Adaptance parameters'))


def texture_admission_policy(role):
    """Describe layout admission without changing raw precision gate results.

    Callers must report raw scalar/local failures and enforce the complete HDR
    comparison, safety and final-output checks before admitting a candidate.
    """
    if role == 'Web toes':
        return dict(basis='hdr_toe_worsening',
                    max_worsening_codes=WEB_TOE_HDR_WORSENING_LIMIT,
                    scalar_precision='diagnostic', local_precision='diagnostic')
    if role in ('Color coefficients', 'Adaptance parameters'):
        return dict(basis='hdr_worsening', max_worsening_codes=FIELD_HDR_WORSENING_LIMIT,
                    scalar_precision='diagnostic', local_precision='diagnostic')
    return dict(basis='scalar_and_local', scalar_precision='required',
                local_precision='required')


def _web_settings(settings):
    """Return a WebSettings-like object from ColorSettings or WebSettings."""
    return getattr(settings, 'web', settings)


def is_alternating_extreme_web(settings):
    """Whether *settings* is the approved alternating extreme Web family.

    The selector is intentionally exact.  It accepts the three equivalent
    uniform hue rotations used by seam tests, while requiring the authored
    +/-16 log-chroma and +/-8 log-scale checkerboards.
    """
    web = _web_settings(settings)
    # The exception is for the standalone extreme Web case.  Do not let the
    # same Web handles relax precision for a compound Color configuration.
    if web is not settings:
        try:
            if (np.any(np.asarray(settings.lightness, dtype=float) != 0.)
                    or np.any(np.asarray(settings.chroma, dtype=float) != 0.)
                    or np.any(np.asarray(settings.adaptance, dtype=float) != 0.)
                    or float(settings.global_gain) != 0.
                    or float(settings.lightness_fit) != 0.
                    or float(settings.chroma_fit) != 0.
                    or float(settings.adaptance_half_saturation) != .25):
                return False
        except (AttributeError, TypeError, ValueError):
            return False
    try:
        chroma = np.asarray(web.log_chroma, dtype=float)
        scale = np.asarray(web.log_scale, dtype=float)
        hue = np.asarray(web.hue_degrees, dtype=float)
    except (AttributeError, TypeError, ValueError):
        return False
    if chroma.shape != (4, 6) or scale.shape != (4, 6) or hue.shape != (4, 6):
        return False
    checker = np.fromfunction(lambda row, col: (-1.) ** (row + col), (4, 6))
    if not np.array_equal(chroma, 16. * checker) or not np.array_equal(scale, 8. * checker):
        return False
    if not np.isfinite(hue).all() or not np.all(hue == hue[0, 0]):
        return False
    return float(hue[0, 0]) in (0., -360., 360.)


def policy_identity(settings):
    """Stable short identity suitable for audit receipts and deduplication."""
    return 'web_alternating_extremes_1e-4' if is_alternating_extreme_web(settings) else 'default'


def scalar_limits(table, settings):
    """Return effective scalar/interpolation limits for one prepared table.

    ``conditioned`` is the field error gate.  The interpolation limits are
    only applicable when the table declares corresponding columns; callers
    should retain the table's declared limit for other metrics.
    """
    name = getattr(table, 'name', '')
    exceptional = is_alternating_extreme_web(settings)
    conditioned = COLOR_TABLE_ERROR_LIMIT
    relative = float(getattr(table, 'relative_interpolation_limit', 0.) or 0.)
    absolute = float(getattr(table, 'absolute_interpolation_limit', 0.) or 0.)
    policy = 'default'
    if exceptional and name in ('Web parameters', 'Web toes'):
        conditioned = ALTERNATING_WEB_LIMIT
        policy = 'web_alternating_extremes_1e-4'
        if name == 'Web parameters' and getattr(table, 'absolute_columns', ()):
            absolute = ALTERNATING_WEB_LIMIT
        if name == 'Web toes' and getattr(table, 'relative_columns', ()):
            relative = ALTERNATING_WEB_LIMIT
    return dict(conditioned=float(conditioned), relative_interpolation=relative,
                absolute_interpolation=absolute, policy=policy)


def field_passed(table, settings):
    """Assess a completed field audit under the effective case policy.

    A partial audit cannot pass even if its currently observed maximum is below
    a relaxed threshold.  This prevents early-stop lower bounds from being
    recorded as complete acceptance evidence.
    """
    limits = scalar_limits(table, settings)
    if not bool(getattr(table, 'audit_complete', False)):
        return False
    conditioned = getattr(table, 'max_error', None)
    if conditioned is None or not np.isfinite(float(conditioned)):
        return False
    if float(conditioned) > limits['conditioned']:
        return False
    if getattr(table, 'relative_columns', ()):
        relative = getattr(table, 'max_relative_interpolation_error', None)
        if relative is None or not np.isfinite(float(relative)) or float(relative) > limits['relative_interpolation']:
            return False
    if getattr(table, 'absolute_columns', ()):
        absolute = getattr(table, 'max_absolute_interpolation_error', None)
        if absolute is None or not np.isfinite(float(absolute)) or float(absolute) > limits['absolute_interpolation']:
            return False
    return True


def audit_field(table, evaluator, knots=(), *, settings, stop_on_failure=True):
    """Retain complete HDR-admitted diagnostics and every relaxed-case probe."""
    name = getattr(table, 'name', '')
    complete_required = (name in HDR_ADMITTED_FIELDS or
                         (is_alternating_extreme_web(settings) and name == 'Web parameters'))
    return _audit_field(table, evaluator, knots,
                        stop_on_failure=False if complete_required else stop_on_failure)


def web_local_limit(settings, stage):
    """Native local Web-stage limit for the exact alternating family."""
    return (ALTERNATING_WEB_LIMIT if stage == 'web' and is_alternating_extreme_web(settings)
            else DEFAULT_WEB_LOCAL_LIMIT)

