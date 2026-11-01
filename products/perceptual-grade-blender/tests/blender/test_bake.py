"""Full-resolution compositor image baking against generated scenes."""

from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import tempfile
import time
from types import SimpleNamespace

import bpy
import numpy as np

from tests.support.session import component as _component, patch
from tests.support.blender import BlenderTest, render, render_scene, sequence
from color_tools.perceptual_grade_blender.integration.components import Component
from color_tools.perceptual_grade_core.model import baking, export, lut as core_lut


capture = _component('scopes.capture')
bake = _component('graph.bake')
gpu = _component('graph.gpu')
lut = _component('graph.lut')
nodes = _component('graph.nodes')
stacks = _component('graph.stacks')
guard = _component('graph.output_guard')
scheduler = _component('graph.scheduler')


def reconcile_images():
    result = bake.runtime_reconcile(max_items=10000)
    if result['error']:
        raise RuntimeError(result['error'])
    return result['done']


class BakeLayout:
    """Record controls and context pointers from each node's action row."""
    def __init__(self, parent=None):
        self.enabled = True if parent is None else parent.enabled
        self.labels = [] if parent is None else parent.labels
        self.controls = [] if parent is None else parent.controls
        self.context = {} if parent is None else parent.context
        self.templates = [] if parent is None else parent.templates

    def row(self, **_kwargs):
        return BakeLayout(self)

    column = row

    def template_ID(self, node, name, **kwargs):
        self.controls.append((name, self.enabled))
        self.templates.append((node, name, kwargs, self.enabled))

    def context_pointer_set(self, name, value):
        self.context[name] = value

    def label(self, *, text='', icon=None):
        self.labels.append((text, icon))

    def prop(self, value, name, **_kwargs):
        self.controls.append((name, self.enabled))

    def operator(self, name, **_kwargs):
        self.controls.append((name, self.enabled))
        return SimpleNamespace()


class ShaderBakeUITests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    def _material(self):
        material = bpy.data.materials.new('Shader Bake UI')
        material.use_nodes = True
        context = SimpleNamespace(scene=bpy.context.scene, screen=None,
                                  space_data=SimpleNamespace(id=material, edit_tree=material.node_tree))
        return material.node_tree, context

    @staticmethod
    def _image(kind='COMPOSITOR'):
        image = bpy.data.images.new('Shared compositor result', width=4, height=2, float_buffer=True)
        image['_pg_bake_schema'] = 2; image['_pg_bake_storage'] = 'FLOAT_RGBA'
        image['_pg_bake_kind'] = kind
        image['_pg_bake_width'] = 4; image['_pg_bake_height'] = 2
        image.pixels.foreach_set((.25, .5, .75, 1.) * 8)
        image.update()
        image.pack()
        return image

    @staticmethod
    def _source(node):
        return next(item for item in node.node_tree.nodes if item.get('_pg_baked_image'))

    def test_add_menu_accepts_embedded_material_and_world_and_rejects_borrowed_trees(self):
        tree, context = self._material()
        world = bpy.data.worlds.new('Shader Bake UI world')
        world.use_nodes = True
        for current in (tree, world.node_tree):
            with self.subTest(tree=current.name):
                self.assertTrue(current.is_embedded_data)
                context.space_data.edit_tree = current
                self.assertTrue(bake.PG_OT_add_bake.poll(context))
                self.assertEqual(bake.PG_OT_add_bake.execute(SimpleNamespace(), context), {'FINISHED'})
                self.assertEqual(current.nodes.active.bl_idname, 'PGShaderBake')
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'linked.blend')
            bpy.data.libraries.write(path, {context.space_data.id})
            with bpy.data.libraries.load(path, link=True) as (source, destination):
                destination.materials = [source.materials[0]]
            context.space_data.edit_tree = destination.materials[0].node_tree
            self.assertFalse(bake.PG_OT_add_bake.poll(context))
            with self.assertRaisesRegex(ValueError, 'local'):
                bake.create_node(context.space_data.edit_tree)
        context.space_data.edit_tree = SimpleNamespace(bl_idname='ShaderNodeTree', is_evaluated=True)
        self.assertFalse(bake.PG_OT_add_bake.poll(context))
        with self.assertRaisesRegex(ValueError, 'local'):
            bake.create_node(context.space_data.edit_tree)

    def test_shader_grade_and_stack_draw_image_uv_status_and_remain_passive(self):
        tree, context = self._material()
        bpy.context.scene.render.engine = 'BLENDER_EEVEE'
        grade = nodes.create_grade(tree)
        stack = sequence(tree, [grade.pg_grade])
        image = tree.nodes.new('ShaderNodeTexImage')
        image.image = self._image()
        coordinates = tree.nodes.new('ShaderNodeTexCoord')
        tr = _component('localization.i18n').tr
        for node in (grade, stack):
            tree.links.new(image.outputs['Color'], node.inputs['Color'])
            # A native link edit is synchronized by a timer, never a redraw.
            tree.links.new(coordinates.outputs['Generated'], node.inputs['Vector'])
            source = self._source(node)
            before = tuple(link.from_socket for link in source.inputs['Vector'].links)
            bake.eligibility(node, context); bake.preflight_tick()
            layout = BakeLayout()
            bake.draw_action(layout, node, context)
            self.assertIn(('pg_bake_image', True), layout.controls)
            self.assertIn(('perceptual_grade.bake_compositor', True), layout.controls)
            self.assertNotIn('pg_bake_width', [name for name, _enabled in layout.controls])
            self.assertIn((tr('bake.route.image'), 'IMAGE_DATA'), layout.labels)
            self.assertEqual(tuple(link.from_socket for link in source.inputs['Vector'].links), before)
        link = tree.links.new(coordinates.outputs['UV'], image.inputs['Vector'])
        for node in (grade, stack):
            layout = BakeLayout()
            bake.draw_action(layout, node, context)
            self.assertIn(('pg_bake_width', True), layout.controls)
            self.assertIn(('pg_bake_height', True), layout.controls)
            self.assertIn((tr('bake.route.uv'), 'IMAGE_DATA'), layout.labels)
            self.assertIn((tr('bake.route.linked_coordinates'), None), layout.labels)
        tree.links.remove(link)
        bound = self._image('SHADER_UV')
        bake.set_baked_image(grade, bound)
        layout = BakeLayout()
        bake.draw_action(layout, grade, context)
        self.assertIn(('W 4  H 2', None), layout.labels)
        self.assertNotIn('pg_bake_width', [name for name, _enabled in layout.controls])
        self.assertIn((tr('bake.route.existing_uv_binding'), None), layout.labels)

    def test_native_selector_filters_and_shares_canonical_images(self):
        tree, context = self._material()
        grade = nodes.create_grade(tree)
        stack = sequence(tree, [grade.pg_grade])
        image = self._image()
        ordinary = bpy.data.images.new('Ordinary user image', width=2, height=2, float_buffer=True)
        compositor = nodes.create_grade(bpy.data.node_groups.new('Shared compositor', 'CompositorNodeTree'))
        bake.set_baked_image(compositor, image)
        for node in (grade, stack):
            self.assertTrue(bake.image_allowed(node, image))
            self.assertFalse(bake.image_allowed(node, ordinary))
            self.assertEqual(node.bl_rna.properties['pg_bake_image'].type, 'POINTER')
            layout = BakeLayout(); bake.draw_action(layout, node, context)
            self.assertEqual(layout.templates[0][2], {'new': 'perceptual_grade.new_bake_image'})
            node.pg_bake_image = image
            self.assertEqual(bake.baked_image(node), compositor.pg_bake_image)
            self.assertEqual(self._source(node).image, image)
            layout = BakeLayout(); bake.draw_action(layout, node, context)
            self.assertEqual(layout.templates[0][2], {'unlink': 'perceptual_grade.unlink_bake_image'})
            image.name = 'Renamed shared Image'
            self.assertEqual(node.pg_bake_image.name, 'Renamed shared Image')
            node.pg_bake_image = None
            self.assertIsNone(bake.baked_image(node))
            self.assertIsNone(self._source(node).image)

    def test_new_image_initializes_empty_content_without_baking_and_rolls_back_failure(self):
        tree, context = self._material()
        grade = nodes.create_grade(tree)
        def forbidden(*_args, **_kwargs):
            raise AssertionError('New started a bake')
        with patch.dict(self.session.components, {'scopes.capture': Component({'start_bake': forbidden})}):
            image = bake.new_image(grade)
        self.assertEqual(grade.pg_bake_image, image)
        self.assertEqual(self._source(grade).image, image)
        self.assertEqual(image.get('_pg_bake_kind'), 'EMPTY')
        self.assertTrue(bake.is_baked_image(image))
        self.assertNotIn('_pg_bake_frame', image)
        self.assertEqual(bake.eligibility(grade, context)['state'], 'ready')
        self.assertIsNone(bake.new_image(grade))
        bake.set_baked_image(grade, None)
        images = {value.session_uid for value in bpy.data.images}
        with patch.object(bake, 'pack_image', side_effect=RuntimeError('Packing failed')):
            with self.assertRaisesRegex(RuntimeError, 'Packing failed'):
                bake.new_image(grade)
        self.assertEqual({value.session_uid for value in bpy.data.images}, images)
        self.assertIsNone(grade.pg_bake_image)
        self.assertIsNone(self._source(grade).image)
        self.assertFalse(_component('ownership.transactions').pending())

    def test_route_blockers_disable_only_bake_and_hover_explains_the_remedy(self):
        tree, context = self._material()
        grade = nodes.create_grade(tree)
        shader = tree.nodes.new('ShaderNodeShaderToRGB')
        tree.links.new(shader.outputs['Color'], grade.inputs['Color'])
        context.pg_node = grade
        layout = BakeLayout()
        bake.draw_action(layout, grade, context)
        self.assertIn(('pg_bake_image', True), layout.controls)
        self.assertIn(('perceptual_grade.bake_compositor', False), layout.controls)
        self.assertFalse(bake.PG_OT_bake_compositor.poll(context))
        self.assertEqual(bake.eligibility(grade, context)['code'], 'shader_to_rgb')
        self.assertEqual(bake.PG_OT_bake_compositor.description(context, None),
                         _component('localization.i18n').tip('bake.blocked.shader_to_rgb'))
        def forbidden(*_args, **_kwargs):
            raise AssertionError('Blocked bake captured')
        with patch.dict(self.session.components, {'scopes.capture': Component({'start_bake': forbidden})}):
            self.assertIsNone(bake.start(grade, context))

    def test_shader_preflight_waits_without_loading_images_and_rejects_stale_completion(self):
        tree, context = self._material()
        grade = nodes.create_grade(tree)
        source = tree.nodes.new('ShaderNodeTexImage')
        image = source.image = self._image()
        tree.links.new(source.outputs['Color'], grade.inputs['Color'])
        image.buffers_free()
        self.assertFalse(image.has_data)
        observation = bake.eligibility(grade, context)
        self.assertEqual((observation['state'], observation['code']), ('waiting', 'checking'))
        bake.draw_action(BakeLayout(), grade, context)
        self.assertFalse(image.has_data, 'Passive eligibility decoded the Image')
        self.assertIsNone(bake.queue)
        self.assertFalse(bake.states)

        routes = _component('scopes.bake_routes')
        describe = routes.describe
        calls = []
        def superseded(*args, **kwargs):
            calls.append(1)
            result = describe(*args, **kwargs)
            bake.preflight_invalidated()
            return result
        adapter = Component({name: getattr(routes, name) for name in
            ('observe', 'observation_key', 'resolve_context', 'RouteBlocked')} | {'describe': superseded})
        with patch.dict(self.session.components, {'scopes.bake_routes': adapter}):
            bake.preflight_tick()
        self.assertEqual(calls, [1])
        self.assertEqual(bake.eligibility(grade, context)['code'], 'checking')
        bake.preflight_tick()
        self.assertTrue(bake.ready(grade, context))
        self.assertTrue(image.has_data)
        self.assertIsNone(bake.queue)
        source.interpolation = 'Closest'
        self.assertEqual(bake.eligibility(grade, context)['code'], 'checking')

    def test_bake_controls_wait_for_acknowledged_native_completion_on_both_pages(self):
        shader, _context = self._material()
        compositor = bpy.data.node_groups.new('Native reader controls', 'CompositorNodeTree')
        image = self._image()
        targets = []
        for tree in (shader, compositor):
            grade = nodes.create_grade(tree)
            targets.extend((grade, sequence(tree, [grade.pg_grade])))
        for node in targets:
            bake.set_baked_image(node, image)
        waiting = _component('localization.i18n').tip('bake.blocked.waiting')

        def controls(enabled):
            # Drawing and polling observe acknowledgements; neither may drain
            # callback ingress or dispatch a new native-evaluation transition.
            with patch.object(guard, 'reconcile', side_effect=AssertionError('Passive UI reconciled')):
                for node in targets:
                    context = SimpleNamespace(pg_node=node if nodes.is_grade(node) else None,
                                              pg_stack_node=node if stacks.is_stack(node) else None,
                                              screen=None)
                    layout = BakeLayout()
                    bake.draw_action(layout, node, context)
                    self.assertIn(('pg_bake_image', enabled), layout.controls)
                    self.assertIn(('perceptual_grade.bake_compositor', enabled), layout.controls)
                    self.assertEqual(bake.PG_OT_bake_compositor.poll(context), enabled)
                    self.assertNotIn((waiting, 'TIME'), layout.labels)
                    if not enabled:
                        self.assertEqual(bake.PG_OT_bake_compositor.description(context, None), waiting)
                    self.assertEqual(bake.baked_image(node), image)

        guard.reconcile()
        controls(True)
        guard.evaluation_started('selector-test', 1)
        try:
            # Playback has stopped, but its final native evaluation still owns
            # a reader. Immediate ingress must block even before the next pump.
            with patch.object(bake, 'playback_active', return_value=False):
                controls(False)
                guard.reconcile()
                controls(False)
                guard.evaluation_finished('selector-test', 2)
                guard.reconcile()
                controls(False)
        finally:
            guard.evaluation_finished('selector-test', 1)
        controls(False)
        guard.reconcile()
        controls(True)
        for node in targets:
            node.pg_bake_image = None
            self.assertIsNone(bake.baked_image(node))

    def test_reader_binding_keeps_native_property_kernel_and_socket_abi_in_agreement(self):
        first, second = self._image(), self._image()
        for tree_type in ('ShaderNodeTree', 'CompositorNodeTree'):
            tree = bpy.data.node_groups.new('Standalone reader', tree_type)
            reader = bake.create_node(tree)
            sockets = tuple((socket.name, socket.identifier) for socket in (*reader.inputs, *reader.outputs))
            bake.set_baked_image(reader, first)
            self.assertEqual(reader.pg_bake_image, first)
            self.assertEqual(bake.baked_image(reader), first)
            self.assertEqual(self._source(reader).image, first)
            clone_tree = tree.copy()
            clone = clone_tree.nodes[reader.name]
            bake.set_baked_image(clone, second)
            self.assertEqual(self._source(clone).image, second)
            self.assertEqual(self._source(reader).image, first)
            bake.set_baked_image(reader, None)
            self.assertIsNone(reader.pg_bake_image)
            self.assertIsNone(self._source(reader).image)
            self.assertEqual(tuple((socket.name, socket.identifier)
                                   for socket in (*reader.inputs, *reader.outputs)), sockets)

    def test_vector_sync_uses_link_or_uv_for_grade_stack_and_portable_reader(self):
        tree, _context = self._material()
        grade = nodes.create_grade(tree)
        stack = sequence(tree, [grade.pg_grade])
        reader = bake.create_node(tree)
        coordinates = tree.nodes.new('ShaderNodeTexCoord')
        for node, socket_name in ((grade, 'Vector'), (stack, 'Vector'), (reader, 'Vector')):
            self.assertTrue(next(field for field in node.node_tree.interface.items_tree
                                 if field.name == socket_name).description)
            source = self._source(node)
            self.assertEqual(source.inputs['Vector'].links[0].from_node.bl_idname, 'ShaderNodeTexCoord')
            link = tree.links.new(coordinates.outputs['Generated'], node.inputs[socket_name])
            bake.sync_coordinates()
            self.assertEqual(source.inputs['Vector'].links[0].from_node.bl_idname, 'NodeGroupInput')
            tree.links.remove(link)
            bake.sync_coordinates()
            self.assertEqual(source.inputs['Vector'].links[0].from_socket.name, 'UV')
        # A saved native reader uses its persistent kernel marker, not the
        # custom Python class name, to choose the Vector input.
        kernel = reader.node_tree
        tree.nodes.remove(reader)
        portable = tree.nodes.new('ShaderNodeGroup')
        portable.node_tree = kernel
        link = tree.links.new(coordinates.outputs['Generated'], portable.inputs['Vector'])
        bake.sync_coordinates()
        self.assertEqual(self._source(portable).inputs['Vector'].links[0].from_node.bl_idname, 'NodeGroupInput')
        tree.links.remove(link)
        bake.sync_coordinates()
        self.assertEqual(self._source(portable).inputs['Vector'].links[0].from_socket.name, 'UV')


class CompositorBakeTests(BlenderTest):
    """Bake snapshots are generated in memory; no repository fixture is used."""

    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    @staticmethod
    def _pixels(image):
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape(image.size[1], image.size[0], image.channels)

    @staticmethod
    def _metadata(image):
        return {key: value.to_list() if hasattr(value, 'to_list') else value
                for key, value in image.items()}

    def _scene(self):
        scene, _ = render_scene()
        scene.render.resolution_x, scene.render.resolution_y = 8, 4
        scene.render.resolution_percentage = 100
        scene.render.compositor_device = 'CPU'

        tree = bpy.data.node_groups.new('Generated compositor bake', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        source_image = bpy.data.images.new('Generated signed HDR', width=8, height=4,
                                            alpha=True, float_buffer=True)
        source_image.colorspace_settings.name = 'Non-Color'
        source_image.alpha_mode = 'CHANNEL_PACKED'
        y, x = np.mgrid[0:4, 0:8]
        source = np.stack((-.25 + x * .1, 2. + y * .25, .5 + x * .03,
                           np.where((x + y) % 2, .375, .75)), axis=-1).astype(np.float32)
        source_image.pixels.foreach_set(source.ravel())
        source_image.update()

        image_node = tree.nodes.new('CompositorNodeImage')
        image_node.image = source_image
        transform = tree.nodes.new('CompositorNodeTransform')
        transform.inputs['X'].default_value = 1
        transform.inputs['Interpolation'].default_value = 'Nearest'
        grade = nodes.create_grade(tree)
        nodes.write_values(grade, {'exposure': .35})
        nodes.write_chromatic(grade, {'global_gain': .1})
        output = tree.nodes.new('NodeGroupOutput')
        output.is_active_output = True
        tree.links.new(image_node.outputs['Image'], transform.inputs['Image'])
        tree.links.new(transform.outputs['Image'], grade.inputs['Color'])
        tree.links.new(grade.outputs['Color'], output.inputs['Image'])
        scene.compositing_node_group = tree

        # Ensure the selected Grade and the Stack both have complete native
        # output resources before the isolated helper receives its snapshot.
        lut.ensure(grade, nodes.bake_model(grade), force=True)
        stack = sequence(tree, [grade.pg_grade])
        tree.links.new(transform.outputs['Image'], stack.inputs['Color'])
        lut.ensure(stack, nodes.bake_model(stack), force=True)
        return scene, tree, source, grade, stack, output

    def _capture(self, node, *, release=True, after_start=None):
        token = capture.start_bake(node)
        deadline = time.monotonic() + 180
        try:
            if after_start is not None:
                after_start()
            result = None
            while result is None:
                capture.poll()
                result = capture.bake_status(token)
                if result is None:
                    self.assertLess(time.monotonic(), deadline,
                                    'Compositor bake did not finish')
                    time.sleep(.01)
            image = bpy.data.images.load(result['path'], check_existing=False)
            try:
                image.colorspace_settings.name = 'Non-Color'
                image.alpha_mode = 'CHANNEL_PACKED'
                pixels = self._pixels(image).copy()
            finally:
                bpy.data.images.remove(image)
            return result, pixels, token
        finally:
            # The foreground owns the artifact only for the duration of the
            # readback. Releasing it here allows the next independent bake.
            if release:
                capture.release_bake(token)

    @staticmethod
    def _analytic(rgba, node, model=None, rows=None):
        model = nodes.bake_model(node) if model is None else model
        before, after = lut.scope_rows(node, model) if rows is None else rows
        native = export.input_repair(rgba[..., :3].astype(np.float64) @ before.T,
                                     core_lut.AP1_Y).astype(np.float32)
        value = (model.prepare().bake_native(native)[..., :3] if stacks.is_stack(node)
                 else baking.kernel(model).evaluate(native))
        result = np.array(rgba, dtype=np.float32, copy=True)
        result[..., :3] = (value.astype(np.float64) @ after.T).astype(np.float32)
        return result

    def test_grade_and_stack_bakes_are_analytic_full_resolution_and_graph_preserving(self):
        scene, tree, source, grade, stack, output = self._scene()
        transform = next(node for node in tree.nodes if node.bl_idname == 'CompositorNodeTransform')
        tree.links.new(transform.outputs['Image'], output.inputs['Image'])
        with tempfile.TemporaryDirectory() as directory:
            upstream = render(Path(directory) / 'upstream.exr')
        tree.links.new(grade.outputs['Baked Color'], output.inputs['Image'])
        with tempfile.TemporaryDirectory() as directory:
            empty = render(Path(directory) / 'unbaked.exr')
        np.testing.assert_array_equal(empty, np.zeros_like(empty))
        tree.links.new(grade.outputs['Color'], output.inputs['Image'])
        before = tuple((node.name, node.bl_idname) for node in tree.nodes), tuple(
            (link.from_node.name, link.from_socket.identifier, link.to_node.name,
             link.to_socket.identifier) for link in tree.links)

        # Native Blender evaluates the upstream Transform; direct per-pixel
        # kernels apply the selected Grade without sampling its preview LUT.
        expected_grade = self._analytic(upstream, grade)
        artifact, actual_grade, token = self._capture(grade, release=False)
        self.assertEqual((artifact['width'], artifact['height']), (8, 4))
        self.assertEqual(tuple(artifact['domain']), (8, 4))
        self.assertEqual(artifact['frame'], scene.frame_current)
        self.assertEqual(artifact['engine'], scene.render.engine)
        np.testing.assert_allclose(actual_grade, expected_grade, rtol=0, atol=2e-5)
        self.assertLess(float(actual_grade[..., :3].min()), 0.)
        self.assertGreater(float(actual_grade[..., :3].max()), 1.)
        self.assertTrue(np.any(np.isclose(actual_grade[..., 3], .375)))
        self.assertTrue(np.any(np.isclose(actual_grade[..., 3], .75)))
        baked_image = bake.image_from_artifact(artifact)
        self.assertEqual(baked_image['_pg_bake_kind'], 'COMPOSITOR')
        self.assertEqual(tuple(baked_image['_pg_bake_domain']), (8, 4))
        self.assertEqual(baked_image['_pg_bake_frame'], scene.frame_current)
        self.assertIsNotNone(baked_image.packed_file)
        self.assertFalse(baked_image.is_dirty)
        self.assertTrue(baked_image.use_fake_user)
        capture.release_bake(token)
        self.assertEqual(before, (tuple((node.name, node.bl_idname) for node in tree.nodes), tuple(
            (link.from_node.name, link.from_socket.identifier, link.to_node.name,
             link.to_socket.identifier) for link in tree.links)))

        # Rewire only the generated scene's output to the Stack and repeat the
        # same native capture contract.  The source graph remains editable.
        tree.links.new(stack.outputs['Color'], output.inputs['Image'])
        expected_stack = self._analytic(upstream, stack)
        stack_artifact, actual_stack, stack_token = self._capture(stack)
        self.assertEqual((stack_artifact['width'], stack_artifact['height']), (8, 4))
        np.testing.assert_allclose(actual_stack, expected_stack, rtol=0, atol=2e-5)

        # The persisted third-kind node reads the packed Image without copying
        # the original Grade/Stack graph.
        baked_node = bake.create_node(tree)
        baked_node.pg_bake_image = baked_image
        self.assertEqual(bake.baked_image(baked_node), baked_image)
        tree.links.new(baked_node.outputs['Color'], output.inputs['Image'])
        with tempfile.TemporaryDirectory() as directory:
            replayed = render(Path(directory) / 'baked-image.exr')
        np.testing.assert_allclose(replayed, expected_grade, rtol=0, atol=2e-5)
        if baked_image.users == 0:
            bpy.data.images.remove(baked_image)

    def test_bake_freezes_analytic_selected_model_and_current_native_upstream(self):
        _scene, tree, _source, grade, _stack, _output = self._scene()
        transform = next(node for node in tree.nodes if node.bl_idname == 'CompositorNodeTransform')
        upstream = nodes.create_grade(tree)
        nodes.write_chromatic(upstream, {'global_gain': .05})
        lut.ensure(upstream, nodes.bake_model(upstream), force=True)
        tree.links.new(transform.outputs['Image'], upstream.inputs['Color'])
        tree.links.new(upstream.outputs['Color'], grade.inputs['Color'])
        before = tuple((node.name, node.bl_idname) for node in tree.nodes), tuple(
            (link.from_node.name, link.from_socket.identifier, link.to_node.name,
             link.to_socket.identifier) for link in tree.links)

        # Deliberately leave both kernels pending after these edits. Baking must
        # establish current final output itself, before it snapshots the scene.
        nodes.write_chromatic(upstream, {'global_gain': -.15})
        nodes.write_values(upstream, {'exposure': -.2})
        nodes.write_chromatic(grade, {'global_gain': .25})
        nodes.write_values(grade, {'exposure': .65})
        for node in (upstream, grade):
            with self.assertRaises(ValueError):
                lut.validate_output(node, nodes.bake_model(node), final=True)
        rendering = nodes._rendering
        frozen = nodes.bake_model(grade)
        rows = lut.scope_rows(grade, frozen)
        artifact, actual, _token = self._capture(grade)
        self.assertEqual(artifact['evaluation'], 'ANALYTIC')
        self.assertTrue(artifact['analytic_signature'])
        self.assertEqual(nodes._rendering, rendering)
        lut.validate_output(upstream, nodes.bake_model(upstream), final=True)
        self.assertEqual(before, (tuple((node.name, node.bl_idname) for node in tree.nodes), tuple(
            (link.from_node.name, link.from_socket.identifier, link.to_node.name,
             link.to_socket.identifier) for link in tree.links)))
        output = next(node for node in tree.nodes if node.bl_idname == 'NodeGroupOutput')
        tree.links.new(upstream.outputs['Color'], output.inputs['Image'])
        with tempfile.TemporaryDirectory() as directory:
            native = render(Path(directory) / 'current-upstream.exr')
        expected = self._analytic(native, grade, frozen, rows)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-5)

    @contextmanager
    def _publication(self):
        """Use a real EXR and Images while controlling helper readiness."""
        tree = bpy.data.node_groups.new('Publication target', 'CompositorNodeTree')
        grade = nodes.create_grade(tree)
        input_observation = capture.bake_input_observation
        changed_error = capture.BakeInputsChanged
        with tempfile.TemporaryDirectory(prefix='pg-bake-publication-') as directory:
            path = Path(directory) / 'bake.exr'
            image = bpy.data.images.new('Publication source', width=3, height=2,
                                        alpha=True, float_buffer=True)
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'CHANNEL_PACKED'
            image.pixels.foreach_set(np.tile(np.array((-.25, 2., .5, .375), np.float32), 6))
            image.filepath_raw = str(path)
            image.file_format = 'OPEN_EXR'
            image.save()
            bpy.data.images.remove(image)
            artifact = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            width=3, height=2, domain=(3, 2), scene='Scene', node=grade.name,
                            frame=3, engine='CYCLES', identity=('publication',))
            fake = SimpleNamespace(artifact=artifact, released=[], cancelled=[], starts=0,
                                   error='', ready=False, release_failures=0,
                                   start_error=None,
                                   defer_retirement=False, pending_retirement=[],
                                   retirement_callbacks={}, registration_failures=0, dispatched={},
                                   ready_tokens=set(), errors={}, inputs={}, on_start=None)
            def start(target, context=None, **_kwargs):
                if fake.start_error is not None:
                    raise fake.start_error
                fake.starts += 1
                token = 'test-bake-' + str(fake.starts)
                location = _component('scopes.context').source_context(target, context)
                fake.inputs[token] = (target, location, input_observation(target, location))
                if fake.on_start is not None:
                    fake.on_start(target)
                return token
            def check_inputs(token, **_kwargs):
                target, location, before = fake.inputs[token]
                if input_observation(target, location, native_lease=bool(_kwargs.get('native_lease'))) != before:
                    raise changed_error('Bake inputs changed')
                return True
            def status(_token):
                error = fake.errors.get(_token, fake.error)
                if error:
                    raise ValueError(error)
                return dict(fake.artifact) if (fake.ready or _token in fake.ready_tokens) and _token in fake.dispatched else None
            def release(token, *, on_retired=None):
                if fake.release_failures:
                    fake.release_failures -= 1
                    raise RuntimeError('retirement registration unavailable')
                fake.released.append(token)
                callback = on_retired or fake.retirement_callbacks.get(token)
                if callback is not None:
                    if fake.defer_retirement:
                        fake.pending_retirement.append(callback)
                    else:
                        callback()
            def on_retired(token, callback):
                if fake.registration_failures:
                    fake.registration_failures -= 1
                    raise RuntimeError('retirement callback unavailable')
                fake.retirement_callbacks[token] = callback
            adapter = Component(dict(start_bake=start, bake_status=status,
                                     check_bake_inputs=check_inputs, BakeInputsChanged=changed_error,
                                     dispatch_bake=lambda token,lane:fake.dispatched.__setitem__(token,lane),
                                     cancel_bake=fake.cancelled.append,
                                     on_bake_retired=on_retired,
                                     release_bake=release, clear=lambda: None,
                                     collect_retired=lambda: not fake.pending_retirement,
                                     invalidate=lambda: None))
            with patch.dict(self.session.components, {'scopes.capture': adapter}), \
                    patch.object(scheduler, 'wake', new=lambda *_args, **_kwargs: None):
                try:
                    yield grade, fake
                finally:
                    bake.clear()

    def test_poll_only_stages_artifact_and_publication_waits_for_native_readers(self):
        with self._publication() as (grade, fake):
            before = {image.name for image in bpy.data.images}
            token = bake.start(grade)
            bake.poll()
            self.assertIsNone(bake.status(token))
            fake.ready = True
            self.assertEqual(bake.poll(), .05)
            self.assertEqual(bake.status(token), fake.artifact)
            self.assertEqual(before, {image.name for image in bpy.data.images})
            with guard.native_operation():
                with self.assertRaises(guard.PublicationDeferred):
                    bake.finish(token)
            self.assertTrue(bake.busy())
            self.assertFalse(fake.released)
            image = bake.finish(token)
            self.assertTrue(image.use_fake_user)
            self.assertGreater(image.packed_file.size, 0)
            self.assertEqual(bake.baked_image(grade), image)
            self.assertIn('Baked Color', grade.outputs)
            self.assertEqual(fake.released, [token])
            self.assertFalse(bake.busy())
            with self.assertRaises(KeyError):
                bake.status(token)

    def test_first_bake_fills_new_empty_image_without_replacing_its_identity(self):
        with self._publication() as (grade, fake):
            image = bake.new_image(grade)
            identity = image.session_uid
            fake.ready = True
            token = bake.start(grade); bake.poll()
            self.assertEqual(bake.finish(token), image)
            self.assertEqual(image.session_uid, identity)
            self.assertEqual(image['_pg_bake_kind'], 'COMPOSITOR')
            self.assertEqual(tuple(image.size), (fake.artifact['width'], fake.artifact['height']))
            self.assertEqual(bytes(image.packed_file.data), Path(fake.artifact['path']).read_bytes())
            self.assertEqual(self._pixels(image).shape[:2],
                             (fake.artifact['height'], fake.artifact['width']))

    def test_two_grade_destinations_are_independent_and_progress_is_node_local(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            other = nodes.create_grade(grade.id_data)
            first = bake.start(grade); bake.poll(); image = bake.finish(first)
            second = bake.start(other); bake.poll(); other_image = bake.finish(second)
            self.assertNotEqual(image, other_image)
            other_before = (bytes(other_image.packed_file.data), self._metadata(other_image),
                            self._pixels(other_image).copy())
            self._rewrite_artifact(fake, 5, 3, (-.75, 4., .125, .625))
            grade.id_data.nodes.active = other
            token = bake.start(grade)
            layouts = {node: BakeLayout() for node in (grade, other)}
            for node, layout in layouts.items():
                bake.draw_action(layout, node)
                self.assertEqual(layout.context['pg_node'], node)
                self.assertIn(('pg_bake_image', node != grade), layout.controls)
            self.assertTrue(any(icon == 'TIME' for _text, icon in layouts[grade].labels))
            self.assertFalse(any(icon == 'TIME' for _text, icon in layouts[other].labels))
            self.assertEqual(len(bake.states), 1)
            bake.poll(); self.assertEqual(bake.finish(token), image)
            self.assertEqual(fake.starts, 3)
            self.assertEqual(bytes(other_image.packed_file.data), other_before[0])
            self.assertEqual(self._metadata(other_image), other_before[1])
            np.testing.assert_array_equal(self._pixels(other_image), other_before[2])
            self.assertEqual(bake.baked_image(other), other_image)
            self.assertEqual(tuple(image.size), (5, 3))

    def test_two_bake_workers_progress_independently_and_retired_lane_serves_next(self):
        with self._publication() as (grade, fake):
            second = nodes.create_grade(grade.id_data)
            third = nodes.create_grade(grade.id_data)
            first_token = bake.start(grade)
            second_token = bake.start(second)
            third_token = bake.start(third)
            self.assertEqual(fake.dispatched, {first_token:'bake_0',second_token:'bake_1'})
            self.assertIsNone(bake.start(grade))
            fake.ready_tokens.add(second_token)
            bake.poll()
            self.assertEqual(fake.dispatched[third_token], 'bake_1')
            self.assertIsNone(bake.baked_image(second))
            second_image = bake.finish(second_token)
            self.assertIsNotNone(second_image)
            self.assertTrue(bake.busy(grade) and bake.busy(third))
            self.assertFalse(bake.busy(second))
            fake.ready_tokens.update((first_token, third_token)); bake.poll()
            first_image, third_image = bake.finish(first_token), bake.finish(third_token)
            self.assertEqual(len({first_image,second_image,third_image}),3)
            self.assertFalse(bake.busy())

    def test_grade_selector_change_is_observed_by_bake_and_preserves_shared_image(self):
        with self._publication() as (grade, fake):
            grades = _component('graph.grades')
            original = grades.new(grade)
            replacement = original.copy()
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            reader = nodes.create_grade(grade.id_data)
            bake.set_baked_image(reader, image)
            before = (bytes(image.packed_file.data), self._metadata(image), self._pixels(image).copy())
            fake.ready = False; fake.defer_retirement = True
            token = bake.start(grade)
            grade.pg_grade = replacement
            self.assertIn(token, bake.states)  # Source callbacks do not cancel consumers.
            self.assertFalse(fake.cancelled)
            bake.poll()
            self.assertEqual(fake.cancelled, [token])
            self.assertNotIn(token, bake.states)
            self.assertTrue(bake.busy(grade))
            self.assertEqual(_component('integration.outcomes').get(grade, 'bake').code,
                             'bake.inputs_changed')
            self.assertEqual(grade.pg_bake_image, image)
            self.assertEqual(reader.pg_bake_image, image)
            self.assertEqual(bytes(image.packed_file.data), before[0])
            self.assertEqual(self._metadata(image), before[1])
            np.testing.assert_array_equal(self._pixels(image), before[2])
            for callback in fake.pending_retirement:
                callback()
            fake.pending_retirement.clear(); fake.defer_retirement = False
            self.assertFalse(bake.busy(grade))
            starts = fake.starts
            bake.poll()
            self.assertEqual(fake.starts, starts)  # Only another click starts a retry.
            retry = bake.start(grade)
            self.assertIsNotNone(retry)
            self.assertIsNone(_component('integration.outcomes').get(grade, 'bake'))
            bake.cancel(retry)

    def test_grade_change_and_revert_revokes_ready_artifact_before_publication(self):
        with self._publication() as (grade, fake):
            grades = _component('graph.grades')
            selected = grades.new(grade)
            replacement = selected.copy()
            fake.ready = True
            token = bake.start(grade); bake.poll()
            before = tuple(bpy.data.images)
            original = nodes.output_intent(grade)
            grade.pg_grade = replacement
            grade.pg_grade = selected
            self.assertEqual(nodes.output_intent(grade), original)
            self.assertIsNone(bake.finish(token))
            self.assertEqual(fake.cancelled, [token])
            self.assertEqual(tuple(bpy.data.images), before)
            self.assertIsNone(grade.pg_bake_image)

    def test_upstream_grade_edit_cancels_only_bakes_that_consume_its_live_output(self):
        with self._publication() as (grade, fake):
            upstream = nodes.create_grade(grade.id_data)
            unrelated = nodes.create_grade(grade.id_data)
            grade.id_data.links.new(upstream.outputs['Color'], grade.inputs['Color'])
            token = bake.start(grade)
            other = bake.start(unrelated)
            nodes.write_chromatic(upstream, {'global_gain': .3})
            self.assertEqual(fake.cancelled, [])
            bake.poll()
            self.assertEqual(fake.cancelled, [token])
            self.assertIn(other, bake.states)
            fake.ready = True; bake.poll()
            self.assertIsNotNone(bake.finish(other))

    def test_stack_contents_and_shared_grade_parameters_interrupt_their_requests(self):
        with self._publication() as (grade, fake):
            selected = _component('graph.grades').new(grade)
            stack = sequence(grade.id_data, [selected, selected])
            for mutate in (lambda: setattr(stack.pg_stack_entries[0], 'enabled', False),
                           lambda: setattr(stack.pg_stack_entries[1], 'direction', 'INVERSE'),
                           lambda: setattr(selected.pg_chromatic, 'global_gain', .2)):
                token = bake.start(stack)
                self.assertIsNotNone(token)
                mutate()
                self.assertIn(token, bake.states)
                bake.poll()
                self.assertNotIn(token, bake.states)
                self.assertIn(token, fake.cancelled)

    def test_source_change_during_snapshot_freeze_never_dispatches(self):
        with self._publication() as (grade, fake):
            fake.on_start = lambda target: nodes.write_chromatic(target, {'global_gain': .2})
            self.assertIsNone(bake.start(grade))
            self.assertFalse(fake.dispatched)
            self.assertEqual(fake.cancelled, ['test-bake-1'])
            self.assertFalse(bake.states)

    def test_layout_selection_and_unrelated_edits_keep_the_same_bake_running(self):
        with self._publication() as (grade, fake):
            upstream = nodes.create_grade(grade.id_data)
            unrelated = nodes.create_grade(grade.id_data)
            grade.id_data.links.new(upstream.outputs['Color'], grade.inputs['Color'])
            token = bake.start(grade)
            grade.id_data.nodes.active = unrelated
            grade.location.x += 100.; upstream.location.y -= 50.
            grade.name = 'Renamed target'; upstream.name = 'Renamed source'
            nodes.write_chromatic(unrelated, {'global_gain': .3})
            bake.poll()
            self.assertIn(token, bake.states)
            self.assertFalse(fake.cancelled)
            fake.ready = True; bake.poll()
            self.assertIsNotNone(bake.finish(token))

    def test_shared_destination_waits_for_prior_publication_and_keeps_frozen_requests(self):
        with self._publication() as (grade, fake):
            fake.ready=True
            original=bake.start(grade);bake.poll();image=bake.finish(original)
            other=nodes.create_grade(grade.id_data);bake.set_baked_image(other,image)
            fake.ready=False
            first=bake.start(grade);second=bake.start(other)
            self.assertEqual(fake.starts,3)  # Both clicks froze their source immediately.
            self.assertNotIn(second,fake.dispatched)
            fake.ready_tokens.add(first);bake.poll()
            with guard.native_operation(),self.assertRaises(guard.PublicationDeferred):
                bake.finish(first)
            self.assertNotIn(second,fake.dispatched)
            self.assertEqual(bake.finish(first),image)
            bake.poll();self.assertIn(second,fake.dispatched)
            fake.ready_tokens.add(second);bake.poll()
            self.assertEqual(bake.finish(second),image)
            self.assertEqual(fake.released[-2:],[first,second])

    def test_eight_request_bound_and_cancelled_worker_retirement_reservations(self):
        with self._publication() as (grade, fake):
            targets=[grade]+[nodes.create_grade(grade.id_data) for _ in range(8)]
            tokens=[bake.start(node) for node in targets[:8]]
            self.assertEqual(len(fake.dispatched),2)
            self.assertIsNone(bake.start(targets[8]))
            self.assertEqual(bake.eligibility(targets[8])['code'], 'queue')
            fake.defer_retirement=True
            bake.cancel(tokens[0])
            self.assertTrue(bake.busy(grade))
            self.assertIsNone(bake.start(targets[8]))
            self.assertEqual(bake.eligibility(targets[8])['code'], 'queue')
            self.assertEqual(len(fake.pending_retirement),1)
            fake.pending_retirement.pop()()
            fake.defer_retirement=False
            replacement=bake.start(targets[8])
            self.assertEqual(len(bake.states),8)
            self.assertEqual(fake.dispatched[tokens[2]],'bake_0')
            self.assertNotIn(replacement,fake.dispatched)

    def test_request_error_stays_on_its_target_when_another_bake_succeeds(self):
        with self._publication() as (grade, fake):
            other=nodes.create_grade(grade.id_data)
            failed=bake.start(grade);success=bake.start(other)
            fake.errors[failed]='Independent capture failure'
            fake.ready_tokens.add(success);bake.poll()
            with self.assertRaisesRegex(ValueError,'Independent capture failure'):
                bake.status(failed)
            bake.cancel(failed);bake.finish(success)
            first,second=BakeLayout(),BakeLayout()
            bake.draw_action(first,grade);bake.draw_action(second,other)
            outcome = _component('integration.outcomes').get(grade, 'bake')
            self.assertEqual(outcome.code, 'outcome.failed')
            self.assertIn('Independent capture failure', outcome.diagnostic)
            self.assertFalse(any('Independent capture failure' in text for text, _icon in first.labels))
            self.assertIsNone(_component('integration.outcomes').get(other, 'bake'))

    def test_modal_bakes_pass_pending_timer_events_through(self):
        with self._publication() as (grade, fake):
            token=bake.start(grade)
            op=SimpleNamespace(token=token)
            event=SimpleNamespace(type='TIMER')
            self.assertEqual(bake.PG_OT_bake_compositor.modal(op,bpy.context,event),{'PASS_THROUGH'})
            fake.ready=True
            with patch.object(guard,'require_available',side_effect=guard.PublicationDeferred('busy')):
                self.assertEqual(bake.PG_OT_bake_compositor.modal(op,bpy.context,event),{'PASS_THROUGH'})

    def test_playback_disables_bake_and_race_click_creates_no_request_or_popup(self):
        with self._publication() as (grade, fake):
            context = SimpleNamespace(pg_node=grade, screen=None)
            reports = []
            op = SimpleNamespace(token='', report=lambda *args: reports.append(args))
            with patch.object(bake, 'playback_active', return_value=True):
                layout = BakeLayout()
                bake.draw_action(layout, grade, context)
                self.assertIn(('perceptual_grade.bake_compositor', False), layout.controls)
                self.assertFalse(bake.PG_OT_bake_compositor.poll(context))
                self.assertIsNone(bake.start(grade, context=context))
                self.assertEqual(bake.PG_OT_bake_compositor._begin(op, context), {'CANCELLED'})
            self.assertEqual(fake.starts, 0)
            self.assertFalse(bake.states)
            self.assertFalse(fake.dispatched)
            self.assertFalse(reports)

    def test_native_reader_race_click_creates_no_request_or_popup(self):
        with self._publication() as (grade, fake):
            context = SimpleNamespace(pg_node=grade, screen=None, window=object())
            reports = []
            op = SimpleNamespace(token='', report=lambda *args: reports.append(args))
            guard.reconcile()
            self.assertTrue(bake.PG_OT_bake_compositor.poll(context))
            before = set(bpy.data.images)
            guard.evaluation_started('after-playback', 1)
            try:
                with patch.object(bake, 'playback_active', return_value=False):
                    self.assertFalse(bake.PG_OT_bake_compositor.poll(context))
                    self.assertIsNone(bake.start(grade, context=context))
                    self.assertEqual(bake.PG_OT_bake_compositor._begin(op, context), {'CANCELLED'})
                self.assertEqual(fake.starts, 0)
                self.assertFalse(bake.states or fake.dispatched or reports)
                self.assertIsNone(bake.queue)
                self.assertEqual(set(bpy.data.images), before)
            finally:
                guard.evaluation_finished('after-playback', 1)
                guard.reconcile()
            self.assertTrue(bake.PG_OT_bake_compositor.poll(context))
            token = bake.start(grade, context=context)
            self.assertIsNotNone(token)
            self.assertEqual(fake.starts, 1)

    def test_bake_controls_and_admission_share_all_native_job_guards(self):
        with self._publication() as (grade, fake):
            context = SimpleNamespace(pg_node=grade, screen=None)
            guard.reconcile()
            for job in guard.JOBS:
                native = SimpleNamespace(app=SimpleNamespace(is_job_running=lambda value: value == job),
                    data=SimpleNamespace(window_managers=[SimpleNamespace(is_interface_locked=False,
                        windows=[SimpleNamespace(modal_operators=[])])]))
                with self.subTest(job=job), patch.object(guard, 'bpy', native):
                    layout = BakeLayout()
                    bake.draw_action(layout, grade, context)
                    self.assertIn(('perceptual_grade.bake_compositor', False), layout.controls)
                    self.assertFalse(bake.PG_OT_bake_compositor.poll(context))
                    self.assertIsNone(bake.start(grade, context=context))
            self.assertEqual(fake.starts, 0)
            self.assertFalse(bake.states)

    def test_native_deferral_during_freeze_releases_admission_without_error(self):
        with self._publication() as (grade, fake):
            context = SimpleNamespace(pg_node=grade, screen=None, window=object())
            reports = []
            op = SimpleNamespace(token='', report=lambda *args: reports.append(args))
            fake.start_error = guard.PublicationDeferred('Native evaluation has not finished')
            self.assertEqual(bake.PG_OT_bake_compositor._begin(op, context), {'CANCELLED'})
            self.assertFalse(reports or bake.states or fake.starts)
            self.assertFalse(any(entry.request for entry in bake.queue.state.entries))
            layout = BakeLayout()
            bake.draw_action(layout, grade, context)
            self.assertFalse(any(icon == 'ERROR' for _text, icon in layout.labels))
            fake.start_error = None
            self.assertIsNotNone(bake.start(grade, context=context))

    def test_playback_cancels_ready_running_and_queued_bakes_but_preserves_images(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            previous = bake.start(grade); bake.poll(); image = bake.finish(previous)
            before = (bytes(image.packed_file.data), self._metadata(image), self._pixels(image).copy())
            fake.ready = False
            targets = [grade] + [nodes.create_grade(grade.id_data) for _ in range(3)]
            ready = bake.start(grade)
            fake.ready_tokens.add(ready); bake.poll()
            tokens = [ready] + [bake.start(node) for node in targets[1:]]
            phases = [bake.queue.state.entries[bake.states[token]['reservation']['slot']].phase
                      for token in tokens]
            self.assertEqual(phases, ['ready', 'running', 'running', 'queued'])
            dispatched = dict(fake.dispatched)
            fake.defer_retirement = True
            with patch.object(bake, 'playback_active', return_value=True):
                bake.poll()
                self.assertFalse(bake.states)
                self.assertEqual(set(fake.cancelled), set(tokens))
                self.assertEqual(fake.dispatched, dispatched)
                for node in targets:
                    self.assertTrue(bake.busy(node))  # Physical retirement owns the reservation.
                    layout = BakeLayout(); bake.draw_action(layout, node)
                    self.assertIn(('Bake interrupted by timeline playback', 'INFO'), layout.labels)
                    self.assertIn(('perceptual_grade.bake_compositor', False), layout.controls)
            self.assertEqual(bake.baked_image(grade), image)
            self.assertEqual(bytes(image.packed_file.data), before[0])
            self.assertEqual(self._metadata(image), before[1])
            np.testing.assert_array_equal(self._pixels(image), before[2])
            self.assertTrue(all(bake.baked_image(node) is None for node in targets[1:]))
            callbacks, fake.pending_retirement = fake.pending_retirement, []
            for callback in callbacks:
                callback()
            self.assertTrue(all(not bake.busy(node) for node in targets))
            fake.defer_retirement = False
            replacement = bake.start(grade)
            layout = BakeLayout(); bake.draw_action(layout, grade)
            self.assertFalse(any(icon == 'INFO' for _, icon in layout.labels))
            bake.cancel(replacement)

    def test_quick_play_stop_latches_cancellation_outside_native_callback(self):
        with self._publication() as (grade, fake):
            token = bake.start(grade)
            with patch.object(bake, 'playback_active', return_value=False):
                with guard.native_callback():
                    bake.playback_started(bpy.context.scene, None)
                    self.assertIn(token, bake.states)
                    self.assertFalse(fake.cancelled)
                bake.poll()
            self.assertEqual(fake.cancelled, [token])
            self.assertFalse(bake.states)

    def test_playback_before_finish_discards_ready_artifact_without_publication(self):
        with self._publication() as (grade, fake):
            token = bake.start(grade); fake.ready = True; bake.poll()
            before = tuple(bpy.data.images)
            with patch.object(bake, 'playback_active', return_value=True):
                self.assertIsNone(bake.finish(token))
            self.assertEqual(tuple(bpy.data.images), before)
            self.assertIsNone(bake.baked_image(grade))
            self.assertEqual(fake.cancelled, [token])

    def test_playback_modal_cancellation_has_no_error_report(self):
        with self._publication() as (grade, fake):
            token = bake.start(grade)
            reports = []
            op = SimpleNamespace(token=token, report=lambda *args: reports.append(args))
            with patch.object(bake, 'playback_active', return_value=True):
                result = bake.PG_OT_bake_compositor.modal(op, bpy.context, SimpleNamespace(type='TIMER'))
            self.assertEqual(result, {'CANCELLED'})
            self.assertFalse(reports)
            self.assertEqual(fake.cancelled, [token])

    def test_playback_preserves_committed_bake_awaiting_helper_retirement(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll()
            fake.defer_retirement = True
            image = bake.finish(token)
            self.assertTrue(bake.states[token]['committed'])
            before = bytes(image.packed_file.data)
            with patch.object(bake, 'playback_active', return_value=True):
                bake.playback_started(bpy.context.scene, None)
                bake.poll()
            self.assertFalse(fake.cancelled)
            self.assertEqual(bake.baked_image(grade), image)
            self.assertEqual(bytes(image.packed_file.data), before)
            callbacks, fake.pending_retirement = fake.pending_retirement, []
            for callback in callbacks:
                callback()
            bake.poll()
            self.assertFalse(bake.busy(grade))

    def test_native_selector_preserves_canonical_identity_and_rejects_invalid_assignment(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            ordinary = bpy.data.images.new('Ordinary Image', width=2, height=2, float_buffer=True)
            ordinary.pack()
            grade.pg_bake_image = ordinary
            self.assertEqual(grade.pg_bake_image, image)
            self.assertEqual(_component('integration.outcomes').get(grade, 'image').code, 'bake.blocked.destination')
            other = nodes.create_grade(grade.id_data)
            with guard.native_operation():
                other.pg_bake_image = image
            self.assertIsNone(bake.baked_image(other))
            for node in (other, sequence(grade.id_data, [grade.pg_grade])):
                node.pg_bake_image = image
                self.assertEqual(bake.baked_image(node), image)
                self.assertEqual(node.bl_rna.properties['pg_bake_image'].type, 'POINTER')
            image.name = 'Renamed Grade bake'
            self.assertEqual(other.pg_bake_image, image)
            other.pg_bake_image = None
            self.assertIsNone(bake.baked_image(other))
            token = bake.start(other); bake.poll(); created = bake.finish(token)
            self.assertNotEqual(created, image)
            self.assertEqual(other.pg_bake_image, created)

    def test_destination_preflight_is_quiet_and_keeps_other_nodes_available(self):
        with self._publication() as (grade, fake):
            other = nodes.create_grade(grade.id_data)
            image = bpy.data.images.new('Unrelated destination', width=2, height=2, float_buffer=True)
            image.pack()
            with bake.binding_suppressed(grade):
                grade.pg_bake_image = image
            self.assertIsNone(bake.start(grade))
            self.assertEqual(fake.starts, 0)
            self.assertEqual(bake.eligibility(grade)['code'], 'destination')
            self.assertTrue(bake.ready(other))
            outcome = _component('integration.outcomes').get(grade, 'bake')
            self.assertEqual(outcome.code, 'bake.blocked.destination')

    def test_ready_cancel_and_native_boundary_leave_no_published_images(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            before = {image.name for image in bpy.data.images}
            for boundary in ('cancel', 'replacement'):
                token = bake.start(grade)
                bake.poll()
                self.assertIsNotNone(bake.status(token))
                if boundary == 'cancel':
                    bake.cancel(token)
                else:
                    nodes.clear_transient_caches()
                self.assertFalse(bake.busy())
                self.assertEqual(before, {image.name for image in bpy.data.images})
                self.assertIn(token, fake.cancelled)
                self.assertIn(token, fake.released)

    def test_start_cancels_capture_if_retirement_callback_registration_fails(self):
        with self._publication() as (grade, fake):
            fake.registration_failures = 1
            with self.assertRaisesRegex(RuntimeError, 'retirement callback unavailable'):
                bake.start(grade)
            self.assertFalse(bake.states)
            self.assertEqual(fake.cancelled, ['test-bake-1'])
            self.assertEqual(fake.released, ['test-bake-1'])
            self.assertIsNone(bake.baked_image(grade))

    def test_terminal_errors_and_failed_publication_do_not_leave_images(self):
        with self._publication() as (grade, fake):
            before = {image.name for image in bpy.data.images}
            token = bake.start(grade)
            fake.error = 'helper stopped'
            bake.poll()
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'helper stopped'):
                    bake.status(token)
            bake.cancel(token)
            fake.error = ''
            fake.ready = True
            token = bake.start(grade)
            bake.poll()
            with patch.object(bake, 'pack_image', side_effect=RuntimeError('pack failed')):
                with self.assertRaisesRegex(RuntimeError, 'pack failed'):
                    bake.finish(token)
            self.assertFalse(bake.busy())
            self.assertEqual(before, {image.name for image in bpy.data.images})
            self.assertEqual(fake.released, ['test-bake-1', 'test-bake-2'])

    def test_repeated_publication_retains_no_completed_rna_state(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            for _ in range(4):
                token = bake.start(grade)
                bake.poll()
                image = bake.finish(token)
                self.assertFalse(bake.states)
                image.use_fake_user = False
                bpy.data.images.remove(image)
            self.assertEqual(len(fake.released), 4)

    def test_rejected_publication_before_native_write_discards_only_backup(self):
        for rejected in ('begin', 'reserved', 'verified'):
            with self.subTest(rejected=rejected), self._publication() as (grade, fake):
                fake.ready = True
                before = {image.name for image in bpy.data.images}
                token = bake.start(grade); bake.poll()
                publication = bake.states[token]['publication']
                require = publication.require

                def reject(kind, action, **values):
                    if kind == rejected:
                        raise RuntimeError('publication admission rejected')
                    return require(kind, action, **values)

                with patch.object(publication, 'require', new=reject), \
                        patch.object(bake, 'replace_packed', side_effect=AssertionError('unexpected native restoration')):
                    with self.assertRaisesRegex(RuntimeError, 'publication admission rejected'):
                        bake.finish(token)
                self.assertFalse(bake.states)
                self.assertIsNone(bake.baked_image(grade))
                self.assertEqual(before, {image.name for image in bpy.data.images})
                self.assertEqual(fake.released, [token])

    def test_committed_image_survives_cleanup_failure_and_retries_retirement(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll()
            state = bake.states[token]
            fake.release_failures = 2
            image = bake.finish(token)
            before = self._pixels(image).copy()
            self.assertTrue(state['committed'])
            self.assertNotIn('repair', state)
            self.assertIn('retirement registration unavailable', bake.last_error)
            self.assertEqual(bake.baked_image(grade), image)
            self.assertFalse(fake.cancelled)
            self.assertFalse(state['workflow'].store.ref.closed)
            bake.clear()
            self.assertIs(bake.states[token], state)
            np.testing.assert_array_equal(self._pixels(image), before)

            fake.defer_retirement = True
            bake.poll()
            self.assertEqual(fake.released, [token])
            self.assertIs(bake.states[token], state)
            self.assertFalse(state['workflow'].store.ref.closed)
            self.assertFalse(bake.physical_retired())
            bake.poll()
            self.assertEqual(fake.released, [token])
            fake.pending_retirement.pop()()
            self.assertTrue(bake.drain_committed())
            self.assertTrue(bake.physical_retired())
            self.assertFalse(bake.states)
            self.assertTrue(state['workflow'].store.ref.closed)
            self.assertTrue(state['publication'].store.ref.closed)
            self.assertFalse(fake.cancelled)
            np.testing.assert_array_equal(self._pixels(image), before)

    def test_committed_cleanup_observes_retirement_after_global_capture_clear(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll()
            state = bake.states[token]
            fake.release_failures = 1
            image = bake.finish(token)
            # The capture adapter's global clear can physically retire a token
            # before its foreground release call is retried.
            fake.retirement_callbacks[token]()
            self.assertTrue(state['retired'])
            self.assertTrue(bake.drain_committed())
            self.assertFalse(bake.states)
            self.assertFalse(fake.released)
            self.assertEqual(bake.baked_image(grade), image)

    def _rewrite_artifact(self, fake, width, height, rgba):
        image = bpy.data.images.new('Replacement pixels', width=width, height=height,
                                    alpha=True, float_buffer=True)
        try:
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'CHANNEL_PACKED'
            image.pixels.foreach_set(np.tile(np.array(rgba, np.float32), width * height))
            image.filepath_raw = fake.artifact['path']
            image.file_format = 'OPEN_EXR'
            image.save()
        finally:
            bpy.data.images.remove(image)
        fake.artifact.update(width=width, height=height, domain=(width, height), frame=9,
                             sha256=hashlib.sha256(Path(fake.artifact['path']).read_bytes()).hexdigest())

    def _restore_encoded_revision(self, image, fake):
        """Model native Undo restoring packed storage while retaining an ImBuf."""
        before = self._pixels(image).copy()
        self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
        restored = bake.image_from_artifact(fake.artifact)
        try:
            operation=json.loads(restored['_pg_bake_operation']);operation['phase']='COMPLETE'
            restored['_pg_bake_operation']=json.dumps(operation)
            expected = self._pixels(restored).copy()
            payload = bytes(restored.packed_file.data)
            image.pack(data=payload, data_len=len(payload))
            for key, value in restored.items():
                if key.startswith('_pg_bake_'):
                    image[key] = value.to_list() if hasattr(value, 'to_list') else value
        finally:
            bpy.data.images.remove(restored)
        np.testing.assert_array_equal(self._pixels(image), before)
        return expected

    def test_rebake_updates_one_shared_image_and_preserves_color_links(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            output = grade.id_data.nodes.new('NodeGroupOutput')
            field = grade.id_data.interface.new_socket(name='Result', in_out='OUTPUT', socket_type='NodeSocketColor')
            grade.id_data.links.new(grade.outputs['Color'], output.inputs[field.identifier])
            links = tuple((link.from_socket.identifier, link.to_socket.identifier) for link in grade.id_data.links)
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            pointer, name = image.as_pointer(), image.name
            standalone = bake.create_node(grade.id_data)
            standalone.pg_bake_image = image
            duplicate = nodes.create_grade(grade.id_data)
            nodes.assign_kernel(duplicate, lut.clone_kernel(grade.node_tree))
            bake.set_baked_image(duplicate, image)
            self.assertEqual(bake.baked_image(duplicate), image)
            self._rewrite_artifact(fake, 5, 3, (-.75, 4., .125, .625))
            token = bake.start(grade); bake.poll(); replacement = bake.finish(token)
            self.assertEqual((replacement.as_pointer(), replacement.name), (pointer, name))
            self.assertEqual(standalone.pg_bake_image, image)
            self.assertEqual(bake.baked_image(duplicate), image)
            self.assertEqual(tuple(image.size), (5, 3))
            np.testing.assert_array_equal(self._pixels(image), np.tile(
                np.array((-.75, 4., .125, .625), np.float32), (3, 5, 1)))
            self.assertEqual(image['_pg_bake_frame'], 9)
            self.assertEqual(image['_pg_bake_schema'], 2)
            self.assertEqual(links, tuple((link.from_socket.identifier, link.to_socket.identifier)
                                         for link in grade.id_data.links))

    def test_failed_shared_image_replacement_restores_pixels_and_metadata(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            before = self._pixels(image).copy()
            packed = bytes(image.packed_file.data)
            frame, pointer = image['_pg_bake_frame'], image.as_pointer()
            self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
            original = bake.replace_packed
            calls = []
            def fail_once(target, payload):
                original(target, payload)
                calls.append(len(payload))
                if len(calls) == 1:
                    raise RuntimeError('replacement interrupted')
            token = bake.start(grade); bake.poll()
            with patch.object(bake, 'replace_packed', new=fail_once):
                with self.assertRaisesRegex(RuntimeError, 'replacement interrupted'):
                    bake.finish(token)
            self.assertFalse(bake.states)
            self.assertEqual(bake.baked_image(grade).as_pointer(), pointer)
            self.assertEqual(bytes(image.packed_file.data), packed)
            self.assertEqual(image['_pg_bake_frame'], frame)
            np.testing.assert_array_equal(self._pixels(image), before)

    def test_publication_failures_restore_each_mutation_phase(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            before = self._pixels(image).copy()
            operation = image['_pg_bake_operation']
            self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
            for wanted in ('packed', 'transferred', 'metadata'):
                token = bake.start(grade); bake.poll()
                def fail(phase):
                    if phase == wanted:
                        raise RuntimeError('publication ' + wanted)
                with patch.object(bake, 'publication_checkpoint', new=fail):
                    with self.assertRaisesRegex(RuntimeError, 'publication ' + wanted):
                        bake.finish(token)
                self.assertFalse(bake.states)
                self.assertEqual(image['_pg_bake_frame'], 3)
                self.assertEqual(image['_pg_bake_operation'], operation)
                np.testing.assert_array_equal(self._pixels(image), before)

    def test_failed_rollback_retains_backup_and_capture_lease_until_repaired(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            before = self._pixels(image).copy()
            self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
            original = bake.replace_packed
            calls = []
            def fail_restore(target, payload):
                calls.append(1)
                if len(calls) > 1:
                    raise RuntimeError('restore unavailable')
                original(target, payload)
            def fail_publication(phase):
                if phase == 'packed':
                    raise RuntimeError('publication interrupted')
            token = bake.start(grade); bake.poll()
            with patch.object(bake, 'replace_packed', new=fail_restore), \
                    patch.object(bake, 'publication_checkpoint', new=fail_publication):
                with self.assertRaisesRegex(RuntimeError, 'rollback requires repair'):
                    bake.finish(token)
                self.assertIn('repair', bake.states[token])
                self.assertNotIn(token, fake.released)
            bake.cancel(token)
            self.assertFalse(bake.states)
            self.assertIn(token, fake.released)
            np.testing.assert_array_equal(self._pixels(image), before)

    def test_failed_restoration_receipt_retains_native_backup_until_acknowledged(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            before = self._pixels(image).copy()
            self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
            token = bake.start(grade); bake.poll()
            state = bake.states[token]
            publication = state['publication']
            require = publication.require

            def fail_publication(phase):
                if phase == 'packed':
                    raise RuntimeError('publication interrupted')

            def reject_receipt(kind, action, **values):
                if kind == 'repaired':
                    raise RuntimeError('restoration receipt unavailable')
                return require(kind, action, **values)

            with patch.object(bake, 'publication_checkpoint', new=fail_publication), \
                    patch.object(publication, 'require', new=reject_receipt):
                with self.assertRaisesRegex(RuntimeError, 'restoration receipt unavailable'):
                    bake.finish(token)
            self.assertIn('repair', state)
            self.assertTrue(publication.state.debt)
            self.assertNotIn(token, fake.released)
            np.testing.assert_array_equal(self._pixels(image), before)
            bake.poll()
            self.assertFalse(bake.states)
            self.assertIn(token, fake.released)
            np.testing.assert_array_equal(self._pixels(image), before)

    def test_native_load_retires_failed_repair_without_touching_replacement_ids(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            self._rewrite_artifact(fake, 5, 3, (-.5, 6., .25, .5))
            original = bake.replace_packed
            calls = []
            def fail_restore(target, payload):
                calls.append(1)
                if len(calls) > 1:
                    raise RuntimeError('restore unavailable')
                original(target, payload)
            def fail_publication(phase):
                if phase == 'packed':
                    raise RuntimeError('publication interrupted')
            token = bake.start(grade); bake.poll()
            with patch.object(bake, 'replace_packed', new=fail_restore), \
                    patch.object(bake, 'publication_checkpoint', new=fail_publication):
                with self.assertRaisesRegex(RuntimeError, 'rollback requires repair'):
                    bake.finish(token)
                self.assertIn('repair', bake.states[token])
                # Real Blender replacement continues even when a pre-handler
                # reports failed repair. Old references must not poison recovery.
                image = grade = None
                bpy.ops.wm.read_factory_settings(use_empty=True)
            self.assertFalse(bake.states)
            for _ in range(100):
                if not nodes.recovery_pending():break
                nodes.recovery_tick()
            self.assertFalse(nodes.recovery_pending())
            self.assertIn(token, fake.released)

    def test_removed_or_rebound_target_cannot_publish(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll()
            other = bpy.data.images.new('User reassignment', width=2, height=2, float_buffer=True)
            with bake.binding_suppressed(grade):
                grade.pg_bake_image = other
            with self.assertRaisesRegex(ReferenceError, 'binding changed'):
                bake.finish(token)
            self.assertEqual(bake.baked_image(grade), other)
            self.assertFalse(bake.states)
            bake.set_baked_image(grade, None)
            token = bake.start(grade); bake.poll()
            grade.id_data.nodes.remove(grade)
            self.assertIsNone(bake.finish(token))
            self.assertFalse(bake.states)

    def test_dirty_bound_image_rejects_rebake_without_losing_edits(self):
        with self._publication() as (grade, fake):
            fake.ready = True
            token = bake.start(grade); bake.poll(); image = bake.finish(token)
            image.pixels[0] = -.875
            self.assertTrue(image.is_dirty)
            before = self._pixels(image).copy()
            packed = bytes(image.packed_file.data)
            self.assertIsNone(bake.start(grade))
            self.assertEqual(bake.eligibility(grade)['code'], 'dirty')
            self.assertEqual(fake.starts, 1)
            self.assertEqual(bake.baked_image(grade), image)
            self.assertTrue(image.is_dirty)
            self.assertEqual(bytes(image.packed_file.data), packed)
            np.testing.assert_array_equal(self._pixels(image), before)
            bake.begin_replacement()
            reconcile_images()
            self.assertTrue(image.is_dirty)
            np.testing.assert_array_equal(self._pixels(image), before)

    @contextmanager
    def _no_content_inspection(self):
        # RNA properties bypass Python descriptors on bpy.types.Image. Wrap
        # just collection access while forwarding cache operations to the real
        # Images, so this premise exercises Blender's actual buffers_free().
        class NativeView:
            def __init__(self,value):self.value=value
            def __getattr__(self,name):
                if name in ('pixels','size','data'):
                    raise AssertionError('Recovery inspected native Image content')
                value=getattr(self.value,name)
                return NativeView(value) if name=='packed_file' and value is not None else value
        data=bpy.data
        class DataView:
            @property
            def images(self):return tuple(NativeView(image) for image in data.images)
            def __getattr__(self,name):return getattr(data,name)
        with patch.object(bpy,'data',new=DataView()):
            image=next(image for image in bpy.data.images if image.packed_file is not None)
            with self.assertRaisesRegex(AssertionError,'inspected native Image content'):_=image.pixels
            with self.assertRaisesRegex(AssertionError,'inspected native Image content'):_=image.packed_file.data
            yield

    def test_managed_revision_invalidates_without_inspecting_content(self):
        with self._publication() as (grade, fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            bake.begin_replacement()
            expected=self._restore_encoded_revision(image,fake)
            with self._no_content_inspection():
                self.assertTrue(reconcile_images())
            self.assertEqual(bake.recovery_outcomes[image.session_uid],'settled_invalidated')
            np.testing.assert_array_equal(self._pixels(image),expected)

    def test_invalidation_failure_retains_only_runtime_work_until_retry(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            bake.begin_replacement();expected=self._restore_encoded_revision(image,fake)
            with patch.object(bake,'publication_checkpoint',side_effect=RuntimeError('cache operation interrupted')):
                result=bake.runtime_reconcile()
            self.assertFalse(result['done']);self.assertIn('interrupted',result['error'])
            self.assertEqual(bake.recovery_states[image.session_uid]['store'].state.phase,'failed')
            with self._no_content_inspection():
                self.assertTrue(reconcile_images())
            self.assertFalse(bake.recovery_pending())
            np.testing.assert_array_equal(self._pixels(image),expected)

    def test_dirty_native_image_preserves_external_edit_and_settles_old_debt(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            bake.begin_replacement();self._restore_encoded_revision(image,fake)
            with patch.object(bake,'publication_checkpoint',side_effect=RuntimeError('cache operation interrupted')):
                self.assertTrue(bake.runtime_reconcile()['error'])
            image.pixels[0]=-.875;external=self._pixels(image).copy()
            packed=bytes(image.packed_file.data)
            with self._no_content_inspection(), patch.object(bake,'publication_checkpoint',side_effect=AssertionError('external Image invalidated')):
                self.assertTrue(reconcile_images())
            self.assertTrue(image.is_dirty)
            self.assertEqual(bytes(image.packed_file.data),packed)
            np.testing.assert_array_equal(self._pixels(image),external)
            self.assertEqual(bake.recovery_outcomes[image.session_uid],'settled_preserved')

    def test_repeated_pre_and_reentrant_replacement_keep_current_operation_fenced(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            bake.begin_replacement();expected=self._restore_encoded_revision(image,fake)
            bake.begin_replacement()
            calls=[]
            def reenter(phase):
                if not calls:
                    calls.append(phase);bake.begin_replacement()
            with patch.object(bake,'publication_checkpoint',new=reenter):
                self.assertIn('superseded',bake.runtime_reconcile()['error'])
            self.assertTrue(bake.recovery_pending())
            with self._no_content_inspection():self.assertTrue(reconcile_images())
            np.testing.assert_array_equal(self._pixels(image),expected)

    def test_native_replacement_does_not_restore_failed_publication_backup(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            self._rewrite_artifact(fake,5,3,(-.5,6.,.25,.5))
            native=bake.replace_packed;calls=[]
            def fail_restore(target,payload):
                calls.append(1)
                if len(calls)>1:raise RuntimeError('restore unavailable')
                native(target,payload)
            token=bake.start(grade);bake.poll();state=bake.states[token]
            with patch.object(bake,'replace_packed',new=fail_restore), patch.object(bake,'publication_checkpoint',side_effect=RuntimeError('publish interrupted')):
                with self.assertRaisesRegex(RuntimeError,'rollback requires repair'):bake.finish(token)
            packed=bytes(image.packed_file.data);metadata=self._metadata(image)
            extra=grade.node_tree.nodes.new('CompositorNodeRGB');extra.name='User native edit'
            with patch.object(bake,'replace_packed',side_effect=AssertionError('Recovery restored backup')):
                bake.begin_replacement()
                self.assertTrue(state['publication'].state.debt)
                self.assertTrue(state['physical_retired'])
                bake.retire_replaced_state();reconcile_images()
            self.assertFalse(bake.fenced_states)
            self.assertEqual(bytes(image.packed_file.data),packed)
            self.assertEqual(self._metadata(image),metadata)
            self.assertIn('User native edit',grade.node_tree.nodes)
            self.assertTrue(state['publication'].store.ref.closed)

    def test_replacement_and_physical_retirement_settle_independently(self):
        for physical_first in (False,True):
            with self.subTest(physical_first=physical_first),self._publication() as (grade,fake):
                fake.defer_retirement=True
                token=bake.start(grade);state=bake.states[token]
                bake.begin_replacement()
                self.assertIn(token,bake.fenced_states)
                if physical_first:
                    fake.pending_retirement.pop()()
                    self.assertIn(token,bake.fenced_states)
                    bake.retire_replaced_state()
                else:
                    bake.retire_replaced_state()
                    self.assertIn(token,bake.fenced_states)
                    fake.pending_retirement.pop()()
                self.assertNotIn(token,bake.fenced_states)
                self.assertTrue(state['workflow'].store.ref.closed)

    def test_completed_operation_ids_are_fresh_and_never_claim_pixel_validity(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            first=json.loads(image['_pg_bake_operation'])
            token=bake.start(grade);bake.poll();bake.finish(token)
            second=json.loads(image['_pg_bake_operation'])
            self.assertEqual((first['phase'],second['phase']),('COMPLETE','COMPLETE'))
            self.assertNotEqual(first['id'],second['id'])
            self.assertNotIn('_pg_bake_pixels_sha256',image)

    def test_rebake_uses_new_packed_bytes_when_external_path_keeps_old_pixels(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            external=Path(fake.artifact['path']).with_name('old-external.exr')
            old=bytes(image.packed_file.data);external.write_bytes(old)
            image.filepath_raw=str(external)
            self._rewrite_artifact(fake,3,2,(-.5,6.,.25,.5))
            encoded=Path(fake.artifact['path']).read_bytes()
            token=bake.start(grade);bake.poll();bake.finish(token)
            self.assertEqual(bytes(image.packed_file.data),encoded)
            np.testing.assert_array_equal(self._pixels(image),np.tile(np.float32((-.5,6.,.25,.5)),(2,3,1)))
            self.assertEqual(external.read_bytes(),old)

    def test_adopted_portable_group_can_select_and_rebake_without_rebuilding_graph(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            grade=_component('graph.grades').replace_node(grade,'CompositorNodeGroup')
            lut.adopt_native(grade,nodes.output_intent(grade))
            kernel=grade.node_tree
            native_nodes=tuple(item.as_pointer() for item in kernel.nodes)
            native_links=tuple((link.from_socket.as_pointer(),link.to_socket.as_pointer())
                               for link in kernel.links)
            self.assertEqual(grade.pg_bake_image,image)
            layout=BakeLayout();bake.draw_action(layout,grade)
            self.assertIn(('pg_bake_image',True),layout.controls)
            grade.pg_bake_image=None;self.assertIsNone(bake.baked_image(grade))
            grade.pg_bake_image=image
            token=bake.start(grade);bake.poll();self.assertEqual(bake.finish(token),image)
            self.assertEqual(grade.bl_idname,'CompositorNodeGroup')
            self.assertEqual(grade.node_tree,kernel)
            self.assertEqual(tuple(item.as_pointer() for item in kernel.nodes),native_nodes)
            self.assertEqual(tuple((link.from_socket.as_pointer(),link.to_socket.as_pointer())
                                  for link in kernel.links),native_links)
            self.assertTrue(lut.is_adopted(grade))

    def test_lut_commit_history_uses_the_same_content_free_image_reconciliation(self):
        with self._publication() as (grade,fake):
            fake.ready=True
            token=bake.start(grade);bake.poll();image=bake.finish(token)
            del image['_pg_bake_operation'];del image['_pg_bake_schema']
            image['_pg_payload_record']=json.dumps(dict(version=1,phase='COMPLETE',operation_id='a'*32))
            bake.begin_replacement();expected=self._restore_encoded_revision(image,fake)
            del image['_pg_bake_operation'];del image['_pg_bake_schema']
            image['_pg_payload_record']=json.dumps(dict(version=1,phase='COMPLETE',operation_id='b'*32))
            with self._no_content_inspection():self.assertTrue(reconcile_images())
            np.testing.assert_array_equal(self._pixels(image),expected)
            self.assertEqual(bake.recovery_outcomes[image.session_uid],'settled_invalidated')

    def test_incomplete_current_output_blocks_without_appending_storage(self):
        with self._publication() as (grade, fake):
            kernel = grade.node_tree
            kernel.nodes.remove(next(item for item in kernel.nodes if item.get('_pg_baked_image')))
            before = tuple(node.as_pointer() for node in kernel.nodes)
            self.assertEqual(bake.eligibility(grade)['code'], 'resources')
            self.assertIsNone(bake.start(grade))
            self.assertEqual(fake.starts, 0)
            self.assertEqual(tuple(node.as_pointer() for node in kernel.nodes), before)

    def test_copy_assignment_and_deletion_preserve_other_bake_nodes(self):
        tree = bpy.data.node_groups.new('Bake copy source', 'CompositorNodeTree')
        first = bpy.data.images.new('First bake', width=2, height=2, float_buffer=True)
        second = bpy.data.images.new('Second bake', width=2, height=2, float_buffer=True)
        for image in (first, second):
            image['_pg_bake_schema'] = 2; image['_pg_bake_storage'] = 'FLOAT_RGBA'; image['_pg_bake_kind'] = 'COMPOSITOR'
            image.pixels.foreach_set((0.,) * 16); image.update(); image.pack()
        source = bake.create_node(tree)
        source.pg_bake_image = first
        cloned_tree = tree.copy()
        clone = cloned_tree.nodes[source.name]
        self.assertEqual(clone.pg_bake_image, first)
        clone.pg_bake_image = second
        self.assertNotEqual(source.node_tree, clone.node_tree)
        self.assertEqual(source.node_tree.nodes['Baked Image'].image, first)
        self.assertEqual(clone.node_tree.nodes['Baked Image'].image, second)
        users = second.users
        cloned_tree.nodes.remove(clone)
        self.assertEqual(second.users, users - 1)
        self.assertEqual(source.node_tree.nodes['Baked Image'].image, first)

