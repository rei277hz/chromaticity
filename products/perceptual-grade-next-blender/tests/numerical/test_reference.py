"""Independent curve/settings comparison, separate from native transport."""
from dataclasses import asdict, replace
import json
import unittest
import numpy as np
from color_tools.kernel import prepare, LinearSettings, ToneSettings
from color_tools.kernel.tables import build_table, audit_tone
from color_tools.perceptual_grade_reference import model, grading
from tools.perceptual_grade.reports import cases, full_cases, oracle
from tools.perceptual_grade.reports.gpu_report import _json_values


class ReferenceTests(unittest.TestCase):
    def test_full_ui_settings_are_reportable(self):
        # Fit-boundary settings retain NumPy integer scalars from their source
        # arrays. Reporting must preserve those values after a successful run.
        for name, linear, tone, color in full_cases.ui_boundaries():
            with self.subTest(case=name):
                settings = dict(linear=asdict(linear), tone=asdict(tone), color=asdict(color))
                encoded = json.dumps(_json_values(settings), allow_nan=False)
                self.assertEqual(json.loads(encoded), _json_values(settings))
        self.assertEqual(_json_values(np.array([np.int64(7)])), [7])
        self.assertEqual(_json_values(np.float32(float('inf'))), 'inf')
        self.assertIs(_json_values(np.bool_(False)), False)

    def test_linear_controls_individually_and_combined(self):
        controls=[LinearSettings()]
        for name,values in {'exposure':(-6.,6.), 'source_xy':((0.,0.),(.9,.9),(.3,.35)),
                            'balance':((-2.,0.),(0.,2.)), 'spread':((-100.,0.),(0.,150.)),
                            'heading':((-180.,0.),(0.,180.))}.items():
            controls.extend(replace(LinearSettings(),**{name:value}) for value in values)
        controls.extend(linear for _,linear,_ in cases.grades())
        controls.append(LinearSettings(matrix=((1.,.2,0.),(0.,0.,0.),(0.,0.,1.))))
        for linear in controls:
            with self.subTest(linear=linear):
                prepared=prepare(linear)
                lp,_=oracle.parameters(linear,ToneSettings())
                expected=model.linear_matrix(lp,model.xyz_from_xy(model.WHITES['D65']))
                np.testing.assert_allclose(prepared.linear.xyz_matrix,expected,rtol=3e-12,atol=3e-12)

    def test_scalar_tone_against_reference_and_selected_quantization(self):
        for name,linear,tone in cases.grades():
            prepared=prepare(linear,tone)
            _,tp=oracle.parameters(linear,tone)
            reference=grading.Tone(tp)
            h=np.r_[0.,np.geomspace(1e-8,1e7,15000),100*reference.source,
                    np.nextafter(100*reference.source,np.inf)]
            expected=reference.remap(h)
            np.testing.assert_allclose(prepared.tone.remap(h),expected,rtol=2e-9,atol=2e-10)
            quantized=prepared.tone.remap_table(h)
            # Rounded H/black/span can amplify the sharp-fit curve slope. The
            # table itself keeps its separate 1e-5 gate; total stage rounding
            # is bounded by the experiment's 1e-4 numerical acceptance level.
            self.assertLessEqual(float(np.max(abs(quantized-expected)/np.maximum(1,abs(expected)))),1e-4,name)
            if prepared.table:
                self.assertLessEqual(audit_tone(prepared.tone).table.max_error,1e-5)
                t=np.r_[0.,np.linspace(0,4,32769),np.geomspace(1e-8,1e6,4097)].astype(np.float32)
                k=np.stack([grading.normalized_kernel(t.astype(float),l,r,reference.width)
                            for l,r in zip(reference.knots[:-1],reference.knots[1:])],axis=-1)
                truth=100*(reference.slope*t.astype(float)+k@reference.residual)
                z=np.minimum(t/np.float32(prepared.table.domain),np.float32(1))
                table_value=100*(np.float32(prepared.tone.slope)*t+prepared.table.evaluate(z))
                self.assertLessEqual(float(np.max(abs(table_value-truth)/np.maximum(1,abs(truth)))),1e-5)
        smooth=prepare(tone=ToneSettings(input_nits=(0.,8.,40.,235.,1150.)))
        sharp=prepare(tone=ToneSettings(input_nits=(.2,.21,42.,250.,1300.),fit=2.))
        self.assertEqual(smooth.table.cells,256)
        self.assertEqual(sharp.table.cells,256)
        self.assertLessEqual(build_table(sharp.tone,256).max_error,1e-5)

    def test_precision_corpus_obeys_ui_ranges(self):
        for name,linear,tone in (*cases.grades(),*cases.ui_boundaries()):
            with self.subTest(case=name):
                cases.assert_ui_settings(linear,tone)
                prepared=prepare(linear,tone)
                if prepared.table:
                    self.assertLessEqual(audit_tone(prepared.tone).table.max_error,1e-5)

    def test_signed_raw_oracle_has_both_valid_and_invalid_samples(self):
        pixels=cases.samples()
        name,linear,tone=list(cases.grades())[-1]
        for space in cases.SPACES:
            result=oracle.evaluate(pixels,linear,tone,space)
            self.assertTrue(np.any(result['valid']))
            self.assertTrue(np.any(~result['valid']))
            self.assertTrue(np.isfinite(result['tone'].q).all())
            self.assertTrue(np.isfinite(result['rgb']).all())


if __name__ == '__main__':
    unittest.main()
