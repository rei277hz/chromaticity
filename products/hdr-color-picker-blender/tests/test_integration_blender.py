"""Host borrows, independent installed copies, and real CPU helper dispatch."""
import importlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bpy
import gpu
import numpy as np

from bl_ext.picker_tests import hdr_color_picker as hdr_color_picker
from bl_ext.picker_tests.hdr_color_picker import hdr_color_picker_core as model
from bl_ext.picker_tests.hdr_color_picker.hdr_color_picker_blender import brush, controller, display, registered_session
from bl_ext.picker_tests.hdr_color_picker.blender_runtime.execution.contracts import JobSpec


def context_for(native_brush):
    return SimpleNamespace(mode='PAINT_GREASE_PENCIL', object=bpy.context.scene,
                           scene=bpy.context.scene,
                           tool_settings=SimpleNamespace(gpencil_paint=SimpleNamespace(
                               brush=native_brush, color_mode='VERTEXCOLOR')))


class IntegrationTests(unittest.TestCase):
    def test_failed_reset_retains_repair_gate_until_native_retry(self):
        session = registered_session()
        instance = session.controller()
        with patch.object(instance.renderer, 'reset', side_effect=RuntimeError('reset interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'reset interrupted'):
                session.reset()
        self.assertEqual(session.app.lifecycle.state.phase, 'repair_needed')
        with self.assertRaises(display.DisplayUnavailable):
            instance.require_view(bpy.context.scene)
        session.reset()
        self.assertEqual(session.app.lifecycle.state.phase, 'active')
        self.assertEqual(instance.arena.physical_counts(), (0, 0))

    def test_real_gp_context_preview_cancel_commit_and_gate(self):
        """Run the production gizmo callbacks against actual paint-mode RNA."""
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.grease_pencil_add(type='EMPTY')
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
        region = next(region for region in area.regions if region.type == 'WINDOW')
        try:
            with bpy.context.temp_override(area=area, region=region):
                context = bpy.context
                paint = context.tool_settings.gpencil_paint
                paint.color_mode = 'VERTEXCOLOR'
                native = paint.brush
                self.assertFalse(native.gpencil_settings.pin_draw_mode)
                self.assertFalse(native.gpencil_settings.use_material_pin)
                native.color = (.1, .2, .3)
                original = tuple(native.color)
                settings = getattr(context.window_manager, 'hdr_color_picker_settings')
                settings.lightness, settings.x, settings.y = .8, .4, .4
                gizmo = SimpleNamespace(_origin=(24, 64), _size=(240, 240))
                gizmo._preview = lambda ctx, event: registered_session().ui.HDRPICKER_GT_slice._preview(gizmo, ctx, event)
                event = SimpleNamespace(mouse_region_x=144, mouse_region_y=184)
                self.assertEqual(registered_session().ui.HDRPICKER_GT_slice.invoke(gizmo, context, event), {'RUNNING_MODAL'})
                self.assertEqual(tuple(native.color), original)
                self.assertAlmostEqual(settings.x, .5)
                self.assertEqual(registered_session().ui.HDRPICKER_GT_slice.modal(gizmo, context, event, set()), {'RUNNING_MODAL'})
                registered_session().ui.HDRPICKER_GT_slice.exit(gizmo, context, True)
                np.testing.assert_allclose((settings.x, settings.y), (.4, .4))
                self.assertEqual(tuple(native.color), original)
                # Actual WM undo/redo dispatch is covered by the foreground runner.
                self.assertEqual(registered_session().ui.HDRPICKER_GT_slice.invoke(gizmo, context, event), {'RUNNING_MODAL'})
                registered_session().ui.HDRPICKER_GT_slice.exit(gizmo, context, False)
                self.assertGreater(max(paint.brush.color), 1)
                # A view feature outside the fidelity gate prevents interaction/write.
                context.scene.view_settings.use_white_balance = True
                before = tuple(context.tool_settings.gpencil_paint.brush.color)
                self.assertEqual(registered_session().ui.HDRPICKER_GT_slice.invoke(gizmo, context, event), {'CANCELLED'})
                self.assertEqual(bpy.ops.hdr_color_picker.confirm(), {'CANCELLED'})
                self.assertEqual(tuple(context.tool_settings.gpencil_paint.brush.color), before)
                context.scene.view_settings.use_white_balance = False
                registered_session().reset()
                with patch.object(display.DisplayTransform, 'gpu', side_effect=RuntimeError('shader failure')):
                    self.assertEqual(registered_session().ui.HDRPICKER_GT_slice.invoke(gizmo, context, event), {'CANCELLED'})
                    self.assertEqual(bpy.ops.hdr_color_picker.confirm(), {'CANCELLED'})
                # Cached presentation failure continues to gate the same view.
                self.assertEqual(bpy.ops.hdr_color_picker.confirm(), {'CANCELLED'})
                self.assertEqual(tuple(context.tool_settings.gpencil_paint.brush.color), before)
                registered_session().reset()
        finally:
            if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

    def test_brush_hdr_conversion_and_concurrent_edit_rejection(self):
        native = bpy.data.brushes.new('HDR test brush', mode='PAINT_GREASE_PENCIL')
        try:
            native.gpencil_brush_type = 'DRAW'
            bpy.ops.wm.set_working_color_space(working_space='Linear Rec.709')
            context = context_for(native)
            identity = brush.capture(context)
            original = tuple(native.color)
            pick = model.evaluate(.8, .5, .5)
            self.assertTrue(pick.valid)
            self.assertEqual(tuple(native.color), original)  # preview has no write
            brush.commit(context, identity, pick.acescg)
            from mathutils import Color
            expected = Color(pick.acescg).from_acescg_to_scene_linear()
            np.testing.assert_allclose(native.color, expected, rtol=2e-6, atol=1e-6)
            self.assertGreater(max(native.color), 1)
            np.testing.assert_allclose(brush.current_acescg(context), pick.acescg, rtol=2e-6, atol=1e-6)
            with self.assertRaises(brush.BrushUnavailable):
                brush.commit(context, identity, pick.acescg)
            native.gpencil_settings.pin_draw_mode = True
            with self.assertRaises(brush.BrushUnavailable):
                brush.capture(context)
        finally:
            bpy.data.brushes.remove(native)

    def test_native_cpu_worker_dispatch_and_session(self):
        service = registered_session().app.execution.get_runtime()
        handle = service.submit(JobSpec('picker_slice', dict(j=.5, width=17, height=13, full_rec2020=True)))
        actual = handle.result(timeout=90)
        np.testing.assert_array_equal(actual, model.render_slice(.5, 17, 13))
        self.assertNotEqual(service.helpers['bulk'].process.pid, __import__('os').getpid())

    def test_private_arenas_and_disable_do_not_touch_peer(self):
        peer = importlib.import_module('bl_ext.picker_tests.perceptual_grade')
        peer.register()
        from bl_ext.picker_tests.perceptual_grade.perceptual_grade_blender.integration import lifecycle
        from bl_ext.picker_tests.hdr_color_picker.blender_runtime import ForeignOwnerError
        from bl_ext.picker_tests.perceptual_grade.blender_runtime import ForeignOwnerError as PeerForeignOwnerError
        peer_nodes = lifecycle.registered_session().component('graph.nodes')
        peer_app = lifecycle.registered_session().app
        picker_app = registered_session().app
        picker_arena, peer_arena = picker_app.ownership, peer_app.ownership
        try:
            self.assertEqual(type(picker_app).__module__,
                             'bl_ext.picker_tests.hdr_color_picker.blender_runtime.app')
            self.assertEqual(type(peer_app).__module__,
                             'bl_ext.picker_tests.perceptual_grade.blender_runtime.app')
            self.assertIsNot(type(picker_app), type(peer_app))
            self.assertIsNot(ForeignOwnerError, PeerForeignOwnerError)
            self.assertFalse(any(name.startswith((
                'bl_ext.picker_tests.hdr_color_picker._vendor',
                'bl_ext.picker_tests.perceptual_grade._vendor')) for name in sys.modules))
            first, second = object(), object()
            a = picker_arena.retain(first, 'test')
            b = peer_arena.retain(second, 'test')
            with self.assertRaises(ForeignOwnerError):
                picker_arena.resolve(b)
            with self.assertRaises(PeerForeignOwnerError):
                peer_arena.resolve(a)
            with self.assertRaises(ForeignOwnerError):
                picker_arena.release(b)
            self.assertIs(peer_arena.resolve(b), second)
            hdr_color_picker.unregister()
            self.assertTrue(picker_app.closed)
            self.assertIs(peer_arena.resolve(b), second)
            self.assertTrue(peer_nodes.PGToneSettings.is_registered)
            hdr_color_picker.register()
            self.assertIsNot(registered_session().app, picker_app)
            self.assertIsNot(registered_session().app.execution.get_runtime(), peer_app.execution.get_runtime())
            peer.unregister()
            self.assertFalse(registered_session().app.execution.get_runtime().closed)
            peer.register()
            peer.unregister()
            self.assertTrue(hasattr(bpy.types.WindowManager, 'hdr_color_picker_settings'))
        finally:
            if lifecycle.registered_session() is not None:
                peer.unregister()

    def test_controller_cpu_fallback_and_boundary_release(self):
        gpu.init()
        instance = controller.Controller(registered_session().app)
        settings = SimpleNamespace(lightness=.5, full_rec2020=True)
        try:
            instance.gpu_failed = True
            instance.update(bpy.context.scene, settings)
            self.assertIsNotNone(instance.pending)
            instance.pending.result(timeout=90)
            instance.update(bpy.context.scene, settings)
            self.assertIsNotNone(instance.arena.resolve(instance.texture_ref))
            instance.reset()
            self.assertEqual(instance.arena.physical_counts(), (0, 0))
            self.assertIsNone(instance.pending)
        finally:
            instance.close()

    def test_pending_preview_is_retired_after_leaving_paint(self):
        instance = registered_session().controller()
        instance.reset()
        instance.gpu_failed = True
        # The earlier fallback case has a completed .5 slice in this App's
        # cache. Establish genuinely queued work for the retirement assertion.
        settings = SimpleNamespace(lightness=.625, full_rec2020=True)
        with patch.object(instance.app.execution.get_runtime(), 'poll'):
            instance.update(bpy.context.scene, settings)
        self.assertIsNotNone(instance.pending)
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.assertEqual(registered_session().ui.tick(), .1)
        self.assertIsNone(instance.pending)
        self.assertEqual(instance.arena.physical_counts(), (0, 0))

    def test_repeated_enable_disable_retires_controller_arenas(self):
        previous = []
        for _ in range(3):
            lifecycle = registered_session()
            instance = lifecycle.controller()
            token = instance.arena.retain(object(), 'test')
            self.assertEqual(len(lifecycle.app.ownership.snapshots()), 1)
            previous.append(lifecycle.app.identity)
            hdr_color_picker.unregister()
            self.assertTrue(lifecycle.closed)
            self.assertTrue(lifecycle.app.closed)
            self.assertIsNone(lifecycle.app.ownership.resolve(token))
            self.assertEqual(lifecycle.app.ownership.snapshots(), ())
            hdr_color_picker.register()
        self.assertEqual(len(set(previous)), 3)
        self.assertIsNone(registered_session().current_controller())

    def test_pending_preview_is_retired_when_viewport_gizmos_are_hidden(self):
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.grease_pencil_add(type='EMPTY')
        bpy.ops.object.mode_set(mode='PAINT_GREASE_PENCIL')
        bpy.context.tool_settings.gpencil_paint.color_mode = 'VERTEXCOLOR'
        settings = bpy.context.window_manager.hdr_color_picker_settings
        settings.visible = True
        areas = [(area, area.spaces.active.show_gizmo)
                 for window in bpy.context.window_manager.windows
                 for area in window.screen.areas if area.type == 'VIEW_3D']
        instance = registered_session().controller()
        try:
            for area, _ in areas:
                area.spaces.active.show_gizmo = False
            instance.reset()
            instance.gpu_failed = True
            instance.update(bpy.context.scene, settings)
            self.assertIsNotNone(instance.pending)
            registered_session().ui.tick()
            self.assertIsNone(instance.pending)
            self.assertEqual(instance.arena.physical_counts(), (0, 0))
        finally:
            for area, visible in areas:
                area.spaces.active.show_gizmo = visible
            settings.visible = False
            bpy.ops.object.mode_set(mode='OBJECT')
