"""Native Shader Bake sampling, alpha association and immutable artifact tests."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest

import bpy
import numpy as np

from color_tools.perceptual_grade_blender.jobs.handlers import shader_bake as worker
from color_tools.perceptual_grade_blender.jobs.handlers import native_capture
from color_tools.perceptual_grade_core.jobs.codec import freeze_model
from color_tools.perceptual_grade_core.model import color, linear, lut, raster, tone, transforms


class Context:
    def __init__(self, cancel_at=None):
        self.checks = 0
        self.cancel_at = cancel_at
        self.progress_values = []

    def checkpoint(self):
        self.checks += 1
        if self.cancel_at is not None and self.checks >= self.cancel_at:
            raise CancelledError('Cancelled Shader Bake')

    def progress(self, value):
        self.progress_values.append(value)


class ShaderBakeWorkerTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.render.engine = 'CYCLES'

    def tearDown(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def fixture(self, *, alpha=.37, premul=False):
        material = bpy.data.materials.new('Shader Bake Source')
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        kernel = bpy.data.node_groups.new('Selected terminal', 'ShaderNodeTree')
        for name, kind in (('Color', 'NodeSocketColor'), ('Alpha', 'NodeSocketFloat')):
            kernel.interface.new_socket(name=name, in_out='INPUT', socket_type=kind)
        terminal = tree.nodes.new('ShaderNodeGroup')
        terminal.node_tree = kernel
        terminal.inputs['Alpha'].default_value = alpha
        image = worker._image('Frozen source', 4, 2)
        source = np.array([[-.2, .3, 2., 0.], [.2, .3, .4, .5],
                           [.5, .4, .7, 1.], [4., 2., 1., .25]] * 2, np.float32).reshape(2, 4, 4)
        if premul:
            source[..., :3] = np.array((.2, .3, .4), np.float32)
            image.colorspace_settings.name = 'Linear Rec.709'
            image.alpha_mode = 'PREMUL'
        image.pixels.foreach_set(source.reshape(-1))
        image.update()
        texture = tree.nodes.new('ShaderNodeTexImage')
        texture.image = image
        tree.links.new(texture.outputs['Color'], terminal.inputs['Color'])
        target = dict(scene=self.scene.name, owner_kind='material', owner_name=material.name,
                      group_path=(), node_name=terminal.name, socket_name='Color')
        descriptor = dict(domain='IMAGE', width=4, height=2, images=[dict(
            group_path=(), node_name=texture.name, image_name=image.name, alpha_linked=False)])
        return material, tree, terminal, texture, source, target, descriptor

    def native_rgba(self, image):
        """Independent native oracle: physically emit R,G,A and then B,0,A."""
        material = bpy.data.materials.new('Native RGBA oracle')
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        source = tree.nodes.new('ShaderNodeTexImage')
        source.image = image
        source.interpolation = 'Closest'
        source.extension = 'EXTEND'
        separate = tree.nodes.new('ShaderNodeSeparateColor')
        combine = tree.nodes.new('ShaderNodeCombineColor')
        tree.links.new(source.outputs['Color'], separate.inputs['Color'])
        tree.links.new(separate.outputs['Red'], combine.inputs['Red'])
        tree.links.new(separate.outputs['Green'], combine.inputs['Green'])
        tree.links.new(source.outputs['Alpha'], combine.inputs['Blue'])
        emission = tree.nodes.new('ShaderNodeEmission')
        endpoint = tree.nodes.new('ShaderNodeOutputMaterial')
        tree.links.new(emission.outputs[0], endpoint.inputs['Surface'])
        obj = worker._plane(self.scene)
        obj.data.materials.append(material)
        worker._select(self.scene, obj, obj.data.uv_layers.active.name)
        self.scene.cycles.samples = 1
        destination = worker._image('Native RGBA oracle pixels', *image.size)
        first = worker._bake(self.scene, obj, material, emission, combine.outputs[0], destination, Context(), 0)
        tree.links.new(separate.outputs['Blue'], combine.inputs['Red'])
        for link in tuple(combine.inputs['Green'].links):
            tree.links.remove(link)
        second = worker._bake(self.scene, obj, material, emission, combine.outputs[0], destination, Context(), 0)
        return np.stack((first[..., 0], first[..., 1], second[..., 0], first[..., 2]), axis=-1)

    def test_source_resolution_signed_hdr_and_independent_terminal_alpha(self):
        _material, tree, _terminal, _texture, source, target, descriptor = self.fixture()
        result, coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        np.testing.assert_array_equal(result[..., :3], source[..., :3])
        np.testing.assert_allclose(result[..., 3], .37, rtol=0, atol=1e-7)
        self.assertTrue(coverage.all())

    def test_native_brightness_contrast_and_source_coordinate_bypass(self):
        _material, tree, terminal, texture, source, target, descriptor = self.fixture()
        brightness = tree.nodes.new('ShaderNodeBrightContrast')
        brightness.inputs['Bright'].default_value = .1
        brightness.inputs['Contrast'].default_value = .25
        tree.links.new(texture.outputs['Color'], brightness.inputs['Color'])
        tree.links.new(brightness.outputs['Color'], terminal.inputs['Color'])
        coordinate = tree.nodes.new('ShaderNodeCombineXYZ')
        coordinate.inputs['X'].default_value = .125
        coordinate.inputs['Y'].default_value = .125
        tree.links.new(coordinate.outputs['Vector'], texture.inputs['Vector'])
        texture.texture_mapping.mapping_x = 'Y'
        texture.texture_mapping.mapping_y = 'X'
        result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        expected = np.maximum(1.25 * source[..., :3] + .1 - .25 * .5, 0.)
        np.testing.assert_allclose(result[..., :3], expected, rtol=0, atol=3e-7)

    def test_premultiplied_alpha_interpretation_is_independent_of_capture_pass(self):
        for linked in (False, True):
            with self.subTest(linked=linked):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.scene = bpy.context.scene
                self.scene.render.engine = 'CYCLES'
                _material, tree, terminal, texture, source, target, descriptor = self.fixture(premul=True)
                descriptor['images'][0]['alpha_linked'] = linked
                if linked:
                    tree.links.new(texture.outputs['Alpha'], terminal.inputs['Alpha'])
                result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
                expected = source[..., :3].copy()
                if linked:
                    np.divide(expected, source[..., 3, None], out=expected, where=source[..., 3, None] != 0.)
                np.testing.assert_allclose(result[..., :3], expected, rtol=0, atol=3e-7)
                np.testing.assert_allclose(result[..., 3], source[..., 3] if linked else .37, rtol=0, atol=1e-7)

    def test_byte_srgb_alpha_link_preserves_pre_decode_unassociation(self):
        _material, tree, terminal, texture, _source, target, descriptor = self.fixture()
        image = bpy.data.images.new('Byte sRGB source', 2, 1, alpha=True, float_buffer=False)
        image.colorspace_settings.name = 'sRGB'
        image.alpha_mode = 'STRAIGHT'
        image.pixels.foreach_set(np.array((.8, .4, .2, .5, .25, .5, .75, .25), np.float32))
        image.update()
        texture.image = image
        descriptor['width'], descriptor['height'] = 2, 1
        descriptor['images'][0]['alpha_linked'] = True
        tree.links.new(texture.outputs['Alpha'], terminal.inputs['Alpha'])
        expected = self.native_rgba(image)
        result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        # Compare with actual native Image Texture output, including byte
        # association rounding and pre-decode unassociation. No Python color
        # transform or assumptions about Blender's stored byte buffer enter.
        np.testing.assert_array_equal(result, expected)

    def test_tiny_nonzero_alpha_keeps_native_unassociation(self):
        _material, tree, terminal, texture, source, target, descriptor = self.fixture(premul=True)
        source[..., :3] = np.array((1e-9, 2e-9, 3e-9), np.float32)
        source[..., 3] = 1e-8
        texture.image.pixels.foreach_set(source.reshape(-1))
        texture.image.update()
        tree.links.new(texture.outputs['Alpha'], terminal.inputs['Alpha'])
        descriptor['images'][0]['alpha_linked'] = True
        expected = self.native_rgba(texture.image)
        result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        np.testing.assert_array_equal(result, expected)
        self.assertGreater(float(result[..., 0].min()), .09)

    def test_render_layer_override_does_not_replace_selected_material(self):
        _material, tree, _terminal, _texture, source, target, descriptor = self.fixture()
        override = bpy.data.materials.new('Unrelated render override')
        override.use_nodes = True
        emission = override.node_tree.nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = (.9, .8, .7, 1.)
        endpoint = next(node for node in override.node_tree.nodes if node.bl_idname == 'ShaderNodeOutputMaterial')
        override.node_tree.links.new(emission.outputs[0], endpoint.inputs['Surface'])
        bpy.context.view_layer.material_override = override
        result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        np.testing.assert_array_equal(result[..., :3], source[..., :3])
        np.testing.assert_allclose(result[..., 3], .37, rtol=0, atol=1e-7)

    def test_nested_target_uses_selected_instance_inputs(self):
        material, tree, terminal, texture, source, target, descriptor = self.fixture()
        nested = bpy.data.node_groups.new('Repeated group', 'ShaderNodeTree')
        nested.interface.new_socket(name='Signal', in_out='INPUT', socket_type='NodeSocketColor')
        entry = nested.nodes.new('NodeGroupInput')
        inner = nested.nodes.new('ShaderNodeGroup')
        inner.node_tree = terminal.node_tree
        inner.inputs['Alpha'].default_value = .625
        nested.links.new(entry.outputs['Signal'], inner.inputs['Color'])
        chosen = tree.nodes.new('ShaderNodeGroup')
        chosen.node_tree = nested
        unused = tree.nodes.new('ShaderNodeGroup')
        unused.node_tree = nested
        unused.inputs['Signal'].default_value = (9., 8., 7., 1.)
        tree.links.new(texture.outputs['Color'], chosen.inputs['Signal'])
        target.update(group_path=(chosen.name,), node_name=inner.name)
        result, _coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        np.testing.assert_array_equal(result[..., :3], source[..., :3])
        np.testing.assert_allclose(result[..., 3], .625, rtol=0, atol=1e-7)

    def test_uv_selected_slot_coverage_and_sixteen_pixel_margin(self):
        material, tree, terminal, texture, _source, target, descriptor = self.fixture(alpha=0.)
        for link in tuple(terminal.inputs['Color'].links):
            tree.links.remove(link)
        terminal.inputs['Color'].default_value = (.3, .5, 2., 1.)
        obj = worker._plane(self.scene)
        obj.data.materials.append(material)
        # A small centered island leaves enough room to distinguish native
        # coverage, the required 16-pixel extension, and genuinely empty pixels.
        for loop in obj.data.uv_layers.active.data:
            loop.uv = (.25 + .5 * loop.uv.x, .25 + .5 * loop.uv.y)
        descriptor.update(domain='UV', width=128, height=128, object_name=obj.name,
                          material_name=material.name, material_slot=0,
                          uv_map=obj.data.uv_layers.active.name, images=[])
        result, coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        self.assertTrue(coverage[64, 64])
        self.assertTrue(coverage[64, 20])
        self.assertFalse(coverage[64, 4])
        np.testing.assert_allclose(result[coverage, :3], np.broadcast_to((.3, .5, 2.), (int(coverage.sum()), 3)),
                                   rtol=0, atol=1e-6)
        np.testing.assert_array_equal(result[..., 3], np.zeros((128, 128), np.float32))

    def test_invalid_domain_dimensions_and_cancellation_reject_before_bake(self):
        _material, tree, _terminal, _texture, _source, target, descriptor = self.fixture()
        with self.assertRaises(CancelledError):
            worker.evaluate(self.scene, tree, target, descriptor, Context(cancel_at=1))
        for change in (dict(domain='UDIM'), dict(width=0), dict(width=32769), dict(width=32768, height=32768)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                worker.evaluate(self.scene, tree, target, dict(descriptor, **change), Context())
        self.scene.render.engine = 'BLENDER_EEVEE'
        with self.assertRaisesRegex(ValueError, 'requires Cycles'):
            worker.evaluate(self.scene, tree, target, dict(descriptor, domain='UV'), Context())

    def test_world_constant_uses_one_texel_without_a_camera_or_mesh(self):
        world = bpy.data.worlds.new('Frozen World')
        world.use_nodes = True
        tree = world.node_tree
        tree.nodes.clear()
        kernel = bpy.data.node_groups.new('World terminal', 'ShaderNodeTree')
        kernel.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        kernel.interface.new_socket(name='Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        terminal = tree.nodes.new('ShaderNodeGroup')
        terminal.node_tree = kernel
        terminal.inputs['Color'].default_value = (.15, .5, 3., 1.)
        terminal.inputs['Alpha'].default_value = .625
        result, coverage = worker.evaluate(self.scene, tree, dict(node_name=terminal.name, group_path=()),
            dict(domain='IMAGE', width=1, height=1, images=[]), Context())
        np.testing.assert_allclose(result, np.array([[[.15, .5, 3., .625]]]), rtol=0, atol=1e-7)
        self.assertTrue(coverage.all())

    def test_uv_geometry_positions_use_frozen_object_and_exclude_other_slots(self):
        material, tree, terminal, _texture, _source, target, descriptor = self.fixture(alpha=.25)
        geometry = tree.nodes.new('ShaderNodeNewGeometry')
        tree.links.new(geometry.outputs['Position'], terminal.inputs['Color'])
        mesh = bpy.data.meshes.new('Two material islands')
        mesh.from_pydata(((-1., -1., 0.), (0., -1., 0.), (0., 1., 0.), (-1., 1., 0.),
                          (.1, -1., 0.), (1., -1., 0.), (1., 1., 0.), (.1, 1., 0.)),
                         (), ((0, 1, 2, 3), (4, 5, 6, 7)))
        uv = mesh.uv_layers.new(name='Frozen UV')
        values = ((0., 0.), (.4, 0.), (.4, 1.), (0., 1.),
                  (.6, 0.), (1., 0.), (1., 1.), (.6, 1.))
        for loop, value in zip(uv.data, values):
            loop.uv = value
        obj = bpy.data.objects.new('Frozen active object', mesh)
        self.scene.collection.objects.link(obj)
        obj.location.x = 3.
        mesh.materials.append(material)
        mesh.materials.append(bpy.data.materials.new('Excluded Material'))
        mesh.polygons[1].material_index = 1
        descriptor.update(domain='UV', width=128, height=32, object_name=obj.name,
                          material_name=material.name, material_slot=0, uv_map=uv.name, images=[])
        result, coverage = worker.evaluate(self.scene, tree, target, descriptor, Context())
        self.assertTrue(coverage[16, 25])
        self.assertFalse(coverage[16, 110])
        # Native bake rasterization slightly offsets samples from ideal texel
        # centers (also present in a direct native emission bake). The bound is
        # under 0.004 of one UV texel here, while the translated geometry and
        # selected material domain remain independently observable.
        self.assertAlmostEqual(float(result[16, 25, 0]), 2. + ((25.5 / 128) / .4), delta=2e-4)
        self.assertAlmostEqual(float(result[16, 25, 1]), -1. + 2. * (16.5 / 32), delta=2e-4)
        self.assertAlmostEqual(float(result[16, 25, 3]), .25, places=7)

    def test_handle_loads_verified_snapshot_applies_analytic_model_and_writes_exr(self):
        material, tree, _terminal, texture, source, target, descriptor = self.fixture()
        texture.image.pack()
        # Keep the material in the saved scene dependency closure.
        obj = worker._plane(self.scene)
        obj.data.materials.append(material)
        model = transforms.Stack((transforms.Settings.from_parameters(linear.Parameters(exposure=.3),
            tone.Parameters(), color.Parameters(global_gain=.12), linear.GradeSpace('D65')),))
        rows = (lut.TO_LUT, lut.FROM_LUT)
        expected = source.copy()
        expected[..., 3] = .37
        raster.grade_rgba(expected, model, rows)
        analytic = dict(version=raster.SCHEMA, kind='GRADE', model=freeze_model(model),
                        rows=tuple(tuple(tuple(v) for v in matrix) for matrix in rows), signature='frozen-model')
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'source.blend'
            bpy.ops.wm.save_as_mainfile(filepath=str(snapshot), check_existing=False)
            inputs = dict(target=target, shader_bake=descriptor, snapshot=dict(path=str(snapshot),
                          sha256=native_capture._hash_file(snapshot)), artifact_dir=directory,
                          analytic=analytic, identity=('test', 1), images=(), clips=())
            artifact = worker.handle(inputs, Context())
            self.assertEqual(artifact['bake_domain'], 'IMAGE')
            self.assertEqual(artifact['analytic_signature'], 'frozen-model')
            self.assertEqual(artifact['identity'], ('test', 1))
            self.assertEqual(native_capture._hash_file(artifact['path']), artifact['sha256'])
            image = bpy.data.images.load(artifact['path'], check_existing=False)
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'CHANNEL_PACKED'
            actual = worker._pixels(image)
            np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-6)
            inputs['snapshot']['sha256'] = 'invalid'
            with self.assertRaisesRegex(ValueError, 'changed after snapshot'):
                worker.handle(inputs, Context())


if __name__ == '__main__':
    unittest.main()
