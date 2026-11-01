"""Independent-oracle checks; this module is test-only and not bundled."""

import unittest
from unittest.mock import patch

import numpy as np

from color_tools.perceptual_grade_next_core.model import GradeModel, StackModel
from color_tools.perceptual_grade_next_core.model.linear import rgb_xyz_matrices
from color_tools.perceptual_grade_next_core.model.stack import _attributes, _repair_ap1
from color_tools.perceptual_grade_next_core.settings import (
    ColorSettings,
    GradeSettings,
    LinearSettings,
    StackEntry,
    StackSettings,
    ToneSettings,
)
from color_tools.perceptual_grade_reference.model import Model as ReferenceModel
from color_tools.perceptual_grade_reference.model import LinearSettings as ReferenceLinearSettings
from color_tools.perceptual_grade_reference.model import Settings as ReferenceSettings
from color_tools.perceptual_grade_reference.grading import (
    ColorSettings as ReferenceColorSettings,
    ToneSettings as ReferenceToneSettings,
)
from color_tools.perceptual_grade_reference.stack import Stack as ReferenceStack
from color_tools.perceptual_grade_reference.cube import Context as ReferenceCubeContext
from color_tools.perceptual_grade_next_core.model.grade import CubeBoundary
from color_tools.color_core import modcam16
from color_tools.perceptual_grade_reference import model as reference_model_module


def _reference_settings(settings):
    return ReferenceSettings(
        white="D65",
        linear=ReferenceLinearSettings(
            exposure=settings.linear.exposure,
            source_xy=settings.linear.source_white_xy,
            balance=settings.linear.balance,
            spread=settings.linear.spread,
            heading=settings.linear.heading,
            matrix=settings.linear.matrix,
        ),
        tone=ReferenceToneSettings(
            input_nits=settings.tone.input_nits,
            fit=settings.tone.fit,
            reference_nits=settings.tone.reference_nits,
            peak_nits=settings.tone.peak_nits,
        ),
        color=ReferenceColorSettings(
            lightness=settings.color.lightness,
            chroma=settings.color.chroma,
            adaptance=settings.color.adaptance,
            lightness_fit=settings.color.lightness_fit,
            chroma_fit=settings.color.chroma_fit,
            global_gain=settings.color.global_gain,
            adaptance_half_saturation=settings.color.adaptance_half_saturation,
            web={
                "log_chroma": settings.color.web.log_chroma,
                "hue_degrees": settings.color.web.hue_degrees,
                "log_scale": settings.color.web.log_scale,
            },
        ),
    )


def _reference_boundary(fl, aw, matrix):
    boundary = CubeBoundary(fl, aw, modcam16.GAMMA)
    np.testing.assert_allclose(matrix, boundary.matrix, rtol=0.0, atol=2e-15)
    white_power = (fl * 1024.0) ** 0.42
    white_response = 400.0 * white_power / (27.13 + white_power)
    white = 100.0 * (3.05 * white_response / aw) ** modcam16.GAMMA
    return _ReferenceBoundaryContext(white, fl, aw, np.asarray(matrix), {})


class _ReferenceBoundaryContext(ReferenceCubeContext):
    def capacity(self, ja, hue):
        # The independent guard only uses capacity as an optional search seed.
        return np.zeros(np.broadcast_shapes(np.shape(ja), np.shape(hue)))


class IndependentReferenceTests(unittest.TestCase):
    def test_neutral_and_color_samples_match_the_independent_forward_model(self):
        settings = GradeSettings(
            tone=ToneSettings(input_nits=(0.0, 1.2, 36.54, 203.0, 1000.0), fit=0.5),
            color=ColorSettings(global_gain=0.15),
        )
        actual = GradeModel(settings).apply_rgb(
            np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18),
                        (0.8, 0.25, 0.08), (0.02, 0.12, 0.4)))
        )
        with patch.object(reference_model_module, "cube_context", side_effect=_reference_boundary):
            reference = ReferenceModel(_reference_settings(settings), "Linear Rec.709").forward(
                np.asarray(((0.0, 0.0, 0.0), (0.18, 0.18, 0.18),
                            (0.8, 0.25, 0.08), (0.02, 0.12, 0.4)))
            )
        np.testing.assert_allclose(actual, reference, rtol=3e-6, atol=3e-5)

    def test_linear_tone_color_and_web_match_the_independent_forward_model(self):
        settings = GradeSettings(
            linear=LinearSettings(
                exposure=0.12,
                balance=(0.035, -0.025),
                spread=(2.0, -1.5),
                heading=(3.0, -2.0),
            ),
            tone=ToneSettings(
                input_nits=(0.0, 1.2, 42.0, 203.0, 1200.0),
                fit=0.4,
                peak_nits=1200.0,
            ),
            color=ColorSettings(
                lightness=((0.25, 0.05, 0.0, 0.0),) + ((0.0, 0.0, 0.0, 0.0),) * 3,
                chroma=((-0.04, 0.03, 0.0, 0.0),) + ((0.0, 0.0, 0.0, 0.0),) * 3,
                adaptance=((0.15, -0.08), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
                global_gain=0.025,
                web={
                    "hue_degrees": ((2.0, 0.0, 0.0, 0.0, 0.0, 0.0),) + ((0.0,) * 6,) * 3,
                    "log_chroma": ((0.08, 0.0, 0.0, 0.0, 0.0, 0.0),) + ((0.0,) * 6,) * 3,
                    "log_scale": ((0.03, 0.0, 0.0, 0.0, 0.0, 0.0),) + ((0.0,) * 6,) * 3,
                },
            ),
        )
        samples = np.asarray(((0.7, 0.24, 0.08), (0.04, 0.19, 0.5)))
        actual = GradeModel(settings).apply_rgb(samples)
        with patch.object(reference_model_module, "cube_context", side_effect=_reference_boundary):
            reference = ReferenceModel(_reference_settings(settings), "Linear Rec.709").forward(samples)
        np.testing.assert_allclose(actual, reference, rtol=5e-6, atol=5e-5)

    def test_two_forward_stages_match_the_independent_stack(self):
        first = GradeSettings(
            linear=LinearSettings(exposure=0.08, balance=(0.02, -0.01)),
            color=ColorSettings(global_gain=0.07),
        )
        second = GradeSettings(
            linear=LinearSettings(exposure=-0.035, spread=(1.0, -0.5)),
            tone=ToneSettings(input_nits=(0.0, 1.5, 40.0, 203.0, 1100.0), fit=0.25,
                              peak_nits=1100.0),
            color=ColorSettings(global_gain=-0.025),
        )
        entries = (StackEntry(first, "FORWARD"), StackEntry(second, "FORWARD"))
        samples = np.asarray(((0.35, 0.14, 0.045), (0.03, 0.1, 0.28)))
        stack = StackModel(StackSettings(entries))
        actual = stack.apply_rgb(samples)
        rec709_to_xyz, _ = rgb_xyz_matrices("Linear Rec.709")
        _, xyz_to_ap1 = rgb_xyz_matrices("ACEScg")
        source_ap1 = (samples @ rec709_to_xyz.T) @ xyz_to_ap1.T
        raw = stack.models[0].grade_ap1(_repair_ap1(source_ap1[0]))
        inverse_result = stack.inverse(stack.models[1], source_ap1[0], raw_state=raw)
        reproduced = _attributes(stack.models[1].grade_ap1(_repair_ap1(inverse_result.value)))
        wanted = _attributes(raw)
        measured = np.max(np.abs(reproduced - wanted) / (1.0 + np.abs(wanted)))
        self.assertAlmostEqual(float(inverse_result.residual), float(measured), places=12)
        self.assertIn(str(inverse_result.status), ("root", "approximate"))
        with patch.object(reference_model_module, "cube_context", side_effect=_reference_boundary):
            reference = ReferenceStack(
                [_reference_settings(first), _reference_settings(second)],
                ("FORWARD", "FORWARD"),
            ).apply(samples)
        np.testing.assert_allclose(actual, reference, rtol=5e-6, atol=5e-5)

    def test_nonmatching_forward_inverse_stack_matches_reference_and_reports_residual(self):
        first = GradeSettings(color=ColorSettings(global_gain=0.08))
        inverse = GradeSettings(color=ColorSettings(global_gain=0.025))
        entries = (StackEntry(first, "FORWARD"), StackEntry(inverse, "INVERSE"))
        samples = np.asarray(((0.35, 0.14, 0.045),))
        actual = StackModel(StackSettings(entries)).apply_rgb(samples)
        with patch.object(reference_model_module, "cube_context", side_effect=_reference_boundary):
            reference = ReferenceStack(
                [_reference_settings(first), _reference_settings(inverse)],
                ("FORWARD", "INVERSE"),
            ).apply(samples)
        np.testing.assert_allclose(actual, reference, rtol=3e-5, atol=1e-5)

    def test_inverse_first_and_inverse_forward_orders_match_reference(self):
        inverse = GradeSettings(
            linear=LinearSettings(exposure=0.06, balance=(0.015, -0.01)),
            color=ColorSettings(global_gain=0.035),
        )
        forward = GradeSettings(
            linear=LinearSettings(exposure=-0.025, spread=(0.5, -0.25)),
            color=ColorSettings(global_gain=-0.02),
        )
        samples = np.asarray(((0.24, 0.12, 0.05), (0.035, 0.11, 0.31)))

        for entries in (
            (StackEntry(inverse, "INVERSE"),),
            (StackEntry(inverse, "INVERSE"), StackEntry(forward, "FORWARD")),
        ):
            with self.subTest(directions=tuple(entry.direction for entry in entries)):
                actual = StackModel(StackSettings(entries)).apply_rgb(samples)
                with patch.object(reference_model_module, "cube_context",
                                  side_effect=_reference_boundary):
                    reference = ReferenceStack(
                        [_reference_settings(entry.settings) for entry in entries],
                        tuple(entry.direction.value for entry in entries),
                    ).apply(samples)
                np.testing.assert_allclose(actual, reference, rtol=3e-5, atol=1e-5)

    def test_forward_inverse_identity_stack_reproduces_legal_inputs(self):
        grade = GradeSettings()
        stack = StackModel(StackSettings((
            StackEntry(grade, "FORWARD"),
            StackEntry(grade, "INVERSE"),
        )))
        values = np.asarray(((0.05, 0.2, 0.7), (0.3, 0.1, 0.025)))
        np.testing.assert_allclose(stack.apply_rgb(values), values, rtol=2e-7, atol=2e-7)


if __name__ == "__main__":
    unittest.main()
