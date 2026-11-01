"""Small native API assumptions exercised by ownership behavior tests.

These fixtures perform isolated native operations. They do not bake LUTs,
dispatch scope analysis, or repeat extension lifecycle sequences.
"""
from tests.support.session import component as _component, SessionTest, patch
import bpy
from pathlib import Path
import tempfile
pass

grades = _component('graph.grades'); stacks = _component('graph.stacks')
transactions = _component('ownership.transactions')
from tests.support.blender import BlenderTest, grade_data


class NativeOwnershipPremises(BlenderTest):
    def test_native_timer_removal_retires_its_arena_reference(self):
        ownership = _component('ownership')
        remove_timer = self.session.app.blender.native.remove_timer
        manager = bpy.context.window_manager
        timer = manager.event_timer_add(60., window=bpy.context.window)
        ref = ownership.retain(timer, 'native.timer.premise')
        remove_timer(manager, timer)
        self.assertIsNone(ownership.resolve(ref))

    def test_native_keymap_item_removal_retires_its_arena_reference(self):
        ownership = _component('ownership')
        remove_keymap_item = self.session.app.blender.native.remove_keymap_item
        config = bpy.context.window_manager.keyconfigs.addon
        keymap = config.keymaps.new(name='Native keymap ownership premise', space_type='NODE_EDITOR')
        try:
            item = keymap.keymap_items.new('perceptual_grade.diagram_drag', 'LEFTMOUSE', 'PRESS')
            ref = ownership.retain(item, 'native.keymap.premise')
            remove_keymap_item(keymap, item)
            self.assertIsNone(ownership.resolve(ref))
        finally:
            config.keymaps.remove(keymap)

    def fixture(self):
        tree = bpy.data.node_groups.new('Native ownership premise', 'CompositorNodeTree')
        node = tree.nodes.new('CompositorNodeGroup')
        grade = grade_data()
        return tree, node, grade

    def test_pointer_occurrences_fake_user_and_driver_dependency(self):
        tree, node, grade = self.fixture()
        self.assertEqual(grade.users, 0)
        grade.use_fake_user = True
        self.assertEqual(grade.users, 1)
        node.pg_grade = grade
        self.assertEqual(grade.users, 2)
        for _ in range(2):
            node.pg_stack_entries.add().grade = grade
        self.assertEqual(grade.users, 4)
        node['dependency'] = 0.
        driver = node.driver_add('["dependency"]').driver
        variable = driver.variables.new()
        variable.type = 'SINGLE_PROP'
        variable.targets[0].id_type = 'NODETREE'
        variable.targets[0].id = grade
        variable.targets[0].data_path = '["' + grades.MATRIX + '"][0]'
        self.assertEqual(grade.users, 4)  # Driver targets do not own counted users.
        node.pg_stack_entries.clear()
        self.assertEqual(grade.users, 2)
        node.pg_grade = None
        self.assertEqual(grade.users, 1)
        grade.use_fake_user = False
        self.assertEqual(grade.users, 0)

    def test_tree_copy_and_whole_tree_removal_account_for_native_properties(self):
        tree, node, grade = self.fixture()
        node.pg_grade = grade
        node.pg_stack_entries.add().grade = grade
        self.assertEqual(grade.users, 2)
        copied = tree.copy()
        self.assertEqual(grade.users, 4)
        bpy.data.node_groups.remove(copied)
        self.assertEqual(grade.users, 2)
        bpy.data.node_groups.remove(tree)
        self.assertEqual(grade.users, 0)

    def test_individual_native_node_removal_requires_explicit_custom_pointer_release(self):
        tree, node, grade = self.fixture()
        node.pg_grade = grade
        node.pg_stack_entries.add().grade = grade
        self.assertEqual(grade.users, 2)
        # Exercise the sanctioned explicit release before native node removal.
        grades.release_node_references(node)
        self.assertEqual(grade.users, 0)
        tree.nodes.remove(node)
        self.assertEqual(grade.users, 0)

    def test_native_individual_node_removal_does_not_release_extension_pointers(self):
        tree, node, grade = self.fixture()
        node.pg_grade = grade
        node.pg_stack_entries.add().grade = grade
        tree.nodes.remove(node)
        self.assertEqual(grade.users, 2)
        # This isolated premise intentionally demonstrates Blender's missing
        # decrement. Explicit ID removal disposes of the fixture; production
        # never repairs this with user_clear or manual user-count writes.
        bpy.data.node_groups.remove(grade)

    def test_kernel_assignment_after_init_and_copy_callback_account_once(self):
        tree = bpy.data.node_groups.new('Callback ownership premise', 'CompositorNodeTree')
        kernel = bpy.data.node_groups.new('Kernel premise', 'CompositorNodeTree')
        node = tree.nodes.new(grades.KINDS['CompositorNodeTree'])
        self.assertIsNone(node.node_tree)
        self.assertTrue(node.get('_pg_pending_init'))
        node.node_tree = kernel
        self.assertEqual(kernel.users, 1)
        copied = tree.copy()
        self.assertEqual(kernel.users, 2)
        self.assertTrue(copied.nodes[node.name].get('_pg_pending_copy'))
        bpy.data.node_groups.remove(copied)
        self.assertEqual(kernel.users, 1)
        tree.nodes.remove(node)
        self.assertEqual(kernel.users, 0)

    def test_discovery_never_initializes_generic_custom_nodes(self):
        nodes = _component('graph.nodes')
        tree = bpy.data.node_groups.new('Deferred initialization premise', 'ShaderNodeTree')
        node = tree.nodes.new(grades.KINDS['ShaderNodeTree'])
        before = (len(bpy.data.node_groups), len(bpy.data.images))
        nodes.refresh_all()
        self.assertIsNone(node.node_tree)
        self.assertEqual(before, (len(bpy.data.node_groups), len(bpy.data.images)))
        self.assertEqual(nodes.resource_action(node), 'initialize')
        nodes.prepare_output_resources(node)
        self.assertTrue(nodes.is_grade(node))
        self.assertIsNone(nodes.resource_action(node))

    def test_initialization_refresh_failure_keeps_structural_result_undoable(self):
        from types import SimpleNamespace
        nodes = _component('graph.nodes'); output_resources = _component('graph.output_resources')
        tree = bpy.data.node_groups.new('Initialization failure premise', 'ShaderNodeTree')
        node = tree.nodes.new(grades.KINDS['ShaderNodeTree'])
        reports = []
        operator = SimpleNamespace(report=lambda kind, message: reports.append((kind,message)))
        context = SimpleNamespace(pg_node=node)
        with patch.object(nodes,'refresh_node',side_effect=RuntimeError('Refresh after allocation failed')):
            result = grades.PG_OT_prepare_output.execute(operator,context)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(len(output_resources.bank_images(node)),4)
        self.assertEqual(node.node_tree.users,1)
        self.assertFalse(reports)
        self.assertEqual(_component('integration.outcomes').get(node, 'resources').code, 'outcome.failed')

    def test_individual_native_duplicate_has_private_output_before_return(self):
        nodes = _component('graph.nodes')
        tree = bpy.data.node_groups.new('Individual duplicate premise', 'ShaderNodeTree')
        node = nodes.create_grade(tree)
        original = node.node_tree
        area = bpy.context.screen.areas[0]
        previous = area.type
        try:
            area.type = 'NODE_EDITOR'
            area.spaces.active.tree_type = 'ShaderNodeTree'
            area.spaces.active.path.start(tree)
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                self.assertEqual(bpy.ops.node.duplicate(), {'FINISHED'})
            copied = next(item for item in tree.nodes if item != node)
            self.assertNotEqual(copied.node_tree, original)
            self.assertEqual((original.users, copied.node_tree.users), (1, 1))
            first = {item.image.as_pointer() for item in original.nodes if item.get('_pg_cube_image')}
            second = {item.image.as_pointer() for item in copied.node_tree.nodes if item.get('_pg_cube_image')}
            self.assertEqual((len(first), len(second)), (4, 4))
            self.assertFalse(first & second)
            self.assertIsNone(nodes.resource_action(copied))
            tree.nodes.remove(copied)
            self.assertEqual(original.users, 1)
        finally:
            area.type = previous

    def test_whole_tree_copy_requires_explicit_independence_for_both_publishers(self):
        nodes = _component('graph.nodes')
        tree = bpy.data.node_groups.new('Whole tree duplicate premise', 'ShaderNodeTree')
        node = nodes.create_grade(tree)
        kernel = node.node_tree
        copied_tree = tree.copy()
        copied = copied_tree.nodes[node.name]
        self.assertEqual(kernel.users, 2)
        before = len(bpy.data.images)
        nodes.refresh_all()
        self.assertEqual(copied.node_tree, kernel)
        self.assertEqual(len(bpy.data.images), before)
        self.assertEqual(nodes.resource_action(node), 'independent')
        self.assertEqual(nodes.resource_action(copied), 'independent')
        nodes.prepare_output_resources(copied)
        self.assertNotEqual(copied.node_tree, kernel)
        self.assertEqual((kernel.users, copied.node_tree.users), (1, 1))
        self.assertIsNone(nodes.resource_action(node))
        self.assertIsNone(nodes.resource_action(copied))


    def test_private_kernel_with_linked_bank_requires_explicit_local_copy(self):
        nodes = _component('graph.nodes'); output_resources = _component('graph.output_resources'); output_guard = _component('graph.output_guard')
        tree = bpy.data.node_groups.new('Borrowed bank premise', 'CompositorNodeTree')
        node = nodes.create_grade(tree)
        bank = output_resources.bank_images(node)[0]
        bank.pack()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'bank.blend')
            bpy.data.libraries.write(path, {bank})
            with bpy.data.libraries.load(path, link=True) as (source, loaded):
                loaded.images = [bank.name]
            borrowed = loaded.images[0]
            self.assertIsNotNone(borrowed.library)
            for item in node.node_tree.nodes:
                if item.get('_pg_cube_image') and item.get(output_resources.SLOT) == 0:
                    item.image = borrowed
            self.assertTrue(output_resources.unique_owner(node))
            self.assertFalse(output_resources.writable_banks(node))
            self.assertEqual(nodes.resource_action(node), 'independent')
            with output_guard.publication(), self.assertRaisesRegex(RuntimeError, 'linked or evaluated'):
                output_resources.reserve(node, 33, 'borrowed payload')
            before = borrowed.pixels[:]
            output_resources.pack_output(node)
            nodes.prepare_output_resources(node)
            self.assertTrue(output_resources.writable_banks(node))
            self.assertIsNone(nodes.resource_action(node))
            self.assertNotIn(borrowed, output_resources.bank_images(node).values())
            self.assertEqual(before, borrowed.pixels[:])

    def test_id_copy_shares_action_until_explicit_action_copy(self):
        grade = grade_data()
        grade.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=1)
        original_action = grade.animation_data.action
        copied = grade.copy()
        self.assertEqual(copied.animation_data.action, original_action)
        copied.animation_data.action = copied.animation_data.action.copy()
        self.assertNotEqual(copied.animation_data.action, original_action)
        self.assertEqual(original_action.users, 1)

    def animated_selector(self):
        tree, node, grade = self.fixture()
        grade.use_fake_user = True
        node.pg_grade = grade
        grades.bind_animation_dependency(node)
        grade.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=1)
        action = grade.animation_data.action
        action.use_fake_user = True
        return tree, node, grade, action

    def test_grade_creation_commits_independent_action_and_counted_selector(self):
        tree, node, old, old_action = self.animated_selector()
        created = grades.new(node)
        self.assertEqual(node.pg_grade, created)
        self.assertEqual((old.users, created.users), (1, 2))
        self.assertNotEqual(created.animation_data.action, old_action)
        self.assertEqual(old_action.users, 2)
        self.assertEqual(created.animation_data.action.users,
                         1 + int(created.animation_data.action.use_fake_user))
        self.assertFalse(transactions.pending())
        self.assertNotIn(transactions.RECORDS, tree)

    def test_grade_creation_compensates_each_effect_including_lost_allocation_results(self):
        tree, node, old, old_action = self.animated_selector()
        original_groups = {value.session_uid for value in bpy.data.node_groups}
        original_actions = {value.session_uid for value in bpy.data.actions}
        original_values = grades.snapshot(node)
        original_apply = transactions.Transaction.apply
        for phase in ('grade_allocate', 'grade_action_allocate', 'grade_action_assign',
                      'grade_fake_user', 'grade_selector_and_dependency', 'grade_node_values'):
            with self.subTest(phase=phase):
                def interrupted(transaction, name, *args, **kwargs):
                    result = original_apply(transaction, name, *args, **kwargs)
                    if name == phase: raise RuntimeError('Interrupted Grade creation: ' + name)
                    return result
                with patch.object(transactions.Transaction, 'apply', interrupted):
                    with self.assertRaisesRegex(RuntimeError, 'Interrupted Grade creation'):
                        grades.new(node)
                self.assertEqual(node.pg_grade, old)
                self.assertEqual(grades.snapshot(node), original_values)
                self.assertEqual((old.users, old_action.users), (2, 2))
                self.assertEqual({value.session_uid for value in bpy.data.node_groups}, original_groups)
                self.assertEqual({value.session_uid for value in bpy.data.actions}, original_actions)
                self.assertFalse(transactions.pending())
                self.assertNotIn(transactions.RECORDS, tree)

    def test_grade_creation_failed_selector_compensation_keeps_allocations_until_repair(self):
        tree, node, old, old_action = self.animated_selector()
        groups = {value.session_uid for value in bpy.data.node_groups}
        actions = {value.session_uid for value in bpy.data.actions}
        with patch.object(grades, 'sync_node', side_effect=RuntimeError('Interrupted Grade values')), \
             patch.object(grades, '_restore_grade_selector', side_effect=RuntimeError('Selector restore failed')):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted Grade values'):
                grades.new(node)
        self.assertTrue(transactions.pending())
        self.assertIn(transactions.RECORDS, tree)
        self.assertNotEqual(node.pg_grade, old)
        self.assertEqual(len(bpy.data.node_groups), len(groups) + 1)
        self.assertEqual(len(bpy.data.actions), len(actions) + 1)
        with self.assertRaisesRegex(RuntimeError, 'repair is still pending'):
            transactions.require_clean()
        transactions.repair_all()
        self.assertEqual(node.pg_grade, old)
        self.assertEqual((old.users, old_action.users), (2, 2))
        self.assertEqual({value.session_uid for value in bpy.data.node_groups}, groups)
        self.assertEqual({value.session_uid for value in bpy.data.actions}, actions)
        self.assertFalse(transactions.pending())

    def test_copied_action_fake_user_and_native_owner_release(self):
        grade = grade_data()
        grade.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=1)
        action = grade.animation_data.action
        action.use_fake_user = True
        copied_grade = grade.copy()
        self.assertEqual(action.users, 3)
        copied_action = action.copy()
        copied_grade.animation_data.action = copied_action
        self.assertEqual(action.users, 2)
        copied_action.use_fake_user = True
        self.assertEqual(copied_action.users, 2)
        bpy.data.node_groups.remove(copied_grade)
        self.assertEqual(copied_action.users, 1)
        copied_action.use_fake_user = False
        self.assertEqual(copied_action.users, 0)
        bpy.data.actions.remove(copied_action)
        self.assertEqual(action.users, 2)

    def test_saved_grade_creation_debt_cannot_authorize_native_mutation(self):
        tree, node, old, old_action = self.animated_selector()
        tree.use_fake_user = True
        names = tree.name, node.name, old.name, old_action.name
        with patch.object(grades, 'sync_node', side_effect=RuntimeError('Interrupted Grade values')), \
             patch.object(grades, '_restore_grade_selector', side_effect=RuntimeError('Selector restore failed')):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted Grade values'):
                grades.new(node)
        # Preserve the detached Action so reopening can verify that saved debt
        # does not authorize retiring native allocations.
        allocated_action = next(action for action in bpy.data.actions if action != old_action)
        allocated_action.use_fake_user = True
        created_names = node.pg_grade.name, allocated_action.name
        del allocated_action
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dirty-grade-creation.blend'
            with patch.object(grades, '_restore_grade_selector', side_effect=RuntimeError('Selector restore failed')):
                self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False), {'FINISHED'})
            self.assertTrue(transactions.pending())
            self.assertIn(transactions.RECORDS, tree)
            del tree, node, old, old_action
            self.assertEqual(bpy.ops.wm.open_mainfile(filepath=str(path)), {'FINISHED'})
            tree = bpy.data.node_groups[names[0]]
            node = tree.nodes[names[1]]
            old = bpy.data.node_groups[names[2]]
            old_action = bpy.data.actions[names[3]]
            self.assertEqual(node.pg_grade.name, created_names[0])
            self.assertIn(created_names[0], bpy.data.node_groups)
            self.assertIn(created_names[1], bpy.data.actions)
            self.assertFalse(transactions.pending())
            self.assertIn(transactions.RECORDS, tree)

    def test_link_replacement_does_not_change_datablock_user_counts(self):
        tree, first, grade = self.fixture()
        kernel = bpy.data.node_groups.new('Socket premise', 'CompositorNodeTree')
        kernel.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        kernel.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        first.node_tree = kernel
        second = tree.nodes.new('CompositorNodeGroup')
        second.node_tree = kernel
        edge = tree.links.new(first.outputs['Color'], second.inputs['Color'])
        self.assertEqual(kernel.users, 2)
        source_name, target_name = edge.from_socket.name, edge.to_socket.name
        tree.links.remove(edge)
        edge = tree.links.new(first.outputs[source_name], second.inputs[target_name])
        self.assertEqual(kernel.users, 2)
        self.assertEqual((edge.from_node, edge.to_node), (first, second))

    def test_native_rename_remaps_paths_and_node_removal_discards_its_curves(self):
        tree, node, grade = self.fixture()
        kernel = bpy.data.node_groups.new('Animated socket premise', 'CompositorNodeTree')
        kernel.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
        node.node_tree = kernel
        node.inputs['Color'].keyframe_insert(data_path='default_value', frame=1)
        node.name = 'Renamed native owner'
        curves = list(grades.owner_curves(tree))
        self.assertEqual(len(curves), 4)
        self.assertTrue(all(curve.data_path.startswith(node.path_from_id()) for curve in curves))
        del curves
        tree.nodes.remove(node)
        self.assertEqual(list(grades.owner_curves(tree)), [])

    def test_evaluated_nodes_borrow_custom_references_without_counted_users(self):
        material = bpy.data.materials.new('Evaluated reference premise')
        material.use_nodes = True
        node = material.node_tree.nodes.new('ShaderNodeGroup')
        stack = material.node_tree.nodes.new('ShaderNodeGroup')
        grade = grade_data()
        grade.use_fake_user = True
        node.pg_grade = grade
        for _ in range(2): stack.pg_stack_entries.add().grade = grade
        mesh = bpy.data.meshes.new('Evaluated reference premise')
        obj = bpy.data.objects.new('Evaluated reference premise', mesh)
        bpy.context.scene.collection.objects.link(obj)
        mesh.materials.append(material)
        evaluated = material.evaluated_get(bpy.context.evaluated_depsgraph_get())
        copied_node = evaluated.node_tree.nodes[node.name]
        copied_stack = evaluated.node_tree.nodes[stack.name]
        borrowed_grade = copied_node.pg_grade
        borrowed_entries = stacks.entries(copied_stack)
        self.assertTrue(copied_node.id_data.is_evaluated)
        self.assertTrue(copied_stack.id_data.is_evaluated)
        self.assertEqual(grade.users, 4)
        grades.release_node_references(copied_node)
        grades.release_node_references(copied_stack)
        self.assertEqual(copied_node.pg_grade, borrowed_grade)
        self.assertEqual(stacks.entries(copied_stack), borrowed_entries)
        self.assertEqual(grade.users, 4)

    def test_saved_dirty_snapshot_is_not_replayed_after_native_reopen(self):
        tree, node, grade = self.fixture()
        tree.use_fake_user = grade.use_fake_user = True
        for index in range(2):
            entry = node.pg_stack_entries.add()
            entry.grade = grade
            entry.key = str(index)
        del entry
        values = stacks.entries(node)
        real = stacks._write_entries
        def interrupted(target, replacement):
            real(target, replacement[:1])
            raise RuntimeError('Interrupted native assignment')
        with patch.object(stacks, '_write_entries', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted native assignment'):
                stacks.assign(node, values[:1])
        self.assertTrue(transactions.pending())
        self.assertIn(transactions.RECORDS, tree)
        names = tree.name, node.name, grade.name
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dirty-ownership.blend'
            # Blender may complete native Save despite a pre-handler error.
            # The durable obligation must therefore be part of the file.
            with patch.object(stacks, '_write_entries', side_effect=interrupted):
                self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False), {'FINISHED'})
            self.assertIn(transactions.RECORDS, tree)
            del tree, node, grade, values
            self.assertEqual(bpy.ops.wm.open_mainfile(filepath=str(path)), {'FINISHED'})
            tree = bpy.data.node_groups[names[0]]
            node = tree.nodes[names[1]]
            grade = bpy.data.node_groups[names[2]]
            self.assertFalse(transactions.pending())
            self.assertIn(transactions.RECORDS, tree)
            self.assertEqual([entry.grade for entry in node.pg_stack_entries], [grade])
            self.assertEqual(grade.users, 2)

    def test_copied_dirty_tree_has_no_live_compensation_authority(self):
        tree, node, grade = self.fixture()
        grade.use_fake_user = True
        for _ in range(2): node.pg_stack_entries.add().grade = grade
        values = stacks.entries(node)
        real = stacks._write_entries
        def interrupted(target, replacement):
            real(target, replacement[:1])
            raise RuntimeError('Interrupted copied ownership')
        with patch.object(stacks, '_write_entries', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted copied ownership'):
                stacks.assign(node, values[:1])
        copied = tree.copy()
        transactions.repair_all()
        self.assertFalse(transactions.pending())
        self.assertNotIn(transactions.RECORDS, tree)
        self.assertIn(transactions.RECORDS, copied)
        self.assertEqual(len(node.pg_stack_entries), 2)
        self.assertEqual(len(copied.nodes[node.name].pg_stack_entries), 1)
        self.assertEqual(grade.users, 4)

    def test_native_creation_exposes_callback_failure_as_a_returned_node(self):
        class FailingInit(bpy.types.Node):
            bl_idname = 'PGOwnershipFailingInit'
            bl_label = 'Ownership native premise'
            def init(self, context):
                self['entered_init'] = True
                raise RuntimeError('Expected native init callback failure')
        tree = bpy.data.node_groups.new('Creation premise', 'CompositorNodeTree')
        bpy.utils.register_class(FailingInit)
        try:
            with self.assertRaises(RuntimeError): tree.nodes.new('PGOwnershipMissingType')
            self.assertEqual(len(tree.nodes), 0)
            node = tree.nodes.new(FailingInit.bl_idname)
            self.assertTrue(node.get('entered_init'))
            self.assertEqual(len(tree.nodes), 1)
            tree.nodes.remove(node)
        finally:
            bpy.utils.unregister_class(FailingInit)
