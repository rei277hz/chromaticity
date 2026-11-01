"""Crease topology, direct fields, geometric accuracy and scaled correspondence."""
import ast
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model import boundary_cache, boundary_table, boundary_polynomial
from color_tools.perceptual_grade_reference import cube
from color_tools.perceptual_grade_reference.cube_guard import guard,guard_scaled
from color_tools.perceptual_grade_reference.responses import signed_hk
from color_tools.perceptual_grade_core.model.creases import Selector
from color_tools.perceptual_grade_reference.model import Model
from color_tools.color_core.scaled import Scalar as S
from color_tools.perceptual_grade_core.model import cube_boundary as blender, forward, linear, tone
from color_tools.perceptual_grade_core.model.cube_guard import guard_scaled as other_guard_scaled
from color_tools.color_core.scaled import Scalar as B
from tools.build.boundary_oracle import capacity_unit,exact_geometry
from tools.build.boundary_table import decode_unit


class BoundaryAccelerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=files('color_tools.perceptual_grade_reference')/'d65_cube.npz'
        with np.load(cls.path,allow_pickle=False) as d:cls.data=dict(d)
        cls.ctx=Model().boundary
        cls.other=forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65'))).boundary

    def test_adopted_approximation_against_independent_geometry(self):
        rng=np.random.default_rng(51931)
        t=np.r_[np.geomspace(1e-12,.02,200),rng.uniform(0,1,4096),1-np.geomspace(1e-12,.02,200)]
        h=rng.uniform(-2*np.pi,4*np.pi,len(t));c=self.ctx
        exact=capacity_unit(t,h,c.fl,c.aw,c.matrix);expected=decode_unit(c,t,h,exact)
        for table in (boundary_table.Table(self.data),boundary_polynomial.PolynomialTable(self.data)):
            u=table.capacity(t,h);rgb=decode_unit(c,t,h,u.astype(float))
            self.assertTrue(np.isfinite(rgb).all())
            # Adoption accepts the measured ~0.53% capacity / ~0.673% RGB
            # approximation. Containment is deliberately not asserted here.
            self.assertLess(float(np.max(abs(u/exact-1))),.006)
            error=np.max(abs(rgb-expected),-1)
            self.assertTrue(np.all(error<=np.maximum(.007*np.max(expected,-1),1e-7)),float(error.max()))
        with patch('tools.build.boundary_oracle.capacity_unit',side_effect=AssertionError('Runtime solve')):
            np.testing.assert_array_equal(c.unit(t,h),boundary_table.Table(self.data).capacity(t,h))

    def test_uint16_nodes_against_source_bspline(self):
        table=boundary_polynomial.PolynomialTable(self.data);d=table.expanded
        self.assertEqual(d['face_codes'].dtype,np.dtype('u2'))
        self.assertEqual(d['face_codes'].shape,(6,257,257))
        self.assertNotIn('face_polynomial',d)
        rng=np.random.default_rng(524);i=rng.integers(0,257,2048);j=rng.integers(0,257,2048)
        for face in range(6):
            a=boundary_table.basis(self.data['sector_t'][face],i/256)
            b=boundary_table.basis(self.data['sector_s'],j/256)
            expected=np.einsum('ia,ab,ib->i',a,self.data['sectors'][face].astype(float),b)
            decoded=d['face_codes'][face,i,j].astype(float)*d['face_scale'][face]+d['face_offset'][face]
            limit=.51*d['face_scale'][face]+16*np.finfo('f4').eps*np.maximum(abs(expected),1)
            self.assertTrue(np.all(abs(decoded-expected)<=limit))
            self.assertFalse(d['face_codes'].flags.writeable)

    def test_twelve_shared_creases_are_continuous_and_sharp(self):
        table=boundary_table.Table(self.data);s=table.selector
        self.assertEqual(len(self.data['edges']),12)
        for edge,(lo,hi) in enumerate(self.data['edges']):
            t=s.vertices[lo]+np.array([.2,.5,.8])*(s.vertices[hi]-s.vertices[lo])
            curves,_=s.curves(t);h=curves[:,edge,0];center=table.capacity(t,h)
            jump=[]
            for delta in (1e-6,1e-7,1e-8):
                left,right=table.capacity(t,h-delta),table.capacity(t,h+delta)
                jump.append(float(np.max(abs(right-left)/center)))
            self.assertLess(jump[2],.12*jump[1]);self.assertLess(jump[1],.12*jump[0])
            self.assertGreater(float(np.max(abs(right-2*center+left)/(1e-8*center))),1e-3)
            np.testing.assert_array_equal(s.select(t,h-1e-6)[0],s.faces[edge,0])
            np.testing.assert_array_equal(s.select(t,h+1e-6)[0],s.faces[edge,1])

    def test_polynomial_expansion_and_hue_seam(self):
        rng=np.random.default_rng(51932);t=rng.uniform(0,1,2048);h=rng.uniform(-np.pi,np.pi,len(t))
        direct=boundary_table.Table(self.data);fast=boundary_polynomial.PolynomialTable(self.data)
        self.assertLess(float(np.max(abs(fast.capacity(t,h)/direct.capacity(t,h)-1))),1e-5)
        np.testing.assert_allclose(direct.capacity(t,h+2*np.pi),direct.capacity(t,h),rtol=1e-12,atol=0)
        self.assertTrue({'profile_knots','profile_values','guard_axis','guard_polynomial'}.isdisjoint(fast.expanded))
        self.assertLess(sum(v.nbytes for v in fast.expanded.values()),1024*1024)

    def test_candidate_hints_preserve_crease_decisions_at_cell_boundaries(self):
        fast=boundary_polynomial.PolynomialTable(self.data);s=fast.selector
        rows,bins=fast.expanded['edge_hints'].shape[1:]
        t=np.unique(np.concatenate([np.linspace(a,b,rows+1,dtype='f4')
                    for a,b in zip(s.heights[:-1],s.heights[1:])]))
        h=np.linspace(0,np.float32(2*np.pi),bins+1,dtype='f4')
        # Probe exact cell seams, both neighboring representable values and
        # unreduced hues outside the hint domain. A hint is never authoritative.
        for direction in (None,0.,np.inf):
            tt=t if direction is None else np.clip(np.nextafter(t,np.float32(direction)),0,1)
            hh=h if direction is None else np.nextafter(h,np.float32(direction))
            tt,hh=np.meshgrid(tt,np.r_[hh,hh-2*np.pi,hh+12*np.pi])
            tt,hh=tt.ravel(),hh.ravel();region=s.region(tt)
            expected=Selector.left(s,tt,hh,region);actual=s.left(tt,hh,region)
            for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)

    def test_uniform_address_retains_stored_knot_ties(self):
        fast=boundary_polynomial.PolynomialTable(self.data);axis=fast.expanded['edge_axis']
        values=np.r_[axis,np.nextafter(axis,np.float32(-np.inf)),np.nextafter(axis,np.float32(np.inf))]
        for a,b in zip(boundary_polynomial.uniform_address(axis,values),boundary_polynomial.address(axis,values)):
            np.testing.assert_array_equal(a,b)

    def test_bounded_wrapping_matches_general_remainder(self):
        rng=np.random.default_rng(525);tau=boundary_polynomial.TAU
        seams=np.arange(-12,13,dtype='f4')*tau
        bits=rng.integers(0,2**32,100000,dtype='u4').view('f4')
        values=np.r_[bits[np.isfinite(bits)],rng.uniform(-2*tau,2*tau,100000).astype('f4'),
            seams,np.nextafter(seams,np.float32(-np.inf)),np.nextafter(seams,np.float32(np.inf)),
            np.array([0.,-0.],dtype='f4')]
        for v in (values,values[:4096].reshape(64,64),values[:0],np.float32(-0.),np.float32(1000)):
            expected=np.remainder(v,tau)
            np.testing.assert_array_equal(boundary_polynomial.wrap_hue(v).view('u4'),expected.view('u4'))
        chunks=np.concatenate([boundary_polynomial.wrap_hue(values[i:i+16384]) for i in range(0,len(values),16384)])
        np.testing.assert_array_equal(chunks.view('u4'),boundary_polynomial.wrap_hue(values).view('u4'))

    def test_compact_candidates_and_general_hues_preserve_every_selector_output(self):
        s=boundary_polynomial.PolynomialTable(self.data).selector
        rng=np.random.default_rng(5251)
        h=rng.integers(0,2**32,16384,dtype='u4').view('f4');h=h[np.isfinite(h)]
        h=np.r_[h,np.linspace(-16*np.pi,16*np.pi,4096,dtype='f4')]
        t=rng.uniform(0,1,len(h)).astype('f4');t[:len(s.vertices)]=s.vertices
        for actual,expected in zip(s.select(t,h),Selector.select(s,t,h)):
            np.testing.assert_array_equal(actual,expected)

    def test_reused_addresses_match_independent_channel_lookups(self):
        table=boundary_polynomial.PolynomialTable(self.data);s=table.selector
        rng=np.random.default_rng(523);v=s.vertices
        vt,vh=np.meshgrid(np.r_[v,np.nextafter(v,0),np.nextafter(v,1)],
                         np.linspace(-2*np.pi,12*np.pi,129,dtype='f4'))
        edge=np.repeat(np.arange(12),len(table.expanded['edge_axis']))
        low,high=v[s.edges[edge]].T
        et=low+(high-low)*np.tile(table.expanded['edge_axis'],12)
        eh=s.curve(et,edge,0)
        t=np.r_[rng.uniform(0,1,4096),vt.ravel(),et,et,et].astype('f4')
        h=np.r_[rng.uniform(-2*np.pi,4*np.pi,4096),vh.ravel(),eh,
                np.nextafter(eh,np.float32(-np.inf)),np.nextafter(eh,np.float32(np.inf))].astype('f4')
        # The float64 selector's control flow recomputes each channel's address
        # on these same float32 coefficients, independently of the reuse path.
        for tt,hh in ((t,h),(t[:65,None],h[None,:33]),(t[0],h[0])):
            for actual,expected in zip(s.select(tt,hh),Selector.select(s,tt,hh)):
                np.testing.assert_array_equal(actual,expected)
        actual=table.capacity(t,h)
        with patch.object(s,'select',side_effect=lambda t,h:Selector.select(s,t,h)):
            np.testing.assert_array_equal(actual,table.capacity(t,h))

    def test_vertex_topology_retains_original_active_edge_ties(self):
        for s in (boundary_table.Table(self.data).selector,boundary_polynomial.PolynomialTable(self.data).selector):
            v=s.vertices;t=np.r_[v,np.nextafter(v,0),np.nextafter(v,1)]
            t,h=np.meshgrid(t,np.linspace(-2*np.pi,4*np.pi,257,dtype=v.dtype));t,h=t.ravel(),h.ravel()
            curves,active=s.curves(t);angles=curves[...,0]%(2*np.pi)
            low,high=s.vertices[s.limits].T
            exists=((t[:,None]>low)|(low==0))&((t[:,None]<high)|(high==1))
            distances=np.where(active&exists[:,s.faces[:,1]],(h[:,None]-angles)%(2*np.pi),np.inf)
            expected=s.faces[distances.argmin(-1),1]
            np.testing.assert_array_equal(s.select(t,h)[0],expected)

    def test_offline_oracle_restores_model_after_failure(self):
        before=self.ctx.unit
        with self.assertRaisesRegex(RuntimeError,'stop audit'):
            with exact_geometry():
                self.assertNotEqual(self.ctx.unit,before);raise RuntimeError('stop audit')
        self.assertEqual(self.ctx.unit,before)

    def test_shared_resource_is_small_and_honest(self):
        self.assertEqual(int(self.data['format']),16)
        self.assertFalse(bool(self.data['certified']))
        self.assertTrue({'profile','knots','guard_knots','guard_coefficients'}.isdisjoint(self.data))
        self.assertLessEqual(sum(v.nbytes for v in self.data.values()),65536)
        self.assertLessEqual(self.path.stat().st_size,65536)
        self.assertEqual((files(blender.__package__)/'d65_boundary.npz').read_bytes(),self.path.read_bytes())
        for module in (boundary_cache,boundary_table,boundary_polynomial):
            tree=ast.parse(Path(module.__file__).read_text())
            self.assertFalse(any(isinstance(n,ast.While) for n in ast.walk(tree)))
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom):self.assertFalse((n.module or '').startswith(('tools','scipy')))

    def test_scaled_limits_and_blender_correspondence(self):
        ja=np.geomspace(1e-70,min(self.ctx.white*.95,1000),41)
        hue=np.linspace(0,2*np.pi,len(ja))
        expected=self.ctx.capacity(ja,hue)
        np.testing.assert_allclose(expected,self.other.capacity(ja,hue),rtol=2e-14,atol=0)
        for ctx,scalar,project in ((self.ctx,S,guard_scaled),(self.other,B,other_guard_scaled)):
            for j,h,c in zip(ja,hue,expected):
                q=[scalar(signed_hk(j,2*c)),scalar(2*c*np.cos(h)),scalar(2*c*np.sin(h))]
                result,energy,rgb=project(ctx,q,scalar(j)*scalar(j))
                self.assertEqual(energy,scalar(j)*scalar(j))
                self.assertTrue(all(0<=v<=1024 for v in rgb))
            for exponent in (-1000,-10000,-100000):
                j=scalar(1.,exponent)
                q=[j,scalar(1.,1000),scalar(-2.,1000)]
                result,energy,rgb=project(ctx,q,j*j)
                self.assertEqual(energy,j*j)
                self.assertTrue(all(0<=v<=1024 for v in rgb))

    def test_explicit_domain_errors(self):
        for c in (self.ctx,self.other):
            for t,h in ((-1.,0.),(1.1,0.),(.5,np.nan)):
                with self.assertRaisesRegex(ValueError,'finite hue'):c.unit(t,h)
            with self.assertRaisesRegex(ValueError,'finite appearance triples|finite appearance triples|finite appearance|finite triples'):
                guard(c,[np.nan,1.,1.],0.)


if __name__=='__main__':unittest.main()
