"""Encoded-space measurement, without quantization or hidden clipping."""
import unittest
from types import SimpleNamespace
import numpy as np
from color_tools.perceptual_grade_reference.responses import State
from tools.analysis.stack_photo_error import metrics,located_metric,crop_triptych,forward_diagnostic
from tools.analysis.photo_stack import ForcedStack,cases,prepare,eval_core


class PhotoMetricTests(unittest.TestCase):
    def test_code_units_thresholds_and_channel_versus_pixel_statistics(self):
        expected=np.zeros((1,4,3));actual=expected.copy()
        actual[0,:,0]=np.array([.5,1,2,4])/255
        result=metrics(actual,expected,255)
        self.assertAlmostEqual(result['codes']['mean_absolute_channel'],7.5/12)
        self.assertAlmostEqual(result['codes']['rmse_channel'],np.sqrt(21.25/12))
        self.assertEqual(result['pixels_above_codes'],{'0.5':3,'1.0':2,'2.0':1,'4.0':0})
        self.assertEqual(result['worst']['flat_index'],3)
        self.assertEqual(result['codes']['maximum'],4)
        hdr=metrics(actual,expected,1023)
        self.assertAlmostEqual(hdr['codes']['maximum'],4*1023/255)

    def test_errors_are_not_clipped_or_quantized(self):
        expected=np.array([[[-.1,1.2,0.]]]);actual=expected+1e-6
        result=metrics(actual,expected,255)
        self.assertGreater(result['encoded']['maximum'],0)
        self.assertEqual(result['exact_pixels'],0)
        self.assertEqual(result['worst']['expected'],[-.1,1.2,0.])
        self.assertEqual(metrics(expected,expected,255)['exact_pixels'],1)
        for invalid in (np.full((1,3),np.nan),np.empty((0,3))):
            with self.assertRaises(ValueError):metrics(invalid,invalid,255)

    def test_spatial_worst_and_edge_crop(self):
        expected=np.zeros((2,3,3));actual=expected.copy();actual[1,2,0]=.5
        fixture={'rgb':np.ones((2,3,3))}
        worst=located_metric(actual,expected,255,fixture)['worst']
        self.assertEqual(worst['sample_xy'],[2,1]);self.assertEqual(worst['original_xy'],[24,12])
        crop,bounds=crop_triptych([expected,actual,actual],1,2)
        self.assertEqual(bounds,(0,2,0,3));self.assertEqual(crop.shape,(16,72,3))

    def test_black_and_independent_reproduction_for_known_preimage(self):
        table=None
        for name,setting in cases().items():
            with self.subTest(case=name):
                stack=ForcedStack([setting,setting],['FORWARD','INVERSE'],table);table=stack.table
                p=prepare(stack,np.zeros((1,3)))
                np.testing.assert_array_equal(eval_core(stack,p['input'])[0,:3],0)
                point=np.array([.1,.2,.3])
                diagnostic=forward_diagnostic(stack,point,point,point)
                self.assertEqual(diagnostic['direct_residual'],0)
                self.assertEqual(diagnostic['lut_residual'],0)

    def test_reproduction_uses_authoritative_signed_energy(self):
        states=State(np.zeros((3,3)),np.array([-16.,16.,-16.]))
        model=SimpleNamespace(enter_native=lambda x:x,grade_state=lambda x:states)
        stack=SimpleNamespace(models=[model])
        diagnostic=forward_diagnostic(stack,np.zeros(3),np.zeros(3),np.zeros(3))
        self.assertEqual(diagnostic['target'][1],-4.)
        self.assertEqual(diagnostic['direct'][1],4.)
        self.assertEqual(diagnostic['direct_residual'],1.6)
        self.assertEqual(diagnostic['lut_residual'],0.)


if __name__=='__main__':unittest.main()
