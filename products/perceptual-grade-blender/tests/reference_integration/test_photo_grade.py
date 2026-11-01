"""Independent settings and native-input contracts for regular Grade studies."""
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.export import input_repair
from tests.reference.legacy_capacity import LegacyCapacityModel
from tests.support import reference as oracle
from tools.analysis.photo_grade import extension_settings,extension_model,prepare
from tools.analysis.photo_stack import cases
from tools.analysis.grade_photo_error import measure


class PhotoGradeTests(unittest.TestCase):
    def test_eight_case_conversion_preserves_controls_and_forward_math(self):
        settings=cases()
        self.assertEqual(set(settings),{'reset','exposure','tone','chroma','hue',
                                       'mixed','mixed_tone','strong_chroma'})
        rgb=np.array([[0.,0.,0.],[.1,.2,.3],[.02,.08,.4],[.08,.08,.08],[2.,1.,.5]])
        for name,value in settings.items():
            with self.subTest(case=name):
                converted=extension_settings(value);expected=LegacyCapacityModel(value,hk_guard=True)
                self.assertEqual(oracle.tone_settings(converted.tone),value.tone)
                self.assertEqual(oracle.color_settings(converted.color),value.color)
                self.assertEqual(converted.space.preset,'D65')
                np.testing.assert_allclose(converted.matrix,expected.linear,rtol=0,atol=0)
                actual=extension_model(value).apply_native(rgb)
                # A photo-stack forward runs the portable float32 kernel; the
                # independent reference evaluates the same controls in float64.
                self.assertEqual(actual.dtype,np.dtype('float32'))
                self.assertLessEqual(float(oracle.error(actual,expected.forward_native(rgb)).max()),1e-6)

    def test_stage_one_exposure_is_outside_the_core_and_applied_once(self):
        source=np.array([[[.125,.25,.5],[300.,20.,10.]],[[0.,0.,0.],[.1,.1,.1]]])
        for name,gain in (('reset',1.),('exposure',4.)):
            with self.subTest(case=name):
                model=extension_model(cases()[name])
                prepared=prepare(model,source)
                expected=input_repair(source*gain,model.grades[0].forward.acescg_y)
                self.assertEqual(prepared.shape,source.shape)
                self.assertEqual(prepared.dtype,np.dtype('float32'))
                np.testing.assert_allclose(prepared,expected,rtol=2e-7,atol=2e-6)
                # The LUT core receives already-exposed pixels, even though
                # the complete model retains the original Stage 1 matrix.
                np.testing.assert_array_equal(model.bake_native(prepared),prepared)
                np.testing.assert_allclose(model.apply_native(source),expected,rtol=2e-7,atol=2e-6)
                np.testing.assert_array_equal(prepared[0,0],source[0,0]*gain)

    def test_input_repair_preserves_vertices_and_defines_signed_inputs(self):
        model=extension_model(cases()['reset'])
        vertices=np.stack(np.meshgrid([0.,1024.],[0.,1024.],[0.,1024.],indexing='ij'),-1)
        np.testing.assert_array_equal(prepare(model,vertices),vertices)
        source=np.array([[0.,0.,0.],[-1.,-1.,-1.],[-1.,2.,3.],
                         [2048.,2048.,2048.],[1e10,2e10,-1e10]])
        actual=prepare(model,source)
        expected=input_repair(source,model.grades[0].forward.acescg_y)
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_array_equal(actual[:2],0.)
        np.testing.assert_array_equal(actual[3],[1024.,1024.,1024.])
        np.testing.assert_allclose(actual,expected,rtol=3e-7,atol=3e-6)
        for invalid in (np.zeros((2,4)),np.full((1,3),np.nan),np.full((1,3),np.inf)):
            with self.assertRaises(ValueError):prepare(model,invalid)

    def test_measure_reports_extra_strict_bands_without_clipping(self):
        # code_max=1 makes exact equality independent of division rounding.
        expected=np.zeros((1,5,3));actual=expected.copy()
        actual[0,:,0]=[.1,.4,.5,1.,2.]
        result=measure(actual,expected,1.)
        counts={'0.1':4,'0.4':3,'0.5':2,'1.0':1,'2.0':0}
        self.assertEqual(result['pixels_above_codes'],counts)
        self.assertEqual(result['fraction_above_codes'],{key:value/5 for key,value in counts.items()})
        self.assertEqual(result['codes']['maximum'],2.)
        self.assertEqual(result['worst']['flat_index'],4)
        outside=np.array([[-.1,1.2,0.]])
        fine=measure(outside+1e-6,outside,1023.)
        self.assertGreater(fine['codes']['maximum'],0.)
        self.assertAlmostEqual(fine['codes']['maximum'],.001023,places=10)
        self.assertEqual(fine['exact_pixels'],0)
        self.assertEqual(fine['worst']['expected'],[-.1,1.2,0.])
        self.assertEqual(measure(outside,outside,255.)['exact_pixels'],1)


if __name__=='__main__':unittest.main()
