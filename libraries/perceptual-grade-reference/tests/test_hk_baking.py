"""Reference H-K export and validated raw-candidate inverse on the portable CPU."""
from unittest.mock import patch
import unittest
import numpy as np

from color_tools.perceptual_grade_core.model import bake_inverse
from color_tools.perceptual_grade_core.model.bake import Kernel
from color_tools.perceptual_grade_core.model.bake_cache import CachedKernel,Store
from color_tools.perceptual_grade_core.model.bake_inverse import TOLERANCE
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Model,Settings
from color_tools.perceptual_grade_reference.responses import hk_energy
from color_tools.perceptual_grade_reference.stack_bake import BakeStack


class HKBakingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=BakeStack([Settings()])
        cls.table=cls.base.table
        cls.points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[.2,.01,.1],[0,0,0]],dtype='f4')

    def stack(self,settings,direction='FORWARD',**kwargs):
        return BakeStack([settings],[direction],self.table,**kwargs)

    def test_guard_repairs_positive_height_negative_energy_and_is_export_only(self):
        settings=Settings(color=ColorSettings(global_gain=3.))
        reference=self.stack(settings);production=self.stack(settings,hk_guard=False)
        k=reference.kernels[0];old=production.kernels[0]
        toned=k.tone_state(k.enter(self.points));raw=k.grade(toned)
        repaired=k._hk_export(raw,toned)
        active=raw[:,3]<0
        self.assertTrue(np.any(active))
        self.assertTrue(np.all(repaired[active,3]>0))
        self.assertTrue(np.all(repaired[active,0]>=raw[active,0]))
        self.assertTrue(np.all(repaired[active,0]<=1.2*raw[active,0]))
        self.assertTrue(np.all(np.hypot(repaired[:,1],repaired[:,2])<=np.hypot(raw[:,1],raw[:,2])))
        np.testing.assert_array_equal(old.grade(toned),raw)
        np.testing.assert_array_equal(k.export(raw),old.export(raw))
        np.testing.assert_array_equal(old.export(raw,toned),old.export(raw))
        np.testing.assert_array_equal(k.export(raw)[active],0.)
        output=k.evaluate(self.points)
        self.assertTrue(np.all(np.max(output[active],axis=-1)>0))
        self.assertTrue(np.all((output>=0)&(output<=1024)))
        np.testing.assert_array_equal(output,k.export(raw,toned))
        # Compare the independently evaluated float64 reference at a gain
        # that actively repairs negative requested energy before cube export.
        expected=Model(settings).forward_native(self.points.astype(float))
        peak=np.max(abs(expected),axis=-1)
        error=np.max(abs(output.astype(float)-expected),axis=-1)
        self.assertTrue(np.all(error<=np.maximum(.001*peak,1e-7)),(output,expected))

    def test_guard_matches_historical_curve_and_degenerate_policies(self):
        k=self.stack(Settings()).kernels[0]
        q=np.array([[50.,80.,0.],[50.,-48.,64.],[-1.,20.,0.],[0.,10.,0.],
                    [100.,0.,0.]],dtype='f4')
        energy=hk_energy(q[:,0].astype(float),np.hypot(q[:,1],q[:,2]).astype(float)).astype('f4')
        raw=np.column_stack((q,energy)).astype('f4')
        reference=np.tile(np.array([50.,20.,0.,1180.],dtype='f4'),(len(raw),1))
        actual=k._hk_export(raw,reference)
        h=50.;c=80.;x=h*h;d=x-66*c;e0=1180.;delta=e0*x/(e0+x)
        t=(delta-d)/delta;e=delta/(1+4*t+10*t*t)**.25
        z=e-d;l=.44*x;g=l*z/np.hypot(2*l,z)
        expected=np.array([np.sqrt(x+g),(x+g-e)/66,0,e])
        np.testing.assert_allclose(actual[0],expected,rtol=8e-7,atol=1e-6)
        np.testing.assert_allclose(actual[1,1:3],expected[1]*np.array([-.6,.8]),rtol=8e-7)
        np.testing.assert_array_equal(actual[2],raw[2])
        np.testing.assert_array_equal(actual[3],0.)
        np.testing.assert_array_equal(actual[4],raw[4])
        reference[:,3]=0
        zero=k._hk_export(raw,reference)
        self.assertEqual(zero[0,3],0)
        self.assertTrue(np.isfinite(zero).all())
        tiny=np.array([[100.,10000/66,0.,1e-12]],dtype='f4')
        np.testing.assert_array_equal(k._hk_export(tiny,tiny),tiny)

    def test_cached_forward_retains_post_tone_reference(self):
        settings=Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
                          color=ColorSettings(global_gain=3.))
        k=self.stack(settings).kernels[0]
        cached=CachedKernel(k,len(self.points),Store())
        np.testing.assert_array_equal(cached.evaluate(self.points,np.arange(len(self.points))),k.evaluate(self.points))
        default=Kernel(k.data,k.tone,Model(settings).color,k.table)
        self.assertFalse(default.hk_guard)

    def test_active_guard_simple_inverse_uses_candidates_and_reports_error(self):
        for gain in (.25,1.,3.):
            settings=Settings(color=ColorSettings(global_gain=gain))
            stack=self.stack(settings,'INVERSE');solver=stack.solvers[0];k=solver.kernel
            target=k.evaluate(self.points)
            with self.subTest(gain=gain):
                # Guarded targets still use the finite analytic candidate set.
                # Full-forward validation may reject every candidate; no
                # numerical RGB fit is allowed to hide that approximation.
                with patch.object(bake_inverse,'minimize',side_effect=AssertionError('Simple inverse must not iterate')):
                    result=solver.evaluate(target)
                limit=solver.acceptance_limit(target)
                if gain==3.:
                    self.assertTrue(np.any(result[:,3]>limit),(gain,result,limit))
                self.assertTrue(np.isfinite(result).all())
                np.testing.assert_array_equal(result[:,3],np.max(abs(solver.residual(result[:,:3],target,False)),axis=-1))
                np.testing.assert_array_equal(solver.evaluate(target[::-1])[::-1],result)
                self.assertTrue(np.all((result[:,:3]>=0)&(result[:,:3]<=1024)))

    def test_active_guard_mixed_inverse_runs_only_raw_solve(self):
        settings=Settings(tone=ToneSettings(input_nits=(0.,7.,45.,203.,1000.)),
                          color=ColorSettings(global_gain=3.,web=WebSettings(hue_degrees=((0.,)*6,(3.,)*6,(0.,)*6,(0.,)*6))))
        solver=self.stack(settings,'INVERSE').solvers[0]
        target=solver.kernel.evaluate(self.points)
        with patch.object(bake_inverse,'minimize',wraps=bake_inverse.minimize) as solve:
            result=solver.evaluate(target)
        self.assertEqual(solve.call_count,1)
        self.assertEqual(solve.call_args.args[4],bake_inverse.ITERATIONS)
        self.assertTrue(np.any(result[:,3]>solver.acceptance_limit(target)))
        np.testing.assert_array_equal(result[:,3],np.max(abs(solver.residual(result[:,:3],target,False)),axis=-1))
        self.assertTrue(np.isfinite(result).all())
        self.assertTrue(np.all((result[:,:3]>=0)&(result[:,:3]<=1024)))

    def test_raw_inverse_and_matching_pair_do_not_apply_export_repair(self):
        settings=Settings(color=ColorSettings(global_gain=3.))
        stack=self.stack(settings,'INVERSE');old=self.stack(settings,'INVERSE',hk_guard=False)
        k=stack.kernels[0];raw=k.grade(k.tone_state(k.enter(self.points)))
        with patch.object(k,'_hk_export',side_effect=AssertionError('Raw inverse must not H-K repair')):
            result=stack.solvers[0].evaluate(raw,True)
        np.testing.assert_array_equal(result,old.solvers[0].evaluate(raw,True))
        self.assertTrue(np.all(result[:,3]<=TOLERANCE),result)
        pair=BakeStack([settings,settings],['FORWARD','INVERSE'],self.table)
        with patch.object(pair.kernels[0],'evaluate',side_effect=AssertionError('Matching pair should cancel')):
            np.testing.assert_array_equal(pair.bake_native(self.points)[:,:3],self.points)


if __name__=='__main__':unittest.main()
