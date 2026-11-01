"""Frozen capture dependencies never overwrite the shared foreground graph."""
from concurrent.futures import CancelledError
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import numpy as np

from tests.support.blender import BlenderTest
from color_tools.perceptual_grade_blender.jobs.handlers import capture_models
from color_tools.perceptual_grade_blender.jobs.handlers import native_capture
from color_tools.perceptual_grade_core.jobs.codec import freeze_model
from color_tools.perceptual_grade_core.model import lut


class CaptureModelTests(BlenderTest):
    def fixture(self, *, nested=False, compositor=False):
        nodes = self.session.component('graph.nodes')
        tree = bpy.data.node_groups.new('Frozen source', 'CompositorNodeTree' if compositor else 'ShaderNodeTree')
        node = nodes.create_grade(tree)
        if compositor:
            bpy.context.scene.compositing_node_group = tree
            owner = bpy.context.scene
            kind, path = 'compositor', ()
        else:
            owner = bpy.data.materials.new('Frozen material')
            owner.use_nodes = True
            kind, path = 'material', ()
            if nested:
                first = owner.node_tree.nodes.new('ShaderNodeGroup');first.node_tree = tree
                second = owner.node_tree.nodes.new('ShaderNodeGroup');second.node_tree = tree
                path = (first.name,)
            else:
                node = nodes.create_grade(owner.node_tree)
        model = nodes.bake_model(node)
        rows = tuple(tuple(tuple(float(x) for x in row) for row in matrix)
                     for matrix in (np.eye(3), np.eye(3) * .5))
        record = dict(owner_kind=kind, owner_name=owner.name, scene=bpy.context.scene.name,
                      group_path=path, node_name=node.name, model=freeze_model(model),
                      rows=rows, cube_signature=lut.signature(model))
        # A supplied numerical payload isolates native graph wiring from the
        # separately tested numerical producer without manufacturing a receipt.
        cube = lut.Cube(lut.lattice().reshape(65, 65, 65, 3), record['cube_signature'], model.space)
        return owner, node, record, cube

    def test_occurrence_copy_keeps_other_instance_and_original_banks_unchanged(self):
        owner, node, record, cube = self.fixture(nested=True)
        original_tree, original_kernel = node.id_data, node.node_tree
        original_banks = tuple(item.image for item in original_kernel.nodes if item.get('_pg_cube_image'))
        context = SimpleNamespace(checkpoint=lambda: None)
        with patch.object(capture_models, '_cube', return_value=cube):
            receipt = capture_models.materialize((record,), context)
        self.assertEqual(receipt, ((cube.signature, 65),))
        first = owner.node_tree.nodes[record['group_path'][0]]
        others = [item for item in owner.node_tree.nodes if item.bl_idname == 'ShaderNodeGroup' and item != first]
        self.assertNotEqual(first.node_tree, original_tree)
        self.assertTrue(all(item.node_tree == original_tree for item in others))
        self.assertEqual(node.node_tree, original_kernel)
        self.assertEqual(tuple(item.image for item in original_kernel.nodes if item.get('_pg_cube_image')), original_banks)
        captured = first.node_tree.nodes[record['node_name']]
        resources = self.session.component('graph.output_resources')
        self.assertEqual(resources.selected_index(captured), 2)
        self.assertNotEqual(resources.bank_images(captured)[2], resources.bank_images(node)[2])
        self.assertEqual(self.session.component('graph.spaces').read_rows(captured),
                         tuple(row for matrix in record['rows'] for row in matrix))

    def test_compositor_receipt_uses_encoded_final_bank(self):
        _, node, record, cube = self.fixture(compositor=True)
        old_kernel = node.node_tree
        with patch.object(capture_models, '_cube', return_value=cube):
            capture_models.materialize((record,), SimpleNamespace(checkpoint=lambda: None))
        self.assertNotEqual(node.node_tree, old_kernel)
        image = self.session.component('graph.output_resources').bank_images(node)[2]
        self.assertEqual(image['_pg_cube_encoding'], 'RGBE_DIFFERENCES')
        self.assertEqual(tuple(image.size), (lut.ATLAS_WIDTH, lut.atlas_height(65, 4)))
        pixels = np.empty(len(image.pixels), np.float32);image.pixels.foreach_get(pixels)
        np.testing.assert_array_equal(pixels, cube.packed_pixels().ravel())

    def test_cancel_before_binding_restores_exact_kernel_and_retires_private_image(self):
        _, node, record, cube = self.fixture()
        original = node.node_tree
        images, groups = len(bpy.data.images), len(bpy.data.node_groups)
        calls = 0
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 3:raise CancelledError('capture cancelled')
        with patch.object(capture_models, '_cube', return_value=cube):
            with self.assertRaises(CancelledError):
                capture_models.materialize((record,), SimpleNamespace(checkpoint=checkpoint))
        self.assertEqual(node.node_tree, original)
        self.assertEqual(len(bpy.data.images), images)
        self.assertEqual(len(bpy.data.node_groups), groups)

    def test_frozen_numerical_producer_rejects_wrong_authored_signature(self):
        _, _, record, _ = self.fixture()
        record['cube_signature'] = 'wrong source'
        with self.assertRaisesRegex(ValueError, 'signature'):
            capture_models._cube(record, False, SimpleNamespace(checkpoint=lambda: None))

    def test_frozen_numerical_producer_finishes_without_live_graph_installation(self):
        _, node, record, _ = self.fixture()
        original = node.node_tree
        cube = capture_models._cube(record, False, SimpleNamespace(checkpoint=lambda: None))
        self.assertEqual(cube.size, 65)
        self.assertEqual(cube.signature, record['cube_signature'])
        self.assertTrue(np.isfinite(cube.values).all())
        self.assertEqual(node.node_tree, original)

    def test_image_companion_reads_private_frozen_buffer_after_live_image_changes(self):
        source = bpy.data.images.new('Original companion', width=2, height=1, alpha=True, float_buffer=True)
        source.colorspace_settings.name = 'Non-Color';source.alpha_mode = 'CHANNEL_PACKED'
        pixels = np.asarray([.1,.2,.3,1., .5,.4,.6,1.],np.float32)
        source.pixels.foreach_set(pixels);source.update()
        descriptor = self.session.component('scopes.images').describe(source)
        frozen = bpy.data.images.new('Private frozen companion', width=2, height=1, alpha=True, float_buffer=True)
        frozen.colorspace_settings.name = 'Non-Color';frozen.alpha_mode = 'CHANNEL_PACKED'
        frozen.pixels.foreach_set(pixels);frozen.update()
        source.pixels.foreach_set(np.ones(8,np.float32));source.update()
        result = native_capture._companion({'_image_source':asdict(descriptor),'identity':('captured',1)},
            {source.name:frozen}, SimpleNamespace(checkpoint=lambda:None))
        np.testing.assert_allclose(result['rgba'].reshape(-1,4),pixels.reshape(-1,4),rtol=0,atol=1e-7)
        self.assertEqual(result['identity'],('captured',1))
        self.assertEqual(result['prepared_provenance'],())
        self.assertFalse(result['rgba'].flags.writeable)

    def test_constant_companion_preserves_sampling_width_and_reference_grid(self):
        from color_tools.perceptual_grade_core.scopes.samples import ordinary_layout
        values=(.1,.2,.3,1.)
        context=SimpleNamespace(checkpoint=lambda:None)
        initial=native_capture._companion({'_constant_source':values}, {}, context)
        self.assertEqual(initial['rgba'].shape,(1,256,4))
        grid=ordinary_layout(3,2)
        data={name:getattr(grid,name) for name in ('mass','x','uv','tiles','ids','key')}
        data['key']=('scope-tiles-v1',grid.key)
        reference=native_capture._companion({'_constant_source':values,'sample_grid':data}, {}, context)
        self.assertEqual(reference['rgba'].shape,(2,3,4))
        self.assertEqual(reference['layout']['key'],data['key'])
        self.assertTrue(reference['layout']['tiled'])
        np.testing.assert_allclose(reference['rgba'],np.broadcast_to(values,(2,3,4)),atol=1e-7)

