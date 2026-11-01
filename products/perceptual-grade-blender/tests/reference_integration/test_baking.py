"""Independent float64 accuracy and bounded reusable float32 work."""
from concurrent.futures import CancelledError,ThreadPoolExecutor
from importlib.resources import files
from threading import Barrier,Event
from unittest.mock import patch
from weakref import ref
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model.bake import Kernel,PreparedKernels,kernels
from color_tools.perceptual_grade_core.model.bake_cache import Store,CachedKernel
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.model import Settings
from tests.reference.legacy_capacity import LegacyCapacityModel
from tools.analysis.bake_check import cases
from tools.build.boundary_oracle import exact_geometry


class BakingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with np.load(files('color_tools.perceptual_grade_reference')/'d65_cube.npz',allow_pickle=False) as a:cls.data=dict(a)
        axis=.01*np.expm1(np.linspace(0,1,17)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
        cls.rgb=np.vstack((np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3),
            [[.0253184813856082,.0071734681614134,.0043407546657122],
             [1024,1024,714.0458374023438],[1024,1024,.0019752890009854],[800,64,256]])).astype('f4')

    def kernel(self,settings):
        model=LegacyCapacityModel(settings,space='ACEScg',hk_guard=False)
        return Kernel(self.data,model.tone,model.color)

    def test_prepared_integrals_preserve_float32_results_at_boundaries(self):
        for knots in ((0.,.05,.18,.52,1.),(0.,.001,.4,.999,1.)):
            knots=np.asarray(knots,dtype='f4')
            values=np.concatenate((knots,np.nextafter(knots,np.float32(-np.inf)),
                np.nextafter(knots,np.float32(np.inf)),np.array([1e-20,.123,2.,1024.,1e4],dtype='f4')))
            values=values[values>=0]
            for fit in (-2.,0.,6.):
                with self.subTest(knots=knots.tolist(),fit=fit):
                    width=np.float32(.05*2**(-fit));prepared=PreparedKernels(knots,width)
                    expected=kernels(values,knots,width);actual=prepared.evaluate(values)
                    self.assertTrue(np.isfinite(actual).all())
                    np.testing.assert_array_equal(actual.view('u4'),expected.view('u4'))
                    for scalar in (np.float32(0),knots[2],np.float32(1),np.float32(1024)):
                        np.testing.assert_array_equal(prepared.evaluate(scalar).view('u4'),
                            kernels(scalar,knots,width).view('u4'))

    def test_terms_reuse_frozen_height_and_shared_fit(self):
        kernel=self.kernel(Settings(tone=ToneSettings(input_nits=(0.,7.,42.,203.,1000.)),
            color=ColorSettings(lightness=((1.,2.,3.,4.),)*4,chroma=((.2,-.1,.03,.04),)*4,
                web=WebSettings(hue_degrees=((1.,)*6,(-2.,)*6,(3.,)*6,(-4.,)*6)),adaptance=((.3,-.2),)*4)))
        q=kernel.tone_state(kernel.enter(self.rgb[::97]));h=np.sqrt(q[:,3]+66*np.hypot(q[:,1],q[:,2]))
        expected=kernel.terms(q)
        for actual in (kernel.terms(q,height=h),kernel.terms(height=h)):
            for value,wanted in zip(actual,expected):np.testing.assert_array_equal(value,wanted)
        shared=kernel.coefficient_curves[0.]
        with patch.object(shared,'evaluate_bounded',wraps=shared.evaluate_bounded) as evaluate:
            actual=kernel.terms(height=h);self.assertEqual(evaluate.call_count,1)
        for value,wanted in zip(actual,expected):np.testing.assert_array_equal(value,wanted)
        self.assertTrue(kernel.directional_drivers)
        nondirectional=self.kernel(Settings(color=ColorSettings(lightness=((0.,.1,0.,0.),)*4,
            web=WebSettings(hue_degrees=((1.,)*6,)*4),adaptance=((.1,-.2),)*4)))
        self.assertFalse(nondirectional.directional_drivers)

    def test_coefficient_endpoint_reuse_preserves_float32_batches(self):
        kernel=self.kernel(Settings())
        for fit in range(-2,7):
            curve=PreparedKernels(kernel.tone.coefficient_knots,.05*2**(-fit))
            for size in (1,2,3,7,8,16,17,65,65536):
                if size==65536 and fit!=0:continue
                for offset in (0,1):
                    with self.subTest(fit=fit,size=size,offset=offset):
                        t=np.resize(np.array([0.,.123,1.,.789],dtype='f4'),size+offset)[offset:]
                        expected=curve.evaluate(t);actual=curve.evaluate_bounded(t)
                        np.testing.assert_array_equal(actual.view('u4'),expected.view('u4'))
            for value in (0.,1.,.5):
                scalar=np.float32(value)
                np.testing.assert_array_equal(curve.evaluate_bounded(scalar).view('u4'),
                    curve.evaluate(scalar).view('u4'))

    def test_adopted_full_grade_against_independent_geometry(self):
        for name,settings in cases():
            with self.subTest(grade=name):
                model=LegacyCapacityModel(settings,space='ACEScg');kernel=Kernel(self.data,model.tone,model.color,hk_guard=True)
                with exact_geometry():expected=model.forward_native(self.rgb.astype(float))
                actual=kernel.evaluate(self.rgb);peak=np.max(expected,axis=-1)
                error=np.max(abs(actual.astype(float)-expected),axis=-1)
                # The adopted uint16 field's 0.7% oracle-error budget and
                # signed overshoot are separate from device/cache exactness.
                self.assertTrue(np.isfinite(actual).all())
                np.testing.assert_array_equal(actual[peak==0],0.)
                self.assertTrue(np.all(error<=np.maximum(.007*peak,1e-7)),float(error.max()))

    def test_mixed_web_center_scale_matches_float64_raw_state(self):
        from color_tools.perceptual_grade_reference.responses import State
        from color_tools.perceptual_grade_blender.model.bake_gpu import parameters, LAYOUT
        web=WebSettings(
            log_chroma=((.2,-.1,.1,-.15,.25,-.2),(-.1,.2,-.1,.1,-.15,.2),(.15,)*6,(-.1,)*6),
            hue_degrees=((8.,-4.,6.,-8.,4.,-6.),(-6.,8.,-4.,6.,-8.,4.),(5.,)*6,(-3.,)*6),
            log_scale=((.15,-.1,.1,0.,-.15,.2),(-.1,.15,0.,-.1,.1,-.15),(.1,)*6,(-.05,)*6))
        settings=Settings(color=ColorSettings(web=web,adaptance=((1.,-2.),(-3.,2.),(2.,3.),(-1.,2.)),
            lightness=((.1,-.2,.03,-.02),)*4,chroma=((.03,-.02,.01,-.01),)*4))
        model=LegacyCapacityModel(settings);k=Kernel(self.data,model.tone,model.color,hk_guard=True)
        heights=np.r_[k.anchors,(k.anchors[:-1]+k.anchors[1:])/2,k.anchors[0]/2,k.anchors[-1]*1.2]
        h,angle,fraction=np.meshgrid(heights,np.linspace(-np.pi,np.pi,49),[.01,.3,.8,.99],indexing='ij')
        c=h*h/66*fraction;energy=h*h-66*c
        raw=np.stack((h,c*np.cos(angle),c*np.sin(angle),energy),-1).reshape(-1,4).astype('f4')
        wanted=model.color.apply_state(State(raw[:,:3].astype(float),raw[:,3].astype(float)))
        actual=k.grade(raw)
        expected=np.column_stack((wanted.q,wanted.energy))
        np.testing.assert_allclose(actual[:,:3],expected[:,:3],rtol=5e-5,atol=5e-5)
        # Signed sqrt(E) is ill-conditioned at E=0. Bound transported E against
        # its physical H² scale, then check signed JA on the appearance scale.
        scale=1+abs(raw[:,3].astype(float))+66*np.hypot(raw[:,1].astype(float),raw[:,2].astype(float))
        self.assertLess(float(np.max(abs(actual[:,3]-expected[:,3])/scale)),2e-6)
        ja=np.sign(actual[:,3])*np.sqrt(abs(actual[:,3].astype(float)))
        expected_ja=np.sign(expected[:,3])*np.sqrt(abs(expected[:,3]))
        self.assertLess(float(np.max(abs(ja-expected_ja)/np.sqrt(scale))),5e-5)
        packed=parameters(k)
        self.assertEqual(packed.shape,(256,));self.assertTrue(np.isfinite(packed).all())
        np.testing.assert_array_equal(packed[LAYOUT['ADAPTANCE_LOG_GAINS']:LAYOUT['ADAPTANCE_LOG_GAINS']+12],
            model.color.adaptation.log_gains.astype('f4').ravel())
        self.assertEqual(packed[LAYOUT['HALF_SATURATION']],np.float32(settings.color.adaptance_half_saturation))
        # State transport and mixed grade are independent of batch shape.
        for index in range(0,len(raw),197):np.testing.assert_array_equal(actual[index],k.grade(raw[index]))

    def test_selective_adaptance_response_poles_and_bounded_mask(self):
        from color_tools.perceptual_grade_core.model.bake import response_transform,reach_weight
        from color_tools.perceptual_grade_core.model.selective_adaptance import response_transform as oracle_transform
        r=np.r_[-1e30,-800.,-400.001,-400.,-399.999,-.01,0.,.01,399.999,400.,400.001,800.,1e30].astype('f4')[:,None]
        gains=np.array([.25,.8,1.,1.2,4.],dtype='f4')
        actual=response_transform(r,gains)
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_allclose(actual,oracle_transform(r,gains),rtol=5e-7,atol=1e-7)
        np.testing.assert_allclose(response_transform(actual,1/gains),np.broadcast_to(r,actual.shape),rtol=5e-7,atol=1e-7)
        np.testing.assert_array_equal(actual[:,2],r[:,0])
        self.assertTrue(np.all(np.diff(actual,axis=0)>0))
        # At the Reach radius C=R*sqrt(|E|), the mask is exactly one half,
        # including source values whose unscaled fourth powers would overflow.
        energy=np.array([0.,1.,-1.,1e30,-1e30],dtype='f4')
        for reach in (.05,.25,1.):
            chroma=np.float32(reach)*np.sqrt(abs(energy))
            np.testing.assert_array_equal(reach_weight(chroma,energy,reach),[1.,.5,.5,.5,.5])
            np.testing.assert_array_equal(reach_weight(np.ones(5,dtype='f4'),np.zeros(5,dtype='f4'),reach),0.)

    def test_selective_adaptance_neutral_targets_signed_raw_and_reach(self):
        from color_tools.perceptual_grade_reference.responses import State,signed_hk
        targets=((1.,-2.),(-3.,2.),(2.,3.),(-1.,2.))
        for reach in (.05,.25,1.):
            model=LegacyCapacityModel(Settings(color=ColorSettings(adaptance=targets,adaptance_half_saturation=reach)))
            k=Kernel(self.data,model.tone,model.color)
            neutral=np.column_stack((k.anchors,np.zeros((4,2),dtype='f4'),k.anchors*k.anchors))
            actual=k.grade(neutral)
            np.testing.assert_allclose(actual[:,1:3],targets,rtol=2e-5,atol=4e-5)
            np.testing.assert_array_equal(actual[:,3],neutral[:,3])
            np.testing.assert_array_equal(k.grade(np.zeros(4,dtype='f4')),0.)
            # Cover negative energy, zero-achromatic states, and exterior
            # responses which cannot be decoded to physical cone values.
            ja,c,angle=np.meshgrid([-600.,-100.,-1.,0.,1.,100.,600.,3000.],
                [0.,.001,10.,200.,1000.],[-2.,0.,1.],indexing='ij')
            raw=np.stack((signed_hk(ja,c),c*np.cos(angle),c*np.sin(angle),ja*abs(ja)),-1).reshape(-1,4).astype('f4')
            expected=model.color.apply_state(State(raw[:,:3].astype(float),raw[:,3].astype(float)))
            expected=np.column_stack((expected.q,expected.energy));actual=k.grade(raw)
            self.assertTrue(np.isfinite(actual).all())
            scale=1+np.max(abs(expected[:,:3]),axis=-1)
            self.assertLess(float(np.max(np.max(abs(actual[:,:3]-expected[:,:3]),axis=-1)/scale)),3e-5)
            escale=1+abs(raw[:,3].astype(float))+66*np.hypot(raw[:,1].astype(float),raw[:,2].astype(float))
            self.assertLess(float(np.max(abs(actual[:,3]-expected[:,3])/escale)),5e-6)
            zero=raw[:,3]==0
            np.testing.assert_array_equal(actual[zero],raw[zero])
            for index in (0,37,88,len(raw)-1):np.testing.assert_array_equal(actual[index],k.grade(raw[index]))

    def test_cache_reuses_fixed_work_and_keys_tone_and_fit(self):
        rgb=self.rgb[:257];ids=np.arange(len(rgb));store=Store()
        first=self.kernel(Settings(color=ColorSettings(global_gain=.5,chroma=((0.,1.,0.,0.),)*4)))
        cached=CachedKernel(first,len(rgb),store)
        np.testing.assert_array_equal(cached.evaluate(rgb,ids),first.evaluate(rgb))
        second=self.kernel(Settings(color=ColorSettings(global_gain=1.,chroma=((0.,2.,0.,0.),)*4)))
        expected=second.evaluate(rgb)
        with (patch.object(second,'enter',side_effect=AssertionError('Repeated entry')),
              patch.object(second,'tonal',side_effect=AssertionError('Repeated weights'))):
            np.testing.assert_array_equal(CachedKernel(second,len(rgb),store).evaluate(rgb,ids),expected)
        for settings in (Settings(tone=ToneSettings(input_nits=(0.,7.,42.,203.,1000.)),color=ColorSettings(global_gain=.5)),
                         Settings(color=ColorSettings(chroma=((0.,1.,0.,0.),)*4,chroma_fit=6.))):
            kernel=self.kernel(settings)
            np.testing.assert_array_equal(CachedKernel(kernel,len(rgb),store).evaluate(rgb,ids),kernel.evaluate(rgb))
        self.assertLessEqual(store.bytes,store.budget)

    def test_partial_rows_and_failed_calculations_are_never_committed(self):
        store=Store(1024);seen=[]
        def calculate(missing):
            seen.append(int(missing.sum()));return np.full((missing.sum(),4),len(seen),dtype='f4')
        store.fetch('a',[0,1,2],10,calculate)
        store.fetch('a',[1,2,3],10,calculate)
        self.assertEqual(seen,[3,1])
        with self.assertRaises(CancelledError):
            store.fetch('a',[4,5],10,lambda missing:(_ for _ in ()).throw(CancelledError()))
        store.fetch('a',[4,5],10,calculate);self.assertEqual(seen,[3,1,2])
        kernel=self.kernel(Settings(color=ColorSettings(global_gain=.5)))
        def cancelled():raise CancelledError()
        with self.assertRaises(CancelledError):CachedKernel(kernel,10,store).evaluate(self.rgb[:10],np.arange(10),cancelled)

    def test_concurrent_disjoint_and_overlapping_fills(self):
        for second in ([4,5,6,7],[0,2,4,5]):
            with self.subTest(second=second),ThreadPoolExecutor(max_workers=2) as pool:
                store=Store(1024);barrier=Barrier(2)
                def expected(ids):return np.repeat(np.asarray(ids,dtype='f4')[:,None],4,axis=1)
                store.fetch('a',[0],10,lambda missing:expected([0]))
                def fetch(ids):
                    def calculate(missing):
                        barrier.wait(timeout=5)
                        return expected(np.asarray(ids)[missing])
                    return store.fetch('a',ids,10,calculate)
                first=pool.submit(fetch,[0,1,2,3]);other=pool.submit(fetch,second)
                np.testing.assert_array_equal(first.result(timeout=10),expected([0,1,2,3]))
                np.testing.assert_array_equal(other.result(timeout=10),expected(second))
                ids=np.union1d([0,1,2,3],second)
                def no_misses(missing):raise AssertionError('Completed rows missing')
                result=store.fetch('a',ids,10,no_misses)
                np.testing.assert_array_equal(result,expected(ids))
                result[:]=-1
                np.testing.assert_array_equal(store.fetch('a',ids,10,no_misses),expected(ids))

    def test_inflight_eviction_clear_and_replacement_do_not_retain_or_publish_old_rows(self):
        for action in ('evict','clear','reserve'):
            with self.subTest(action=action),ThreadPoolExecutor(max_workers=1) as pool:
                store=Store(340);store.reserve('lookup',170);entered=Event();release=Event()
                def calculate(missing):
                    entered.set()
                    if not release.wait(timeout=5):raise AssertionError('Calculation not released')
                    return np.ones((missing.sum(),4),dtype='f4')
                pending=pool.submit(store.fetch,'a',[0],10,calculate)
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    with store.lock:
                        values,valid=(ref(a) for a in store.rows['a'][:2])
                    if action=='evict':store.fetch('b',[0],10,lambda m:np.ones((m.sum(),4),dtype='f4'))
                    elif action=='clear':store.clear();store.reserve('lookup',170)
                    else:store.reserve('lookup',340);store.reserve('lookup',170)
                    self.assertIsNone(values());self.assertIsNone(valid())
                    store.fetch('a',[1],10,lambda m:np.full((m.sum(),4),2,dtype='f4'))
                    self.assertLessEqual(store.bytes,store.budget)
                finally:release.set()
                np.testing.assert_array_equal(pending.result(timeout=5),np.ones((1,4),dtype='f4'))
                def replacement(missing):
                    np.testing.assert_array_equal(missing,[True,False])
                    return np.full((1,4),3,dtype='f4')
                np.testing.assert_array_equal(store.fetch('a',[0,1],10,replacement),[[3]*4,[2]*4])
                self.assertLessEqual(store.bytes,store.budget)

    def test_concurrent_failed_fill_does_not_publish_partial_rows(self):
        for failure in (CancelledError(),np.full((1,4),np.nan),np.ones((1,3))):
            with self.subTest(failure=failure),ThreadPoolExecutor(max_workers=2) as pool:
                store=Store(1024);barrier=Barrier(2)
                def fail(missing):
                    barrier.wait(timeout=5)
                    if isinstance(failure,Exception):raise failure
                    return failure
                def complete(missing):
                    barrier.wait(timeout=5)
                    return np.ones((missing.sum(),4),dtype='f4')
                failed=pool.submit(store.fetch,'a',[0],10,fail)
                completed=pool.submit(store.fetch,'a',[1],10,complete)
                with self.assertRaises((CancelledError,ArithmeticError)):failed.result(timeout=10)
                np.testing.assert_array_equal(completed.result(timeout=10),np.ones((1,4),dtype='f4'))
                def retry(missing):
                    np.testing.assert_array_equal(missing,[True,False])
                    return np.full((1,4),2,dtype='f4')
                np.testing.assert_array_equal(store.fetch('a',[0,1],10,retry),[[2]*4,[1]*4])

    def test_concurrent_full_lattice_matches_uncached_math(self):
        axis=.01*np.expm1(np.linspace(0,1,65)*np.log1p(1024/.01));axis[0],axis[-1]=0.,1024.
        rgb=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3).astype('f4')
        kernel=self.kernel(Settings(tone=ToneSettings(input_nits=(0.,7.,42.,203.,1000.)),
            color=ColorSettings(global_gain=.5,chroma=((0.,1.,0.,0.),)*4,
                web=WebSettings(hue_degrees=((0.,)*6,(8.,)*6,(0.,)*6,(0.,)*6)))))
        store=Store();cached=CachedKernel(kernel,len(rgb),store)
        chunks=[np.arange(start,min(start+16384,len(rgb))) for start in range(0,len(rgb),16384)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            result=np.concatenate(list(pool.map(lambda ids:cached.evaluate(rgb[ids],ids),chunks)))
        # Match batch sizes to exclude NumPy's scalar/vector rounding differences.
        np.testing.assert_array_equal(result,np.concatenate([kernel.evaluate(rgb[ids]) for ids in chunks]))
        self.assertTrue(np.isfinite(result).all())
        np.testing.assert_array_equal(result[np.max(rgb,axis=-1)==0],0.)
        self.assertLessEqual(store.bytes,store.budget)

    def test_budget_eviction_and_failed_reservation_leave_valid_state(self):
        store=Store(400);compute=lambda m:np.ones((m.sum(),4),dtype='f4')
        store.reserve('lookup',60);store.fetch('a',[0],10,compute);store.fetch('b',[0],10,compute)
        self.assertEqual(store.bytes,400)
        store.fetch('a',[0],10,compute);store.fetch('c',[0],10,compute)
        self.assertEqual(list(store.rows),['a','c'])
        with self.assertRaises(MemoryError):store.reserve('lookup',401)
        self.assertEqual(store.fixed,{'lookup':60});self.assertEqual(list(store.rows),['a','c'])
        store.reserve('lookup',230);self.assertEqual(list(store.rows),['c']);self.assertEqual(store.bytes,400)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.lock:
                # Repeating an existing reservation must not wait for rows.
                pool.submit(store.reserve,'lookup',230).result(timeout=1)
        store.clear();self.assertEqual(store.bytes,0)


if __name__=='__main__':unittest.main()
