"""Real Blender ID ownership across portable saves and node deletion."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
pass

import bpy
from color_tools import perceptual_grade_blender as addon
grades = _component('graph.grades'); gpu = _component('graph.gpu'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks')
from tests.support.blender import BlenderTest, sequence


from tests.blender.ownership_support import OwnershipFixture
transactions = _component('ownership.transactions')


class OwnershipTests(OwnershipFixture):
    def test_edge_multiplicity_preserves_typed_nested_identities(self):
        edges = (3, 3, '3', ('node', 3), ('node', '3'), None)
        for selected, expected in ((3, 2), ('3', 1), (('node', 3), 1),
                                   (('node', '3'), 1), (None, 1), ('missing', 0)):
            with self.subTest(selected=selected):
                self.assertEqual(transactions.edge_count(edges, selected), expected)

    def test_saved_repair_records_never_authorize_runtime_compensation(self):
        tree = bpy.data.node_groups.new('Authored native graph', 'CompositorNodeTree')
        tree[transactions.RECORDS] = 'historical data is not an executable command'
        before = dict(tree.items())
        transactions._discovered = None
        with patch.object(transactions, 'trees', side_effect=AssertionError('Historical journal scan')):
            transactions.discover()
            transactions.require_clean()
        self.assertEqual(dict(tree.items()), before)

    def test_native_replacement_retires_old_compensation_without_native_writes(self):
        ownership = _component('ownership')
        tree = bpy.data.node_groups.new('Replacement owns the graph', 'CompositorNodeTree')
        tx = transactions.Transaction('driver', {'tree': transactions.id_key(tree)})
        tx.apply('authored', lambda: tree.__setitem__('authored', 'new'),
                 lambda: tree.__setitem__('authored', 'old'))
        journal = tree[transactions.RECORDS]
        self.assertTrue(transactions.pending())
        ownership.begin_boundary()
        tokens = ownership.native_replaced()
        try:
            transactions.native_replaced(tokens)
            self.assertFalse(tx.rollback())
            self.assertEqual(tree['authored'], 'new')
            self.assertEqual(tree[transactions.RECORDS], journal)
            self.assertFalse(transactions.pending())
        finally:
            tx.close()
            ownership.recovered(tokens)

    def test_created_node_is_adopted_for_compensation_when_result_delivery_fails(self):
        tree, grade = self.graph('CompositorNodeTree')
        original = next(node for node in tree.nodes if nodes.is_grade(node))
        expected = self.graph_state(tree)
        real = transactions.Transaction.apply
        def lose_result(transaction, name, *args, **kwargs):
            result = real(transaction, name, *args, **kwargs)
            if name == 'replacement_create': raise RuntimeError('Lost native creation result')
            return result
        with patch.object(transactions.Transaction, 'apply', new=lose_result):
            with self.assertRaisesRegex(RuntimeError, 'Lost native creation result'):
                grades.replace_node(original, 'CompositorNodeGroup')
        self.assertEqual(self.graph_state(tree), expected)
        self.assertEqual(grade.users, 5)
        self.assertFalse(transactions.pending())

    def test_ambiguous_creation_retains_debt_without_deleting_unknown_nodes(self):
        tree, grade = self.graph('CompositorNodeTree')
        original = next(node for node in tree.nodes if nodes.is_grade(node))
        expected = self.graph_state(tree)
        real = transactions.Transaction.apply
        other_name = None
        def ambiguous(transaction, name, *args, **kwargs):
            nonlocal other_name
            result = real(transaction, name, *args, **kwargs)
            if name == 'replacement_create':
                other_name = tree.nodes.new('CompositorNodeGroup').name
                raise RuntimeError('Ambiguous native creation result')
            return result
        with patch.object(transactions.Transaction, 'apply', new=ambiguous):
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous native creation result'):
                grades.replace_node(original, 'CompositorNodeGroup')
        self.assertTrue(transactions.pending())
        self.assertEqual(len(tree.nodes), 5)
        tree.nodes.remove(tree.nodes[other_name])
        transactions.repair_all()
        self.assertEqual(self.graph_state(tree), expected)
        self.assertEqual(grade.users, 5)
        self.assertFalse(transactions.pending())

    def test_partial_link_removal_is_compensated(self):
        tree, grade = self.graph('CompositorNodeTree')
        original = next(node for node in tree.nodes if nodes.is_grade(node)
                        and any(link.to_node == node for link in tree.links))
        expected = self.graph_state(tree)
        real = grades._drop_links
        first = True
        def fail_after_one(owner, node):
            nonlocal first
            if first:
                first = False
                link = next(link for link in owner.links if link.from_node == node or link.to_node == node)
                owner.links.remove(link)
                raise RuntimeError('partial link removal')
            return real(owner, node)
        with patch.object(grades, '_drop_links', side_effect=fail_after_one):
            with self.assertRaisesRegex(RuntimeError, 'partial link removal'):
                grades.replace_node(original, 'CompositorNodeGroup')
        self.assertEqual(self.graph_state(tree), expected)
        self.assertEqual(grade.users, 5)
        self.assertFalse(transactions.pending())

    def test_partial_editor_rebind_is_compensated_before_retirement(self):
        editing = _component('graph.editing')
        tree, grade = self.graph('CompositorNodeTree')
        original = next(node for node in tree.nodes if stacks.is_stack(node))
        targets = [editing.Target(original, original.pg_stack_entries[0]) for _ in range(2)]
        for index, target in enumerate(targets): editing._targets[index] = target
        self.addCleanup(editing.clear)
        real = editing.rebind
        first = True
        def partial(previous, replacement):
            nonlocal first
            if first:
                first = False
                targets[0].stack = replacement
                raise RuntimeError('partial editor rebind')
            return real(previous, replacement)
        with patch.object(editing, 'rebind', side_effect=partial):
            with self.assertRaisesRegex(RuntimeError, 'partial editor rebind'):
                grades.replace_node(original, 'CompositorNodeGroup')
        self.assertTrue(all(target.stack == original for target in targets))
        self.assertEqual(grade.users, 5)
        self.assertFalse(transactions.pending())

    def test_failed_compensation_keeps_value_debt_until_repair(self):
        tree, grade = self.graph('CompositorNodeTree')
        original = next(node for node in tree.nodes if nodes.is_grade(node))
        expected = self.graph_state(tree)
        with patch.object(grades, '_replacement_links', side_effect=RuntimeError('cannot install links')):
            with self.assertRaisesRegex(RuntimeError, 'cannot install links'):
                grades.replace_node(original, 'CompositorNodeGroup')
        self.assertTrue(transactions.pending())
        with self.assertRaisesRegex(RuntimeError, 'ownership repair'):
            transactions.require_clean()
        for debt in transactions._pending.values(): transactions.plain(debt)
        transactions.repair_all()
        self.assertFalse(transactions.pending())
        self.assertEqual(self.graph_state(tree), expected)
        self.assertEqual(grade.users, 5)

    def test_partial_stack_assignment_restores_occurrences(self):
        tree, grade = self.graph('CompositorNodeTree')
        node = next(node for node in tree.nodes if stacks.is_stack(node))
        expected = stacks.entries(node)
        real = stacks._write_entries
        first = True
        def partial(target, values):
            nonlocal first
            if first:
                first = False
                real(target, values[:1])
                raise RuntimeError('partial Stack assignment')
            return real(target, values)
        with patch.object(stacks, '_write_entries', side_effect=partial):
            with self.assertRaisesRegex(RuntimeError, 'partial Stack assignment'):
                stacks.assign(node, expected[:1])
        self.assertEqual(stacks.entries(node), expected)
        self.assertEqual(grade.users, 5)

    def test_partial_kernel_assignment_restores_links_and_kernel_users(self):
        tree, grade = self.graph('CompositorNodeTree')
        node = next(node for node in tree.nodes if nodes.is_grade(node))
        previous = node.node_tree
        candidate = previous.copy()
        expected = self.graph_state(tree)
        users = previous.users
        real = transactions.find_node
        first = True
        def missing_once(owner, identity):
            nonlocal first
            if first:
                first = False
                return None
            return real(owner, identity)
        with patch.object(transactions, 'find_node', side_effect=missing_once):
            with self.assertRaisesRegex(RuntimeError, 'lost a linked node'):
                nodes.assign_kernel(node, candidate)
        self.assertEqual(node.node_tree, previous)
        self.assertEqual(previous.users, users)
        self.assertEqual(candidate.users, 0)
        self.assertEqual(self.graph_state(tree), expected)

    def test_conversion_failure_restores_original_graph_and_owned_users(self):
        for phase in ('assign_values', '_replacement_links', 'rebind', 'release_node_references'):
            with self.subTest(phase=phase):
                tree, grade = self.graph('CompositorNodeTree')
                original = next(node for node in tree.nodes if nodes.is_grade(node))
                original_name = original.name
                expected = self.graph_state(tree)
                module = grades if phase != 'rebind' else nodes.editing
                real = getattr(module, phase)
                calls = 0
                def fail_once(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        raise RuntimeError('Injected portable conversion failure')
                    return real(*args, **kwargs)
                with patch.object(module, phase, side_effect=fail_once):
                    with self.assertRaisesRegex(RuntimeError, 'Injected portable conversion failure'):
                        grades.replace_node(original, 'CompositorNodeGroup')
                self.assertEqual(tree.nodes.get(original_name), original)
                self.assertEqual(self.graph_state(tree), expected)
                self.assertEqual(grade.users, 5)
                self.assert_dependencies(tree, grade)
                bpy.data.node_groups.remove(tree)


    def test_prepare_save_failure_and_missing_completion_do_not_strand_flags(self):
        tree, grade = self.graph('CompositorNodeTree')
        real = grades.representations
        def fail_portable(portable=False):
            if portable:
                raise RuntimeError('Injected save preparation failure')
            return real(portable)
        with patch.object(grades, 'representations', side_effect=fail_portable):
            with self.assertRaisesRegex(RuntimeError, 'Injected save preparation failure'):
                grades.prepare_save()
        self.assertFalse(grades._saving or grades._converting)
        self.assertEqual(grade.users, 5)
        nodes.save_handler()
        self.assertTrue(grades._saving)
        # The timer fallback does not need a save_post callback to resume.
        grades.resume_after_save()
        self.assertFalse(grades._saving or grades._converting)
        self.assertTrue(all(node.bl_idname in (*grades.KINDS.values(), *stacks.KINDS.values())
                            for node in tree.nodes))
        self.assertEqual(grade.users, 5)
        self.assert_dependencies(tree, grade)


    def test_copy_tree_and_individual_node_deletion_release_only_owned_users(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                tree, grade = self.graph(kind)
                copied = tree.copy()
                nodes.refresh_all()
                self.assertEqual(grade.users, 9)
                bpy.data.node_groups.remove(copied)
                self.assertEqual(grade.users, 5)
                stack = next(node for node in tree.nodes if stacks.is_stack(node))
                tree.nodes.remove(stack)
                self.assertEqual(grade.users, 3)
                for expected, node in zip((2, 1), list(tree.nodes)):
                    tree.nodes.remove(node)
                    self.assertEqual(grade.users, expected)


    def test_evaluated_nodes_keep_borrowed_references(self):
        material = bpy.data.materials.new('Evaluated ownership')
        material.use_nodes = True
        node = nodes.create_grade(material.node_tree)
        nodes.write_values(node, {'exposure': .2})
        grade = node.pg_grade
        stack = sequence(material.node_tree, [grade, grade])
        mesh = bpy.data.meshes.new('Evaluated ownership')
        obj = bpy.data.objects.new('Evaluated ownership', mesh)
        bpy.context.scene.collection.objects.link(obj)
        mesh.materials.append(material)
        evaluated = material.evaluated_get(bpy.context.evaluated_depsgraph_get())
        copied_node, copied_stack = (evaluated.node_tree.nodes[n.name] for n in (node, stack))
        borrowed_grade = copied_node.pg_grade
        borrowed_entries = stacks.entries(copied_stack)
        self.assertTrue(copied_node.id_data.is_evaluated)
        self.assertTrue(copied_stack.id_data.is_evaluated)
        self.assertEqual(grade.users, 4)
        for copied in (copied_node, copied_stack):
            grades.release_node_references(copied)
        self.assertEqual(copied_node.pg_grade, borrowed_grade)
        self.assertEqual(stacks.entries(copied_stack), borrowed_entries)
        self.assertEqual(node.pg_grade, grade)
        self.assertEqual(grade.users, 4)


