"""Viewport camera reconstruction preserves framing and the complete clip volume."""
import unittest

import bpy
import numpy as np
from mathutils import Matrix

from color_tools.perceptual_grade_blender.jobs.handlers import native_capture


class ScopeCameraTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.render.resolution_x = 120
        self.scene.render.resolution_y = 80
        self.scene.render.resolution_percentage = 100

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def projection(self, camera):
        return np.asarray(camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),
            x=self.scene.render.resolution_x, y=self.scene.render.resolution_y))

    def reconstruct(self, projection, view=None, clip_start=.01, clip_end=1000.):
        view = Matrix.Identity(4) if view is None else view
        native_capture._camera(self.scene, dict(view_matrix=tuple(map(tuple, view)),
            projection_matrix=projection, clip_start=clip_start, clip_end=clip_end))
        effective = self.projection(self.scene.camera) @ np.asarray(
            self.scene.camera.matrix_world.inverted())
        expected = projection / (projection[3, 3] or -projection[3, 2]) @ np.asarray(view)
        # Perspective retains the existing XY-only contract; orthographic
        # checks every clip coordinate after its origin shift.
        if abs(projection[3, 3]) > 1e-6:
            # Blender stores object transforms as floats. A large orthographic
            # origin shift can amplify their sub-ULP rotation error.
            np.testing.assert_allclose(effective, expected, rtol=2e-5, atol=5e-5)
        else:
            np.testing.assert_allclose(effective[:2], expected[:2], rtol=2e-5, atol=2e-5)
        return self.scene.camera

    def test_orthographic_origin_moves_behind_both_sides_of_viewport(self):
        projection = np.diag((.5, .75, -.002, 1.))
        view = Matrix(((1., 0., 0., -.95), (0., 0., 1., -.08),
                       (0., -1., 0., .4), (0., 0., 0., 1.)))
        camera = self.reconstruct(projection, view)
        self.assertAlmostEqual(camera.data.clip_start, .01)
        self.assertAlmostEqual(camera.data.clip_end, 1000.01, places=3)
        for world_y in (-.5, .5):
            point = np.array((0., world_y, 0., 1.))
            old_z = (np.asarray(view) @ point)[2]
            new_z = (np.asarray(camera.matrix_world.inverted()) @ point)[2]
            self.assertLess(new_z, -camera.data.clip_start)
            self.assertGreater(new_z, -camera.data.clip_end)
            self.assertEqual(old_z > 0, world_y < 0)

    def test_asymmetric_depth_and_homogeneous_scaling_preserve_clip_boundaries(self):
        for scale, offset in ((-.2, .7), (-.1, -2.)):
            with self.subTest(scale=scale, offset=offset):
                projection = np.diag((.5, .75, scale, 1.))
                projection[:3, 3] = (.1, -.2, offset)
                camera = self.reconstruct(3.0 * projection)
                actual = self.projection(camera) @ np.asarray(camera.matrix_world.inverted())
                near_z, far_z = (-1. - offset) / scale, (1. - offset) / scale
                for z, expected in ((near_z, -1.), (far_z, 1.)):
                    self.assertAlmostEqual((actual @ (0., 0., z, 1.))[2], expected, places=5)
                self.assertLess((actual @ (0., 0., near_z + .1, 1.))[2], -1.)
                self.assertGreater((actual @ (0., 0., far_z - .1, 1.))[2], 1.)

    def test_perspective_camera_and_fallback_remain_equivalent(self):
        original = bpy.data.objects.new('Original perspective', bpy.data.cameras.new('Original perspective'))
        self.scene.collection.objects.link(original)
        original.data.lens = 47.
        original.data.sensor_fit = 'HORIZONTAL'
        original.data.clip_start, original.data.clip_end = .2, 45.
        original.data.shift_x, original.data.shift_y = .07, -.03
        view = Matrix.Translation((.2, -.3, -4.))
        original.matrix_world = view.inverted()
        projection = self.projection(original)
        camera = self.reconstruct(projection, view, .2, 45.)
        self.assertEqual(camera.data.type, 'PERSP')
        self.assertAlmostEqual(camera.data.clip_start, .2)
        self.assertAlmostEqual(camera.data.clip_end, 45.)
        np.testing.assert_allclose(self.projection(camera), projection, rtol=2e-5, atol=2e-5)
        np.testing.assert_allclose(camera.matrix_world, original.matrix_world, atol=1e-6)
        native_capture._camera(self.scene, dict(camera=original.name))
        self.assertEqual(self.scene.camera, original)

    def test_invalid_or_oblique_projection_is_rejected(self):
        projection = np.diag((.5, .75, -.2, 1.))
        for row, column, value in ((2, 2, 0.), (2, 2, .2), (2, 3, float('nan')),
                                    (2, 0, .1), (0, 1, .1), (3, 0, .1)):
            with self.subTest(row=row, column=column, value=value):
                changed = projection.copy()
                changed[row, column] = value
                with self.assertRaisesRegex(ValueError, 'viewport projection'):
                    native_capture._orthographic_projection(changed, .01)


if __name__ == '__main__':
    unittest.main()
