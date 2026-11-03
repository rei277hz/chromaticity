"""Isolated guard roots and native export, independent of Stage 1/2/3 errors."""
from unittest import TestCase,main,mock
import numpy as np
import bpy
from color_tools.perceptual_grade_nodes import prepare
from color_tools.perceptual_grade_nodes.boundary import prepare_boundary
from color_tools.perceptual_grade_nodes.guard_graph import GuardedSockets,hk_guard,output_guard
from color_tools.perceptual_grade_nodes import guard_graph
from color_tools.perceptual_grade_nodes.color_graph import ColorSockets
from color_tools.perceptual_grade_nodes.graph import Graph,BuiltGrade,count_nodes
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.responses import signed_hk
from color_tools.perceptual_grade_reference.cube_guard import guard as reference_cube
from color_tools.perceptual_grade_core.model.hk_guard import guard as reference_hk
from tools.perceptual_grade_nodes.native import NativeFixture
from tools.perceptual_grade_nodes.oracle import metrics,exact_boundary


from tools.perceptual_grade_nodes.guard_cases import guard_builder,hk_probes,boundary_probes
from tools.perceptual_grade_nodes import build_boundary


class GuardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared=prepare();p=cls.prepared
        cls.boundary=prepare_boundary(p.fl,p.aw,p.gamma)
        cls.prepared=prepare(boundary=cls.boundary)
        cls.reference=exact_boundary(Model())

    def test_prepared_geometry_and_independent_root_gate(self):
        b=self.boundary;ref=self.reference
        np.testing.assert_allclose(b.matrix,ref.matrix,atol=2e-14,rtol=2e-14)
        self.assertLess(b.seed_max_error,1e-6)
        self.assertLessEqual(b.max_error,2e-5)
        self.assertGreater(b.probe_count,160000)
        rng=np.random.default_rng(20261029)
        t=np.r_[rng.uniform(.001,.999,30000),np.geomspace(1e-8,.001,1000),1-np.geomspace(1e-7,.001,1000)]
        hue=rng.uniform(-np.pi,np.pi,len(t))
        exact=b.exact(t,hue);actual=b.corrected(t,hue)
        scale=b.response_white*t*(1-t)
        self.assertLessEqual(float(np.max(abs(scale*(actual-exact))/(1+scale*exact))),2e-5)
        # The bracketed preparation root is checked against a separately owned
        # actual-decoder cube projection, not only against itself.
        ids=np.arange(0,30000,937);ja=b.white*t[ids]**b.gamma;c=scale[ids]*exact[ids]
        q=np.column_stack((signed_hk(ja,2*c),2*c*np.cos(hue[ids]),2*c*np.sin(hue[ids])))
        result,_,_=reference_cube(ref,q,ja*ja)
        radius=np.hypot(result[:,1],result[:,2])
        self.assertLessEqual(float(np.max(abs(radius-c)/(1+c))),2e-8)

    def test_inaccurate_seed_is_rejected_during_preparation(self):
        # Coarse geometry must fail the independent root gate, even though its
        # packed coefficients are finite and internally self-consistent.
        with mock.patch.object(build_boundary,'SEED_HUE_CELLS',8):
            with self.assertRaisesRegex(ValueError,'Output-boundary root internal gate failed'):
                build_boundary.generate_boundary(self.prepared.fl,self.prepared.aw,self.prepared.gamma)

    def test_native_hk_internal_gate(self):
        values,expected,energy=hk_probes()
        for context,mode in ((context,mode) for context in ('shader','compositor') for mode in ('hk','hk_color')):
            fixture=NativeFixture(self.prepared,values,context,builder=guard_builder(mode))
            try: actual=fixture.render()
            finally: fixture.close()
            q_error=metrics(actual['rgb'],expected)['max_normalized']
            print(f'HK {context}/{mode}: coordinates={q_error:.9g} energy={float(np.max(abs(actual["valid"]-energy)/(1+abs(energy)))):.9g}',flush=True)
            self.assertLessEqual(q_error,1e-5)
            self.assertLessEqual(float(np.max(abs(actual['valid']-energy)/(1+abs(energy)))),1e-5)

    def test_native_boundary_internal_and_rgb_gates(self):
        b=self.boundary;probes=boundary_probes(b,self.reference)
        values,energy,c,expected_radius,radial,native=(probes[name] for name in
            ('values','energy','chroma','radius','radial','native'))
        for space in ('Linear Rec.709','Linear Rec.2020','ACEScg'):
            p=prepare(space=space,boundary=b);adapter=p.from_cones@b.inverse
            expected=native[:,1,None]+(native-native[:,1,None])@adapter.T
            for context in ('shader','compositor'):
                fixture=NativeFixture(p,values,context,builder=guard_builder('boundary'))
                try: actual=fixture.render()
                finally: fixture.close()
                self.assertTrue(np.isfinite(actual['rgb']).all())
                np.testing.assert_array_equal(actual['valid'],1.)
                print(f'Boundary RGB {space}/{context}: {metrics(actual["rgb"],expected)["max_normalized"]:.9g}',flush=True)
                self.assertLessEqual(metrics(actual['rgb'],expected)['max_normalized'],1e-4,(space,context,metrics(actual['rgb'],expected)))
                self.assertLess(actual['stats']['expanded_nodes'],1000)
        for context in ('shader','compositor'):
            fixture=NativeFixture(self.prepared,values,context,builder=guard_builder('boundary_native'))
            try: actual=fixture.render()
            finally: fixture.close()
            self.assertTrue(np.all((actual['rgb']>=0)&(actual['rgb']<=1024)))
            error=abs(actual['margin']-expected_radius)/(1+expected_radius)
            print(f'Boundary native {context}: radius={float(np.max(error[radial],initial=0)):.9g} min={float(np.min(actual["rgb"])):.9g} max={float(np.max(actual["rgb"])):.9g}',flush=True)
            self.assertLessEqual(float(np.max(error[radial],initial=0)),2e-5,(context,np.flatnonzero(radial)[np.argmax(error[radial])],float(np.max(error[radial],initial=0))))
            endpoint=(energy<=0)|(energy>=b.white*b.white)
            np.testing.assert_array_equal(actual['margin'][endpoint],0.)
            direct=(~endpoint)&(c<=expected_radius+1e-10)
            self.assertLessEqual(float(np.max(error[direct],initial=0)),2e-5)

    def test_neutral_fallback_reports_returned_radius(self):
        # Force only the projected trial's legality check to fail. The input
        # rays are outside the cube, so the returned state must be the legal
        # neutral fallback; its radius must not describe the rejected trial.
        b=self.boundary
        energy=.25*b.white*b.white
        angles=np.arange(256)*(2*np.pi/256)
        values=np.column_stack((np.full(256,energy),1e6*np.cos(angles),
                                1e6*np.sin(angles),np.ones(256))).astype(np.float32)
        for context in ('shader','compositor'):
            fixture=NativeFixture(self.prepared,values,context,
                                  builder=guard_builder('boundary_native_fallback'))
            try: actual=fixture.render()
            finally: fixture.close()
            np.testing.assert_array_equal(actual['margin'],0.)
            np.testing.assert_array_equal(actual['valid'],1.)
            np.testing.assert_array_equal(actual['rgb'][:,0],actual['rgb'][:,1])
            np.testing.assert_array_equal(actual['rgb'][:,1],actual['rgb'][:,2])
            self.assertTrue(np.all((actual['rgb']>0)&(actual['rgb']<1024)))
            t=(float(values[0,0])/(b.white*b.white))**(1/(2*b.gamma))
            np.testing.assert_allclose(actual['alpha'],400-b.response_white*t,
                                       rtol=2e-7,atol=0.)



if __name__=='__main__':main()
