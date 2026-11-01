"""Independent decimal anchors, exact cube rays, and finite spindle contracts."""
from decimal import Decimal,localcontext
import unittest
import tempfile
from pathlib import Path
import numpy as np
from color_tools.perceptual_grade_reference.spindle import (Context,radius_map,capacity_unit,beta,white_response,
    _release_radius,_compress_radius)
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_reference.appearance import encode_cones
from color_tools.perceptual_grade_reference.responses import GAMMA,hk_energy
from color_tools.color_core.scaled import Scalar as S
from tools.build.boundary_oracle import ray_valid,capacity_unit as oracle_capacity


class SpindlePrimitives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from color_tools.perceptual_grade_reference.spindle import context
        model=Model()
        cls.ctx=context(model.fl,model.aw,model.native_matrix)

    def test_full_radius_decimal_and_inverse(self):
        with localcontext() as d:
            d.prec=90
            for k in (1.,np.nextafter(1.,2.),1.01,2.,17.2,1000.,1e8):
                x=np.unique(np.r_[0.,np.geomspace(1e-300,.01,80),np.linspace(0,1,301),np.nextafter(1.,0.)])
                expected=[];dk=Decimal.from_float(k)
                for value in x:
                    v=Decimal.from_float(float(value))
                    expected.append(float(v+(dk-1)*v**3))
                actual=radius_map(x,1.,k,True)
                np.testing.assert_allclose(actual,expected,rtol=8e-16,atol=0.)
                np.testing.assert_allclose(radius_map(actual,1.,k),x,rtol=4e-15,atol=0.)
                self.assertEqual(float(radius_map(k,1.,k)),1.)
                self.assertEqual(float(radius_map(1.,1.,k,True)),k)
                if k>1.01:self.assertGreater(float(radius_map(.1,1.,k,True)),.1)
                self.assertTrue(np.all(np.diff(actual)>=0))
        np.testing.assert_array_equal(radius_map([0.,1.],0.,3.),0.)

    def test_radial_broadcasting_and_physical_clipping(self):
        k=np.array([1.,2.,17.2]);b=np.array([.01,1.,100.])
        x=np.linspace(0,1,33)[:,None]*b
        np.testing.assert_allclose(radius_map(radius_map(x,b,k,True),b,k),x,rtol=4e-15,atol=0.)
        np.testing.assert_array_equal(radius_map(b*2,b,k,True),b*k)
        np.testing.assert_array_equal(radius_map(b*k*2,b,k),b)
        for k0 in (2.,10.,17.2):
            before=np.nextafter(k0,0.)
            result=float(radius_map(before,1.,k0))
            self.assertLessEqual(result,1.)
            self.assertGreaterEqual(result,0.)
        for args in ((-1.,1.,2.),(1.,-1.,2.),(1.,1.,.9)):
            with self.assertRaises(ValueError):radius_map(*args)

    def test_unclipped_cubic_inverse(self):
        x=np.r_[0.,np.geomspace(1e-100,10.,250)]
        for k in (1.,np.nextafter(1.,2.),1.01,2.,10.,100.):
            y=_release_radius(x,k)
            self.assertTrue(np.all(np.diff(y)>0))
            np.testing.assert_allclose(_compress_radius(y,k),x,rtol=4e-15,atol=0.)
        np.testing.assert_array_equal(_release_radius(x,1.),x)
        np.testing.assert_array_equal(_compress_radius(x,1.),x)

    def test_radial_derivatives(self):
        k=5.;x=np.linspace(.01,.99,50);eps=1e-6
        slope=1+3*(k-1)*x*x
        curve=6*(k-1)*x
        left=_release_radius(x-eps,k);center=_release_radius(x,k);right=_release_radius(x+eps,k)
        np.testing.assert_allclose((right-left)/(2*eps),slope,rtol=2e-7,atol=2e-8)
        second_step=1e-5
        before=_release_radius(x-second_step,k);after=_release_radius(x+second_step,k)
        np.testing.assert_allclose((after+before-2*center)/second_step**2,curve,rtol=3e-4,atol=3e-5)
        self.assertTrue(np.all(slope>1))
        boundary_step=1e-6
        slope_at_one=float((_release_radius(1+boundary_step,k)-_release_radius(1-boundary_step,k))/(2*boundary_step))
        self.assertAlmostEqual(slope_at_one,3*k-2,places=7)

    def test_cartesian_neutral_derivative(self):
        ctx=self.ctx;angles=np.linspace(-np.pi,np.pi,127,endpoint=False)
        directions=np.column_stack((np.cos(angles),np.sin(angles)))
        for fraction in (.01,.15,.4,.85,.99):
            j=fraction*ctx.white;body=ctx.body(j);k=ctx.capacity(j,angles)/body
            for release in (False,True):
                previous=None
                for r in (1e-3,5e-4,2.5e-4):
                    mapped=radius_map(r*body,body,k,release)/body
                    error=np.max(np.linalg.norm((mapped-r)[:,None]*directions,axis=1))/r
                    self.assertLessEqual(error,(np.max(k)-1)*r*r+2e-15)
                    if previous is not None:self.assertLess(error,previous*.26)
                    previous=error

    def test_scaled_neutral_below_float_range(self):
        body=S(float(self.ctx.body(100.)))
        for c in (S(1,-100000),body*S(1,-1074),body*S(.7,-1060)):
            q=[S(100),c,-2*c];e=S(10000)
            for release in (False,True):
                out,energy=self.ctx.finite_scaled(q,e,release)
                self.assertEqual(energy,e)
                self.assertEqual(out[1],q[1]);self.assertEqual(out[2],q[2])

    def test_subnormal_chroma_is_not_lost_by_normalized_inverse(self):
        smallest=np.nextafter(0.,1.)
        for k0 in (2.,10.,17.2):
            for value in (smallest,1e-322,1e-310):
                self.assertEqual(float(radius_map(value,1.,k0)),value)

    def test_cube_reset_and_witnesses(self):
        from tools.build.boundary_oracle import exact_geometry
        with exact_geometry():self.exact_cube_reset()

    def exact_cube_reset(self):
        ctx=self.ctx
        rgb=np.array([[0.,0.,0.],[1024.]*3,[0.,1.,0.],[0.,938.63,0.],[0.,1024.,0.],
                      [1024.,1024.,0.],[1019.786927720954,1024.,15.754414476996],[2.,0.,128.],
                      [.16888587493041068,.04064936767165314,1024.],
                      [.5175845487618758,.5175845487618758,1024.],
                      [16.197876794372785,.35789176097077685,1024.]])
        inv=np.linalg.inv(ctx.matrix);cones=rgb[:,1,None]+(rgb-rgb[:,1,None])@inv.T
        a=encode_cones(cones);q,e=ctx.compress(a.q,a.ja**2);q,e=ctx.guard(q,e);q,e=ctx.release(q,e)
        actual=ctx.decode(q,e)
        self.assertTrue(np.all((actual>=0)&(actual<=1024)),actual)
        # Include boundary reconstruction and RGB decode in the reset budget;
        # isolated radial/Decimal tests retain their stricter error budgets.
        np.testing.assert_allclose(actual,rgb,rtol=0,atol=2e-10)
        np.testing.assert_array_equal(actual[0],0.)
        j=np.geomspace(1e-25,1000.,31);h=np.linspace(-3,8,len(j))
        b=ctx.body(j);c=b*.8;q=np.column_stack((np.hypot(j,np.sqrt(66*c)),c*np.cos(h),c*np.sin(h)))
        x,en=ctx.compress(q,j*j);y,ee=ctx.release(x,en)
        np.testing.assert_allclose(y,q,rtol=2e-13,atol=0.)
        np.testing.assert_array_equal(ee,j*j)

    def test_guard_projection_and_signed_energy(self):
        ctx=self.ctx;h=np.array([0.,1.,100.,1000.,ctx.white,1e100]);cap,energy=ctx.boundary(h[1:4])
        q=np.column_stack((h,np.zeros_like(h),np.zeros_like(h)))
        q[1:4,1:]=cap[:,None]*np.array([1.2,1.6])
        e=hk_energy(h,np.hypot(q[:,1],q[:,2]));out,en=ctx.guard(q,e)
        np.testing.assert_array_equal(out[:,0],np.minimum(h,ctx.white))
        again,ee=ctx.guard(out,en)
        np.testing.assert_array_equal(again,out);np.testing.assert_array_equal(ee,en)
        np.testing.assert_allclose(out[1:4,2]/out[1:4,1],q[1:4,2]/q[1:4,1],rtol=3e-16)
        np.testing.assert_allclose(np.hypot(out[1:4,1],out[1:4,2]),cap,rtol=5e-16)
        tiny=S(1.,-100000)
        a,b=ctx.guard_scaled([tiny,S(1),S(2)],S(-1))
        self.assertEqual(a[0],tiny);self.assertGreater(b,0)
        released,er=ctx.finite_scaled(a,b,True)
        self.assertEqual(er,b);self.assertTrue(all(v>=0 for v in ctx.decode_scaled(released,er)))

    def test_capacity_tip_limits_and_brackets(self):
        ctx=self.ctx;t=np.array([0.,1e-25,.2,.8,1-1e-12,1.]);h=np.array([.1,1.,2.,3.,4.,5.])
        u=oracle_capacity(t,h,ctx.fl,ctx.aw,ctx.matrix);d=beta(h,ctx.aw);rw=white_response(ctx.fl)
        from tools.build.boundary_oracle import exact_geometry
        with exact_geometry():np.testing.assert_allclose(ctx.unit(t,h),u,rtol=3e-14,atol=0)
        self.assertTrue(ray_valid(t,u,d,rw,ctx.matrix).all())
        self.assertTrue((~ray_valid(t,u*(1+1e-8),d,rw,ctx.matrix)).all())
        self.assertTrue(np.all(u>0))

    def test_white_distance_decode_on_geometric_rays(self):
        from color_tools.perceptual_grade_core.model.spindle import Context as Blender
        from tools.build.boundary_oracle import exact_geometry
        c=self.ctx;b=Blender(c.knots.copy(),c.profile.copy(),c.white,c.fl,c.aw,c.matrix.copy(),c.cache)
        h=np.linspace(0,2*np.pi,721,endpoint=False)
        for position in (.1,.5,.9,1-1e-9,1-1e-12,np.nextafter(1.,0.)):
            j=c.white*position**GAMMA
            # Check the decoder on the true cube, independently of the adopted
            # uint16 approximation's known boundary overshoot.
            with exact_geometry():radius=c.capacity(j,h)*(1-1e-7)
            q=np.column_stack((np.hypot(j,np.sqrt(66*radius)),radius*np.cos(h),radius*np.sin(h)))
            for context in (c,b):
                rgb=context.decode(q,j*j)
                self.assertTrue(np.all((rgb>=0)&(rgb<=1024)),(position,rgb.min(),rgb.max()))
        from color_tools.color_core.scaled import Scalar as B
        for context,scalar in ((c,S),(b,B)):
            for height in (c.white-1e-9,np.nextafter(c.white,0.),c.white):
                for angle in np.linspace(0,2*np.pi,17):
                    q=[scalar(height),scalar(np.cos(angle))*scalar(1,10000),scalar(np.sin(angle))*scalar(1,10000)]
                    q,e=context.guard_scaled(q,scalar(-1,10000))
                    q,e=context.finite_scaled(q,e,True)
                    self.assertTrue(all(0<=v<=1024 for v in context.decode_scaled(q,e)))

    def test_independent_blender_and_scaled_paths(self):
        from color_tools.perceptual_grade_core.model.spindle import Context as Blender, map_radius
        c=self.ctx;b=Blender(c.knots.copy(),c.profile.copy(),c.white,c.fl,c.aw,c.matrix.copy(),c.cache)
        rng=np.random.default_rng(9321);j=np.exp(rng.uniform(-80,np.log(1000),81));h=rng.uniform(-5,8,len(j))
        radius=c.body(j)*rng.uniform(.1,2,len(j))
        q=np.column_stack((np.hypot(j,np.sqrt(66*radius)),radius*np.cos(h),radius*np.sin(h)))
        x,e=c.guard(q,j*j);y,f=b.guard(q,j*j)
        np.testing.assert_allclose(x,y,rtol=3e-13,atol=0.);np.testing.assert_allclose(e,f,rtol=3e-13,atol=0.)
        from color_tools.color_core.scaled import Scalar as BS
        # Independent float64 implementations use the same production cubic.
        for release in (False,True):
            z,g=(c.release if release else c.compress)(x,e)
            bz,bg=(b.release if release else b.compress)(x,e)
            np.testing.assert_allclose(z,bz,rtol=3e-13,atol=0.)
            np.testing.assert_array_equal(g,bg)
        for context,scalar in ((c,S),(b,BS)):
            for release in (False,True):
                z,g=(context.release if release else context.compress)(x,e)
                for i in (0,20,80):
                    a,ae=context.finite_scaled(list(map(scalar,x[i])),scalar(e[i]),release)
                    np.testing.assert_allclose(list(map(float,a)),z[i],rtol=3e-13,atol=0.)
                    self.assertEqual(float(ae),float(g[i]))
        t=np.array([0.,1e-12,.5,1-1e-12,1.]);h=np.arange(5.)
        np.testing.assert_allclose(b.unit(t,h),c.unit(t,h),rtol=3e-13)
        for k in (1.,3.,100.):
            x=np.linspace(0,1,131)
            np.testing.assert_allclose(map_radius(x,1.,k,True),x+(k-1)*x**3,rtol=8e-16)
            for release in (False,True):
                radius=x if release else x*k
                np.testing.assert_allclose(radius_map(radius,1.,k,release),
                    map_radius(radius,1.,k,release),rtol=4e-15,atol=0.)

    def test_directed_power_against_decimal(self):
        from tools.build.spindle_certificate import I,power
        x=np.geomspace(1e-4,100.,61)
        with localcontext() as d:
            d.prec=90
            for n,den in ((21,50),(29,50),(50,21),(29,21)):
                enclosure=power(I(x),n,den)
                for v,lo,hi in zip(x,enclosure.lo,enclosure.hi):
                    exact=Decimal.from_float(float(v))**(Decimal(n)/Decimal(den))
                    self.assertLessEqual(Decimal.from_float(float(lo)),exact)
                    self.assertGreaterEqual(Decimal.from_float(float(hi)),exact)

    def test_interval_classification_against_decoder(self):
        from tools.build.spindle_certificate import I,directions,classify
        c=self.ctx;t=np.tile(np.array([0.,.01,.49,.51,.99,1.]),12)
        h=np.repeat(np.linspace(0,2*np.pi,12,endpoint=False),6)
        tl=np.maximum(0.,t-1e-7);th=np.minimum(1.,t+1e-7);hl=h-1e-7;hh=h+1e-7
        d=directions(hl,hh,c.aw);center=directions(h,h,c.aw)[:,:,0]
        u=capacity_unit(t,h,c.fl,c.aw,c.matrix)
        for factor in (.95,1.05):
            inside,outside=classify(I(tl,th),I(u*factor),d[:,:,0],c.fl,c.matrix,center,d[:,:,1],I(np.full(len(t),1.00000001e-7)),
                I(t),I(u*factor),I(np.zeros_like(t)),I(np.maximum(t-tl,th-t)))
            self.assertTrue(np.all(inside if factor<1 else outside))
            for a in (0.,.5,1.):
                for b in (0.,.5,1.):
                    valid=ray_valid(tl*(1-a)+th*a,u*factor,beta(hl*(1-b)+hh*b,c.aw),white_response(c.fl),c.matrix)
                    self.assertFalse(np.any(inside&~valid));self.assertFalse(np.any(outside&valid))

    def test_cache_validation_and_aggregate_budget(self):
        from color_tools.perceptual_grade_core.model.spindle import Context as Blender
        c=self.ctx
        from importlib.resources import files
        with np.load(files('color_tools.perceptual_grade_reference')/'d65_boundary.npz') as source:data=dict(source)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'context.npz'
            for cls in (Context,Blender):
                np.savez_compressed(path,**data)
                loaded=cls.load(path,c.fl,c.aw,c.matrix)
                self.assertFalse(loaded.profile.flags.writeable)
                with self.assertRaises(ValueError):cls.load(path,c.fl*2,c.aw,c.matrix)
                np.savez_compressed(path,**dict(data,profile_certified=False))
                with self.assertRaises(ValueError):cls.load(path,c.fl,c.aw,c.matrix)
                # A highly compressible extra array is still part of the total
                # decoded payload; compressed archive size alone is insufficient.
                np.savez_compressed(path,**dict(data,extra=np.zeros(8192)))
                with self.assertRaises(ValueError):cls.load(path,c.fl,c.aw,c.matrix)


if __name__=='__main__':unittest.main()
