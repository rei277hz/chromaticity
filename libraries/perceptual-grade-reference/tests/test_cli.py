"""Run the packaged reference CLI with its declared Buck2 runtime dependencies."""
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from color_tools.perceptual_grade_reference.model import Model,Settings,LinearSettings
from color_tools.perceptual_grade_reference.grading import ColorSettings


class CLITests(unittest.TestCase):
    def invoke(self, request):
        executable = Path(str(files('tests.reference') / 'evaluate')).resolve()
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([str(executable)], input=json.dumps(request), text=True,
                                  capture_output=True, cwd=directory)

    def test_forward_inverse_json_from_an_unrelated_directory(self):
        request = dict(values=[[.18, .18, .18], [-.1, .2, 1.]], linear=dict(exposure=1))
        forward = self.invoke(request)
        self.assertEqual(forward.returncode, 0, forward.stderr)
        output = json.loads(forward.stdout)
        model=Model(Settings(linear=LinearSettings(exposure=1)))
        expected=model.forward(request['values'])
        np.testing.assert_allclose(output['value'],expected,rtol=2e-12,atol=1e-14)
        np.testing.assert_allclose(output['value'][0],[.36]*3,rtol=2e-12)
        inverse = self.invoke(dict(operation='inverse', values=output['value'], linear=request['linear']))
        self.assertEqual(inverse.returncode, 0, inverse.stderr)
        output = json.loads(inverse.stdout)
        self.assertEqual(output['status'], ['root', 'root'])
        np.testing.assert_allclose(model.forward(output['value']),expected,rtol=2e-8,atol=5e-10)

    def test_invalid_operation_and_controls_fail(self):
        for request in (dict(operation='typo', values=[0, 0, 0]),
                        dict(values=[0, 0, 0], tone=dict(fit=float('inf')))):
            with self.subTest(request=request):
                self.assertNotEqual(self.invoke(request).returncode, 0)

    def test_low_high_controls_use_analytic_crossover_in_both_directions(self):
        color = dict(lightness=[[.1, -.1, 0., 0.]]*4, chroma=[[.1, -.05, 0., 0.]]*4)
        values = [[.1, .2, .3], [.6, .25, .1]]
        model = Model(Settings(color=ColorSettings(**color)))
        expected = model.forward(values)
        response = self.invoke(dict(values=values, color=color))
        self.assertEqual(response.returncode, 0, response.stderr)
        np.testing.assert_allclose(json.loads(response.stdout)['value'], expected, rtol=2e-12, atol=1e-14)
        inverse = self.invoke(dict(operation='inverse', values=expected.tolist(), color=color))
        self.assertEqual(inverse.returncode, 0, inverse.stderr)
        output = json.loads(inverse.stdout)
        self.assertEqual(output['status'], ['root', 'root'])
        np.testing.assert_allclose(model.forward(output['value']), expected, rtol=2e-8, atol=5e-10)

    def test_tonal_web_json_matches_reference_and_rejects_old_hue_controls(self):
        web = dict(log_chroma=[[.1, 0., 0., 0., 0., 0.]]*4,
                   hue_degrees=[[4., 0., 0., 0., 0., 0.]]*4,
                   log_scale=[[.02, 0., 0., 0., 0., 0.]]*4)
        values = [[.3, .15, .09], [.08, .25, .22]]
        response = self.invoke(dict(values=values, color=dict(web=web)))
        self.assertEqual(response.returncode, 0, response.stderr)
        actual = np.asarray(json.loads(response.stdout)['value'])
        expected = Model(Settings(color=ColorSettings(web=web))).forward(values)
        np.testing.assert_allclose(actual, expected, rtol=2e-12, atol=1e-14)
        self.assertGreater(float(np.max(abs(actual-Model().forward(values)))), 1e-4)
        for color in (dict(hue=[1.]*4), dict(web=dict(log_chroma=[[1.]]))):
            with self.subTest(color=color):
                self.assertNotEqual(self.invoke(dict(values=values, color=color)).returncode, 0)

    def test_final_negative_neutral_is_black_but_chromatic_state_survives_json(self):
        response = self.invoke(dict(space='ACEScg', white='D65',
                                    color=dict(lightness=[[0., -100., 0., 0.]]*4),
                                    values=[[0., 0., 2.], [-.1, -.1, -.1]]))
        self.assertEqual(response.returncode, 0, response.stderr)
        output = np.asarray(json.loads(response.stdout)['value'])
        self.assertTrue(np.isfinite(output).all())
        np.testing.assert_array_equal(output[1],0.)
        # Strong negative lightness may reach the hard black endpoint.
        self.assertGreaterEqual(float(output[0].max()),0.)
        self.assertTrue((output>=0).all());self.assertTrue((output<=1024).all())

    def test_negative_a_is_repaired_at_export_json(self):
        from color_tools.perceptual_grade_reference.model import Model
        from color_tools.perceptual_grade_reference.appearance import decode, encode
        from color_tools.perceptual_grade_reference.responses import hk_energy
        model=Model();h=.5*np.sqrt(66*20.)
        source=decode([h,20.,0.],hk_energy(h,20.),model.white)
        response=self.invoke(dict(space='Linear Rec.709',values=(source@model.xyz_to_rgb.T).tolist()))
        self.assertEqual(response.returncode,0,response.stderr)
        output=np.asarray(json.loads(response.stdout)['value'])
        self.assertTrue(np.isfinite(output).all());self.assertGreaterEqual(np.max(np.abs(output)),0)
        self.assertGreaterEqual(encode(output@model.rgb_to_xyz.T,model.white).ja,0)
        self.assertTrue((output@model.to_acescg.T>=-1e-14).all())
