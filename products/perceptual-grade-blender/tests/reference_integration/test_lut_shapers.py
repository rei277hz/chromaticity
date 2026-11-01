"""Input placement changes must retain physical RGB interpolation contracts."""
from collections import Counter
from itertools import permutations
import unittest
import numpy as np
from tools.analysis import photo_stack
from tools.analysis.grade_shaper_error import CPU,ranking
from tools.analysis.lut_shapers import Shaper,initial_candidates,refinements,addresses,tetrahedral
from tools.analysis.photo_grade import extension_model


class LUTShaperTests(unittest.TestCase):
    def test_ranking_balances_relative_errors_and_excludes_reset_controls(self):
        def row(name,view,maximum,p99):
            return dict(case=name,view=view,total=dict(codes=dict(maximum=maximum,p99=p99)))
        scales={'tone':.01,'chroma':.3,'hue':1.,'mixed':3.,'mixed_tone':6.,'strong_chroma':100.}
        baseline=[];actual=[]
        for name,scale in scales.items():
            for view,factor in (('SDR100',1.),('HDR1000',10.)):
                value=scale*factor
                baseline.append(row(name,view,value,value*.1))
                ratio=2. if name=='tone' else .5 if name=='strong_chroma' else 1.
                actual.append(row(name,view,value*ratio,value*.1))
        for name in ('reset','exposure'):
            for view in ('SDR100','HDR1000'):
                baseline.append(row(name,view,0.,0.));actual.append(row(name,view,1e30,1e30))
        result=ranking({'aggregates':actual[::-1]},{'aggregates':baseline})
        self.assertEqual(result,dict(worst_maximum_ratio=2.,geometric_mean_p99_ratio=1.,
                                     all_maxima_improved=False))
        # Changing a case's units cannot change its relative importance.
        for index,(a,b) in enumerate(zip(actual,baseline)):
            for metric in ('maximum','p99'):
                a['total']['codes'][metric]*=2.**index
                b['total']['codes'][metric]*=2.**index
        self.assertEqual(ranking({'aggregates':actual},{'aggregates':baseline}),result)

    def test_distinct_shaper_bakers_do_not_alias_cached_row_ids(self):
        model=extension_model(photo_stack.cases()['chroma'])
        first=CPU(Shaper(),model,False,False)
        second=CPU(Shaper('linear'),model,False,False)
        rows=np.array([1,66,172,33000,65535,150123,65**3-2])
        self.assertFalse(first.kernel.identity)
        self.assertIsNot(first.cached.store,second.cached.store)
        expected_first=first.kernel.evaluate(first.samples[rows])
        expected_second=second.kernel.evaluate(second.samples[rows])
        self.assertFalse(np.array_equal(expected_first,expected_second))
        np.testing.assert_array_equal(first.evaluate_rows(rows),expected_first)
        np.testing.assert_array_equal(second.evaluate_rows(rows),expected_second)
        np.testing.assert_array_equal(first.evaluate_rows(rows),expected_first)

    def test_candidate_grid_and_one_parameter_refinements(self):
        candidates=initial_candidates()
        self.assertEqual(len(candidates),83)
        self.assertEqual(len({s.key for s in candidates}),83)
        self.assertEqual(Counter(s.family for s in candidates),
            {'linear':1,'log':13,'tanh':9,'log_tanh':60})
        self.assertIn(Shaper().key,{s.key for s in candidates})
        self.assertEqual(refinements(Shaper('linear')),())
        examples=((Shaper('log',.01),2),
                  (Shaper('tanh',strength=2.,center=.5),4),
                  (Shaper('log_tanh',.01,2.,.5),6))
        for original,count in examples:
            with self.subTest(family=original.family):
                children=refinements(original)
                self.assertEqual(len(children),count)
                self.assertEqual(len({s.key for s in children}),count)
                for child in children:
                    self.assertEqual(child.family,original.family)
                    self.assertEqual(sum(getattr(child,n)!=getattr(original,n)
                        for n in ('kappa','strength','center')),1)
                    self.assertNotEqual(child.key,original.key)
        log_values=sorted(s.kappa for s in refinements(Shaper('log',.01)))
        np.testing.assert_allclose(log_values,10.**np.array([-2.25,-1.75]),rtol=2e-15,atol=0)

    def test_baseline_reproduces_existing_axes_lattice_and_lookup_exactly(self):
        baseline=Shaper()
        for size in (33,65):
            np.testing.assert_array_equal(baseline.axis(size),photo_stack.axis(size))
            np.testing.assert_array_equal(baseline.lattice(size),photo_stack.lattice(size))
        grid=baseline.axis(33)
        nodes=np.stack(np.meshgrid(grid,grid,grid,indexing='ij'),-1)
        values=(nodes+1)**2/(1+np.max(nodes,axis=-1,keepdims=True))
        points=np.array([[0.,0.,0.],[1024.,1024.,1024.],[.08,.08001,.07999],
                         [.001,800.,.2],[13.7,.004,512.],[3.,17.,90.]])
        a=addresses(points,baseline,33);b=photo_stack._addresses(points,33)
        np.testing.assert_array_equal(a[0],b[0])
        for left,right in zip(a[1],b[1]):np.testing.assert_array_equal(left,right)
        np.testing.assert_array_equal(a[2],b[2])
        np.testing.assert_array_equal(tetrahedral(values,points,baseline),photo_stack.tetrahedral(values,points))

    def test_all_axes_are_finite_strict_float32_and_nested(self):
        for shaper in initial_candidates():
            with self.subTest(shaper=shaper.key):
                axis=shaper.axis();rounded=axis.astype('f4')
                np.testing.assert_array_equal(axis[[0,-1]],[0.,1024.])
                np.testing.assert_array_equal(rounded[[0,-1]],[0.,1024.])
                self.assertTrue(np.isfinite(rounded).all())
                self.assertTrue(np.all(np.diff(axis)>0))
                self.assertTrue(np.all(np.diff(rounded)>0))
                encoded=shaper.encode(rounded,dtype=np.float32)
                decoded=shaper.decode(np.linspace(0,1,65,dtype=np.float32),dtype=np.float32)
                for values in (encoded,decoded):
                    self.assertEqual(values.dtype,np.dtype('float32'))
                    self.assertTrue(np.isfinite(values).all())
                    self.assertTrue(np.all(np.diff(values)>0))
                np.testing.assert_array_equal(encoded[[0,-1]],[0.,1.])
                np.testing.assert_array_equal(decoded[[0,-1]],[0.,1024.])
                np.testing.assert_array_equal(shaper.axis(33),axis[::2])
                np.testing.assert_allclose(shaper.encode(axis),np.linspace(0,1,65),rtol=0,atol=2e-12)
                probes=np.r_[0.,np.geomspace(1e-12,1024.,97),axis]
                np.testing.assert_allclose(shaper.decode(shaper.encode(probes)),probes,
                    rtol=3e-12,atol=2e-12)
                np.testing.assert_array_equal(shaper.encode(np.array([0.,1024.])),[0.,1.])
                np.testing.assert_array_equal(shaper.decode(np.array([0.,1.])),[0.,1024.])
                if shaper.family in ('tanh','log_tanh'):
                    # Check the approved curve independently: an incorrect
                    # encode/decode pair could still roundtrip perfectly.
                    z=np.array([.05,.25,.5,.75,.95])
                    x=(shaper.kappa*np.expm1(z*np.log1p(1024/shaper.kappa))
                       if shaper.family=='log_tanh' else 1024*z)
                    a,c=shaper.strength,shaper.center
                    lower=np.tanh(-a*c);upper=np.tanh(a*(1-c))
                    expected=(np.tanh(a*(z-c))-lower)/(upper-lower)
                    np.testing.assert_allclose(shaper.encode(x),expected,rtol=3e-14,atol=4e-16)

    def test_physical_fractions_all_tetrahedra_ties_and_knot_neighbors(self):
        matrix=np.array([[1.,2.,-.5],[.1,-.3,.7],[0.,2.,1.]])
        offset=np.array([.2,-.1,.4])
        fractions=np.array([*permutations((.8,.5,.1)),(.5,.5,.5),(.75,.75,.25),(0.,0.,0.),(1.,0.,1.)])
        for shaper in initial_candidates():
            with self.subTest(shaper=shaper.key):
                axis=shaper.axis(33)
                nodes=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1)
                # Float64 samples isolate interpolation from output quantization.
                values=nodes@matrix.T+offset
                low,high=axis[17],axis[18]
                points=low+fractions*(high-low)
                _,_,actual_fractions=addresses(points,shaper,33)
                np.testing.assert_allclose(actual_fractions[:8],np.sort(fractions[:8],axis=1)[:,::-1],
                    rtol=0,atol=2e-13)
                neighbors=np.concatenate((np.nextafter(axis[1:-1],-np.inf),axis,
                                          np.nextafter(axis[1:-1],np.inf)))
                near=np.column_stack((neighbors,np.full(len(neighbors),axis[11]),
                                      np.full(len(neighbors),axis[23])))
                all_points=np.concatenate((points,near))
                actual=tetrahedral(values,all_points,shaper)
                np.testing.assert_allclose(actual,all_points@matrix.T+offset,rtol=3e-14,atol=3e-12)


if __name__=='__main__':unittest.main()
