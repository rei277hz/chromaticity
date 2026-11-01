"""Independent input projection, base responses and complete spindle extremes."""
from decimal import Decimal, localcontext
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
from color_tools.perceptual_grade_reference.appearance import response_constants, encode_cones
from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings, normalized_kernel, fit_width, coefficient_weights
from color_tools.perceptual_grade_reference.grading import ColorSettings
from color_tools.perceptual_grade_reference.model import Model, Settings, LinearSettings
from color_tools.perceptual_grade_reference.responses import compress, coordinates
from color_tools.color_core.scaled import Scalar as S, norm, smooth_floor, smooth_cap
from color_tools.perceptual_grade_reference.export import input_repair

class GuardTests(unittest.TestCase):
    def test_input_projection_decimal_identity_range_and_idempotence(self):
        weights=np.array([.25,.7,.05])
        values=np.array([[1.,2.,3.],[-1.,2.,.5],[4.,-1.,2.],[-1.,-2.,-3.],
                         [0.,0.,0.],[2048.,400.,1.],[1024.,1024.,1024.]])
        expected=[]
        with localcontext() as ctx:
            ctx.prec=80
            for row in values:
                r=[Decimal(str(x))for x in row];y=sum(Decimal(str(w))*x for w,x in zip(weights,r))
                k=max(Decimal(0),-min(r));n=max(Decimal(0),y)
                v=[n*(x+k)/(n+k) if n+k else Decimal(0) for x in r]
                maximum=max(Decimal(1024),*v)
                expected.append([float(1024*x/maximum)for x in v])
        actual=input_repair(values,weights)
        np.testing.assert_allclose(actual,expected,rtol=5e-15,atol=1e-15)
        self.assertTrue((actual>=0).all());self.assertTrue((actual<=1024).all())
        np.testing.assert_array_equal(input_repair(actual,weights),actual)
        np.testing.assert_array_equal(actual[[0,4,6]],values[[0,4,6]])
        huge=np.array([[np.finfo(float).max,-1.,np.finfo(float).max]])
        self.assertTrue(np.isfinite(input_repair(huge,weights)).all())
        for value in ([1,2],[np.nan,0,0],[np.inf,0,0]):
            with self.assertRaises(ValueError):input_repair(value,weights)

    def test_input_projection_continuity_at_zero_y_origin_and_cube_edges(self):
        weights=np.array([.25,.7,.05]);center=np.array([-1.,.25/.7,0.])
        for step in (1e-3,1e-5,1e-7):
            result=input_repair(np.array([center-step,center+step]),weights)
            self.assertLess(np.max(abs(result)),4*step)
            np.testing.assert_allclose(input_repair([[1024-step,100,1],[1024+step,100,1]],weights),
                                       [[1024,100,1]]*2,rtol=0,atol=2*step)
            self.assertLess(np.max(abs(input_repair(step*center,weights))),step)

    def test_cone_zero_continuity(self):
        model = Model(Settings(color=ColorSettings(global_gain=-.3, web=WebSettings(hue_degrees=((20.,)*6,)*4))))
        matrix = model.cones_to_xyz
        center = model.forward_xyz(np.array([0., .2, .1]) @ matrix.T)
        self.assertGreater(np.max(np.abs(center)), 0.)
        previous = None
        for step in (1e-3, 1e-4, 1e-5, 1e-6):
            cones = np.array([[-step, .2, .1], [step, .2, .1]])
            output = model.forward_xyz(cones @ matrix.T)
            error = np.max(np.abs(output-center))
            self.assertTrue(np.isfinite(output).all())
            if previous is not None:
                self.assertLess(error, previous*.65)  # Cone compression has exponent .42.
            previous = error

    def test_offset_free_subnormal_and_external_colour_rewrite(self):
        tiny = np.nextafter(0., 1.)
        source = [compress(S(tiny)*v, response_constants(203.)[0]) for v in (1., 2., 4.)]
        q, ja = coordinates(source, response_constants(203.)[1])
        self.assertGreater(ja, 0)
        self.assertGreater(norm(q[1:]), 0)
        actual = encode_cones([tiny, 2*tiny, 4*tiny])
        self.assertGreater(actual.ja, 0)
        self.assertGreater(np.hypot(*actual.q[1:]), 0)
        np.testing.assert_allclose(actual.q, [float(v) for v in q], rtol=1e-13, atol=0)

    def test_continuous_nits_and_fractional_extreme_fits(self):
        for fit in (-np.finfo(float).max, -2000., -2.25, .125, 7., 2000., np.finfo(float).max):
            tone = Tone(ToneSettings(input_nits=(0., 8., 40., 235., 1150.), fit=fit))
            h = np.linspace(0., 300., 501)
            self.assertTrue((np.diff(tone.remap(h)) > 0).all())
            w = coefficient_weights(h, tone.coefficient_knots, tone.high, fit)
            self.assertTrue((w >= 0).all())
            np.testing.assert_allclose(w.sum(axis=-1), 1., atol=3e-16)
        for lower, upper in [(48., 1000.), (406., 10000.)]:
            for joint in (lower, lower+1, upper-1, upper):
                step = .001
                y = [float(smooth_cap(smooth_floor(joint+d, lower), upper)) for d in (-step, 0., step)]
                self.assertLess(abs((y[2]-2*y[1]+y[0])/step**2), .03)
        a = Tone(ToneSettings(reference_nits=203.2, peak_nits=1000.3))
        self.assertEqual(a.reference, 203.2)
        self.assertEqual(a.peak, 1000.3)
        t = np.array([0., .1, .5, 1., 2.])
        np.testing.assert_array_equal(normalized_kernel(t, .2, .4, fit_width(-np.finfo(float).max)), t)

    def test_extreme_rgb_and_every_continuous_control_family(self):
        maximum, tiny = np.finfo(float).max, np.nextafter(0., 1.)
        values = np.array([[0., 0., 0.], [tiny, 0., -tiny], [maximum, maximum, maximum],
                           [-maximum, maximum, maximum], [maximum, -maximum, tiny], [.18, .1, .04]])
        profiles = [Settings(), Settings(linear=LinearSettings(exposure=maximum)),
                    Settings(linear=LinearSettings(exposure=-maximum)),
                    Settings(linear=LinearSettings(balance=(maximum, -maximum), spread=(maximum, -maximum), heading=(maximum, -maximum))),
                    Settings(linear=LinearSettings(matrix=((maximum, maximum, -maximum),)*3)),
                    Settings(tone=ToneSettings(input_nits=(maximum,)*5, fit=maximum, peak_nits=maximum)),
                    Settings(color=ColorSettings(global_gain=maximum)), Settings(color=ColorSettings(global_gain=-maximum)),
                    Settings(color=ColorSettings(lightness=((maximum, -maximum, maximum, -maximum),)*4,
                        chroma=((maximum, -maximum, maximum, -maximum),)*4,
                        adaptance=((1., -.5),)*4, adaptance_half_saturation=1.,
                        lightness_fit=maximum, chroma_fit=-maximum))]
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            for settings in profiles:
                with self.subTest(settings=settings):
                    y = Model(settings).forward(values)
                    self.assertTrue(np.isfinite(y).all())
                    native=y@Model(settings).to_acescg.T
                    self.assertGreaterEqual(native.min(),-2e-10)
                    self.assertLessEqual(native.max(),1024.+2e-10)

    def test_vector_and_scaled_equations_agree(self):
        x = np.array([[.18, .1, .04], [-.1, .2, .5], [1e-6, .1, 2.], [128., 40., 1000.],
                      [-.1, -.1, -.1], [-.3, -.05, .01], [-128., 40., -1000.]])
        settings = Settings(tone=ToneSettings(input_nits=(0., 8., 40., 235., 1150.), fit=.3),
                            color=ColorSettings(global_gain=.2, adaptance=((.05,-.02),)*4,
                                web=WebSettings(hue_degrees=((2.,-3.,1.,0.,-2.,1.),)*4,
                                                log_chroma=((.03,-.02,.01,0.,-.01,.02),)*4,
                                                log_scale=((.01,0.,-.01,.02,0.,-.01),)*4)))
        model = Model(settings)
        vector = model.forward(x)
        model.vector_controls = False
        scaled = model.forward(x)
        np.testing.assert_allclose(vector, scaled, rtol=3e-12, atol=3e-12)

    def test_tiny_tone_levels_and_large_dark_controls_survive_scaling(self):
        tiny = np.nextafter(0., 1.)
        model = Model(Settings(tone=ToneSettings(input_nits=(tiny, 8., 40., 235., 1150.))))
        self.assertGreater(model.tone.black, 0.)
        plateau = Model(Settings(tone=ToneSettings(input_nits=(1000*tiny, 8., 40., 235., 1150.))))
        np.testing.assert_array_equal(plateau.forward([[tiny, tiny, tiny]]), 0.)
        dark = Model(Settings(linear=LinearSettings(exposure=-2000.),
                     color=ColorSettings(lightness=((0., 0., np.finfo(float).max, 0.),)*4)))
        y = dark.forward([[.8, .1, .02]])
        self.assertTrue(np.isfinite(y).all())
        self.assertGreater(np.max(np.abs(y)), 1.)

