import unittest
import threading
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import bpy
import numpy as np

from color_tools.perceptual_grade_next_blender import recovery
from color_tools.perceptual_grade_next_blender import output_operators
from color_tools.perceptual_grade_next_blender import scope_runtime


class _Node(dict):
    def __init__(self, pointer, **values):
        super().__init__(values)
        self.pointer = pointer

    def as_pointer(self):
        return self.pointer


class RecoveryTests(unittest.TestCase):
    @staticmethod
    def _tree_with_color_interface(name):
        tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
        tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        source = tree.nodes.new("NodeGroupInput")
        sink = tree.nodes.new("NodeGroupOutput")
        tree.links.new(source.outputs["Color"], sink.inputs["Color"])
        return tree

    def _replacement_fixture(self, backend="native_grade_graph"):
        from color_tools.perceptual_grade_next_blender import controls
        from color_tools.perceptual_grade_next_core import GradeSettings, StackSettings

        controls.register()
        host = bpy.data.node_groups.new("Next Tree Backing Host", "ShaderNodeTree")
        host.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        host.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        source = host.nodes.new("NodeGroupInput")
        sink = host.nodes.new("NodeGroupOutput")
        owner = host.nodes.new("ShaderNodeGroup")
        prior = self._tree_with_color_interface("Next Tree Backing Prior")
        candidate = self._tree_with_color_interface("Next Tree Backing Candidate")
        owner.node_tree = prior
        host.links.new(source.outputs["Color"], owner.inputs["Color"])
        host.links.new(owner.outputs["Color"], sink.inputs["Color"])
        owner["perceptual_grade_next_backend"] = backend
        if backend == "native_grade_graph":
            controls.attach_controls(owner, GradeSettings())
        else:
            controls.attach_stack_controls(owner, StackSettings())
        owner.inputs["Color"].default_value = (0.1, 0.2, 0.3, 0.4)
        owner["perceptual_grade_next_tree_marker"] = "prior"
        return controls, host, owner, prior, candidate, source, sink

    def _dispose_replacement_fixture(self, controls, host, owner, prior, candidate):
        try:
            from color_tools.perceptual_grade_next_blender.preparation_ledger import (
                discard_owner_ledger,
            )
            discard_owner_ledger(owner)
        finally:
            for tree in (host, prior, candidate):
                try:
                    if tree.users == 0:
                        bpy.data.node_groups.remove(tree, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            controls.unregister()

    def test_output_operators_register_owned_menu_hooks_and_unregister_cleanly(self):
        output_operators.unregister()
        menus = tuple(
            getattr(bpy.types, name, None)
            for name in ("TOPBAR_MT_file", "TOPBAR_MT_render")
        )
        before = tuple(tuple(getattr(menu.draw, "_draw_funcs", ())) if menu else ()
                       for menu in menus)
        had_draw_funcs = tuple(
            bool(menu and hasattr(menu.draw, "_draw_funcs")) for menu in menus
        )
        before_draw = tuple(menu.draw if menu else None for menu in menus)
        window_manager = bpy.context.window_manager
        user_keyconfig = getattr(getattr(window_manager, "keyconfigs", None), "user", None)
        addon_keyconfig = getattr(getattr(window_manager, "keyconfigs", None), "addon", None)
        original_user_keymaps = tuple(
            (keymap, item, item.active)
            for keymap in getattr(user_keyconfig, "keymaps", ())
            for item in keymap.keymap_items
            if (item.active and output_operators._redirect_target(
                item.idname,
                animation=getattr(getattr(item, "properties", None), "animation", False),
            ) is not None)
        )
        output_operators.register()
        self.assertTrue(any(
            cls.bl_idname == "wm.pg_next_save" and cls.is_registered
            for cls in output_operators._CLASSES
        ))
        for menu, original in zip(menus, before):
            if menu is None:
                continue
            self.assertIsNot(menu.draw, before_draw[menus.index(menu)])
            if had_draw_funcs[menus.index(menu)]:
                self.assertIs(menu.draw._draw_funcs,
                              before_draw[menus.index(menu)]._draw_funcs)
            self.assertEqual(tuple(menu.draw._draw_funcs), original)

        class RecordingLayout:
            def __init__(self):
                self.operator_context = "INVOKE_REGION_WIN"
                self.operators = []

            def operator(self, operator_id, **kwargs):
                properties = SimpleNamespace()
                self.operators.append((self.operator_context, operator_id, kwargs, properties))
                return properties

            def row(self):
                return self

            def menu(self, *_args, **_kwargs):
                return None

            def separator(self, *_args, **_kwargs):
                return None

            def prop(self, *_args, **_kwargs):
                return None

        file_layout = RecordingLayout()
        file_context = SimpleNamespace(
            blend_data=SimpleNamespace(is_saved=True),
            view_layer=SimpleNamespace(has_export_collections=True),
        )
        menus[0].draw(
            SimpleNamespace(layout=file_layout), file_context,
        )
        file_actions = [(operator_id, kwargs.get("text"), context)
                        for context, operator_id, kwargs, _props in file_layout.operators]
        self.assertIn(("wm.pg_next_save", "Save", "INVOKE_AREA"), file_actions)
        self.assertIn(("wm.pg_next_save_as", "Save As...", "INVOKE_AREA"), file_actions)
        self.assertIn(("wm.save_as_mainfile", "Save Copy...", "INVOKE_AREA"), file_actions)
        self.assertIn(("wm.save_mainfile", "Save Incremental", "EXEC_AREA"), file_actions)
        self.assertNotIn(("wm.save_mainfile", "Save", "EXEC_AREA"), file_actions)
        save_props = next(props for _ctx, op, kwargs, props in file_layout.operators
                          if op == "wm.pg_next_save" and kwargs.get("text") == "Save")
        self.assertFalse(hasattr(save_props, "show_save_modified_images_dialog"))

        render_layout = RecordingLayout()
        scene = SimpleNamespace(name="Scene", render=SimpleNamespace(use_sequencer=True))
        sequencer_scene = SimpleNamespace(name="Sequencer", render=SimpleNamespace(use_sequencer=True))
        render_context = SimpleNamespace(
            scene=scene, sequencer_scene=sequencer_scene, strips=(object(),),
        )
        menus[1].draw(SimpleNamespace(layout=render_layout), render_context)
        render_actions = [(operator_id, kwargs.get("text"))
                          for _ctx, operator_id, kwargs, _props in render_layout.operators]
        self.assertIn(("render.pg_next_render_image", "Render Image"), render_actions)
        self.assertIn(("render.pg_next_render_animation", "Render Animation"), render_actions)
        self.assertIn(("render.render", "Render Sequencer Image"), render_actions)
        self.assertIn(("render.render", "Render Sequencer Animation"), render_actions)
        animation_props = next(props for _ctx, op, kwargs, props in render_layout.operators
                               if op == "render.pg_next_render_animation")
        self.assertTrue(animation_props.use_viewport)
        self.assertFalse(hasattr(animation_props, "animation"))

        callback = lambda _self, _context: None
        for menu in menus:
            if menu is not None:
                menu.append(callback)
        installed = tuple(output_operators._MENU_WRAPPERS)
        redirects = tuple(output_operators._KEYMAP_ITEMS)
        self.assertEqual(len(output_operators._KEYMAP_REDIRECTS), len(redirects))
        if user_keyconfig is not None and addon_keyconfig is not None:
            self.assertEqual(len(redirects), len(original_user_keymaps))
        else:
            self.assertFalse(redirects)
        for (_, _active, target_id), (_, redirect) in zip(
                output_operators._KEYMAP_REDIRECTS, redirects):
            self.assertEqual(redirect.idname, target_id)
            self.assertIn(redirect.idname, {
                "wm.pg_next_save", "wm.pg_next_save_as",
                "render.pg_next_render_image", "render.pg_next_render_animation",
            })
        output_operators.unregister()
        for menu, original_draw, wrapper, _had_draw_funcs in installed:
            self.assertIsNot(menu.draw, wrapper)
            self.assertIs(menu.draw, original_draw)
            self.assertEqual(tuple(menu.draw._draw_funcs),
                             before[menus.index(menu)] + (callback,))
            menu.remove(callback)
        for _keymap, item, active in original_user_keymaps:
            self.assertEqual(item.active, active)
        self.assertFalse(output_operators._KEYMAP_ITEMS)

    def test_packed_bake_backup_restores_partial_and_preserves_verified_commit(self):
        from color_tools.perceptual_grade_next_blender.image_publication import (
            BlenderImageBackupStore,
        )

        store = BlenderImageBackupStore(bpy)
        image = bpy.data.images.new("Next Bake Backup Test", width=2, height=1,
                                    alpha=True, float_buffer=True)
        image.use_half_precision = False
        original = np.asarray((0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8), dtype=np.float32)
        candidate = np.asarray((0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1), dtype=np.float32)
        image.pixels.foreach_set(original)
        image.update()
        try:
            token = store.save(image, store.snapshot(image), operation=7)
            image.pixels.foreach_set(candidate)
            image.pixels[0] = 0.0
            image.update()
            self.assertEqual(store.recover_pending(), ((token, "previous_restored"),))
            restored = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(restored)
            np.testing.assert_array_equal(restored, original)

            token = store.save(image, store.snapshot(image), operation=8)
            image.pixels.foreach_set(candidate)
            image.update()
            store.mark_committed(token, candidate)
            self.assertEqual(store.recover_pending(), ((token, "committed_preserved"),))
            image.pixels.foreach_get(restored)
            np.testing.assert_array_equal(restored, candidate)
        finally:
            for item in tuple(bpy.data.images):
                if item == image or item.name.startswith(store.IMAGE_PREFIX):
                    bpy.data.images.remove(item)

    def test_failed_backup_pack_removes_candidate_without_marking_target(self):
        from color_tools.perceptual_grade_next_blender.image_publication import (
            BlenderImageBackupStore,
        )

        store = BlenderImageBackupStore(bpy)
        image = bpy.data.images.new("Next Failed Backup Test", width=1, height=1,
                                    alpha=True, float_buffer=True)
        image.use_half_precision = False
        prior = {
            item.as_pointer() for item in bpy.data.images
            if item.name.startswith(store.IMAGE_PREFIX)
        }

        class FaultyImage:
            def __init__(self, image):
                object.__setattr__(self, "image", image)

            def __getattr__(self, name):
                return getattr(self.image, name)

            def __setattr__(self, name, value):
                setattr(self.image, name, value)

            def __getitem__(self, key):
                return self.image[key]

            def __setitem__(self, key, value):
                self.image[key] = value

            def get(self, key, default=None):
                return self.image.get(key, default)

            def pop(self, key, default=None):
                return self.image.pop(key, default)

            def pack(self, *args, **kwargs):
                raise RuntimeError("injected recovery pack failure")

        class FaultyImages:
            def new(self, *args, **kwargs):
                return FaultyImage(bpy.data.images.new(*args, **kwargs))

            @staticmethod
            def remove(image):
                bpy.data.images.remove(image.image)

        store.bpy = SimpleNamespace(data=SimpleNamespace(images=FaultyImages()))

        try:
            with self.assertRaisesRegex(RuntimeError, "injected recovery pack"):
                store.save(image, store.snapshot(image), operation=9)
            self.assertFalse(image.get(store.TARGET_KEY))
            self.assertFalse(image.get(store.ACTIVE_KEY))
            self.assertEqual(
                {item.as_pointer() for item in bpy.data.images
                 if item.name.startswith(store.IMAGE_PREFIX)},
                prior,
            )
        finally:
            for item in tuple(bpy.data.images):
                if item == image or item.name.startswith(store.IMAGE_PREFIX):
                    bpy.data.images.remove(item)

    def test_same_image_bake_publications_are_serialized_by_persistent_backup(self):
        from color_tools.perceptual_grade_next_blender.image_publication import (
            BlenderImageBackupStore,
        )

        store = BlenderImageBackupStore(bpy)
        image = bpy.data.images.new("Next Serialized Bake Test", width=1, height=1,
                                    alpha=True, float_buffer=True)
        image.use_half_precision = False
        image.pixels.foreach_set((0.1, 0.2, 0.3, 0.4))
        image.update()
        try:
            first = store.save(image, store.snapshot(image), operation=11)
            with self.assertRaisesRegex(RuntimeError, "already has a pending Bake"):
                store.save(image, store.snapshot(image), operation=12)
            self.assertTrue(store.rollback(first))

            second = store.save(image, store.snapshot(image), operation=13)
            with self.assertRaisesRegex(RuntimeError, "already has a pending Bake"):
                store.save(image, store.snapshot(image), operation=14)
            store.mark_committed(second, store.snapshot(image))
            self.assertEqual(
                store.recover_pending(), ((second, "committed_preserved"),),
            )

            third = store.save(image, store.snapshot(image), operation=15)
            self.assertTrue(store.rollback(third))
        finally:
            for item in tuple(bpy.data.images):
                if item == image or item.name.startswith(store.IMAGE_PREFIX):
                    bpy.data.images.remove(item)

    def test_requeue_uses_authored_backend_nodes_and_ignores_other_nodes(self):
        grade = _Node(1, perceptual_grade_next_backend="native_grade_graph")
        grade.perceptual_grade_next_controls = SimpleNamespace(perceptual_grade_next_ready=True)
        stack = _Node(2, perceptual_grade_next_backend="native_stack_lut")
        stack.perceptual_grade_next_stack_controls = SimpleNamespace(perceptual_grade_next_ready=True)
        ordinary = _Node(3, perceptual_grade_next_backend="other")
        nodes = (grade, stack, ordinary)
        queued = []

        result = recovery.requeue_prepared_nodes(
            (SimpleNamespace(nodes=nodes),), mark_dirty=lambda node: queued.append(node) or True,
        )
        self.assertEqual(result, (grade, stack))
        self.assertEqual(queued, [grade, stack])

    def test_requeue_queues_owner_even_when_ready_marker_was_not_serialized(self):
        """Authored controls remain recoverable when the transient ready bit is false."""
        grade = _Node(4, perceptual_grade_next_backend="native_grade_graph")
        grade.perceptual_grade_next_controls = SimpleNamespace(
            perceptual_grade_next_ready=False,
        )
        queued = []

        result = recovery.requeue_prepared_nodes(
            (SimpleNamespace(nodes=(grade,)),),
            mark_dirty=lambda node: queued.append(node) or True,
        )

        self.assertEqual(result, (grade,))
        self.assertEqual(queued, [grade])

    def test_candidate_image_collection_deduplicates_shared_datablocks(self):
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            _candidate_images,
        )

        image = SimpleNamespace(as_pointer=lambda: 31)
        tree = SimpleNamespace(
            as_pointer=lambda: 30,
            nodes=(SimpleNamespace(image=image), SimpleNamespace(image=image)),
        )

        self.assertEqual(_candidate_images(tree), (image,))

    def test_ledger_owner_id_is_recovered_when_custom_property_was_not_serialized(self):
        """The serialized PointerProperty ledger can repair an absent owner ID."""
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_OWNER_KEY, LEDGER_SCHEMA, LEDGER_TX_KEY, OWNER_ID_KEY,
            _ledger_for,
        )

        class Ledger(dict):
            pass

        owner = _Node(5, perceptual_grade_next_backend="native_grade_graph")
        ledger = Ledger(
            perceptual_grade_next_preparation_ledger_schema=LEDGER_SCHEMA,
            **{
                LEDGER_OWNER_KEY: "serialized-owner",
                LEDGER_TX_KEY: "tx-1",
            },
        )
        owner.perceptual_grade_next_controls = SimpleNamespace(
            preparation_ledger=ledger,
        )

        controls, found = _ledger_for(owner, "", "tx-1")

        self.assertIs(found, ledger)
        self.assertIs(controls, owner.perceptual_grade_next_controls)
        self.assertEqual(owner[OWNER_ID_KEY], "serialized-owner")

    def test_recovery_rebuilds_missing_derived_data_and_discards_transient_operations(self):
        grade = _Node(11, perceptual_grade_next_backend="native_grade_graph")
        grade.perceptual_grade_next_controls = SimpleNamespace(
            perceptual_grade_next_ready=True,
        )
        host = SimpleNamespace(as_pointer=lambda: 10, nodes=(grade,))
        queued = []
        with patch.object(recovery, "_invalidate_runtime_state"), \
                patch("color_tools.perceptual_grade_next_blender.project_readiness.begin_document",
                      return_value=7), \
                patch("color_tools.perceptual_grade_next_blender.project_readiness.refresh_project_readiness"):
            result = recovery.recover_document(
                (host,), mark_dirty=lambda node: queued.append(node) or True,
            )
        self.assertEqual(queued, [grade])
        self.assertEqual(result.generation, 7)
        self.assertEqual(result.queued, ("10:11",))
        self.assertTrue(result.pending)
        self.assertFalse(result.complete)
        self.assertEqual(result.discarded_operations, ("bake", "save", "render"))

    def test_recovery_result_is_complete_only_when_no_owner_is_queued_or_invalid(self):
        settled = recovery.RecoveryResult(generation=1, reused=("owner",))
        waiting = recovery.RecoveryResult(generation=1, queued=("owner",))
        invalid = recovery.RecoveryResult(generation=1, invalid=("owner",))
        self.assertTrue(settled.complete)
        self.assertFalse(settled.pending)
        self.assertFalse(waiting.complete)
        self.assertTrue(waiting.pending)
        self.assertFalse(invalid.complete)
        self.assertFalse(invalid.pending)

    def test_fresh_recovery_retry_drops_resolved_backup_references(self):
        from color_tools.perceptual_grade_next_blender import updates

        owner = _Node(4, perceptual_grade_next_backend="native_grade_graph")
        updates._write_ledger(
            owner, kind="grade", revision=2, stage="backed_up",
            backup_transaction="old-transaction", backup_slots=("tone",),
            new_transaction=True,
        )
        old_transaction = updates._read_ledger(owner)["transaction_id"]
        updates._write_ledger(
            owner, kind="grade", revision=3, stage="queued",
            new_transaction=True,
        )

        ledger = json.loads(owner[updates.PREPARATION_LEDGER_KEY])
        self.assertNotEqual(ledger["transaction_id"], old_transaction)
        self.assertEqual(ledger["backup_transaction"], "")
        self.assertEqual(ledger["backup_slots"], [])

    def test_new_edit_cannot_overwrite_any_retained_preparation_ledger(self):
        from color_tools.perceptual_grade_next_blender import updates

        owner = _Node(14, perceptual_grade_next_backend="native_grade_graph")
        owner.id_data = SimpleNamespace()
        owner.perceptual_grade_next_controls = SimpleNamespace(
            preparation_ledger=object(),
        )
        updates._write_ledger(
            owner, kind="grade", revision=7, stage="failed",
            backup_transaction="field-repair", backup_slots=("tone",),
        )
        previous_ledger = owner[updates.PREPARATION_LEDGER_KEY]
        with patch.object(updates, "_refresh_project_readiness"):
            self.assertFalse(updates.mark_node_dirty(owner))

        self.assertEqual(owner[updates.PREPARATION_LEDGER_KEY], previous_ledger)
        self.assertEqual(updates._read_ledger(owner)["backup_transaction"], "field-repair")
        self.assertEqual(owner.get("perceptual_grade_next_edit_revision", 0), 0)
        self.assertEqual(owner["perceptual_grade_next_preparation_state"], "FAILED")
        self.assertIn("recovery is pending", owner["perceptual_grade_next_preparation_error"])

    def test_failed_grade_restore_preserves_repair_debt(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            GRADE_UPDATE, LEDGER_DATA_KEY, LEDGER_MODE_KEY, LEDGER_SLOTS_KEY,
            LEDGER_TX_KEY,
        )

        class Ledger(dict):
            nodes = ()

        owner = _Node(6, perceptual_grade_next_backend="native_grade_graph")
        owner.perceptual_grade_next_controls = SimpleNamespace(
            preparation_ledger=Ledger({
                LEDGER_MODE_KEY: GRADE_UPDATE,
                LEDGER_TX_KEY: "damaged-backing",
                LEDGER_DATA_KEY: json.dumps({"backup_slots": ["tone"]}),
                LEDGER_SLOTS_KEY: '["tone"]',
            }),
        )
        host = SimpleNamespace(as_pointer=lambda: 5, nodes=(owner,))
        updates._write_ledger(
            owner, kind="grade", revision=3, stage="committing",
            new_transaction=True,
        )
        updates._write_ledger(
            owner, kind="grade", revision=3, stage="committing",
            backup_transaction="damaged-backing", backup_slots=("tone",),
        )
        discarded = []
        queued = []

        def mark_dirty(node):
            queued.append(node)
            node["perceptual_grade_next_preparation_state"] = "PENDING"
            return True

        with patch.dict(updates._LIVE, {updates._key(host, owner): object()}), patch(
            "color_tools.perceptual_grade_next_blender.preparation_ledger"
            ".restore_grade_backing",
            side_effect=RuntimeError("backing digest mismatch"),
        ), patch(
            "color_tools.perceptual_grade_next_blender.preparation_ledger"
            ".discard_owner_ledger",
            side_effect=lambda node: discarded.append(node) or True,
        ):
            result = recovery.requeue_prepared_nodes(
                (host,), mark_dirty=mark_dirty,
            )
            self.assertNotIn(updates._key(host, owner), updates._LIVE)

        self.assertEqual(result, ())
        self.assertEqual(queued, [])
        self.assertEqual(discarded, [])
        self.assertIn(updates.PREPARATION_LEDGER_KEY, owner)
        self.assertEqual(
            updates._read_ledger(owner)["backup_transaction"], "damaged-backing",
        )
        self.assertEqual(owner["perceptual_grade_next_preparation_state"], "FAILED")

    def test_malformed_grade_snapshot_is_rejected_before_any_restore_writes(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_DATA_KEY, LEDGER_ROLE_KEY, digest, discard_owner_ledger,
            restore_grade_backing, stage_grade_backing,
        )

        controls, host, owner, prior, candidate, source, sink = self._replacement_fixture()
        image = bpy.data.images.new(
            "Next Invalid Snapshot Field", width=1, height=1,
            alpha=True, float_buffer=True,
        )
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        original = np.asarray((0.1, 0.2, 0.3, 0.4), dtype=np.float32)
        image.pixels.foreach_set(original)
        image.update()
        native_source = prior.nodes.new("ShaderNodeValue")
        target_node = prior.nodes.new("ShaderNodeMath")
        prior.links.new(native_source.outputs[0], target_node.inputs[0])
        image_node = prior.nodes.new("ShaderNodeTexImage")
        image_node.image = image
        old_table = object()
        native = SimpleNamespace(
            tree=prior,
            controller=SimpleNamespace(
                _graph=SimpleNamespace(
                    bindings=[(None, target_node.inputs[0], None)],
                    image_slots={"tone": (old_table, image)},
                ),
                prepared=SimpleNamespace(table=old_table),
            ),
        )
        ledger = None
        try:
            updates._write_ledger(
                owner, kind="grade", revision=1, stage="queued",
                new_transaction=True,
            )
            transaction, slots = stage_grade_backing(
                host, owner, native, SimpleNamespace(table=object()),
                "invalid-snapshot",
            )
            updates._write_ledger(
                owner, kind="grade", revision=1, stage="committing",
                backup_transaction=transaction, backup_slots=slots,
            )
            ledger = owner.perceptual_grade_next_controls.preparation_ledger
            backup = next(node.image for node in ledger.nodes
                          if node.get(LEDGER_ROLE_KEY) == "backup")

            damaged = np.asarray((0.9, 0.8, 0.7, 0.6), dtype=np.float32)
            image.pixels.foreach_set(damaged)
            image.update()
            target_node.inputs[0].default_value = 0.875
            owner.inputs["Color"].default_value = (0.9, 0.8, 0.7, 0.6)
            host.links.remove(next(link for link in host.links
                                   if link.from_node == source and link.to_node == owner))
            alternate_source = prior.nodes.new("ShaderNodeValue")
            prior.links.remove(next(link for link in prior.links
                                    if link.to_node == target_node))
            prior.links.new(alternate_source.outputs[0], target_node.inputs[0])
            before_native_links = tuple(
                (link.from_node, link.from_socket, link.to_node, link.to_socket)
                for link in prior.links
            )
            before_host_links = tuple(
                (link.from_node, link.from_socket, link.to_node, link.to_socket)
                for link in host.links
            )
            before_owner_default = tuple(owner.inputs["Color"].default_value)
            snapshot_data = json.loads(ledger[LEDGER_DATA_KEY])
            snapshot_data["grade_snapshot"]["bindings"] = []
            ledger[LEDGER_DATA_KEY] = json.dumps(snapshot_data, sort_keys=True)

            with self.assertRaisesRegex(RuntimeError, "bindings are incomplete"):
                restore_grade_backing(host, owner, updates._read_ledger(owner))

            actual = np.empty(len(image.pixels), dtype=np.float32)
            image.pixels.foreach_get(actual)
            np.testing.assert_array_equal(actual, damaged)
            self.assertAlmostEqual(target_node.inputs[0].default_value, 0.875)
            self.assertEqual(tuple(owner.inputs["Color"].default_value), before_owner_default)
            self.assertEqual(
                tuple((link.from_node, link.from_socket, link.to_node, link.to_socket)
                      for link in prior.links),
                before_native_links,
            )
            self.assertEqual(
                tuple((link.from_node, link.from_socket, link.to_node, link.to_socket)
                      for link in host.links),
                before_host_links,
            )
            self.assertIs(owner.perceptual_grade_next_controls.preparation_ledger, ledger)
            self.assertTrue(backup.packed_file)
            backup_pixels = np.empty(len(backup.pixels), dtype=np.float32)
            backup.pixels.foreach_get(backup_pixels)
            self.assertEqual(digest(backup_pixels), digest(original))
            self.assertEqual(
                updates._read_ledger(owner)["backup_transaction"], transaction,
            )
        finally:
            if ledger is not None:
                discard_owner_ledger(owner)
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)
            if image.users == 0:
                bpy.data.images.remove(image, do_unlink=True)

    def test_structural_backing_restores_tree_links_defaults_and_properties(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            restore_tree_backing, stage_tree_backing,
        )

        controls, host, owner, prior, candidate, source, sink = self._replacement_fixture()
        try:
            defaults = {"Color": tuple(owner.inputs["Color"].default_value)}
            properties = {
                "perceptual_grade_next_tree_marker": (True, "prior"),
                "perceptual_grade_next_missing_marker": (False, None),
            }
            transaction = stage_tree_backing(
                host, owner, prior, candidate, "tree-restore",
                defaults=defaults, properties=properties,
            )
            self.assertEqual(transaction, "tree-restore")
            ledger = owner.perceptual_grade_next_controls.preparation_ledger
            self.assertIsNotNone(ledger)
            self.assertGreater(prior.users, 0)
            self.assertGreater(candidate.users, 0)

            owner.node_tree = candidate
            owner.inputs["Color"].default_value = (0.9, 0.8, 0.7, 0.6)
            owner["perceptual_grade_next_tree_marker"] = "candidate"
            owner["perceptual_grade_next_missing_marker"] = "candidate-only"
            for link in tuple(host.links):
                host.links.remove(link)
            ledger_data = updates._read_ledger(owner)
            restored = restore_tree_backing(host, owner, ledger_data)
            self.assertTrue(restored)
            self.assertIs(owner.node_tree, prior)
            self.assertEqual(tuple(owner.inputs["Color"].default_value), defaults["Color"])
            self.assertEqual(owner["perceptual_grade_next_tree_marker"], "prior")
            self.assertNotIn("perceptual_grade_next_missing_marker", owner)
            self.assertTrue(any(link.from_node == source and link.to_node == owner
                                for link in host.links))
            self.assertTrue(any(link.from_node == owner and link.to_node == sink
                                for link in host.links))
            self.assertIsNone(owner.perceptual_grade_next_controls.preparation_ledger)
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_structural_backing_commit_preserves_candidate_through_recovery(self):
        from unittest.mock import patch
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            commit_tree_backing, restore_tree_backing, stage_tree_backing,
        )

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture(
            "native_stack_lut",
        )
        try:
            transaction = stage_tree_backing(
                host, owner, prior, candidate, "tree-commit",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            owner.node_tree = candidate
            with patch(
                "color_tools.perceptual_grade_next_blender.preparation_ledger"
                "._validate_replacement_candidate",
            ) as validate:
                commit_tree_backing(owner, transaction)
                validate.assert_called_once_with(owner, candidate)
                self.assertIsNotNone(owner.perceptual_grade_next_stack_controls.preparation_ledger)
                self.assertGreater(candidate.users, 0)
                self.assertIs(owner.node_tree, candidate)
                self.assertTrue(restore_tree_backing(host, owner))
                self.assertEqual(validate.call_count, 2)
            self.assertIs(owner.node_tree, candidate)
            self.assertIsNone(owner.perceptual_grade_next_stack_controls.preparation_ledger)
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_structural_backing_rejects_unvalidated_grade_and_stack_candidates(self):
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_COMMITTED_KEY, commit_tree_backing, restore_tree_backing,
            stage_tree_backing,
        )

        for backend in ("native_grade_graph", "native_stack_lut"):
            controls, host, owner, prior, candidate, _source, _sink = (
                self._replacement_fixture(backend)
            )
            try:
                owner["perceptual_grade_next_edit_revision"] = 1
                owner["perceptual_grade_next_applied_revision"] = 1
                owner["perceptual_grade_next_preparation_state"] = "READY"
                transaction = stage_tree_backing(
                    host, owner, prior, candidate, "invalid-" + backend,
                    defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                    properties={"perceptual_grade_next_tree_marker": (True, "prior")},
                )
                owner.node_tree = candidate
                with self.assertRaises(RuntimeError):
                    commit_tree_backing(owner, transaction)
                ledger = owner.perceptual_grade_next_controls.preparation_ledger
                self.assertIsNotNone(ledger)
                self.assertIs(ledger.get(LEDGER_COMMITTED_KEY), False)
                self.assertTrue(restore_tree_backing(host, owner))
                self.assertIs(owner.node_tree, prior)
            finally:
                self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_ledger_image_cleanup_deduplicates_and_retains_failed_debt(self):
        from color_tools.perceptual_grade_next_blender import preparation_ledger

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture()
        owned = shared = None
        try:
            preparation_ledger.stage_tree_backing(
                host, owner, prior, candidate, "cleanup-dedup",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            ledger = owner.perceptual_grade_next_controls.preparation_ledger
            owned = bpy.data.images.new(
                "Next Duplicate Ledger Image", width=1, height=1,
                alpha=True, float_buffer=True,
            )
            shared = bpy.data.images.new(
                "Next Shared Ledger Image", width=1, height=1,
                alpha=True, float_buffer=True,
            )
            for _ in range(2):
                node = ledger.nodes.new("ShaderNodeTexImage")
                node.image = owned
                node[preparation_ledger.LEDGER_ROLE_KEY] = "backup"
            shared_node = ledger.nodes.new("ShaderNodeTexImage")
            shared_node.image = shared
            shared_node[preparation_ledger.LEDGER_ROLE_KEY] = "backup"
            external = host.nodes.new("ShaderNodeTexImage")
            external.image = shared
            self.assertEqual(len(preparation_ledger._ledger_images(ledger)), 2)

            with patch.object(
                preparation_ledger, "_discard_backup_images",
                side_effect=RuntimeError("image removal failed"),
            ), self.assertRaisesRegex(RuntimeError, "image removal failed"):
                preparation_ledger.discard_owner_ledger(owner)
            self.assertIs(owner.perceptual_grade_next_controls.preparation_ledger, ledger)

            preparation_ledger.discard_owner_ledger(owner)
            self.assertIsNone(owner.perceptual_grade_next_controls.preparation_ledger)
            self.assertIsNone(bpy.data.images.get(owned.name))
            self.assertIs(bpy.data.images.get(shared.name), shared)
            self.assertIs(external.image, shared)
        finally:
            preparation_ledger.discard_owner_ledger(owner)
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)
            for image in (owned, shared):
                if image is not None:
                    try:
                        if image.users == 0:
                            bpy.data.images.remove(image, do_unlink=True)
                    except (ReferenceError, RuntimeError):
                        pass

    def test_structural_backing_survives_blend_library_serialization(self):
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_ROLE_KEY, discard_owner_ledger, restore_tree_backing,
            stage_tree_backing,
        )

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture()
        loaded_host = loaded_owner = loaded_prior = loaded_candidate = None
        try:
            stage_tree_backing(
                host, owner, prior, candidate, "tree-serialized",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            owner.node_tree = candidate
            owner["perceptual_grade_next_tree_marker"] = "candidate"
            with TemporaryDirectory() as directory:
                path = str(Path(directory) / "tree-backing.blend")
                bpy.data.libraries.write(path, {host})
                with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                    self.assertIn(host.name, data_from.node_groups)
                    data_to.node_groups = [host.name]
                loaded_host = data_to.node_groups[0]
            loaded_owner = next(node for node in loaded_host.nodes
                                if node.get("perceptual_grade_next_backend") == "native_grade_graph")
            ledger = loaded_owner.perceptual_grade_next_controls.preparation_ledger
            self.assertIsNotNone(ledger)
            references = {node.get(LEDGER_ROLE_KEY): node.node_tree for node in ledger.nodes
                          if node.get(LEDGER_ROLE_KEY) in {"prior_tree", "candidate_tree"}}
            self.assertEqual(set(references), {"prior_tree", "candidate_tree"})
            loaded_prior = references["prior_tree"]
            loaded_candidate = references["candidate_tree"]
            self.assertIs(loaded_owner.node_tree, loaded_candidate)
            self.assertGreater(loaded_prior.users, 0)
            self.assertGreater(loaded_candidate.users, 0)
            self.assertTrue(restore_tree_backing(loaded_host, loaded_owner))
            self.assertIs(loaded_owner.node_tree, loaded_prior)
            self.assertEqual(loaded_owner["perceptual_grade_next_tree_marker"], "prior")
            self.assertIsNone(loaded_owner.perceptual_grade_next_controls.preparation_ledger)
        finally:
            if loaded_owner is not None:
                discard_owner_ledger(loaded_owner)
            for tree in (loaded_host, loaded_prior, loaded_candidate):
                try:
                    if tree is not None and tree.users == 0:
                        bpy.data.node_groups.remove(tree, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_grade_field_backing_survives_blend_library_serialization_without_owner_id(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_DIGEST_KEY, LEDGER_OWNER_KEY, LEDGER_ROLE_KEY, OWNER_ID_KEY,
            digest, discard_owner_ledger, stage_grade_backing,
        )

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture()
        image = bpy.data.images.new(
            "Next Serialized Grade Field", width=2, height=1,
            alpha=True, float_buffer=True,
        )
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        original = np.asarray(
            (0.123456789, 0.2, 0.3, 0.4, 1.23456789, -0.6, 0.7, 0.8),
            dtype=np.float32,
        )
        image.pixels.foreach_set(original)
        image.update()
        image.pack()
        reference = prior.nodes.new("ShaderNodeTexImage")
        reference.image = image
        binding_node = prior.nodes.new("ShaderNodeMath")
        old_table = object()
        native = SimpleNamespace(controller=SimpleNamespace(
            _graph=SimpleNamespace(
                image_slots={"tone": (old_table, image)},
                bindings=((None, binding_node.inputs[0], None),),
            ),
            prepared=SimpleNamespace(table=old_table),
        ))
        loaded_host = loaded_owner = loaded_tree = loaded_image = None
        try:
            updates._write_ledger(
                owner, kind="grade", revision=2, prior_revision=1,
                stage="queued", new_transaction=True,
            )
            transaction, slots = stage_grade_backing(
                host, owner, native, SimpleNamespace(table=object()), "field-serialized",
            )
            updates._write_ledger(
                owner, kind="grade", revision=2, prior_revision=1,
                stage="committing", backup_transaction=transaction, backup_slots=slots,
            )
            self.assertEqual(slots, ("tone",))
            ledger = owner.perceptual_grade_next_controls.preparation_ledger
            retained_owner_id = ledger[LEDGER_OWNER_KEY]

            # Persist an interrupted field write and omit both progress markers;
            # only the real PointerProperty roots the transaction and backup.
            damaged = original.copy()
            damaged[:4] = (0.9, 0.8, 0.7, 0.6)
            image.pixels.foreach_set(damaged)
            image.update()
            image.pack()
            del owner[OWNER_ID_KEY]
            del owner[updates.PREPARATION_LEDGER_KEY]
            with TemporaryDirectory() as directory:
                path = str(Path(directory) / "grade-field-backing.blend")
                bpy.data.libraries.write(path, {host})
                with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                    self.assertIn(host.name, data_from.node_groups)
                    data_to.node_groups = [host.name]
                loaded_host = data_to.node_groups[0]

            self.assertNotEqual(loaded_host.as_pointer(), host.as_pointer())
            loaded_owner = loaded_host.nodes[owner.name]
            loaded_tree = loaded_owner.node_tree
            self.assertNotIn(OWNER_ID_KEY, loaded_owner)
            ledger = loaded_owner.perceptual_grade_next_controls.preparation_ledger
            self.assertIsNotNone(ledger)
            references = {node.get(LEDGER_ROLE_KEY): node.image for node in ledger.nodes}
            self.assertEqual(set(references), {"target", "backup"})
            loaded_image = references["target"]
            backup = references["backup"]
            self.assertNotEqual(loaded_image.as_pointer(), image.as_pointer())
            self.assertEqual(backup[LEDGER_DIGEST_KEY], digest(original))
            self.assertTrue(backup.packed_file)
            self.assertFalse(backup.use_half_precision)
            restored = np.empty(len(loaded_image.pixels), dtype=np.float32)
            loaded_image.pixels.foreach_get(restored)
            np.testing.assert_array_equal(restored, damaged)
            backup.pixels.foreach_get(restored)
            np.testing.assert_array_equal(restored, original)

            from color_tools.perceptual_grade_next_blender import updates
            retained = loaded_owner.perceptual_grade_next_controls.preparation_ledger
            self.assertFalse(updates.mark_node_dirty(loaded_owner))
            self.assertIs(
                loaded_owner.perceptual_grade_next_controls.preparation_ledger,
                retained,
            )
            self.assertNotIn(updates.PREPARATION_LEDGER_KEY, loaded_owner)
            self.assertEqual(loaded_owner.get("perceptual_grade_next_edit_revision", 0), 0)

            queued = []
            with patch(
                "color_tools.perceptual_grade_next_blender.preparation_ledger"
                ".restore_grade_backing",
                side_effect=RuntimeError("injected field restore failure"),
            ):
                self.assertEqual(recovery.requeue_prepared_nodes(
                    (loaded_host,), mark_dirty=lambda item: queued.append(item) or True,
                ), ())
            self.assertEqual(queued, [])
            self.assertIsNotNone(loaded_owner.perceptual_grade_next_controls.preparation_ledger)
            self.assertEqual(loaded_owner["perceptual_grade_next_preparation_state"], "FAILED")

            self.assertEqual(recovery.requeue_prepared_nodes(
                (loaded_host,), mark_dirty=lambda item: queued.append(item) or True,
            ), (loaded_owner,))
            self.assertEqual(queued, [loaded_owner])
            self.assertEqual(loaded_owner[OWNER_ID_KEY], retained_owner_id)
            self.assertIsNone(loaded_owner.perceptual_grade_next_controls.preparation_ledger)
            self.assertIsNone(updates._read_ledger(loaded_owner))
            loaded_image.pixels.foreach_get(restored)
            np.testing.assert_array_equal(restored, original)
            self.assertEqual(digest(restored), digest(original))
            self.assertTrue(loaded_image.packed_file)
            self.assertFalse(loaded_image.use_half_precision)
        finally:
            if loaded_owner is not None:
                discard_owner_ledger(loaded_owner)
            for tree in (loaded_host, loaded_tree):
                try:
                    if tree is not None and tree.users == 0:
                        bpy.data.node_groups.remove(tree, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)
            for field in (loaded_image, image):
                try:
                    if field is not None and field.users == 0:
                        bpy.data.images.remove(field, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass

    def test_binding_only_grade_backing_restores_links_defaults_and_revision_after_load(self):
        from color_tools.perceptual_grade_next_blender import controls, updates, preparation_ledger
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            discard_owner_ledger,
        )

        controls, host, owner, native_tree, candidate, source_node, sink_node = (
            self._replacement_fixture()
        )
        value = native_tree.nodes.new("ShaderNodeValue")
        math_node = native_tree.nodes.new("ShaderNodeMath")
        native_tree.links.new(value.outputs["Value"], math_node.inputs[0])
        prior_first_default = math_node.inputs[0].default_value
        math_node.inputs[1].default_value = 2.5
        native_tree["perceptual_grade_next_settings"] = "prior-native-settings"
        native_tree["perceptual_grade_nodes_revision"] = 7
        owner["perceptual_grade_next_settings"] = "prior-owner-settings"
        owner["perceptual_grade_next_applied_revision"] = 7
        owner["perceptual_grade_next_accepted_grade_manifest"] = "prior-manifest"
        old_table = object()
        graph = SimpleNamespace(
            image_slots={"tone": (old_table, None)},
            bindings=((None, math_node.inputs[0], None),
                      (None, math_node.inputs[1], None)),
        )
        native = SimpleNamespace(
            tree=native_tree,
            controller=SimpleNamespace(
                _graph=graph,
                prepared=SimpleNamespace(table=old_table),
            ),
        )
        loaded_host = loaded_native = None
        try:
            updates._write_ledger(
                owner, kind="grade", revision=8, prior_revision=7,
                prior_settings="prior-owner-settings", stage="queued",
                new_transaction=True,
            )
            transaction, slots = preparation_ledger.stage_grade_backing(
                host, owner, native, SimpleNamespace(table=old_table),
                "binding-only-transaction",
            )
            self.assertEqual(slots, ())
            self.assertTrue(transaction)
            native_tree.links.remove(next(
                link for link in native_tree.links if link.to_socket == math_node.inputs[0]
            ))
            math_node.inputs[0].default_value = 4.0
            math_node.inputs[1].default_value = 8.0
            for link in tuple(host.links):
                if link.from_node == owner or link.to_node == owner:
                    host.links.remove(link)
            owner.inputs["Color"].default_value = (0.9, 0.8, 0.7, 0.6)
            native_tree["perceptual_grade_next_settings"] = "partial-native-settings"
            native_tree["perceptual_grade_nodes_revision"] = 99
            owner["perceptual_grade_next_settings"] = "partial-owner-settings"
            owner["perceptual_grade_next_applied_revision"] = 99
            owner["perceptual_grade_next_accepted_grade_manifest"] = "partial-manifest"
            del owner["perceptual_grade_next_preparation_ledger"]

            with TemporaryDirectory() as directory:
                path = str(Path(directory) / "grade-binding-backing.blend")
                bpy.data.libraries.write(path, {host})
                with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                    self.assertIn(host.name, data_from.node_groups)
                    data_to.node_groups = [host.name]
                loaded_host = data_to.node_groups[0]
            loaded_owner = loaded_host.nodes[owner.name]
            loaded_native = loaded_owner.node_tree
            loaded_math = loaded_native.nodes.get(math_node.name)
            self.assertIsNotNone(loaded_math)
            self.assertEqual(loaded_owner.get("perceptual_grade_next_settings"),
                             "partial-owner-settings")

            queued = []
            result = recovery.requeue_prepared_nodes(
                (loaded_host,), mark_dirty=lambda item: queued.append(item) or True,
            )
            self.assertEqual(result, (loaded_owner,))
            self.assertEqual(queued, [loaded_owner])
            self.assertEqual(loaded_native.get("perceptual_grade_next_settings"),
                             "prior-native-settings")
            self.assertEqual(loaded_native.get("perceptual_grade_nodes_revision"), 7)
            self.assertEqual(loaded_owner.get("perceptual_grade_next_settings"),
                             "prior-owner-settings")
            self.assertEqual(loaded_owner.get("perceptual_grade_next_applied_revision"), 7)
            self.assertEqual(
                loaded_owner.get("perceptual_grade_next_accepted_grade_manifest"),
                "prior-manifest",
            )
            self.assertEqual(len([link for link in loaded_native.links
                                  if link.to_socket == loaded_math.inputs[0]]), 1)
            self.assertEqual(tuple(link.from_socket.name for link in loaded_native.links
                                   if link.to_socket == loaded_math.inputs[0]), ("Value",))
            self.assertEqual(loaded_math.inputs[0].default_value, prior_first_default)
            self.assertEqual(loaded_math.inputs[1].default_value, 2.5)
            np.testing.assert_allclose(tuple(loaded_owner.inputs["Color"].default_value),
                                       (0.1, 0.2, 0.3, 0.4), rtol=0, atol=1e-7)
            self.assertTrue(any(link.from_node == loaded_host.nodes[source_node.name]
                                and link.to_node == loaded_owner
                                for link in loaded_host.links))
            self.assertTrue(any(link.from_node == loaded_owner
                                and link.to_node == loaded_host.nodes[sink_node.name]
                                for link in loaded_host.links))
            self.assertIsNone(loaded_owner.perceptual_grade_next_controls.preparation_ledger)
        finally:
            if loaded_host is not None:
                for node in loaded_host.nodes:
                    if node.get("perceptual_grade_next_backend") == "native_grade_graph":
                        preparation_ledger.discard_owner_ledger(node)
            for tree in (loaded_host, loaded_native):
                try:
                    if tree is not None and tree.users == 0:
                        bpy.data.node_groups.remove(tree, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            self._dispose_replacement_fixture(controls, host, owner, native_tree, candidate)

    def test_native_admission_leases_are_exclusive_and_exact(self):
        from color_tools.perceptual_grade_next_blender import native_admission

        reader = native_admission.acquire_reader("scope-1", reader_probe=lambda: True)
        self.assertIsNotNone(reader)
        self.assertIsNone(native_admission.acquire_writer(
            "grade-1", reader_probe=lambda: True,
        ))
        self.assertFalse(native_admission.release(
            native_admission.NativeLease("wrong", "reader", "scope-1"),
        ))
        self.assertTrue(native_admission.release(reader))
        writer = native_admission.acquire_writer("grade-2", reader_probe=lambda: True)
        self.assertIsNotNone(writer)
        self.assertIsNone(native_admission.acquire_reader(
            "bake-2", reader_probe=lambda: True,
        ))
        self.assertTrue(native_admission.release(writer))
        self.assertIsNone(native_admission.acquire_writer(
            "grade-3", reader_probe=lambda: False,
        ))

    def test_timer_and_synchronous_updates_defer_while_native_reader_is_live(self):
        from color_tools.perceptual_grade_next_blender import native_admission, updates

        class Identity(dict):
            def __init__(self, pointer, **values):
                super().__init__(values)
                self.pointer = pointer

            def as_pointer(self):
                return self.pointer

        tree = Identity(301)
        tree.animation_data = None
        node = Identity(302, perceptual_grade_next_edit_revision=1)
        key = updates._key(tree, node)
        installed = []
        reader = native_admission.acquire_reader("scope-defer", reader_probe=lambda: True)
        try:
            with patch.object(updates, "_prepare", return_value="candidate"), \
                    patch.object(updates, "_install_admitted",
                                 side_effect=lambda *args: installed.append(args[-1])), \
                    patch("color_tools.perceptual_grade_next_blender.native_admission"
                          "._host_readers_idle", return_value=True):
                updates._PENDING[key] = (tree, node, "grade", 1, "settings", None)
                updates._process_one()
                future = updates._JOBS[key][0]
                future.result(timeout=10)
                updates._process_one()
                self.assertIn(key, updates._JOBS)
                self.assertEqual(node.get("perceptual_grade_next_preparation_state"), None)
                self.assertEqual(installed, [])
                native_admission.release(reader)
                reader = None
                updates._process_one()
                self.assertNotIn(key, updates._JOBS)
                self.assertEqual(installed, ["candidate"])

                reader = native_admission.acquire_reader(
                    "scope-sync-defer", reader_probe=lambda: True,
                )
                updates._PENDING[key] = (tree, node, "grade", 1, "settings", None)
                self.assertEqual(updates.process_pending_updates(), ())
                self.assertIn(key, updates._PENDING)
                self.assertEqual(installed, ["candidate"])
                native_admission.release(reader)
                reader = None
                self.assertEqual(updates.process_pending_updates(), ())
                self.assertNotIn(key, updates._PENDING)
                self.assertEqual(installed, ["candidate", "candidate"])
        finally:
            if reader is not None:
                native_admission.release(reader)
            updates._PENDING.pop(key, None)
            updates._JOBS.pop(key, None)
            updates.cancel_pending_updates()

    def test_structural_backing_restore_failure_keeps_ledger_for_compensation(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            restore_tree_backing, stage_tree_backing,
        )

        controls, host, owner, prior, candidate, source, _sink = self._replacement_fixture()
        try:
            stage_tree_backing(
                host, owner, prior, candidate, "tree-failure",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            owner.node_tree = candidate
            host.nodes.remove(source)
            with self.assertRaises((RuntimeError, ValueError, KeyError)):
                restore_tree_backing(host, owner)
            self.assertIs(owner.node_tree, candidate)
            self.assertIsNotNone(owner.perceptual_grade_next_controls.preparation_ledger)
            self.assertGreater(prior.users, 0)
            self.assertGreater(candidate.users, 0)
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_requeue_restores_tree_backing_even_when_json_marker_is_missing(self):
        from color_tools.perceptual_grade_next_blender import recovery, updates
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            stage_tree_backing,
        )

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture()
        queued = []
        try:
            stage_tree_backing(
                host, owner, prior, candidate, "tree-pointer-only",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            owner.node_tree = candidate
            owner["perceptual_grade_next_preparation_state"] = "PENDING"
            owner["perceptual_grade_next_edit_revision"] = 1
            owner["perceptual_grade_next_applied_revision"] = 0
            self.assertNotIn(updates.PREPARATION_LEDGER_KEY, owner)
            result = recovery.requeue_prepared_nodes(
                (host,), mark_dirty=lambda node: queued.append(node) or True,
            )
            self.assertEqual(result, (owner,))
            self.assertEqual(queued, [owner])
            self.assertIs(owner.node_tree, prior)
            self.assertIsNone(owner.perceptual_grade_next_controls.preparation_ledger)
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_requeue_keeps_tree_repair_debt_when_compensation_fails(self):
        from color_tools.perceptual_grade_next_blender import recovery
        from color_tools.perceptual_grade_next_blender import preparation_ledger

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture()
        queued = []
        try:
            preparation_ledger.stage_tree_backing(
                host, owner, prior, candidate, "tree-repair-debt",
                defaults={"Color": tuple(owner.inputs["Color"].default_value)},
                properties={"perceptual_grade_next_tree_marker": (True, "prior")},
            )
            owner.node_tree = candidate
            with patch.object(
                preparation_ledger, "restore_tree_backing",
                side_effect=RuntimeError("repair still blocked"),
            ):
                result = recovery.requeue_prepared_nodes(
                    (host,), mark_dirty=lambda node: queued.append(node) or True,
                )
            self.assertEqual(result, ())
            self.assertEqual(queued, [])
            self.assertIsNotNone(owner.perceptual_grade_next_controls.preparation_ledger)
            self.assertIs(owner.node_tree, candidate)
            self.assertEqual(owner.get("perceptual_grade_next_preparation_state"), "FAILED")
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_failed_structural_install_and_compensation_keep_both_tree_references(self):
        from color_tools.perceptual_grade_next_blender import updates
        from color_tools.perceptual_grade_next_blender import preparation_ledger
        from color_tools.perceptual_grade_next_core import StackSettings

        controls, host, owner, prior, candidate, _source, _sink = self._replacement_fixture(
            "native_stack_lut",
        )
        settings = StackSettings()
        try:
            with patch(
                "color_tools.perceptual_grade_next_blender.stack_graph.build_native_stack",
                return_value=SimpleNamespace(tree=candidate),
            ), patch.object(
                updates, "_restore_links", side_effect=RuntimeError("injected link failure"),
            ), patch.object(
                preparation_ledger, "_socket", side_effect=RuntimeError("injected restore failure"),
            ), patch.object(updates, "_dispose") as dispose:
                with self.assertRaisesRegex(RuntimeError, "rollback both failed"):
                    updates._install(
                        host, owner, "stack", 1, settings,
                        SimpleNamespace(settings=settings),
                    )
            dispose.assert_not_called()
            self.assertIsNotNone(owner.perceptual_grade_next_stack_controls.preparation_ledger)
            self.assertGreater(prior.users, 0)
            self.assertGreater(candidate.users, 0)
            self.assertIsNotNone(updates._read_ledger(owner))
        finally:
            self._dispose_replacement_fixture(controls, host, owner, prior, candidate)

    def test_recovery_removes_unreferenced_candidate_tree_after_interrupted_swap(self):
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            CANDIDATE_IMAGE_PREFIX, CANDIDATE_OWNER_KEY,
            discard_orphan_candidates,
        )

        candidate = bpy.data.node_groups.new(".PG Next Candidate Recovery Test", "ShaderNodeTree")
        candidate[CANDIDATE_OWNER_KEY] = "owner"
        orphan_image = bpy.data.images.new(
            CANDIDATE_IMAGE_PREFIX + "owner revision field",
            width=1, height=1, alpha=True, float_buffer=True,
        )
        name = candidate.name
        image_name = orphan_image.name
        try:
            self.assertEqual(
                discard_orphan_candidates(bpy.data.node_groups),
                (name,),
            )
            self.assertIsNone(bpy.data.node_groups.get(name))
            self.assertIsNone(bpy.data.images.get(image_name))
        finally:
            if name in bpy.data.node_groups:
                bpy.data.node_groups.remove(candidate, do_unlink=True)

    def test_orphan_ledger_cleanup_removes_only_unreferenced_groups(self):
        from color_tools.perceptual_grade_next_blender.preparation_ledger import (
            LEDGER_PREFIX, discard_orphan_ledgers,
        )

        orphan = bpy.data.node_groups.new(LEDGER_PREFIX + "orphan-test", "ShaderNodeTree")
        orphan_image = bpy.data.images.new(
            LEDGER_PREFIX + "Image orphan-test",
            width=1, height=1, alpha=True, float_buffer=True,
        )
        retained = bpy.data.node_groups.new(LEDGER_PREFIX + "retained-test", "ShaderNodeTree")
        host = bpy.data.node_groups.new("Next retained-ledger host", "ShaderNodeTree")
        reference = host.nodes.new("ShaderNodeGroup")
        reference.node_tree = retained
        for _ in range(2):
            image_node = orphan.nodes.new("ShaderNodeTexImage")
            image_node.image = orphan_image
            image_node["perceptual_grade_next_preparation_ledger_role"] = "backup"
        orphan_name, retained_name = orphan.name, retained.name
        orphan_image_name = orphan_image.name
        try:
            removed = discard_orphan_ledgers(bpy.data.node_groups)
            self.assertIn(orphan_name, removed)
            self.assertNotIn(retained_name, removed)
            self.assertIsNone(bpy.data.node_groups.get(orphan_name))
            self.assertIsNone(bpy.data.images.get(orphan_image_name))
            self.assertIs(bpy.data.node_groups.get(retained_name), retained)
        finally:
            bpy.data.node_groups.remove(host, do_unlink=True)
            for name in (orphan_name, retained_name):
                tree = bpy.data.node_groups.get(name)
                if tree is not None:
                    bpy.data.node_groups.remove(tree, do_unlink=True)

    def test_persistent_handlers_register_idempotently_and_unregister(self):
        recovery.register()
        recovery.register()
        load = recovery._HANDLERS["load_post"]
        undo = recovery._HANDLERS["undo_post"]
        self.assertEqual(bpy.app.handlers.load_post.count(load), 1)
        self.assertEqual(bpy.app.handlers.undo_post.count(undo), 1)
        output_handlers = tuple(
            (name, recovery._HANDLERS[name])
            for name in ("render_pre", "render_complete", "render_cancel", "save_pre", "save_post")
            if name in recovery._HANDLERS
        )
        self.assertTrue(output_handlers)
        self.assertIn("render_pre", recovery._HANDLERS)
        self.assertTrue({"render_complete", "render_cancel"} & recovery._HANDLERS.keys())
        self.assertTrue(all(getattr(bpy.app.handlers, name).count(callback) == 1
                            for name, callback in output_handlers))
        recovery.unregister()
        self.assertNotIn(load, bpy.app.handlers.load_post)
        self.assertNotIn(undo, bpy.app.handlers.undo_post)
        self.assertTrue(all(callback not in getattr(bpy.app.handlers, name)
                            for name, callback in output_handlers))

    def test_render_handlers_hold_native_publication_until_completion(self):
        from color_tools.perceptual_grade_next_blender import updates

        recovery._render_started(None)
        self.assertIn("native_render", updates._PUBLICATION_HOLDS)
        recovery._render_finished(None)
        self.assertNotIn("native_render", updates._PUBLICATION_HOLDS)

    def test_save_handlers_hold_native_publication_until_completion(self):
        from color_tools.perceptual_grade_next_blender import updates

        recovery._save_started(None)
        self.assertIn("native_save", updates._PUBLICATION_HOLDS)
        recovery._save_finished(None)
        self.assertNotIn("native_save", updates._PUBLICATION_HOLDS)

    def test_scope_handlers_are_persistent_idempotent_and_removed(self):
        registered_class = scope_runtime.register()
        self.assertIsNotNone(registered_class)
        self.assertIs(scope_runtime.register(), registered_class)
        self.assertEqual(registered_class.bl_idname, "PGNEXT_GGT_scope")
        self.assertIsNotNone(scope_runtime._OPEN_OPERATOR_CLASS)
        self.assertIsNotNone(scope_runtime._CLOSE_OPERATOR_CLASS)
        for name in ("frame_change_pre", "frame_change_post", "depsgraph_update_pre",
                     "depsgraph_update_post", "animation_playback_pre",
                     "animation_playback_post", "load_pre"):
            callback = scope_runtime._HANDLERS[name]
            self.assertEqual(getattr(bpy.app.handlers, name).count(callback), 1)
            self.assertTrue(getattr(callback, "_bpy_persistent", False))
        scope_runtime.unregister()
        self.assertFalse(scope_runtime._HANDLERS)

    def test_preparation_runs_off_thread_and_installs_on_main_after_render_hold(self):
        from color_tools.perceptual_grade_next_blender import updates

        class Identity(dict):
            def __init__(self, pointer, **values):
                super().__init__(values)
                self.pointer = pointer

            def as_pointer(self):
                return self.pointer

        tree = Identity(101)
        tree.animation_data = None
        node = Identity(202, perceptual_grade_next_edit_revision=1)
        key = updates._key(tree, node)
        main_thread = threading.get_ident()
        installed = []
        updates._PENDING[key] = (tree, node, "grade", 1, "snapshot", None)
        updates.hold_publication("native_render")
        try:
            with patch.object(updates, "_prepare",
                              side_effect=lambda *_: threading.get_ident()), \
                    patch.object(updates, "_install",
                                 side_effect=lambda *args: installed.append((threading.get_ident(), args[-1]))):
                updates._process_one()
                self.assertNotIn(key, updates._JOBS)
                updates.release_publication("native_render")
                self.assertEqual(updates._process_one(), 0.2)
                future = updates._JOBS[key][0]
                self.assertNotEqual(future.result(timeout=10), main_thread)
                self.assertIsNone(updates._process_one())
            self.assertEqual(installed, [(main_thread, future.result())])
        finally:
            updates.cancel_pending_updates()


if __name__ == "__main__":
    unittest.main()
