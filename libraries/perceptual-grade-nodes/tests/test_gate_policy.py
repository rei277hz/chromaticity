"""Regression tests for the narrowly scoped Web precision exception."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

from color_tools.perceptual_grade_nodes import ColorSettings, WebSettings
from tools.perceptual_grade_nodes.gate_policy import (
    audit_field, field_passed, is_alternating_extreme_web, scalar_limits, web_local_limit,
    texture_admission_policy)


def alternating(hue=0.):
    signs = np.fromfunction(lambda row, col: (-1.) ** (row + col), (4, 6))
    return ColorSettings(web=WebSettings(
        log_chroma=tuple(map(tuple, 16*signs)),
        log_scale=tuple(map(tuple, 8*signs)),
        hue_degrees=((hue,)*6,)*4))


class WebGatePolicyTests(unittest.TestCase):
    def test_hdr_admission_keeps_raw_scalar_results_and_other_role_gates(self):
        toe = texture_admission_policy('Web toes')
        self.assertEqual(toe['max_worsening_codes'], .05)
        self.assertEqual(toe['scalar_precision'], 'diagnostic')
        row = SimpleNamespace(name='Web toes', relative_columns=(0,), absolute_columns=(),
            relative_interpolation_limit=1e-6, absolute_interpolation_limit=0.,
            max_error=.01, max_relative_interpolation_error=.03, audit_complete=True)
        self.assertFalse(field_passed(row, ColorSettings()))
        self.assertFalse(field_passed(row, alternating()))
        for role in ('Color coefficients', 'Adaptance parameters'):
            policy = texture_admission_policy(role)
            self.assertEqual(policy['max_worsening_codes'], .05)
            self.assertEqual(policy['scalar_precision'], 'diagnostic')
            self.assertEqual(policy['local_precision'], 'diagnostic')
            failed = SimpleNamespace(name=role, relative_columns=(), absolute_columns=(),
                                     max_error=.01, audit_complete=True)
            self.assertFalse(field_passed(failed, ColorSettings()))
        for role in ('Web parameters', 'Tone', 'Output boundary'):
            self.assertEqual(texture_admission_policy(role)['scalar_precision'], 'required')
            self.assertEqual(texture_admission_policy(role)['local_precision'], 'required')
        self.assertEqual(web_local_limit(ColorSettings(), 'web'), 1e-5)

    def test_exact_checkerboard_and_seam_rotations_receive_exception(self):
        for hue in (0., -360., 360.):
            settings = alternating(hue)
            self.assertTrue(is_alternating_extreme_web(settings))
            self.assertEqual(web_local_limit(settings, 'web'), 1e-4)
            self.assertEqual(web_local_limit(settings, 'terms'), 1e-5)
            self.assertEqual(web_local_limit(settings, 'scale'), 1e-5)

    def test_nearby_or_compound_controls_keep_original_limits(self):
        controls = []
        base = alternating()
        changed = np.asarray(base.web.log_chroma).copy()
        changed[0, 0] = np.nextafter(changed[0, 0], np.inf)
        controls.append(ColorSettings(web=WebSettings(log_chroma=tuple(map(tuple, changed)),
            log_scale=base.web.log_scale)))
        controls.append(ColorSettings(web=WebSettings(
            log_chroma=tuple(map(tuple, -np.asarray(base.web.log_chroma))),
            log_scale=base.web.log_scale)))
        controls.append(ColorSettings(web=WebSettings(log_chroma=base.web.log_chroma,
            log_scale=base.web.log_scale, hue_degrees=((0., -360., 0., 0., 0., 0.),)*4)))
        controls.append(ColorSettings(chroma=((1., 0., 0., 0.),)*4, web=base.web))
        for settings in controls:
            self.assertFalse(is_alternating_extreme_web(settings))
            self.assertEqual(web_local_limit(settings, 'web'), 1e-5)

    def test_limits_are_role_scoped_and_complete_audit_is_required(self):
        settings = alternating()
        params = SimpleNamespace(name='Web parameters', absolute_columns=(1,), relative_columns=(),
            absolute_interpolation_limit=3e-6, relative_interpolation_limit=0.)
        toes = SimpleNamespace(name='Web toes', absolute_columns=(), relative_columns=(0,),
            absolute_interpolation_limit=0., relative_interpolation_limit=1e-6)
        other = SimpleNamespace(name='Adaptance parameters', absolute_columns=(), relative_columns=(),
            absolute_interpolation_limit=0., relative_interpolation_limit=0.)
        self.assertEqual(scalar_limits(params, settings)['absolute_interpolation'], 1e-4)
        self.assertEqual(scalar_limits(toes, settings)['relative_interpolation'], 1e-4)
        self.assertEqual(scalar_limits(other, settings)['conditioned'], 1e-5)
        row = dict(name='Web parameters', relative_columns=(), absolute_columns=(1,),
            max_error=1e-4, max_relative_interpolation_error=0.,
            max_absolute_interpolation_error=1e-4, audit_complete=True)
        self.assertTrue(field_passed(SimpleNamespace(**row), settings))
        row['audit_complete'] = False
        self.assertFalse(field_passed(SimpleNamespace(**row), settings))
        row.update(audit_complete=True, max_absolute_interpolation_error=1.00001e-4)
        self.assertFalse(field_passed(SimpleNamespace(**row), settings))
        for invalid in (None, float('nan'), float('inf')):
            row['max_absolute_interpolation_error'] = invalid
            self.assertFalse(field_passed(SimpleNamespace(**row), settings))

    def test_exceptional_audit_is_always_complete(self):
        extreme = SimpleNamespace(name='Web parameters')
        ordinary = SimpleNamespace(name='Web parameters')
        toes = SimpleNamespace(name='Web toes')
        with patch('tools.perceptual_grade_nodes.gate_policy._audit_field', side_effect=lambda *a, **k: k):
            self.assertFalse(audit_field(extreme, None, settings=alternating())['stop_on_failure'])
            self.assertTrue(audit_field(ordinary, None, settings=ColorSettings())['stop_on_failure'])
            self.assertFalse(audit_field(toes, None, settings=ColorSettings())['stop_on_failure'])
            for name in ('Color coefficients', 'Adaptance parameters'):
                self.assertFalse(audit_field(SimpleNamespace(name=name), None,
                                             settings=ColorSettings())['stop_on_failure'])
            self.assertTrue(audit_field(SimpleNamespace(name='Web parameters'), None,
                                        settings=ColorSettings())['stop_on_failure'])


if __name__ == '__main__':
    unittest.main()
