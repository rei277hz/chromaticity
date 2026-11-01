"""Regression coverage of the archived p=1.001, d=20 radial experiment."""
from decimal import Decimal, localcontext
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.pole_spindle import (
    radius_map, _release_radius, _compress_radius, RADIAL_POLE,
)


class HistoricalPoleSpindle(unittest.TestCase):
    def test_full_radius_decimal_and_inverse(self):
        with localcontext() as d:
            d.prec=90
            for k in (1.,np.nextafter(1.,2.),1.01,2.,17.2,1000.,1e8):
                x=np.unique(np.r_[0.,np.geomspace(1e-300,.01,80),np.linspace(0,1,301),np.nextafter(1.,0.)])
                expected=[];p=Decimal(1002001)/1000000;dk=Decimal.from_float(k)
                a=Decimal(1925963)/1000000;b=-Decimal(1921961)/1000000
                for value in x:
                    v=Decimal.from_float(float(value));z=v*v
                    f=z*(a+b*z)/((1+z)*(p-z))
                    expected.append(float(v*(1+(dk*dk-1)*f).sqrt()))
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

    def test_analytic_extension_and_pole(self):
        x=1+(RADIAL_POLE-1)*np.array([0.,.2,.4,.8,.98,.998])
        for k in (1.01,2.,10.):
            y=_release_radius(x,k)
            self.assertTrue(np.all(np.diff(y)>0))
            np.testing.assert_allclose(_compress_radius(y,k),x,rtol=4e-15,atol=0.)
            # A simple pole in F gives a square-root divergence in release.
            distance=(RADIAL_POLE-1)*np.array([2e-3,2e-5,2e-7])
            scaled=_release_radius(RADIAL_POLE-distance,k)*np.sqrt(distance)
            p=RADIAL_POLE;limit=np.sqrt(39*(k*k-1)*p**3*(p*p-1)**2/(2*(p*p+1)))
            errors=np.abs(scaled/limit-1)
            self.assertTrue(np.all(errors[1:]<errors[:-1]*.03),errors)
            self.assertLess(errors[-1],2e-4)
            self.assertGreater(float(_release_radius(RADIAL_POLE-(RADIAL_POLE-1)*1e-8,k)),100.)
        np.testing.assert_array_equal(_release_radius(x,1.),x)
        np.testing.assert_array_equal(_compress_radius(x,1.),x)

    def test_radial_derivatives(self):
        k=5.;x=np.linspace(.01,.99,50);eps=1e-6;p=1002001/1000000;z=x*x
        profile_a=1925963/1000000;profile_b=-1921961/1000000
        # Independent partial-fraction differentiation of the release curve.
        f=-profile_b-(profile_a-profile_b)/((p+1)*(1+z))+p*(profile_a+profile_b*p)/((p+1)*(p-z))
        df=(profile_a-profile_b)/((p+1)*(1+z)**2)+p*(profile_a+profile_b*p)/((p+1)*(p-z)**2)
        ddf=-2*(profile_a-profile_b)/((p+1)*(1+z)**3)+2*p*(profile_a+profile_b*p)/((p+1)*(p-z)**3)
        gain=k*k-1;g=1+gain*f
        slope=np.sqrt(g)+gain*z*df/np.sqrt(g)
        curve=gain*x*((3*df+2*z*ddf)*g-gain*z*df*df)/g**1.5
        left=_release_radius(x-eps,k);center=_release_radius(x,k);right=_release_radius(x+eps,k)
        np.testing.assert_allclose((right-left)/(2*eps),slope,rtol=2e-7,atol=2e-8)
        # A wider second-difference step avoids cancellation at low curvature.
        second_step=1e-5
        before=_release_radius(x-second_step,k);after=_release_radius(x+second_step,k)
        np.testing.assert_allclose((after+before-2*center)/second_step**2,curve,rtol=3e-4,atol=3e-5)
        self.assertTrue(np.all(slope>1))
        # Resolve the narrower pole shoulder with a correspondingly smaller
        # first-difference step at x=1; the second derivative is large here.
        boundary_step=1e-8
        slope_at_one=float((_release_radius(1+boundary_step,k)-_release_radius(1-boundary_step,k))/(2*boundary_step))
        self.assertAlmostEqual(slope_at_one,21*k-20/k,places=5)


if __name__ == "__main__":
    unittest.main()
