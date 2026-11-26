"""Full reference contracts, with no imports of either implementation under test."""
from dataclasses import replace
import unittest
from unittest.mock import patch
import colour
import numpy as np
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import (Model, Settings, LinearSettings, source_white,
    xyz_from_xy, linear_matrix, adaptation, WHITES)
from color_tools.perceptual_grade_reference.grading import ToneSettings, LOW_Y
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_reference.appearance import CAT16, viewing, encode, decode
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_reference.cube_guard import guard
from color_tools.perceptual_grade_reference.export import OutputCompressionSettings, compress_saturation
from color_tools.perceptual_grade_reference.responses import State, requested_energy, signed_hk
from color_tools.perceptual_grade_reference.stack import Stack


class ModelTests(unittest.TestCase):
    def test_linear_first_reset_is_repaired_linear_result(self):
        from color_tools.perceptual_grade_reference.export import input_repair
        base=Model()
        native_to_xyz=base.cones_to_xyz@np.linalg.inv(base.boundary.matrix)
        matrix=np.array([[1.,.3,-.1],[0.,.6,.2],[.05,0.,1.2]])
        xyz_matrix=native_to_xyz@matrix@np.linalg.inv(native_to_xyz)
        engine=Model(Settings(linear=LinearSettings(matrix=tuple(map(tuple,xyz_matrix)))))
        native=np.array([[-.1,.4,2.],[4096.,30.,0.],[0.,0.,0.],[.2,.7,.3],[100.,1024.,3.]])
        expected=input_repair(native@matrix.T,base.acescg_y)
        result=engine.forward_native(native)
        error=np.max(abs(result-expected),axis=-1)/(1+np.max(abs(expected),axis=-1))
        self.assertLessEqual(error.max(),2e-12)
        previous=input_repair(input_repair(native,base.acescg_y)@matrix.T,base.acescg_y)
        self.assertGreater(np.max(abs(previous-expected)),.01)
        integers=np.array([[2**63-1,-2**61,1]],dtype=np.int64)
        np.testing.assert_array_equal(base.forward_native(integers),base.forward_native(integers.astype(float)))

    def test_linear_identity_adaptation_and_exposure(self):
        for name, xy in [('D65',WHITES['D65'])]:
            white = xyz_from_xy(xy)
            lp = LinearSettings(source_xy=xy)
            np.testing.assert_array_equal(linear_matrix(lp, white), np.eye(3))
            np.testing.assert_allclose(adaptation(xyz_from_xy(WHITES['D65']), white) @ xyz_from_xy(WHITES['D65']), white, atol=5e-15)
            np.testing.assert_allclose(linear_matrix(replace(lp, exposure=2), white), 4*np.eye(3), atol=0)
            creative = replace(lp, balance=(.5, -.25), spread=(20, -10), heading=(15, -7))
            matrix = linear_matrix(creative, white)
            np.testing.assert_allclose(matrix @ white, white, atol=5e-15)
            np.testing.assert_allclose(np.linalg.inv(matrix) @ matrix, np.eye(3), atol=5e-15)

    def test_source_white_projection(self):
        for xy in [(0., 0.), (.55, .5), (.9, .9), (.1, .01), (.3127, .329)]:
            safe = source_white(xy)
            self.assertTrue(np.all(CAT16 @ xyz_from_xy(safe) > 0))
            np.testing.assert_allclose(source_white(safe), safe, atol=1e-14)
        point = np.array([.55, .5])
        normal = CAT16[2, :2]-CAT16[2, 2]
        offset = CAT16[2, 2]-.002*np.linalg.norm(normal)
        expected = point-(normal @ point+offset)/(normal @ normal)*normal
        np.testing.assert_allclose(source_white(point), expected, rtol=0, atol=2e-15)
        with self.assertRaises(ValueError):
            source_white((np.nan, .3))

    def test_nonlinear_xyz_skips_only_the_linear_stage(self):
        model=Model(Settings(linear=LinearSettings(exposure=2)))
        reset=Model()
        xyz=np.array([[0.,0.,0.],[.2,.3,.4],[-.1,.3,2.]])
        np.testing.assert_array_equal(model.nonlinear_xyz(xyz),reset.forward_xyz(xyz))
        self.assertGreater(np.max(abs(model.forward_xyz(xyz)-model.nonlinear_xyz(xyz))),.1)

    def test_reset_signed_hdr_shapes_and_independence(self):
        x = np.array([[0., 0., 0.], [-.1, .3, 2.], [-1., -1., -1.], [128., 128., 128.], [1e-10, .2, 1.]])
        for space in ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg'):
            model = Model(space=space)
            rgb_output=model.forward(x)
            self.assertTrue((rgb_output@model.to_acescg.T>=-3e-13).all())
            np.testing.assert_array_equal(rgb_output[0],0.)
            if model.neutral_rgb:np.testing.assert_array_equal(rgb_output[2],0.)
            np.testing.assert_allclose(model.forward([.2,.3,.4]),[.2,.3,.4],rtol=2e-12,atol=0)
            xyz_output=model.forward_xyz(x)
            native=xyz_output@model.xyz_to_rgb.T@model.to_acescg.T
            self.assertTrue((native>=-3e-13).all())
            np.testing.assert_array_equal(xyz_output[0],0.)
            np.testing.assert_array_equal(model.forward_xyz(-model.white),0.)
            np.testing.assert_allclose(model.forward_xyz(.18*model.rgb_white),.18*model.rgb_white,rtol=2e-12,atol=0)
            self.assertEqual(model.forward(np.empty((0, 3))).shape, (0, 3))
        with self.assertRaises(ValueError):
            Model().forward_xyz([np.nan, 0, 0])
        with self.assertRaises(ValueError):
            Model(Settings(color=ColorSettings(web={"hue_degrees":[[1.,2.]]})))
        with self.assertRaises(ValueError):
            Model(Settings(tone=ToneSettings(fit=np.inf)))

    def test_hue_grade_uses_raw_coordinates_and_saved_cube_export(self):
        model=Model(Settings(color=ColorSettings(web=WebSettings(hue_degrees=((30.,)*6,)*4))))
        native=np.array([[.2,.3,.4],[0.,1.,0.],[0.,938.63,0.]])
        np.testing.assert_array_equal(model.prepare_native(native),native)
        state=model.enter_native(native)
        a=encode(native@np.linalg.inv(model.native_matrix).T@model.cones_to_xyz.T,model.white)
        np.testing.assert_allclose(state.q,a.q,rtol=2e-14,atol=2e-12)
        stage2=model.tone.apply(state)
        expected=model.release_state(model.grade_state(state),guard=True)
        np.testing.assert_allclose(model.forward_native(native),expected,rtol=2e-12,atol=1e-10)

    def test_explicit_unguarded_handoff_carries_raw_signed_energy(self):
        first=Model(Settings(color=ColorSettings(global_gain=3)),hk_guard=False)
        second=Model(Settings(color=ColorSettings(global_gain=-3)),hk_guard=False)
        x=np.array([[.2,.3,.4],[0.,1.,0.],[0.,938.63,0.],[0.,0.,0.]])
        original=first.enter_native(x)
        intermediate=first.grade_state(original)
        result_state=second.grade_state(intermediate)
        result=second.release_state(result_state,guard=True)
        self.assertTrue(np.any(intermediate.energy<0))
        self.assertGreater(np.max(np.hypot(intermediate.q[:,1],intermediate.q[:,2])),
                           np.max(np.hypot(original.q[:,1],original.q[:,2])))
        np.testing.assert_allclose(result_state.q,original.q,rtol=3e-15,atol=3e-13)
        np.testing.assert_allclose(result,x,rtol=2e-12,atol=2e-10)
        self.assertTrue((result>=0).all() and (result<=1024).all())
        np.testing.assert_array_equal(result[-1],0.)

    def test_default_handoff_carries_repaired_energy_and_export_does_not_repair_again(self):
        first=Model(Settings(color=ColorSettings(global_gain=3)))
        second=Model(Settings(color=ColorSettings(global_gain=-3)))
        source=np.array([[.2,.3,.4],[0.,1.,0.],[0.,938.63,0.],[0.,0.,0.]])
        intermediate=first.grade_state(first.enter_native(source))
        self.assertTrue(np.all(intermediate.energy>=0))
        result=second.grade_state(intermediate)
        self.assertTrue(np.all(result.energy>=0))
        with patch('color_tools.perceptual_grade_reference.grading.guard',
                   side_effect=AssertionError('Export must not repeat H-K repair')):
            output=second.release_state(result,guard=True)
        self.assertTrue(np.all((output>=0)&(output<=1024)))
        np.testing.assert_array_equal(output[-1],0.)

    def test_raw_release_preserves_signed_energy_in_vector_and_scaled_decode(self):
        model=Model(Settings(color=ColorSettings(global_gain=3)),hk_guard=False)
        x=np.array([[.2,.3,.4],[0.,1.,0.],[.1,.2,.3],[0.,0.,0.]])
        state=model.grade_state(model.enter_native(x))
        self.assertTrue(np.any(state.energy<0))
        before=model.cones_to_xyz@np.linalg.inv(model.boundary.matrix)
        expected=decode(state.q,state.energy,model.white)@np.linalg.inv(before).T
        actual=model.release_state(state,guard=False)
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_allclose(actual,expected,rtol=3e-12,atol=2e-10)
        np.testing.assert_allclose(model.forward_native(x,export=False),actual,rtol=2e-12,atol=1e-10)
        for q,energy,rgb in zip(state.q,state.energy,actual):
            scaled=model.boundary.decode_scaled([S(v) for v in q],S(energy))
            np.testing.assert_allclose([float(v) for v in scaled],rgb,rtol=3e-12,atol=2e-10)


class OutputCompressionTests(unittest.TestCase):
    def test_curve_preserves_signed_energy_and_hue(self):
        for dtype in (np.float32, np.float64):
            with self.subTest(dtype=dtype):
                ja = np.array([4, 4, 4, -4, -4, 4, 0, 0], dtype=dtype)
                chroma = np.array([0, 1, 2, 4, 6, 400, 0, 4], dtype=dtype)
                direction = np.array([.6, -.8], dtype=dtype)
                q = np.column_stack((signed_hk(ja, chroma), chroma[:, None] * direction)).astype(dtype)
                state = State(q, ja * abs(ja))
                off = compress_saturation(state, OutputCompressionSettings())
                np.testing.assert_array_equal(off.q, q)
                result = compress_saturation(state, OutputCompressionSettings(enabled=True))
                self.assertEqual(result.q.dtype, dtype)
                np.testing.assert_array_equal(result.energy, state.energy)
                # The first three rows are neutral, below the knee, and at the knee.
                np.testing.assert_array_equal(result.q[:3], q[:3])
                expected = np.array([0, 1, 2, 3, 10 / 3, 3.99, 0, 0], dtype=dtype)
                np.testing.assert_allclose(result.q[:, 1:], expected[:, None] * direction, rtol=5e-7)
                np.testing.assert_allclose(result.q[:, 0], signed_hk(ja, expected), rtol=5e-7)

    def test_scaled_energy_survives_near_black(self):
        # This J_A and its signed energy are both smaller than any float64.
        ja = S(-1., -1500)
        q = np.array([signed_hk(ja, S(1.)), S(), S(-1.)], dtype=object)
        state = State(q, np.array(ja * abs(ja), dtype=object))
        result = compress_saturation(state, OutputCompressionSettings(enabled=True))
        self.assertEqual(result.q.dtype, object)
        self.assertEqual(result.energy.item(), state.energy.item())
        self.assertEqual(result.q[1], S())
        self.assertAlmostEqual(float(result.q[2] / ja), 1.)
        self.assertEqual(result.q[0], signed_hk(ja, abs(result.q[2])))

    def test_curve_is_monotone_and_asymptotic(self):
        saturation = np.array([0., .25, .5, .75, 1., 2., 8., 1e12])
        ja = np.full(saturation.shape, 4.)
        chroma = saturation * ja
        q = np.column_stack((signed_hk(ja, chroma), chroma, np.zeros_like(chroma)))
        state = State(q, ja * ja)
        compressed = compress_saturation(
            state, OutputCompressionSettings(enabled=True),
        )
        mapped = np.hypot(compressed.q[:, 1], compressed.q[:, 2]) / ja
        self.assertTrue(np.all(np.diff(mapped) >= 0.))
        self.assertTrue(np.all(mapped <= 1.))
        self.assertGreater(mapped[-1], .999999999)

    def test_invalid_limits_are_rejected(self):
        for knee, ceiling in [(-1., 1.), (1., 1.), (2., 1.), (0., 8.1),
                              (np.nan, 1.), (0., np.inf)]:
            with self.subTest(knee=knee, ceiling=ceiling), self.assertRaises(ValueError):
                Model(Settings(output_compression=OutputCompressionSettings(
                    enabled=True, knee=knee, ceiling=ceiling)))

    def test_rgb_adapters_agree_on_compressed_xyz(self):
        base = Model()
        xyz = np.array([[1., .04, .02], [.1, .2, 2.]]) @ base.rgb_to_xyz.T
        settings = Settings(output_compression=OutputCompressionSettings(True, .1, .3))
        expected = Model(settings).forward_xyz(xyz)
        self.assertGreater(np.max(abs(expected - base.forward_xyz(xyz))), .01)
        for space in ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg'):
            with self.subTest(space=space):
                model = Model(settings, space=space)
                rgb = xyz @ model.xyz_to_rgb.T
                np.testing.assert_allclose(model.forward(rgb) @ model.rgb_to_xyz.T,
                                           expected, rtol=2e-12, atol=1e-12)

    def test_reset_grade_applies_compression_only_at_final_export(self):
        base = Model()
        settings = OutputCompressionSettings(enabled=True, knee=.1, ceiling=.3)
        compressed = Model(Settings(output_compression=settings))
        points = np.array([[1., .03, .01], [.01, .2, 2.], [.18, .18, .18]])
        graded = base.grade_state(base.enter_native(points))
        state = compress_saturation(graded, settings)
        expected = guard(base.boundary, state.q, state.energy)[2]
        self.assertGreater(np.max(abs(expected - points)), .01)
        np.testing.assert_allclose(compressed.release_output_state(graded), expected,
                                   rtol=2e-12, atol=1e-12)
        np.testing.assert_allclose(compressed.forward_native(points), expected, rtol=2e-12, atol=1e-12)
        np.testing.assert_array_equal(compressed.forward_native(points, export=False),
                                      base.forward_native(points, export=False))

        first = Settings(output_compression=settings)
        np.testing.assert_allclose(Stack([first, Settings()]).apply_native(points), points,
                                   rtol=2e-12, atol=1e-12)
        np.testing.assert_allclose(Stack([first, first]).apply_native(points), expected,
                                   rtol=2e-12, atol=1e-12)

    def test_inverse_last_compresses_after_the_linear_inverse(self):
        base = Model()
        native_to_xyz = base.cones_to_xyz @ np.linalg.inv(base.boundary.matrix)
        gains = np.array([.5, 1., 2.])
        linear = native_to_xyz @ np.diag(gains) @ np.linalg.inv(native_to_xyz)
        controls = OutputCompressionSettings(enabled=True, knee=.1, ceiling=.3)
        final = Settings(linear=LinearSettings(matrix=tuple(map(tuple, linear))),
                         output_compression=controls)
        points = np.array([[.6, .1, .2], [.03, .05, 1.]])
        model = Model(Settings(output_compression=controls))
        expected = model.release_output_state(model.encode_native(points / gains))
        wrong_order = model.forward_native(points) / gains
        self.assertGreater(np.max(abs(expected - wrong_order)), .01)
        for entries, directions in (([final], ['INVERSE']),
                                    ([Settings(), final], ['FORWARD', 'INVERSE'])):
            with self.subTest(directions=directions):
                actual = Stack(entries, directions).apply_native(points)
                np.testing.assert_allclose(actual, expected, rtol=2e-12, atol=1e-12)

    def test_inverse_only_white_endpoint_with_compression_off(self):
        final = Settings(linear=LinearSettings(exposure=-1.))
        actual = Stack([final], ['INVERSE']).apply_native([[700., 700., 700.]])
        np.testing.assert_array_equal(actual, [[1024., 1024., 1024.]])

    def test_standalone_inverse_solves_the_uncompressed_grade(self):
        base = Model()
        settings = OutputCompressionSettings(enabled=True, knee=0., ceiling=.1)
        compressed = Model(Settings(output_compression=settings))
        rgb = np.array([[.5, .2, .1]])
        xyz = rgb @ base.rgb_to_xyz.T
        for method, values in [('inverse', rgb), ('inverse_xyz', xyz)]:
            with self.subTest(method=method):
                actual = getattr(compressed, method)(values)
                expected = getattr(base, method)(values)
                np.testing.assert_array_equal(actual.value, expected.value)
                np.testing.assert_array_equal(actual.residual, expected.residual)
                np.testing.assert_array_equal(actual.status, expected.status)
