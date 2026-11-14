"""Actual Blender evaluation and caller-owned persistence checks."""
from pathlib import Path
from functools import partial
import unittest
import numpy as np
import bpy
from color_tools.kernel import prepare, LinearSettings, ToneSettings
from color_tools.template_build.graph import build_group
raw_group = partial(build_group, export=False)
from tools.perceptual_grade.reports import cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture
from tools.perceptual_grade.reports.evaluate import assess


class NativeTests(unittest.TestCase):
    def test_raw_shader_and_compositor_match_reference(self):
        values=cases.rgba(256)
        selected=[row for row in cases.grades() if row[0] in ('reset','narrow','combined','poles')]
        selected.extend(row for row in cases.ui_boundaries() if row[0] == 'tone_minimum_gap_3')
        for space in cases.SPACES:
            for name,linear,tone in selected:
                prepared=prepare(linear,tone,space)
                expected=oracle.evaluate(values[:,:3],linear,tone,space)
                for context in ('shader','compositor'):
                    with self.subTest(space=space,case=name,context=context):
                        fixture=NativeFixture(prepared,values,context,builder=raw_group)
                        try:
                            actual=fixture.render()
                            result=assess(actual,expected,values)
                            self.assertTrue(result['passed'],result)
                            self.assertEqual(result['validity_mismatches'],[])
                            self.assertLessEqual(actual['stats']['expanded_nodes'],300)
                            if name == 'reset':
                                np.testing.assert_array_equal(actual['rgb'],values[:,:3])
                            np.testing.assert_array_equal(actual['rgb'][np.all(values[:,:3]==0,axis=-1)],0.)
                            if context == 'compositor':
                                np.testing.assert_array_equal(actual['embedded_alpha'],values[:,3])
                        finally:
                            fixture.close()

    def test_packed_save_reopen_retains_native_graph(self):
        linear,tone=list(cases.grades())[2][1:]
        values=cases.rgba(256)
        for context in ('shader','compositor'):
            fixture=NativeFixture(prepare(linear,tone),values,context,builder=raw_group)
            try:
                before=fixture.render()
                self.assertTrue(all(image.packed_file for image in fixture.built.images))
                fixture.input_image.pack()
                filename=Path(fixture.directory.name)/'native-grade.blend'
                bpy.ops.wm.save_as_mainfile(filepath=str(filename))
                bpy.ops.wm.open_mainfile(filepath=str(filename))
                after=fixture.render()
                np.testing.assert_array_equal(before['rgb'],after['rgb'])
                np.testing.assert_array_equal(before['alpha'],after['alpha'])
            finally:
                fixture.close()

    def test_instances_own_independent_resources(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        prepared=prepare(tone=ToneSettings(input_nits=(0,8,40,235,1150)))
        a,b=build_group(prepared),build_group(prepared)
        self.assertNotEqual(a.tree,b.tree)
        self.assertNotEqual(a.images[0],b.images[0])
        first_pixels=np.asarray(a.images[0].pixels[:])
        b.dispose()
        np.testing.assert_array_equal(first_pixels,a.images[0].pixels[:])
        a.dispose()

    def test_singular_matrix_override_native_robustness(self):
        # An explicit matrix is a portable API feature, not a Gizmo precision
        # case. Render a singular transform to verify that it remains usable
        # without an inverse of the authored correction or a Tone texture.
        linear=LinearSettings(matrix=((1., .2, 0.), (0., 0., 0.), (0., -.1, 1.)))
        values=cases.rgba(256)
        expected=oracle.evaluate(values[:,:3],linear,ToneSettings(),'ACEScg')['linear']
        for context in ('shader','compositor'):
            fixture=NativeFixture(prepare(linear,space='ACEScg'),values,context,builder=raw_group)
            try:
                actual=fixture.render()
                self.assertTrue(np.isfinite(actual['rgb']).all())
                self.assertLessEqual(oracle.metrics(actual['rgb'],expected)['max_normalized'],1e-5)
                np.testing.assert_array_equal(actual['alpha'],values[:,3])
                self.assertEqual(fixture.built.images,())
            finally:
                fixture.close()


if __name__ == '__main__':
    unittest.main()
