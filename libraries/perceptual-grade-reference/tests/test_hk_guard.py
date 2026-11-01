"""Historical H-K export repair, signed-energy integration and inverse contracts."""
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model.hk_guard import guard, guard_scaled, inverse, requested_square
from color_tools.perceptual_grade_reference.responses import State, hk_energy
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_reference.stack import Stack
from color_tools.color_core.scaled import Scalar as S


class HKGuardTests(unittest.TestCase):
    @staticmethod
    def samples():
        h, ratio, ref, angle = np.meshgrid(np.geomspace(.01,1000,9),
            [0.,.2,.6,.9,1.,1.5,4.,16.],[.1,1.,10.],[0.,.7,3.7],indexing='ij')
        h,ratio,ref,angle=[v.ravel() for v in (h,ratio,ref,angle)]
        c=ratio*h*h/66
        return np.column_stack((h,c*np.cos(angle),c*np.sin(angle))),hk_energy(h,c),ref*h*h

    def test_historical_formula_and_projection_properties(self):
        q,e,e0=self.samples();h=q[:,0];c=np.hypot(q[:,1],q[:,2]);x=h*h;d=x-66*c
        delta=e0*x/(e0+x);active=d<delta
        expected=d.copy();t=(delta[active]-d[active])/delta[active]
        expected[active]=delta[active]/(1+4*t+10*t*t)**.25
        out,energy=guard(q,e,e0);cg=np.hypot(out[:,1],out[:,2])
        np.testing.assert_allclose(energy,expected,rtol=3e-14,atol=1e-12)
        self.assertTrue(np.all(energy>0))
        self.assertTrue(np.all(out[:,0]>=h))
        self.assertTrue(np.all(out[:,0]<=1.2*h))
        self.assertTrue(np.all(cg<=c*(1+4e-16)))
        self.assertTrue(np.all(cg>=0))
        np.testing.assert_allclose(out[:,0]**2,energy+66*cg,rtol=1e-14,atol=1e-12)
        chromatic=c>0
        np.testing.assert_allclose(out[chromatic,1:]/cg[chromatic,None],q[chromatic,1:]/c[chromatic,None],atol=4e-16)
        np.testing.assert_array_equal(out[~active],q[~active])
        np.testing.assert_array_equal(energy[~active],e[~active])

    def test_energy_knee_matches_identity_slope_and_curvature(self):
        # Hold H/reference fixed and move D through delta by varying chroma.
        h=10.;e0=100.;delta=50.
        for step in (.01,.001):
            d=delta+np.arange(-2,3)*step;c=(h*h-d)/66
            q=np.column_stack((np.full(5,h),c,np.zeros(5)))
            _,e=guard(q,hk_energy(h,c),e0)
            left=(e[2]-e[1])/step;right=(e[3]-e[2])/step
            self.assertLess(abs(left-right),2e-6)
            self.assertLess(abs((e[2]-2*e[1]+e[0])/step**2),2e-4)

    def test_signed_deficit_conversion_and_tiny_carried_energy(self):
        h=np.array([5.,10.,15.]);c=np.full(3,100/66)
        e=hk_energy(h,c)
        np.testing.assert_allclose(requested_square(e,c),h*h-66*c,atol=3e-14)
        self.assertNotEqual(e[0],h[0]**2-66*c[0])
        # Rounded H has lost a small positive departure; carried E must survive.
        tiny=1e-30;q=np.array([np.sqrt(66.),1.,0.])
        out,energy=guard(q,tiny,tiny)
        np.testing.assert_array_equal(out,q);self.assertEqual(float(energy),tiny)

    def test_scaled_and_vector_active_branches_agree(self):
        q,e,e0=self.samples();ids=np.arange(0,len(q),31)
        out,energy=guard(q[ids],e[ids],e0[ids])
        for row,value,ref,expected,ee in zip(q[ids],e[ids],e0[ids],out,energy):
            actual,ae=guard_scaled(list(map(S,row)),S(value),S(ref))
            np.testing.assert_allclose(list(map(float,actual)),expected,rtol=4e-14,atol=1e-13)
            self.assertLess(abs(float(ae)-ee)/(1+ee),3e-14)
        # Same ratios outside IEEE exponent range remain meaningful.
        q0=[S(10.,2000),S(20.,4000),S()]
        repaired,ee=guard_scaled(q0,S(-1800.,4000),S(100.,4000))
        self.assertGreater(ee,0);self.assertGreaterEqual(repaired[0],q0[0])
        self.assertLessEqual(repaired[0],1.2*q0[0])

    def test_zero_reference_black_neutral_negative_h_and_input_validation(self):
        q=np.array([[0.,0.,0.],[10.,0.,0.],[5.,20.,0.],[-10.,20.,0.]])
        e=hk_energy(q[:,0],np.hypot(q[:,1],q[:,2]))
        out,energy=guard(q,e,np.zeros(4))
        np.testing.assert_array_equal(out[:2],q[:2]);np.testing.assert_array_equal(energy[:2],e[:2])
        self.assertEqual(energy[2],0)
        np.testing.assert_array_equal(out[3],q[3]);self.assertEqual(energy[3],e[3])
        result=inverse(out[:3],energy[:3],np.zeros(3))
        np.testing.assert_array_equal(result.status,'degenerate')
        for bad in ([np.nan,0,0],[np.inf,0,0],[1,2]):
            with self.assertRaises(ValueError):guard(bad,1,1)
        with self.assertRaises(ValueError):guard([1,0,0],np.inf,1)
        with self.assertRaises(ValueError):inverse([1,0,0],2,1)
        self.assertEqual(guard(np.empty((0,3)),np.empty(0),1)[0].shape,(0,3))

    def test_fixed_reference_inverse_roundtrip(self):
        q,e,e0=self.samples();out,energy=guard(q,e,e0)
        found=inverse(out,energy,e0)
        self.assertTrue(np.all(np.isin(found.status,['root','identity'])),np.unique(found.status))
        self.assertLess(found.residual.max(),2e-10)
        np.testing.assert_allclose(found.state.q,q,rtol=5e-11,atol=5e-11)
        # Guard is a one-time repair, not an idempotent projector.
        twice,te=guard(out,energy,e0)
        self.assertGreater(np.max(abs(twice-out)),.01)

    def test_active_inverse_retains_tiny_carried_energy(self):
        q=np.array([10.,100/66,0.]);tiny=1e-30;ref=1e-20
        out,energy=guard(q,tiny,ref)
        self.assertGreater(float(energy),tiny)
        found=inverse(out,energy,ref)
        self.assertEqual(str(found.status),'root')
        self.assertGreater(float(found.state.energy),0.)
        np.testing.assert_allclose(found.state.energy,tiny,rtol=5e-5,atol=0.)

    def test_inverse_extreme_radial_ratio_does_not_overflow(self):
        q=np.array([1e-60,1e240,0.]);e=hk_energy(q[0],q[1]);ref=1e-120
        out,energy=guard(q,e,ref)
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            found=inverse(out,energy,ref)
        self.assertEqual(str(found.status),'root')
        np.testing.assert_allclose(found.state.q,q,rtol=2e-13,atol=0.)

    def test_pipeline_repairs_negative_energy_before_cube_export(self):
        settings=Settings(color=ColorSettings(global_gain=3))
        model=Model(settings);old=Model(settings,hk_guard=False)
        rgb=np.array([[.1,.2,.3],[0.,.2,0.],[.2,0.,0.],[0,0,0.]])
        raw=model.grade_state(model.enter_native(rgb))
        self.assertTrue(np.any(raw.energy<0))
        expected_e=model.tone.apply(model.enter_native(rgb)).ja**2
        np.testing.assert_allclose(raw.reference_energy,expected_e)
        output=model.release_state(raw,guard=True)
        np.testing.assert_allclose(output,model.forward_native(rgb),atol=3e-13,rtol=3e-12)
        self.assertTrue(np.all((output>=0)&(output<=1024)))
        self.assertTrue(np.all(output[:3].max(axis=-1)>0))
        self.assertTrue(np.all(old.forward_native(rgb[:3])==0))
        np.testing.assert_array_equal(model.release_state(raw),old.release_state(raw))
        # A bare handoff/seed intentionally has no invented tone reference.
        bare=State(raw.q,raw.energy)
        np.testing.assert_array_equal(model.release_state(bare,guard=True),old.release_state(bare,guard=True))
        np.testing.assert_array_equal(model.release_state(bare,guard=True,reference_energy=raw.reference_energy),output)
        model.vector_controls=False
        scaled=model.grade_state(model.enter_native(rgb))
        np.testing.assert_allclose(model.release_state(scaled,guard=True),output,rtol=4e-12,atol=3e-13)

    def test_rgb_inverse_uses_forward_repair_without_standalone_inverse(self):
        model=Model(Settings(color=ColorSettings(global_gain=1)))
        source=np.array([[.1,.2,.3],[.7,.2,.1]])
        target=model.forward(source)
        with patch('color_tools.perceptual_grade_core.model.hk_guard.inverse',side_effect=AssertionError('Nested guard inverse')):
            result=model.inverse(target)
        self.assertTrue(np.all(result.status=='root'),result)
        np.testing.assert_allclose(model.forward(result.value),target,rtol=2e-8,atol=5e-10)

    def test_matching_stack_pair_keeps_raw_cancellation(self):
        settings=Settings(color=ColorSettings(global_gain=3))
        rgb=np.array([[.1,.2,.3],[0.,.2,0.],[1024.,0.,0.],[0,0,0.]])
        stack=Stack([settings,settings],['FORWARD','INVERSE'])
        with patch('color_tools.perceptual_grade_reference.model.hk_guard',side_effect=AssertionError('Guarded handoff')):
            np.testing.assert_allclose(stack.apply_native(rgb),rgb,rtol=3e-12,atol=1e-11)


if __name__=='__main__':unittest.main()
