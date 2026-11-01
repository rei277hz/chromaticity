"""Direct DCTL compact-cache and grading parity, through compiled float32 code."""
import re
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.model import Model as ReferenceModel
from tests.support.dctl_reference import Model, Settings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from tests.support.dctl_reference import ColorSettings
from color_tools.perceptual_grade_reference.boundary_compact import CompactTable
from color_tools.perceptual_grade_core.model.bake import Kernel,GAMMA
from color_tools.perceptual_grade_core.model.tone_table import _Curve
from color_tools.perceptual_grade_core.model import tone
from tests.support import oracle


class NumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=ReferenceModel(hk_guard=False);cls.data=cls.model.boundary.cache
        cls.table=CompactTable(cls.data);cls.kernel=Kernel(cls.data,cls.model.tone,cls.model.color,cls.table,hk_guard=False)
        cls.to_xyz=cls.model.cones_to_xyz@np.linalg.inv(cls.model.boundary.matrix)

    def test_all_declared_constants_fit_64kib(self):
        source=oracle.SOURCE
        declared=re.findall(r'__CONSTANT__\s+(?:float|unsigned int)\s+\w+\[(\d+)\]',source)
        actual=sum((int(n)*4+15)//16*16 for n in declared)
        stated=int(re.search(r'#define PG_CONSTANT_BYTES (\d+)',source).group(1))
        self.assertGreater(actual,55000);self.assertEqual(actual,stated);self.assertLess(actual,65536)
        self.assertNotIn('PG_FACE_ATLAS',source)

    def test_input_repair_rounds_inward_by_one_float_step(self):
        # Include both neighbors of powers of two, subnormal/normal transition,
        # and positive infinity (an overflowing repair limit yields FLT_MAX).
        powers=np.ldexp(np.ones(254,dtype='f4'),np.arange(-126,128))
        rng=np.random.default_rng(2011)
        random_bits=rng.integers(1,0x7f800000,size=4096,dtype=np.uint32)
        values=np.unique(np.r_[np.float32(0),np.uint32(1).view('f4'),
            np.nextafter(powers,np.float32(0)),powers,
            np.nextafter(powers,np.float32(np.inf)),random_bits.view('f4'),np.float32(np.inf)]).astype('f4')
        samples=np.repeat(values[:,None],3,axis=1)
        actual=oracle.run('next_down',samples)[:,:3].astype('f4')
        expected=np.nextafter(samples,np.float32(0))
        np.testing.assert_array_equal(actual.view('u4'),expected.view('u4'))

        # Exercise repair itself: exact identity for the cube, bounded output
        # after mixed-sign repair and scaling of very large positive channels.
        inside=np.array([[0,0,0],[1024]*3,[0,1024,0],[.2,.3,.4]],dtype='f4')
        np.testing.assert_array_equal(oracle.run('input_repair',inside)[:,:3],inside)
        outside=np.array([[2048,1024,512],[-1,3,128],[-1,-2,-3],
                          [np.finfo('f4').max,1,0],[2,-.1,1]],dtype='f4')
        repaired=oracle.run('input_repair',outside)[:,:3]
        self.assertTrue(np.isfinite(repaired).all())
        self.assertTrue(np.all((repaired>=0)&(repaired<=1024)))
        np.testing.assert_array_equal(oracle.run('input_repair',repaired)[:,:3],repaired)

    def test_fresh_and_reset_shadow_defaults_preserve_float32_identity(self):
        # A mismatch between LOW_Y and the UI default can silently activate
        # tone remapping. Test the compiled bypass, including chromatic input
        # near the new shadow anchor and the neighboring float32 neutrals.
        shadow=np.float32(tone.LOW_Y)
        neutrals=np.array([np.nextafter(shadow,np.float32(0)),shadow,
                           np.nextafter(shadow,np.float32(np.inf)),.18,1.,1000./203.],dtype='f4')
        rgb=np.vstack((np.repeat(neutrals[:,None],3,axis=1),
                       shadow*np.array([[.2,1.,1.7],[1.8,.7,.1],[1.,0.,2.]],dtype='f4')))
        reset={name:float(np.float32(value)) for name,value in zip(
            ('inputBlack','inputShadows','inputMidtones','inputWhite','inputHighlights'),
            tone.LEVEL_DEFAULTS)}
        for settings in (None,reset):
            with self.subTest(settings=settings):
                np.testing.assert_array_equal(oracle.run('forward_native',rgb,settings)[:,:3],rgb)

    def test_cartesian_response_controls_match_reference(self):
        rgb=np.array([[.1,.2,.3],[.4,.07,.02],[7,20,4],[0,1,0]],dtype='f4')
        # Fractional S/M/W coefficients retain their signs and directions;
        # Highlights use values exactly representable by its integer sliders.
        for family,target,pairs in (
            ('lightness','J',((3.1,4.2),(-2.3,1.4),(0.,-3.5),(-2.,1.))),
            ('chroma','C',((.15,-.2),(-.1,.25),(.2,0.),(1.,-1.)))):
            for axis in (None,0,1):
                rows=tuple((0.,0.,a if axis!=1 else 0.,b if axis!=0 else 0.) for a,b in pairs)
                model=Model(Settings(color=ColorSettings(**{family:rows})))
                controls={f'tone{tone}{name}To{target}':row[index+2]
                          for tone,row in zip('SMWH',rows) for index,name in enumerate('ab')}
                actual=oracle.run('forward_native',rgb,controls)[:,:3];expected=model.forward_native(rgb)
                limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
                self.assertTrue(np.all(np.max(abs(actual-expected),axis=-1)<=limit),(family,axis,actual,expected))

    def test_low_high_controls_keep_the_legacy_capacity_classifier(self):
        from tests.support.dctl_reference import capacity_drivers
        chroma=np.array([11.25,22.5,45.])
        q=np.column_stack((np.full(3,100.),chroma,np.zeros(3)))
        visible=chroma*chroma/(chroma*chroma+4)
        np.testing.assert_allclose(capacity_drivers(q,[56.25]*3)[:,:2]/visible[:,None],
                                   [[.8,.2],[.5,.5],[.2,.8]],rtol=2e-15)
        rgb=np.array([[.1,.2,.3],[.4,.07,.02],[7,20,4],[0,1,0]],dtype='f4')
        for family,target,low,high in (('lightness','J',3.,-2.),('chroma','C',1.,-1.)):
            for index,amount in ((0,low),(1,high)):
                rows=tuple(tuple(amount if j==index else 0. for j in range(4)) for _ in range(4))
                model=Model(Settings(color=ColorSettings(**{family:rows})))
                driver=('Low','High')[index]
                controls={f'tone{tone}{driver}To{target}':amount for tone in 'SMWH'}
                actual=oracle.run('forward_native',rgb,controls)[:,:3]
                expected=model.forward_native(rgb)
                limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
                with self.subTest(family=family,driver=driver):
                    self.assertTrue(np.all(np.max(abs(actual-expected),axis=-1)<=limit),(actual,expected))

    def test_faces_creases_vertices_and_hue_seam(self):
        d=self.data;s=self.table.selector
        heights=np.unique(np.r_[np.linspace(0,1,31),d['vertex_t']]).astype('f4')
        t,h=np.meshgrid(heights,np.linspace(-2*np.pi,2*np.pi,61,dtype='f4'),indexing='ij')
        ts=[t.ravel()];hs=[h.ravel()]
        for edge in range(12):
            low,high=d['vertex_t'][d['edges'][edge]]
            points=np.linspace(low,high,21,dtype='f4');angle=s.curve(points,edge,0)
            for a in (angle,np.nextafter(angle,np.float32(-np.inf)),np.nextafter(angle,np.float32(np.inf))):
                ts.append(points);hs.append(a)
        t=np.concatenate(ts);h=np.concatenate(hs)
        expected=self.table.capacity(t,h);actual=oracle.run('capacity',np.column_stack((t,h,np.zeros(len(t)))))[:,0]
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_allclose(actual,expected,rtol=2e-5,atol=1e-6)

    def test_physical_capacity_is_hue_dependent_and_zero_at_cube_tips(self):
        t,h=np.meshgrid(np.linspace(.001,.999,31,dtype='f4'),
                        np.linspace(-np.pi,np.pi,37,dtype='f4'),indexing='ij')
        ja=np.float32(self.data['white'])*t**GAMMA
        ab=np.stack((np.cos(h),np.sin(h)),-1)
        expected=self.kernel.capacity(ja*ja,ab).ravel()
        values=np.column_stack((ja.ravel(),h.ravel(),np.zeros(ja.size)))
        actual=oracle.run('physical_capacity',values)[:,0]
        np.testing.assert_allclose(actual,expected,rtol=2e-5,atol=1e-6)
        self.assertGreater(float(np.ptp(actual.reshape(t.shape)[15])),1.)
        outside=np.array([[-1,0,0],[0,0,0],[self.kernel.white,0,0],
                          [self.kernel.white*2,0,0]],dtype='f4')
        np.testing.assert_array_equal(oracle.run('physical_capacity',outside)[:,0],0)

    def test_entry_is_raw_and_export_uses_actual_cube(self):
        rng=np.random.default_rng(771)
        rgb=np.vstack((rng.uniform(0,1024,(1000,3)),[[0,0,0],[1024]*3,[0,1,0],[2,0,128],
            [0,1024,0],[1024,0,0],[0,0,1024],[.00001,.00002,.00003]])).astype('f4')
        entry=oracle.run('entry',rgb);expected=self.kernel.enter(rgb)
        actual=np.column_stack((entry[:,:3],entry[:,4]))
        # Opponent coordinates subtract large cone responses. Compare their
        # error at the shared appearance scale, not relative to a near-zero a.
        limit=4e-6*np.maximum(1,np.max(abs(expected[:,:3]),axis=-1))
        self.assertTrue(np.all(np.max(abs(actual[:,:3]-expected[:,:3]),axis=-1)<=limit))
        np.testing.assert_allclose(actual[:,3],expected[:,3],rtol=4e-6,atol=1e-6)
        output=oracle.run('export',expected)[:,:3];target=self.kernel.export(expected)
        error=np.max(abs(output-target),axis=-1);limit=np.maximum(.001*np.max(abs(target),axis=-1),1e-7)
        self.assertTrue(np.all(error<=limit),(float(np.max(error/limit)),rgb[np.argmax(error/limit)]))
        np.testing.assert_array_equal(output[-8],0)
        self.assertTrue(np.all((output>=0)&(output<=1024)),(float(output.min()),float(output.max())))

    def test_export_guard_preserves_valid_decode_and_contains_escape_rays(self):
        ja,h=np.meshgrid(self.kernel.white*np.array([.001,.02,.2,.5,.9,.999],dtype='f4'),
                        np.linspace(-np.pi,np.pi,41,dtype='f4'),indexing='ij')
        ab=np.stack((np.cos(h),np.sin(h)),-1)
        capacity=self.kernel.capacity(ja*ja,ab)
        # Include both legal inner rays and response-pole trials far beyond
        # the physical cube. The fit is only an initial bracket seed.
        c=np.concatenate([capacity.ravel()*factor for factor in (.2,.9,1.1,4.,10000.)])
        direction=np.tile(ab.reshape(-1,2),(5,1));energy=np.tile((ja*ja).ravel(),5)
        states=np.column_stack((np.sqrt(energy+66*c),direction*c[:,None],energy)).astype('f4')
        direct=oracle.run('decode',states);actual=oracle.run('export',states)[:,:3]
        self.assertTrue(np.isfinite(actual).all())
        self.assertTrue(np.all((actual>=0)&(actual<=1024)))
        legal=(direct[:,3]!=0)&np.all((direct[:,:3]>=0)&(direct[:,:3]<=1024),axis=-1)
        np.testing.assert_array_equal(actual[legal],direct[legal,:3])
        expected=self.kernel.export(states)
        limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
        self.assertTrue(np.all(np.max(abs(actual-expected),axis=-1)<=limit))
        entered=oracle.run('entry',actual)
        # Chroma radial projection preserves neutral lightness and hue;
        # float32 encoding can perturb a nearly black boundary slightly.
        np.testing.assert_allclose(entered[:,4],energy,rtol=2e-5,atol=1e-6)
        angle=np.arctan2(entered[:,2],entered[:,1]);wanted=np.arctan2(states[:,2],states[:,1])
        delta=np.arctan2(np.sin(angle-wanted),np.cos(angle-wanted))
        # Re-encoding nearly neutral float32 RGB loses a few mrad of hue;
        # the guard's tested appearance ray itself has exact hue preservation.
        self.assertLess(float(np.max(abs(delta))),3e-3)
        tips=np.array([[0,30,40,-1],[0,30,40,0],
                       [0,30,40,self.kernel.white*self.kernel.white]],dtype='f4')
        np.testing.assert_array_equal(oracle.run('export',tips)[:,:3],[[0]*3,[0]*3,[1024]*3])

    def test_direct_forward_controls_against_compact_reference(self):
        rng=np.random.default_rng(144);rgb=np.exp(rng.uniform(-6,6,(128,3))).astype('f4')
        rgb=np.vstack((rgb,[[0,0,0],[.1,.2,.3],[.7,.2,.1]]))
        for setting,controls in (
            (Settings(color=ColorSettings(global_gain=.25)),dict(globalChromaGain=.25)),
            (Settings(color=ColorSettings(hue=(8.,)*4)),{f'tone{x}Hue':8 for x in 'SMWH'}),
            (Settings(tone=ToneSettings(input_nits=(0,7,45,203,1000))),dict(inputShadows=7,inputMidtones=45))):
            model=Model(setting)
            expected=model.forward_native(rgb)
            actual=oracle.run('grade',rgb@self.to_xyz.T,controls)[:,:3]@np.linalg.inv(self.to_xyz).T
            error=np.max(abs(actual-expected),axis=-1);limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
            self.assertTrue(np.all(error<=limit),(controls,float(np.max(error/limit))))

    def test_bounded_inverse_tone_matches_float64_equation(self):
        for fit in (-2.,0.,4.):
            settings=ToneSettings(input_nits=(0,7,45,203,1000),fit=fit)
            model=Model(Settings(tone=settings));curve=_Curve(model.tone)
            height=np.r_[0,np.geomspace(1e-7,1e5,150)].astype('f4')
            actual=oracle.run('inverse_tone',np.column_stack((height,np.zeros((len(height),2)))),
                              dict(inputShadows=7,inputMidtones=45,remapFit=fit))[:,0]
            expected=100*(float(model.tone.black)+float(model.tone.span)*curve.inverse(height))
            expected[0]=0
            np.testing.assert_allclose(actual,expected,rtol=2e-5,atol=1e-7)
