"""The saved native node interface contains only user controls and results."""
import bpy

from tests.support.blender import BlenderTest
from tests.support.session import component, patch

nodes = component('graph.nodes')
grades = component('graph.grades')
stacks = component('graph.stacks')
lut = component('graph.lut')
spaces = component('graph.spaces')
bake = component('graph.bake')


class PublicInterfaceTests(BlenderTest):
    def fixtures(self):
        for tree_type in ('ShaderNodeTree', 'CompositorNodeTree'):
            for create in (nodes.create_grade, stacks.create):
                tree = bpy.data.node_groups.new('Public interface', tree_type)
                yield create(tree)

    def assert_public(self, node):
        shader = node.id_data.bl_idname == 'ShaderNodeTree'
        inputs = ['Color', 'Alpha'] if shader else ['Color']
        if nodes.is_grade(node):
            inputs.append('Color Reference')
        if shader:
            inputs.append('Vector')
        outputs = ['Color', 'Alpha', 'Baked Color', 'Baked Alpha'] if shader else ['Color', 'Baked Color']
        self.assertEqual([socket.name for socket in node.inputs], inputs)
        self.assertEqual([socket.name for socket in node.outputs], outputs)
        self.assertEqual([(field.in_out, field.name) for field in node.node_tree.interface.items_tree
                          if field.item_type == 'SOCKET'],
                         [('OUTPUT', name) for name in outputs] + [('INPUT', name) for name in inputs])

    def test_all_node_kinds_have_only_public_native_sockets(self):
        for node in self.fixtures():
            with self.subTest(kind=node.bl_idname):
                self.assert_public(node)
                self.assertTrue(nodes.resources_ready(node))
                self.assertEqual(len(spaces.read_rows(node)), 6)
                self.assertEqual(lut.resources.selected_index(node), -1)
                for socket in (*node.inputs, *node.outputs):
                    self.assertFalse(socket.hide)

    def test_portable_save_roundtrip_preserves_constants_links_visibility_and_image(self):
        for node in self.fixtures():
            tree, name, kernel = node.id_data, node.name, node.node_tree
            image = bpy.data.images.new('Saved Image pointer', width=1, height=1, float_buffer=True)
            with bake.binding_suppressed(node):
                node.pg_bake_image = image
            bake.materialize_binding(node)
            rows = ((.5, .25, .125), *spaces.read_rows(node)[1:])
            spaces.write_rows(node, rows)
            lut.resources.select_payload(node, 3)
            node.inputs['Color'].hide = True
            if tree.bl_idname == 'ShaderNodeTree':
                coordinates = tree.nodes.new('ShaderNodeTexCoord')
                tree.links.new(coordinates.outputs['UV'], node.inputs['Vector'])
                bake.sync_coordinates()
            links = tuple((link.from_socket.identifier, link.to_socket.identifier) for link in tree.links)
            lut.adopt_native(node, nodes.output_intent(node))
            with patch.object(lut, 'ensure', side_effect=AssertionError('Save recomputed adopted output')):
                grades.prepare_save()
                portable = tree.nodes[name]
                self.assertIn(portable.bl_idname, ('ShaderNodeGroup', 'CompositorNodeGroup'))
                self.assert_public(portable)
                self.assertEqual(portable.pg_bake_image, image)
                self.assertTrue(portable.inputs['Color'].hide)
                grades.finish_save()
            restored = tree.nodes[name]
            self.assert_public(restored)
            self.assertEqual(restored.node_tree, kernel)
            self.assertEqual(restored.pg_bake_image, image)
            self.assertEqual(bake.baked_image(restored), image)
            self.assertEqual(spaces.read_rows(restored), rows)
            self.assertEqual(lut.resources.selected_index(restored), 3)
            self.assertTrue(restored.inputs['Color'].hide)
            self.assertEqual(tuple((link.from_socket.identifier, link.to_socket.identifier)
                                  for link in tree.links), links)

    def test_saved_wrapper_metadata_restores_controls_only_after_adoption(self):
        for node in self.fixtures():
            tree, name, kind, kernel = node.id_data, node.name, node.bl_idname, node.node_tree
            if nodes.is_grade(node):
                grade = grades.ensure(node)
            else:
                grade = bpy.data.node_groups.new('Saved Stack Grade', grades.PGGradeData.bl_idname)
                grade[grades.TAG] = grades.SCHEMA
                grades.assign_values(grade, grades.defaults())
                with grades.guarded(node):
                    item = node.pg_stack_entries.add()
                    item.grade = grade; item.key = 'saved'
                stacks.bind_dependencies(node)
            image = bpy.data.images.new('Saved destination', width=1, height=1, float_buffer=True)
            with bake.binding_suppressed(node):node.pg_bake_image = image
            bake.materialize_binding(node)
            node.inputs['Color'].hide = True
            dependency = tree.animation_data.drivers[0]
            dependency.mute = True
            lut.adopt_native(node, nodes.output_intent(node))
            grades.prepare_save()
            portable = tree.nodes[name]
            self.assertEqual(grades.wrapper_plan(portable), (kind, True))
            self.assertIn(grades.WRAPPER_STATE, portable)
            grades.recover_flags()  # Serialization creates a later Session/recovery.
            nodes.undo_redo_pre_handler(); nodes.reset_cache_handler()
            phases = []
            with patch.object(lut, 'ensure', side_effect=AssertionError('Restoration recomputed output')), \
                    patch.object(lut, 'validate_output', side_effect=AssertionError('Restoration validated output')):
                for _ in range(100):
                    phases.append(nodes.recovery_status()['state'])
                    if phases[-1] in ('completed', 'failed'):break
                    nodes.recovery_tick()
            self.assertEqual(nodes.recovery_status()['state'], 'completed', nodes.recovery_status())
            self.assertIn('restoring', phases)
            restored = tree.nodes[name]
            self.assertEqual(restored.bl_idname, kind)
            self.assertTrue(restored.show_options)
            self.assertNotIn(grades.WRAPPER_STATE, restored)
            self.assertEqual(restored.node_tree, kernel)
            self.assertEqual(restored.pg_bake_image, image)
            self.assertTrue(restored.inputs['Color'].hide)
            self.assertTrue(tree.animation_data.drivers[0].mute)
            self.assertTrue(lut.is_adopted(restored))
            self.assertEqual(restored.pg_grade if nodes.is_grade(restored)
                             else restored.pg_stack_entries[0].grade, grade)

    def test_unmarked_native_wrapper_has_no_restoration_authority(self):
        node = next(self.fixtures())
        tree, name = node.id_data, node.name
        lut.adopt_native(node, nodes.output_intent(node))
        grades.representations(portable=True)
        node = tree.nodes[name]
        del node[grades.WRAPPER_STATE]
        pointer = node.as_pointer()
        self.assertIsNone(grades.wrapper_plan(node))
        self.assertEqual(grades.restore_wrapper(node).as_pointer(), pointer)
        self.assertEqual(node.bl_idname, 'ShaderNodeGroup')
        grades.prepare_save(); grades.finish_save()
        self.assertEqual(tree.nodes[name].as_pointer(), pointer)
        self.assertEqual(tree.nodes[name].bl_idname, 'ShaderNodeGroup')
        self.assertNotIn(grades.WRAPPER_STATE, tree.nodes[name])

    def test_inline_control_revision_tracks_reverts_but_excludes_presentation(self):
        node = next(self.fixtures())
        self.assertIsNone(node.pg_grade)
        first = nodes.observe_intent(node)
        node.name = 'Renamed'; node.location = (250, 80)
        node.pg_chromatic.family = 'WARP'
        self.assertEqual(nodes.observe_intent(node), first)
        before = grades.snapshot(node)
        with grades.guarded(node):node.pg_chromatic.global_gain = .2
        second = nodes.observe_intent(node)
        self.assertGreater(second, first)
        grades.assign_values(node, before)
        third = nodes.observe_intent(node)
        self.assertGreater(third, second)
        self.assertIsNone(node.pg_grade)

    def test_malformed_saved_wrapper_is_a_recovery_error_without_mutation(self):
        node = next(self.fixtures())
        tree, name = node.id_data, node.name
        grades.representations(portable=True)
        node = tree.nodes[name]
        node[grades.WRAPPER_STATE] = '{invalid'
        pointer, kernel = node.as_pointer(), node.node_tree
        with self.assertRaisesRegex(RuntimeError, 'metadata is invalid'):
            grades.wrapper_plan(node)
        self.assertEqual(node.as_pointer(), pointer)
        self.assertEqual(node.node_tree, kernel)
        with self.assertRaisesRegex(RuntimeError, 'metadata is invalid'):
            grades.prepare_save()
        self.assertEqual(tree.nodes[name].as_pointer(), pointer)

    def test_failed_portable_save_restores_custom_node_and_removes_marker(self):
        for node in self.fixtures():
            grades.ensure(node) if nodes.is_grade(node) else None
            tree, name, kind = node.id_data, node.name, node.bl_idname
            scheduler = component('graph.scheduler')
            with patch.object(scheduler, 'wake', side_effect=RuntimeError('serialization setup failed')):
                with self.assertRaisesRegex(RuntimeError, 'serialization setup failed'):
                    grades.prepare_save()
            restored = tree.nodes[name]
            self.assertEqual(restored.bl_idname, kind)
            self.assertNotIn(grades.WRAPPER_STATE, restored)
            self.assertFalse(grades._saving)

    def test_kernel_assignment_preserves_only_the_canonical_image_destination(self):
        for node in self.fixtures():
            source=next(item for item in node.node_tree.nodes if item.get('_pg_baked_image'))
            foreign=bpy.data.images.new('Foreign Image destination',width=1,height=1,float_buffer=True)
            source.image=foreign
            candidate=lut.clone_kernel(node.node_tree)
            source.image=None
            previous=node.node_tree
            nodes.assign_kernel(node,candidate)
            self.assertIsNone(node.pg_bake_image)
            self.assertIsNone(next(item for item in candidate.nodes if item.get('_pg_baked_image')).image)
            own=bpy.data.images.new('Canonical Image destination',width=1,height=1,float_buffer=True)
            with bake.binding_suppressed(node):node.pg_bake_image=own
            bake.materialize_binding(node)
            replacement=lut.clone_kernel(previous)
            nodes.assign_kernel(node,replacement)
            self.assertEqual(node.pg_bake_image,own)
            self.assertEqual(next(item for item in replacement.nodes if item.get('_pg_baked_image')).image,own)

    def test_unsupported_layout_is_not_managed_or_rebuilt(self):
        for node in self.fixtures():
            kernel = node.node_tree
            kernel[lut.resources.LAYOUT_KEY] = -1
            before = (kernel, len(bpy.data.node_groups), len(bpy.data.images))
            self.assertFalse(nodes.is_grade(node) or stacks.is_stack(node))
            self.assertFalse(nodes.resources_ready(node))
            with self.assertRaisesRegex(ValueError, 'Unsupported or incomplete'):
                nodes.prepare_output_resources(node)
            nodes.refresh_all()
            self.assertEqual((node.node_tree, len(bpy.data.node_groups), len(bpy.data.images)), before)

    def test_shared_kernel_constants_cannot_be_published_by_one_owner(self):
        for node in self.fixtures():
            tree = node.id_data
            second = tree.nodes.new('ShaderNodeGroup' if tree.bl_idname == 'ShaderNodeTree'
                                    else 'CompositorNodeGroup')
            second.node_tree = node.node_tree
            before = lut._graph_snapshot(node)
            with self.assertRaisesRegex(RuntimeError, 'private writable'):
                lut.commit_endpoint_rows(node, ((2., 0., 0.), (0., 1., 0.), (0., 0., 1.)),
                                         ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
            self.assertEqual(lut._graph_snapshot(node), before)
            self.assertEqual(spaces.read_rows(second), before['rows'])
