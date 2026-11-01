"""Production Stack adapters, handoffs and current portable inverse contracts."""
from dataclasses import replace
from unittest.mock import patch
import unittest
import numpy as np
from color_tools.perceptual_grade_blender.model.baker import Baker
from color_tools.perceptual_grade_core.model import transforms, linear, tone, color, lut
from color_tools.perceptual_grade_core.model.bake_inverse import TOLERANCE
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tests.support import reference as oracle


def settings(gain=0.,exposure=0.,**controls):
    return transforms.Settings.from_parameters(linear.Parameters(exposure=exposure),tone.Parameters(),
        color.Parameters(global_gain=gain,**controls),linear.GradeSpace('D65'))


def reference(values,directions):
    return LegacyCapacityBakeStack([oracle.evaluator(v.tone,v.color,v.space,v.matrix)[0].settings for v in values],directions,hk_guard=False)


class InverseTests(unittest.TestCase):
    def test_matching_pair_cancels_projection_folds_and_black_plateaus(self):
        x=np.array([[0.,.2,0.],[2.,-.1,1.],[1024.,0.,1.],[2048.,10.,2.],[0,0,0]])
        a=settings(10.,1.,c_high_2=-16.)
        a=replace(a,tone=replace(a.tone,input_black=1.))
        b=replace(a,matrix=tuple(map(tuple,.5*np.eye(3))))
        stack=transforms.Stack([a,b],directions=['FORWARD','INVERSE'])
        expected=oracle.input_repair(x@stack.input_matrix.T,lut.AP1_Y)@stack.output_matrix.T
        with patch.object(stack.prepare().kernels[0],'grade',side_effect=AssertionError('Matching pair must cancel')):
            actual=stack.apply_native(x)
        np.testing.assert_allclose(actual,expected,rtol=2e-6,atol=2e-6)

    def test_raw_handoff_retains_signed_energy_without_response_decode(self):
        value=settings(10.);core=transforms.Stack([value],directions=['INVERSE']).prepare()
        kernel=core.kernels[0];x=np.array([[0.,.2,0.],[.2,0.,0.]],dtype='f4')
        raw=kernel.grade(kernel.tone_state(kernel.enter(x)))
        self.assertTrue((raw[:,3]<0).all())
        actual=core.solvers[0].evaluate(raw,True)
        ref=reference([value],['INVERSE']);k=ref.kernels[0]
        expected=ref.solvers[0].evaluate(k.grade(k.tone_state(k.enter(x))),True)
        np.testing.assert_allclose(actual,expected,rtol=1e-5,atol=1e-6)
        self.assertLess(float(actual[:,3].max()),float(TOLERANCE))

    def test_nonmatching_raw_inverse_agrees_with_portable_oracle(self):
        value=settings(.15,web_hue_1_0=3.,web_chroma_1_1=.03,adaptance_b_2=.01,j_high_1=.1)
        core=transforms.Stack([value],directions=['INVERSE']).prepare()
        x=np.array([[.1,.2,.3],[.7,.2,.1]],dtype='f4');k=core.kernels[0]
        raw=k.grade(k.tone_state(k.enter(x)));actual=core.solvers[0].evaluate(raw,True)
        expected=reference([value],['INVERSE']).solvers[0].evaluate(raw,True)
        np.testing.assert_allclose(actual,expected,rtol=2e-6,atol=1e-6)
        self.assertLess(float(actual[:,3].max()),float(TOLERANCE))

    def test_all_transitions_and_inverse_endings(self):
        a,b=settings(.1,.2),settings(.05,-.1)
        native=np.array([[.1,.2,.3],[.6,.4,.2]])
        for directions in (['FORWARD','FORWARD'],['FORWARD','INVERSE'],['INVERSE','FORWARD'],['INVERSE','INVERSE']):
            with self.subTest(directions=directions):
                stack=transforms.Stack([a,b],directions=directions)
                expected=reference([a,b],directions).apply_native(native)
                np.testing.assert_allclose(stack.apply_native(native),expected,rtol=2e-5,atol=2e-6)
                rgb=native@lut.FROM_LUT.T
                np.testing.assert_allclose(stack.apply_native(native)@lut.FROM_LUT.T,stack.apply(rgb),rtol=2e-5,atol=2e-6)

    def test_final_inverse_matrix_preserves_signed_and_above_cube_output(self):
        a=settings();b=replace(a,matrix=((.001,.0008,0.),(0.,.001,0.),(0.,0.,.001)))
        stack=transforms.Stack([a,b],directions=['FORWARD','INVERSE'])
        x=np.array([[0,1024,0],[1024,0,1024]],dtype=float)
        result=stack.apply_native(x)
        self.assertLess(result.min(),0);self.assertGreater(result.max(),1024)
        np.testing.assert_allclose(result,x@stack.output_matrix.T,rtol=2e-6,atol=2e-6)
        cube=Baker(stack,progressive=True).finish_preview()
        np.testing.assert_array_equal(cube.values.reshape(-1,3),lut.lattice(33).astype('f4'))
        np.testing.assert_allclose(stack.apply_cube(cube,x@lut.FROM_LUT.T)@lut.TO_LUT.T,result,rtol=2e-6,atol=2e-6)

    def test_endpoint_matrix_keys_and_singular_inverse(self):
        a=settings(.1);b=settings(.2)
        original=transforms.Stack([a,b],directions=['FORWARD','INVERSE'])
        changed=transforms.Stack([replace(a,matrix=tuple(map(tuple,2*np.eye(3)))),
                                 replace(b,matrix=tuple(map(tuple,.5*np.eye(3))))],directions=original.directions)
        self.assertEqual(lut.signature(original),lut.signature(changed));self.assertNotEqual(original.cache_key,changed.cache_key)
        internal=transforms.Stack([a,b,a],directions=['FORWARD','FORWARD','INVERSE'])
        self.assertNotEqual(lut.signature(internal),lut.signature(transforms.Stack([a,changed.entries[1],a],directions=internal.directions)))
        singular=replace(a,matrix=((1.,0.,0.),(0.,0.,0.),(0.,0.,1.)))
        with self.assertRaisesRegex(ValueError,'singular'):transforms.Stack([singular],directions=['INVERSE'])
        transforms.Stack([singular])
        transforms.Stack([replace(a,matrix=((-1.,0.,0.),(0.,1.,0.),(0.,0.,1.)))],directions=['INVERSE'])

    def test_approximation_is_finite_and_batch_order_independent(self):
        inverse=transforms.Stack([settings(-8.)],directions=['INVERSE']).prepare().solvers[0]
        x=np.array([[.2,.01,.1],[0,0,0.]],dtype='f4')
        value=inverse.evaluate(x)
        self.assertTrue(np.isfinite(value).all());self.assertGreater(value[0,3],TOLERANCE)
        np.testing.assert_array_equal(inverse.evaluate(x[::-1])[::-1],value)
        stack=transforms.Stack([settings(-8.)],directions=['INVERSE'])
        with self.assertRaisesRegex(ValueError,'triples'):stack.bake_native(np.zeros(6))
