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
from color_tools.perceptual_grade_reference.responses import requested_energy


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
